"""
OAuth manager for Calendar MCP Service.

This module handles OAuth2 authentication for Google Calendar and Microsoft Graph APIs,
including:
- Token caching with automatic refresh
- Single-flight token refresh with async locks
- Double-check pattern to prevent redundant refreshes
- Token validation and expiry management
- Credential management for both providers

The manager integrates with the error handler and circuit breaker patterns
to ensure reliable API access with graceful degradation.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Dict as TypeDict
from dataclasses import dataclass, field
from enum import Enum

import aiohttp
from google.oauth2.credentials import Credentials as GoogleCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from msgraph.generated.authentication.authentication import Authentication
from msgraph.generated.authentication.user_token_credential import UserTokenCredential

from src.services.error_handler import ErrorHandler, MCPErrors

# Configure logging
logger = logging.getLogger(__name__)


class OAuthProvider(Enum):
    """Supported OAuth providers."""
    GOOGLE = "google"
    OUTLOOK = "outlook"


class TokenStatus(Enum):
    """Status of an OAuth token."""
    VALID = "valid"
    EXPIRING = "expiring"  # Within 5-minute buffer
    EXPIRED = "expired"
    INVALID = "invalid"
    REFRESHING = "refreshing"


@dataclass
class OAuthToken:
    """
    OAuth token with metadata.
    
    Attributes:
        access_token: Access token for API calls
        refresh_token: Refresh token for obtaining new access tokens
        token_type: Token type (usually "Bearer")
        expiry: Token expiry timestamp
        provider: OAuth provider name
        user_id: User identifier
        status: Current token status
        created_at: When token was created/refreshed
        metadata: Additional token metadata
    """
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expiry: datetime
    provider: OAuthProvider = OAuthProvider.GOOGLE
    user_id: str = ""
    status: TokenStatus = TokenStatus.VALID
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_valid(self) -> bool:
        """Check if token is currently valid."""
        return self.status == TokenStatus.VALID
    
    @property
    def is_expiring(self) -> bool:
        """Check if token is within expiry buffer."""
        return self.status == TokenStatus.EXPIRING
    
    @property
    def is_expired(self) -> bool:
        """Check if token has expired."""
        return self.status == TokenStatus.EXPIRED
    
    @property
    def time_until_expiry(self) -> timedelta:
        """Time remaining until token expiry."""
        return self.expiry - datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expiry": self.expiry.isoformat(),
            "provider": self.provider.value,
            "user_id": self.user_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class OAuthConfig:
    """
    OAuth configuration for a provider.
    
    Attributes:
        client_id: OAuth client ID
        client_secret: OAuth client secret
        token_url: Token endpoint URL
        auth_url: Authorization endpoint URL
        scopes: Required OAuth scopes
        expiry_buffer_minutes: Minutes before expiry to refresh
        max_retries: Maximum retry attempts for token operations
    """
    client_id: str
    client_secret: str
    token_url: str
    auth_url: str
    scopes: list
    expiry_buffer_minutes: int = 5
    max_retries: int = 3


@dataclass
class TokenRefreshResult:
    """
    Result of a token refresh operation.
    
    Attributes:
        success: Whether refresh succeeded
        token: New OAuthToken if successful
        error_message: Error message if failed
        retry_count: Number of retry attempts
        status_code: HTTP status code if applicable
    """
    success: bool
    token: Optional[OAuthToken] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    status_code: Optional[int] = None


class OAuthManager:
    """
    Manager for OAuth2 authentication and token management.
    
    This class handles:
    - Token caching with automatic refresh
    - Single-flight token refresh with async locks
    - Double-check pattern to prevent redundant refreshes
    - Token validation and expiry management
    - Provider-specific OAuth flows (Google, Outlook)
    
    Attributes:
        providers: Configuration for each OAuth provider
        tokens: Dictionary of cached tokens by user/provider
        refresh_locks: Dictionary of async locks for refresh operations
        error_handler: Error handler for MCP error mapping
        expiry_buffer_minutes: Minutes before expiry to refresh token
    """
    
    def __init__(
        self,
        providers: Optional[Dict[str, OAuthConfig]] = None,
        error_handler: Optional[ErrorHandler] = None,
        expiry_buffer_minutes: int = 5,
    ):
        """
        Initialize the OAuth manager.
        
        Args:
            providers: Configuration for each OAuth provider
            error_handler: Error handler for MCP error mapping
            expiry_buffer_minutes: Minutes before expiry to refresh token
        """
        # Default provider configurations
        self._providers: Dict[str, OAuthConfig] = {
            "google": OAuthConfig(
                client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
                client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
                token_url="https://oauth2.googleapis.com/token",
                auth_url="https://accounts.google.com/o/oauth2/auth",
                scopes=["https://www.googleapis.com/auth/calendar",
                        "https://www.googleapis.com/auth/calendar.readonly"],
                expiry_buffer_minutes=expiry_buffer_minutes,
                max_retries=3,
            ),
            "outlook": OAuthConfig(
                client_id=os.getenv("OUTLOOK_CLIENT_ID", ""),
                client_secret=os.getenv("OUTLOOK_CLIENT_SECRET", ""),
                token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
                auth_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                scopes=["Calendars.Read", "Calendars.ReadWrite"],
                expiry_buffer_minutes=expiry_buffer_minutes,
                max_retries=3,
            ),
        }
        
        # Override with provided configurations
        if providers:
            self._providers.update(providers)
        
        # Token cache: user_id -> provider -> token
        self._tokens: Dict[str, Dict[str, OAuthToken]] = {}
        
        # Refresh locks: user_id:provider -> asyncio.Lock
        self._refresh_locks: Dict[str, asyncio.Lock] = {}
        
        self.error_handler = error_handler
        self.expiry_buffer_minutes = expiry_buffer_minutes
    
    async def get_token(
        self,
        user_id: str,
        provider: str,
    ) -> Optional[OAuthToken]:
        """
        Get a cached token for a user/provider combination.
        
        Args:
            user_id: User identifier
            provider: Provider name
            
        Returns:
            OAuthToken or None if not found
        """
        key = f"{user_id}:{provider}"
        
        if key not in self._tokens:
            return None
        
        token = self._tokens[key]
        
        # Check token status
        if token.is_expired:
            logger.info(
                f"Token expired for {user_id}:{provider}, "
                f"status: {token.status.value}"
            )
            token.status = TokenStatus.EXPIRED
        
        return token
    
    async def refresh_token(
        self,
        user_id: str,
        provider: str,
    ) -> TokenRefreshResult:
        """
        Refresh an OAuth token with single-flight pattern.
        
        This method implements the double-check pattern:
        1. Acquire lock for the user/provider combination
        2. Double-check if refresh is still needed
        3. Perform refresh if needed
        4. Release lock
        
        Args:
            user_id: User identifier
            provider: Provider name
            
        Returns:
            TokenRefreshResult with refresh status
        """
        config = self._providers.get(provider)
        if not config:
            return TokenRefreshResult(
                success=False,
                error_message=f"Unknown provider: {provider}",
            )
        
        key = f"{user_id}:{provider}"
        
        # Acquire refresh lock
        if key not in self._refresh_locks:
            self._refresh_locks[key] = asyncio.Lock()
        
        lock = self._refresh_locks[key]
        
        try:
            # Acquire lock
            async with lock:
                # Double-check pattern: check again after acquiring lock
                token = await self.get_token(user_id, provider)
                
                if not token or token.is_expired:
                    logger.info(
                        f"Token expired or not found for {user_id}:{provider}, "
                        f"refreshing"
                    )
                    
                    # Perform refresh
                    return await self._refresh_token_internal(
                        user_id, provider, config
                    )
                elif token.is_expiring:
                    # Token is expiring, refresh it
                    logger.info(
                        f"Token expiring for {user_id}:{provider}, "
                        f"refreshing (time until expiry: {token.time_until_expiry.total_seconds():.0f}s)"
                    )
                    return await self._refresh_token_internal(
                        user_id, provider, config
                    )
                else:
                    # Token is valid, no refresh needed
                    logger.debug(
                        f"Token valid for {user_id}:{provider}, "
                        f"no refresh needed (time until expiry: {token.time_until_expiry.total_seconds():.0f}s)"
                    )
                    return TokenRefreshResult(
                        success=True,
                        token=token,
                    )
                    
        except Exception as e:
            logger.error(
                f"Token refresh failed for {user_id}:{provider}: {e}"
            )
            
            if self.error_handler:
                error_code = self.error_handler.map_error(e)
                return TokenRefreshResult(
                    success=False,
                    error_message=str(e),
                    retry_count=0,
                    status_code=error_code.value if error_code else None,
                )
            
            return TokenRefreshResult(
                success=False,
                error_message=str(e),
            )
        finally:
            # Lock is released by context manager
    
    async def _refresh_token_internal(
        self,
        user_id: str,
        provider: str,
        config: OAuthConfig,
    ) -> TokenRefreshResult:
        """
        Internal token refresh implementation.
        
        Args:
            user_id: User identifier
            provider: Provider name
            config: OAuth configuration
            
        Returns:
            TokenRefreshResult with refresh status
        """
        retry_count = 0
        max_retries = config.max_retries
        
        while retry_count < max_retries:
            try:
                # Perform provider-specific refresh
                if provider == "google":
                    result = await self._refresh_google_token(
                        user_id, config
                    )
                elif provider == "outlook":
                    result = await self._refresh_outlook_token(
                        user_id, config
                    )
                else:
                    return TokenRefreshResult(
                        success=False,
                        error_message=f"Unknown provider: {provider}",
                    )
                
                if result.success:
                    # Store token in cache
                    self._store_token(user_id, provider, result.token)
                    
                    logger.info(
                        f"Token refreshed for {user_id}:{provider} "
                        f"expires at {result.token.expiry.isoformat()}"
                    )
                    
                    return result
                
                # If we get here, refresh failed but didn't return error
                # This shouldn't happen, but handle it
                return TokenRefreshResult(
                    success=False,
                    error_message="Unknown refresh failure",
                )
                
            except Exception as e:
                retry_count += 1
                logger.warning(
                    f"Token refresh attempt {retry_count}/{max_retries} "
                    f"for {user_id}:{provider} failed: {e}"
                )
                
                if retry_count < max_retries:
                    # Wait before retry
                    delay = 1.0 * (2 ** (retry_count - 1))
                    logger.info(
                        f"Waiting {delay:.0f}s before retry "
                        f"for {user_id}:{provider}"
                    )
                    await asyncio.sleep(delay)
                else:
                    # Max retries exceeded
                    logger.error(
                        f"Max retries exceeded for token refresh "
                        f"for {user_id}:{provider}: {e}"
                    )
                    
                    return TokenRefreshResult(
                        success=False,
                        error_message=str(e),
                        retry_count=retry_count,
                    )
        
        return TokenRefreshResult(
            success=False,
            error_message="Max retries exceeded",
            retry_count=max_retries,
        )
    
    async def _refresh_google_token(
        self,
        user_id: str,
        config: OAuthConfig,
    ) -> TokenRefreshResult:
        """
        Refresh a Google OAuth token.
        
        Args:
            user_id: User identifier
            config: OAuth configuration
            
        Returns:
            TokenRefreshResult with refresh status
        """
        try:
            # For Google, we use the refresh token flow
            # In production, this would use google-auth-library
            # For now, we simulate with environment variables
            
            # Check if we have a refresh token
            # In a real implementation, this would come from the token cache
            # or from a stored refresh token
            
            # For demonstration, we'll create a new token
            # In production, you would use google.oauth2.credentials.Credentials.refresh()
            
            # Simulate token refresh
            new_expiry = datetime.utcnow() + timedelta(hours=1)
            
            new_token = OAuthToken(
                access_token=os.getenv("GOOGLE_ACCESS_TOKEN", ""),
                refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN", ""),
                token_type="Bearer",
                expiry=new_expiry,
                provider=OAuthProvider.GOOGLE,
                user_id=user_id,
                status=TokenStatus.VALID,
                metadata={
                    "refreshed_at": datetime.utcnow().isoformat(),
                    "provider": "google",
                },
            )
            
            return TokenRefreshResult(
                success=True,
                token=new_token,
            )
            
        except Exception as e:
            logger.error(f"Failed to refresh Google token: {e}")
            return TokenRefreshResult(
                success=False,
                error_message=str(e),
            )
    
    async def _refresh_outlook_token(
        self,
        user_id: str,
        config: OAuthConfig,
    ) -> TokenRefreshResult:
        """
        Refresh an Outlook OAuth token.
        
        Args:
            user_id: User identifier
            config: OAuth configuration
            
        Returns:
            TokenRefreshResult with refresh status
        """
        try:
            # For Outlook, we use the refresh token flow with MS Graph SDK
            # In production, this would use msgraph.authentication.UserTokenCredential
            
            # Check if we have a refresh token
            # In a real implementation, this would come from the token cache
            # or from a stored refresh token
            
            # For demonstration, we'll create a new token
            # In production, you would use UserTokenCredential.refresh()
            
            # Simulate token refresh
            new_expiry = datetime.utcnow() + timedelta(hours=1)
            
            new_token = OAuthToken(
                access_token=os.getenv("OUTLOOK_ACCESS_TOKEN", ""),
                refresh_token=os.getenv("OUTLOOK_REFRESH_TOKEN", ""),
                token_type="Bearer",
                expiry=new_expiry,
                provider=OAuthProvider.OUTLOOK,
                user_id=user_id,
                status=TokenStatus.VALID,
                metadata={
                    "refreshed_at": datetime.utcnow().isoformat(),
                    "provider": "outlook",
                },
            )
            
            return TokenRefreshResult(
                success=True,
                token=new_token,
            )
            
        except Exception as e:
            logger.error(f"Failed to refresh Outlook token: {e}")
            return TokenRefreshResult(
                success=False,
                error_message=str(e),
            )
    
    def _store_token(
        self,
        user_id: str,
        provider: str,
        token: OAuthToken,
    ) -> None:
        """
        Store a token in the cache.
        
        Args:
            user_id: User identifier
            provider: Provider name
            token: OAuthToken to store
        """
        if user_id not in self._tokens:
            self._tokens[user_id] = {}
        
        self._tokens[user_id][provider] = token
    
    async def validate_token(
        self,
        user_id: str,
        provider: str,
    ) -> bool:
        """
        Validate a token is still valid.
        
        Args:
            user_id: User identifier
            provider: Provider name
            
        Returns:
            True if token is valid
        """
        token = await self.get_token(user_id, provider)
        
        if not token:
            return False
        
        # Check if token is expired or expiring
        if token.is_expired or token.is_expiring:
            # Refresh the token
            result = await self.refresh_token(user_id, provider)
            return result.success
        
        return token.is_valid
    
    async def revoke_token(
        self,
        user_id: str,
        provider: str,
    ) -> bool:
        """
        Revoke a token and clear from cache.
        
        Args:
            user_id: User identifier
            provider: Provider name
            
        Returns:
            True if token revoked
        """
        key = f"{user_id}:{provider}"
        
        if key in self._tokens:
            del self._tokens[key]
            
            logger.info(
                f"Token revoked for {user_id}:{provider}"
            )
            
            return True
        
        return False
    
    async def get_token_expiry(
        self,
        user_id: str,
        provider: str,
    ) -> Optional[datetime]:
        """
        Get the expiry time for a token.
        
        Args:
            user_id: User identifier
            provider: Provider name
            
        Returns:
            Expiry datetime or None if not found
        """
        token = await self.get_token(user_id, provider)
        
        if token:
            return token.expiry
        
        return None
    
    async def get_token_status(
        self,
        user_id: str,
        provider: str,
    ) -> Optional[TokenStatus]:
        """
        Get the status of a token.
        
        Args:
            user_id: User identifier
            provider: Provider name
            
        Returns:
            TokenStatus or None if not found
        """
        token = await self.get_token(user_id, provider)
        
        if token:
            return token.status
        
        return None
    
    async def clear_cache(
        self,
        user_id: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> int:
        """
        Clear token cache entries.
        
        Args:
            user_id: User identifier (None to clear all)
            provider: Provider name (None to clear all)
            
        Returns:
            Number of tokens cleared
        """
        cleared = 0
        
        if user_id and provider:
            # Clear specific user/provider
            if user_id in self._tokens and provider in self._tokens[user_id]:
                del self._tokens[user_id][provider]
                cleared += 1
        elif user_id:
            # Clear all providers for user
            if user_id in self._tokens:
                del self._tokens[user_id]
                cleared += 1
        elif provider:
            # Clear all users for provider
            for user_id in list(self._tokens.keys()):
                if provider in self._tokens[user_id]:
                    del self._tokens[user_id][provider]
                    cleared += 1
        else:
            # Clear all tokens
            self._tokens.clear()
            cleared = len(self._tokens)
        
        logger.info(
            f"Cleared {cleared} tokens from cache"
        )
        
        return cleared
    
    def get_cache_stats(
        self,
    ) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        stats = {
            "total_tokens": sum(
                len(tokens) for tokens in self._tokens.values()
            ),
            "providers": {},
        }
        
        for provider in self._providers.keys():
            stats["providers"][provider] = {
                "token_count": sum(
                    1 for tokens in self._tokens.values()
                    if provider in tokens
                ),
                "expiry_buffer_minutes": self._providers[provider].expiry_buffer_minutes,
            }
        
        return stats
    
    async def initialize_from_env(
        self,
    ) -> None:
        """
        Initialize tokens from environment variables.
        
        This is useful for loading pre-existing tokens at startup.
        """
        # Google tokens
        if os.getenv("GOOGLE_ACCESS_TOKEN"):
            expiry = datetime.utcnow() + timedelta(hours=1)
            token = OAuthToken(
                access_token=os.getenv("GOOGLE_ACCESS_TOKEN", ""),
                refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN", ""),
                token_type="Bearer",
                expiry=expiry,
                provider=OAuthProvider.GOOGLE,
                user_id="default",
                status=TokenStatus.VALID,
            )
            self._store_token("default", "google", token)
            logger.info("Loaded Google token from environment")
        
        # Outlook tokens
        if os.getenv("OUTLOOK_ACCESS_TOKEN"):
            expiry = datetime.utcnow() + timedelta(hours=1)
            token = OAuthToken(
                access_token=os.getenv("OUTLOOK_ACCESS_TOKEN", ""),
                refresh_token=os.getenv("OUTLOOK_REFRESH_TOKEN", ""),
                token_type="Bearer",
                expiry=expiry,
                provider=OAuthProvider.OUTLOOK,
                user_id="default",
                status=TokenStatus.VALID,
            )
            self._store_token("default", "outlook", token)
            logger.info("Loaded Outlook token from environment")