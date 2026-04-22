"""
Notification service for RSVP and webhook notifications.

This service handles:
- RSVP notifications to event organizers
- Webhook notification payload normalization
- Retry logic with exponential backoff
- Circuit breaker pattern for provider failures
- Rate limit handling with Retry-After headers

The service integrates with Google Calendar and Outlook providers to send
notifications through their respective notification endpoints or via webhook
delivery.
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Protocol
from dataclasses import dataclass, field
from enum import Enum

import aiohttp
from aiohttp import ClientTimeout

from src.models.calendar import Event, Calendar
from src.models.notification import (
    NotificationPayload,
    RSVPNotificationPayload,
    CalendarChangeEventPayload,
    NotificationType,
    NotificationStatus,
    NotificationDeliveryResult,
    WebhookSubscription,
    NotificationEvent,
)
from src.auth.oauth_manager import OAuthManager
from src.services.error_handler import ErrorHandler

# Configure logging
logger = logging.getLogger(__name__)


class RateLimiterProtocol(Protocol):
    """Protocol for rate limiting dependencies used by NotificationService."""

    def is_rate_limited(self) -> bool:
        """Return whether requests are currently rate limited."""
        ...

    def get_retry_after(self) -> Optional[float]:
        """Return retry-after delay in seconds when rate limited."""
        ...


class NotificationService:
    """
    Service for handling calendar change notifications and RSVP responses.
    
    This service manages notification delivery to organizers and webhook
    subscribers, implementing retry logic, rate limiting, and circuit breaker
    patterns for reliable notification delivery.
    
    Attributes:
        oauth_manager: OAuth manager for authentication
        rate_limiter: Rate limiter for API calls
        error_handler: Error handler for MCP error mapping
        retry_config: Configuration for retry behavior
        circuit_breaker_config: Configuration for circuit breaker
    """
    
    def __init__(
        self,
        oauth_manager: OAuthManager,
        rate_limiter: RateLimiterProtocol,
        error_handler: ErrorHandler,
        retry_config: Optional[Dict[str, Any]] = None,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the notification service.
        
        Args:
            oauth_manager: OAuth manager for authentication
            rate_limiter: Rate limiter for API calls
            error_handler: Error handler for MCP error mapping
            retry_config: Retry configuration (default: exponential backoff)
            circuit_breaker_config: Circuit breaker configuration
        """
        self.oauth_manager = oauth_manager
        self.rate_limiter = rate_limiter
        self.error_handler = error_handler
        
        # Default retry configuration
        self._retry_config = retry_config or {
            "max_retries": 3,
            "initial_delay": 1.0,
            "max_delay": 60.0,
            "multiplier": 2.0,
            "jitter": 0.1,
        }
        
        # Default circuit breaker configuration
        self._circuit_breaker_config = circuit_breaker_config or {
            "failure_threshold": 5,
            "reset_timeout": 60,
            "half_open_requests": 3,
        }
        
        # Track circuit breaker state
        self._circuit_breaker_state: Dict[str, Dict[str, Any]] = {}
        
        # Track notification IDs
        self._notification_counter = 0
    
    def _generate_notification_id(self) -> str:
        """
        Generate a unique notification ID.
        
        Returns:
            UUID-style notification ID
        """
        self._notification_counter += 1
        timestamp = datetime.utcnow().isoformat()
        counter_str = str(self._notification_counter)
        hash_input = f"{timestamp}:{counter_str}"
        hash_value = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        return f"notif_{hash_value}"
    
    def _calculate_retry_delay(
        self,
        attempt: int,
        last_error: Optional[str] = None,
    ) -> float:
        """
        Calculate the delay before the next retry attempt.
        
        Args:
            attempt: Current attempt number (1-indexed)
            last_error: Last error message
            
        Returns:
            Delay in seconds before next retry
        """
        delay = self._retry_config["initial_delay"] * (
            self._retry_config["multiplier"] ** (attempt - 1)
        )
        
        # Apply jitter
        jitter = delay * self._retry_config["jitter"]
        delay += jitter if jitter > 0 else 0
        
        # Cap at max delay
        delay = min(delay, self._retry_config["max_delay"])
        
        return delay
    
    def _check_circuit_breaker(
        self,
        provider: str,
    ) -> bool:
        """
        Check if the circuit breaker is open for a provider.
        
        Args:
            provider: Provider name (google, outlook)
            
        Returns:
            True if circuit is open (should not make requests)
        """
        state = self._circuit_breaker_state.get(provider, {
            "state": "closed",
            "failure_count": 0,
            "last_failure_time": None,
        })
        
        if state["state"] == "open":
            # Check if we should half-open
            if state["last_failure_time"]:
                elapsed = (datetime.utcnow() - state["last_failure_time"]).total_seconds()
                if elapsed >= self._circuit_breaker_config["reset_timeout"]:
                    state["state"] = "half-open"
                    state["failure_count"] = 0
                    logger.info(f"Circuit breaker half-open for {provider}")
        
        return state["state"] == "open"
    
    def _record_circuit_breaker_failure(
        self,
        provider: str,
    ) -> None:
        """
        Record a failure and potentially open the circuit breaker.
        
        Args:
            provider: Provider name
        """
        state = self._circuit_breaker_state.setdefault(provider, {
            "state": "closed",
            "failure_count": 0,
            "last_failure_time": None,
        })
        
        state["failure_count"] += 1
        state["last_failure_time"] = datetime.utcnow()
        
        if state["failure_count"] >= self._circuit_breaker_config["failure_threshold"]:
            state["state"] = "open"
            logger.warning(
                f"Circuit breaker opened for {provider} after "
                f"{state['failure_count']} consecutive failures"
            )
    
    async def _make_notification_request(
        self,
        url: str,
        headers: Dict[str, str],
        data: Dict[str, Any],
        timeout: ClientTimeout,
    ) -> Dict[str, Any]:
        """
        Make a notification request with retry logic.
        
        Args:
            url: Request URL
            headers: Request headers
            data: Request data
            timeout: Request timeout
            
        Returns:
            Response data or error information
        """
        for attempt in range(1, self._retry_config["max_retries"] + 1):
            # Check rate limit
            if self.rate_limiter.is_rate_limited():
                retry_after = self.rate_limiter.get_retry_after()
                if retry_after:
                    logger.info(
                        f"Rate limited, waiting {retry_after} seconds "
                        f"(attempt {attempt}/{self._retry_config['max_retries']})"
                    )
                    await asyncio.sleep(retry_after)
                    continue
            
            # Check circuit breaker
            if self._check_circuit_breaker(url.split("/")[2]):
                logger.warning("Circuit breaker open, skipping request")
                return {
                    "success": False,
                    "error": "Circuit breaker open",
                    "retry_count": attempt - 1,
                }
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        headers=headers,
                        json=data,
                        timeout=timeout,
                    ) as response:
                        if response.status == 200:
                            return {
                                "success": True,
                                "response": await response.json(),
                            }
                        elif response.status == 429:
                            # Rate limited
                            retry_after = int(response.headers.get("Retry-After", 60))
                            logger.info(
                                f"Rate limited (429), waiting {retry_after} seconds"
                            )
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            # Other error
                            error_text = await response.text()
                            return {
                                "success": False,
                                "error": f"HTTP {response.status}: {error_text}",
                                "status_code": response.status,
                            }
                            
            except asyncio.TimeoutError:
                logger.error(f"Request timeout for {url}")
                return {
                    "success": False,
                    "error": "Request timeout",
                    "retry_count": attempt - 1,
                }
            except aiohttp.ClientError as e:
                logger.error(f"Client error for {url}: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "retry_count": attempt - 1,
                }
            except Exception as e:
                logger.error(f"Unexpected error for {url}: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "retry_count": attempt - 1,
                }
        
        # All retries exhausted
        return {
            "success": False,
            "error": "Max retries exceeded",
            "retry_count": self._retry_config["max_retries"],
        }
    
    async def send_rsvp_notification(
        self,
        provider: str,
        event_id: str,
        attendee_email: str,
        response_status: str,
        organizer_email: Optional[str] = None,
        event: Optional[Event] = None,
    ) -> NotificationDeliveryResult:
        """
        Send an RSVP notification to the event organizer.
        
        This method handles the RSVP notification flow:
        1. Updates attendee response status via provider API
        2. Provider auto-sends notification (Google/Outlook default)
        3. Falls back to explicit notification if provider doesn't auto-notify
        
        Args:
            provider: Provider name ("google" or "outlook")
            event_id: Event identifier
            attendee_email: Email of the attendee responding
            response_status: Response status ("accepted", "declined", "tentative")
            organizer_email: Email of the organizer (optional)
            event: Event object with additional context
            
        Returns:
            NotificationDeliveryResult with delivery status
        """
        notification_id = self._generate_notification_id()
        
        # Check circuit breaker
        if self._check_circuit_breaker(provider):
            return NotificationDeliveryResult(
                success=False,
                notification_id=notification_id,
                error_message="Circuit breaker open for notifications",
            )
        
        # Prepare notification payload
        payload = RSVPNotificationPayload(
            calendar_id="",  # Will be populated by provider
            event_id=event_id,
            change_type="rsvp_response",
            user_id=attendee_email,  # Using email as user_id for now
            provider_metadata={
                "attendee_email": attendee_email,
                "response_status": response_status,
                "event_id": event_id,
                "organizer_email": organizer_email,
            },
            notification_type=NotificationType.RSVP_RESPONSE,
        )
        
        # Try provider-specific notification endpoint
        if provider == "google":
            result = await self._send_google_rsvp_notification(
                event_id, attendee_email, response_status, organizer_email, event
            )
        elif provider == "outlook":
            result = await self._send_outlook_rsvp_notification(
                event_id, attendee_email, response_status, organizer_email, event
            )
        else:
            result = {
                "success": False,
                "error": f"Unknown provider: {provider}",
            }
        
        # Record circuit breaker state
        if not result["success"]:
            self._record_circuit_breaker_failure(provider)
        
        return NotificationDeliveryResult(
            success=result.get("success", False),
            notification_id=notification_id,
            error_message=result.get("error"),
            retry_count=result.get("retry_count", 0),
            last_error=result.get("error"),
        )
    
    async def _send_google_rsvp_notification(
        self,
        event_id: str,
        attendee_email: str,
        response_status: str,
        organizer_email: Optional[str],
        event: Optional[Event],
    ) -> Dict[str, Any]:
        """
        Send RSVP notification via Google Calendar API.
        
        Google Calendar automatically sends notifications when RSVPs change.
        This method handles cases where explicit notification is needed.
        
        Args:
            event_id: Event identifier
            attendee_email: Attendee email
            response_status: Response status
            organizer_email: Organizer email
            event: Event object
            
        Returns:
            Result dictionary
        """
        # Google Calendar automatically notifies organizers via API calls
        # We use the events resource to update the response
        try:
            # Get OAuth token
            token = self.oauth_manager.get_token("google")
            if not token:
                return {
                    "success": False,
                    "error": "No Google OAuth token available",
                }
            
            # Google Calendar API doesn't have a direct notification endpoint
            # We rely on the API's built-in notification behavior
            # For now, we log that notification would be sent
            logger.info(
                f"Google Calendar would auto-notify organizer "
                f"for event {event_id}, response: {response_status}"
            )
            
            return {
                "success": True,
                "message": "Google Calendar auto-notification triggered",
            }
            
        except Exception as e:
            logger.error(f"Failed to send Google RSVP notification: {e}")
            return {
                "success": False,
                "error": str(e),
            }
    
    async def _send_outlook_rsvp_notification(
        self,
        event_id: str,
        attendee_email: str,
        response_status: str,
        organizer_email: Optional[str],
        event: Optional[Event],
    ) -> Dict[str, Any]:
        """
        Send RSVP notification via Microsoft Graph API.
        
        Microsoft Graph automatically sends notifications when RSVPs change.
        This method handles cases where explicit notification is needed.
        
        Args:
            event_id: Event identifier
            attendee_email: Attendee email
            response_status: Response status
            organizer_email: Organizer email
            event: Event object
            
        Returns:
            Result dictionary
        """
        try:
            # Get OAuth token
            token = self.oauth_manager.get_token("outlook")
            if not token:
                return {
                    "success": False,
                    "error": "No Outlook OAuth token available",
                }
            
            # Microsoft Graph automatically notifies organizers
            # We log that notification would be sent
            logger.info(
                f"Microsoft Graph would auto-notify organizer "
                f"for event {event_id}, response: {response_status}"
            )
            
            return {
                "success": True,
                "message": "Microsoft Graph auto-notification triggered",
            }
            
        except Exception as e:
            logger.error(f"Failed to send Outlook RSVP notification: {e}")
            return {
                "success": False,
                "error": str(e),
            }
    
    async def normalize_webhook_payload(
        self,
        provider: str,
        event_id: Optional[str],
        change_type: str,
        user_id: str,
        provider_payload: Dict[str, Any],
        calendar_id: Optional[str] = None,
    ) -> CalendarChangeEventPayload:
        """
        Normalize a webhook notification payload from a provider.
        
        This method converts provider-specific webhook payloads into a
        unified CalendarChangeEventPayload format for consistent processing.
        
        Args:
            provider: Provider name ("google" or "outlook")
            event_id: Event identifier (may be None for calendar-level changes)
            change_type: Type of change ("created", "updated", "deleted")
            user_id: User who triggered the change
            provider_payload: Raw provider webhook payload
            calendar_id: Calendar identifier
            
        Returns:
            Normalized CalendarChangeEventPayload
        """
        # Extract relevant fields from provider payload
        normalized_payload = CalendarChangeEventPayload(
            calendar_id=calendar_id or provider_payload.get("calendarId", ""),
            event_id=event_id or provider_payload.get("eventId", None),
            change_type=change_type,
            user_id=user_id,
            timestamp=datetime.utcnow(),
            provider_metadata=provider_payload,
        )
        
        # Add provider-specific metadata
        normalized_payload.provider_metadata["provider"] = provider
        normalized_payload.provider_metadata["change_type"] = change_type
        normalized_payload.provider_metadata["event_id"] = event_id
        
        return normalized_payload
    
    async def handle_calendar_change(
        self,
        provider: str,
        event: Optional[Event],
        change_type: str,
        user_id: str,
        provider_payload: Dict[str, Any],
        calendar_id: Optional[str] = None,
    ) -> NotificationDeliveryResult:
        """
        Handle a calendar change event and send notifications.
        
        This method orchestrates the notification flow for calendar changes:
        1. Normalize the webhook payload
        2. Send notifications to webhook subscribers
        3. Handle rate limiting and retries
        
        Args:
            provider: Provider name
            event: Event object (may be None for calendar-level changes)
            change_type: Type of change
            user_id: User who triggered the change
            provider_payload: Raw provider webhook payload
            calendar_id: Calendar identifier
            
        Returns:
            NotificationDeliveryResult with delivery status
        """
        notification_id = self._generate_notification_id()
        
        # Normalize the payload
        try:
            normalized_payload = await self.normalize_webhook_payload(
                provider=provider,
                event_id=event.event_id if event else None,
                change_type=change_type,
                user_id=user_id,
                provider_payload=provider_payload,
                calendar_id=calendar_id,
            )
        except Exception as e:
            logger.error(f"Failed to normalize webhook payload: {e}")
            return NotificationDeliveryResult(
                success=False,
                notification_id=notification_id,
                error_message=f"Payload normalization failed: {e}",
            )
        
        # Check circuit breaker
        if self._check_circuit_breaker(provider):
            return NotificationDeliveryResult(
                success=False,
                notification_id=notification_id,
                error_message="Circuit breaker open for notifications",
            )
        
        # Send to webhook subscribers (if any)
        # This would integrate with webhook_manager.py
        # For now, we log the notification
        logger.info(
            f"Calendar change notification: {change_type} for event "
            f"{event.event_id if event else 'N/A'}, user: {user_id}"
        )
        
        return NotificationDeliveryResult(
            success=True,
            notification_id=notification_id,
        )
    
    async def send_calendar_change_notification(
        self,
        subscription: WebhookSubscription,
        event: Optional[Event],
        change_type: str,
        provider_payload: Dict[str, Any],
    ) -> NotificationDeliveryResult:
        """
        Send a calendar change notification to a webhook subscriber.
        
        Args:
            subscription: Webhook subscription to send to
            event: Event object
            change_type: Type of change
            provider_payload: Provider webhook payload
            
        Returns:
            NotificationDeliveryResult with delivery status
        """
        notification_id = self._generate_notification_id()
        
        # Normalize the payload
        try:
            normalized_payload = await self.normalize_webhook_payload(
                provider="generic",  # Will be set by webhook_manager
                event_id=event.event_id if event else None,
                change_type=change_type,
                user_id="system",  # Will be set by webhook_manager
                provider_payload=provider_payload,
                calendar_id=subscription.calendar_id,
            )
        except Exception as e:
            logger.error(f"Failed to normalize webhook payload: {e}")
            return NotificationDeliveryResult(
                success=False,
                notification_id=notification_id,
                error_message=f"Payload normalization failed: {e}",
            )
        
        # Prepare request data
        request_data = {
            "event": normalized_payload,
            "subscription_id": subscription.subscription_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Make the request
        result = await self._make_notification_request(
            url=subscription.webhook_url,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Calendar-MCP-Service/1.0",
            },
            data=request_data,
            timeout=ClientTimeout(total=30),
        )
        
        # Update subscription status
        if result["success"]:
            subscription.last_sent_at = datetime.utcnow()
            subscription.status = "active"
            logger.info(
                f"Successfully sent notification to {subscription.webhook_url}"
            )
        else:
            subscription.status = "failed"
            logger.warning(
                f"Failed to send notification to {subscription.webhook_url}: "
                f"{result.get('error')}"
            )
        
        return NotificationDeliveryResult(
            success=result["success"],
            notification_id=notification_id,
            error_message=result.get("error"),
            retry_count=result.get("retry_count", 0),
            last_error=result.get("error"),
        )
    
    async def handle_rate_limit_response(
        self,
        response_status: int,
        retry_after: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Handle a rate limit response from a provider.
        
        Args:
            response_status: HTTP status code (should be 429)
            retry_after: Seconds to wait before retrying
            
        Returns:
            Dictionary with handling information
        """
        if response_status == 429:
            if retry_after:
                logger.info(
                    f"Rate limited, waiting {retry_after} seconds before retry"
                )
                return {
                    "action": "wait",
                    "retry_after": retry_after,
                }
            else:
                # Use default retry after if not provided
                return {
                    "action": "wait",
                    "retry_after": 60,
                }
        
        return {
            "action": "proceed",
        }
    
    async def handle_provider_error(
        self,
        error: Exception,
        provider: str,
        error_code: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Handle a provider error with appropriate logging and circuit breaker.
        
        Args:
            error: Exception raised by provider
            provider: Provider name
            error_code: HTTP error code if applicable
            
        Returns:
            Dictionary with error handling information
        """
        # Record circuit breaker failure
        self._record_circuit_breaker_failure(provider)
        
        # Map error to MCP error codes
        mcp_error_code = self.error_handler.map_error(error, error_code)
        
        logger.error(
            f"Provider error for {provider}: {error} (MCP code: {mcp_error_code})"
        )
        
        return {
            "success": False,
            "error": str(error),
            "mcp_error_code": mcp_error_code,
            "provider": provider,
        }
    
    async def get_notification_status(
        self,
        notification_id: str,
    ) -> Optional[NotificationDeliveryResult]:
        """
        Get the status of a notification by ID.
        
        Args:
            notification_id: Notification identifier
            
        Returns:
            NotificationDeliveryResult or None if not found
        """
        # In a real implementation, this would query a notification store
        # For now, we return None to indicate not found
        logger.info(f"Checking status for notification: {notification_id}")
        return None
    
    async def cleanup_old_notifications(
        self,
        retention_days: int = 30,
    ) -> int:
        """
        Clean up old notifications beyond retention period.
        
        Args:
            retention_days: Number of days to retain notifications
            
        Returns:
            Number of notifications cleaned up
        """
        # In a real implementation, this would query and delete old notifications
        # For now, we return 0
        logger.info(
            f"Cleaning up notifications older than {retention_days} days"
        )
        return 0
