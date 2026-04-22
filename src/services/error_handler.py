"""
Error handler for Calendar MCP Service.

This module provides:
- MCP error code mapping from HTTP status codes
- Retry logic with exponential backoff
- Circuit breaker pattern for provider API failures
- Rate limit handling with Retry-After headers
- Error tracking and statistics

The error handler integrates with all provider calls and notification services
to ensure reliable operation with graceful degradation.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any, Callable, Type, Union
from functools import wraps
from dataclasses import dataclass, field
from enum import Enum

import aiohttp
from aiohttp import ClientError

from src.models.notification import NotificationStatus

# Configure logging
logger = logging.getLogger(__name__)


class MCPErrors(Enum):
    """MCP error codes as defined in the specification."""
    # Standard JSON-RPC 2.0 errors
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    # Custom errors for provider-specific issues
    REQUEST_TIMEOUT = -32000
    RATE_LIMITED = -32001
    SERVICE_UNAVAILABLE = -32002
    INVALID_CREDENTIALS = -32003
    EVENT_NOT_FOUND = -32004
    CALENDAR_NOT_FOUND = -32005
    RECURRING_EVENT_ERROR = -32006


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker pattern."""
    failure_threshold: int = 5  # Number of failures before opening
    reset_timeout: int = 60  # Seconds to wait before half-opening
    half_open_requests: int = 3  # Number of requests to test half-open
    success_threshold: int = 2  # Successes needed to close circuit


@dataclass
class RetryConfig:
    """Configuration for retry logic."""
    max_retries: int = 3
    initial_delay: float = 1.0  # Seconds
    max_delay: float = 60.0  # Seconds
    multiplier: float = 2.0  # Exponential multiplier
    jitter: float = 0.1  # Random jitter factor (0-1)


@dataclass
class CircuitBreakerState:
    """State tracking for a circuit breaker."""
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    half_open_requests: int = 0


class ErrorHandler:
    """
    Error handler for provider API calls and MCP protocol errors.
    
    This class provides:
    - HTTP to MCP error code mapping
    - Retry logic with exponential backoff
    - Circuit breaker pattern implementation
    - Rate limit handling
    
    Attributes:
        retry_config: Configuration for retry behavior
        circuit_breaker_config: Configuration for circuit breaker
        error_mapping: Dictionary mapping HTTP codes to MCP errors
    """
    
    def __init__(
        self,
        retry_config: Optional[RetryConfig] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
    ):
        """
        Initialize the error handler.
        
        Args:
            retry_config: Retry configuration (default: exponential backoff)
            circuit_breaker_config: Circuit breaker configuration
        """
        self.retry_config = retry_config or RetryConfig()
        self.circuit_breaker_config = circuit_breaker_config or CircuitBreakerConfig()
        
        # Circuit breaker state per provider
        self._circuit_breakers: Dict[str, CircuitBreakerState] = {}
        
        # Error mapping from HTTP status to MCP error codes
        self._error_mapping: Dict[int, MCPErrors] = {
            400: MCPErrors.INVALID_PARAMS,
            401: MCPErrors.INVALID_CREDENTIALS,
            403: MCPErrors.INVALID_CREDENTIALS,
            404: MCPErrors.EVENT_NOT_FOUND,
            405: MCPErrors.INVALID_PARAMS,
            409: MCPErrors.INVALID_PARAMS,
            422: MCPErrors.INVALID_PARAMS,
            429: MCPErrors.RATE_LIMITED,
            500: MCPErrors.INTERNAL_ERROR,
            502: MCPErrors.INTERNAL_ERROR,
            503: MCPErrors.SERVICE_UNAVAILABLE,
            504: MCPErrors.INTERNAL_ERROR,
        }
    
    def map_error(
        self,
        error: Union[Exception, int],
        error_code: Optional[int] = None,
    ) -> MCPErrors:
        """
        Map an error to an MCP error code.
        
        Args:
            error: Exception object or HTTP status code
            error_code: HTTP status code (optional, extracted from exception)
            
        Returns:
            MCP error code
        """
        # If error is an exception, extract status code
        if isinstance(error, Exception):
            if hasattr(error, 'status'):
                error_code = error.status
            elif isinstance(error, aiohttp.ClientError):
                if hasattr(error, 'status'):
                    error_code = error.status
                else:
                    # Timeout or other client error
                    return MCPErrors.REQUEST_TIMEOUT
        
        # Use provided error code or mapping
        if error_code is not None:
            return self._error_mapping.get(error_code, MCPErrors.INTERNAL_ERROR)
        
        # Default mapping for exceptions
        if isinstance(error, asyncio.TimeoutError):
            return MCPErrors.REQUEST_TIMEOUT
        elif isinstance(error, aiohttp.ClientError):
            return MCPErrors.REQUEST_TIMEOUT
        elif isinstance(error, ConnectionError):
            return MCPErrors.SERVICE_UNAVAILABLE
        else:
            return MCPErrors.INTERNAL_ERROR
    
    def get_mcp_error_message(
        self,
        error_code: MCPErrors,
        error_details: Optional[str] = None,
    ) -> str:
        """
        Get a human-readable error message for an MCP error code.
        
        Args:
            error_code: MCP error code
            error_details: Additional error details
            
        Returns:
            Human-readable error message
        """
        messages = {
            MCPErrors.PARSE_ERROR: "Invalid JSON received",
            MCPErrors.INVALID_REQUEST: "Invalid request format",
            MCPErrors.METHOD_NOT_FOUND: "Method not found",
            MCPErrors.INVALID_PARAMS: "Invalid parameters provided",
            MCPErrors.INTERNAL_ERROR: "Internal server error",
            MCPErrors.REQUEST_TIMEOUT: "Request timed out",
            MCPErrors.RATE_LIMITED: "Rate limit exceeded",
            MCPErrors.SERVICE_UNAVAILABLE: "Service temporarily unavailable",
            MCPErrors.INVALID_CREDENTIALS: "Invalid or expired credentials",
            MCPErrors.EVENT_NOT_FOUND: "Event not found",
            MCPErrors.CALENDAR_NOT_FOUND: "Calendar not found",
            MCPErrors.RECURRING_EVENT_ERROR: "Recurring event operation failed",
        }
        
        base_message = messages.get(error_code, "An error occurred")
        
        if error_details:
            return f"{base_message}: {error_details}"
        
        return base_message
    
    def handle_rate_limit(
        self,
        response: aiohttp.ClientResponse,
    ) -> Dict[str, Any]:
        """
        Handle a rate limit response (429).
        
        Args:
            response: HTTP response from provider
            
        Returns:
            Dictionary with handling information
        """
        retry_after = int(response.headers.get("Retry-After", 60))
        
        logger.warning(
            f"Rate limited by provider, waiting {retry_after} seconds"
        )
        
        return {
            "action": "wait",
            "retry_after": retry_after,
            "error_code": MCPErrors.RATE_LIMITED,
        }
    
    async def handle_timeout(
        self,
        timeout: aiohttp.ClientTimeout,
    ) -> Dict[str, Any]:
        """
        Handle a timeout error.
        
        Args:
            timeout: Timeout configuration
            
        Returns:
            Dictionary with handling information
        """
        logger.error("Request timed out")
        
        return {
            "action": "retry",
            "error_code": MCPErrors.REQUEST_TIMEOUT,
            "retry_after": self.retry_config.initial_delay,
        }
    
    async def execute_with_retry(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a function with retry logic.
        
        Args:
            func: Async function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
            
        Returns:
            Function result or error information
        """
        last_error: Optional[Exception] = None
        last_error_code: Optional[int] = None
        
        for attempt in range(1, self.retry_config.max_retries + 1):
            try:
                result = await func(*args, **kwargs)
                return result
                
            except Exception as e:
                last_error = e
                last_error_code = self.map_error(e)
                
                # Check if we should retry
                if attempt < self.retry_config.max_retries:
                    # Check for rate limit
                    if isinstance(e, aiohttp.ClientResponseError) and e.status == 429:
                        retry_after = int(e.headers.get("Retry-After", 60))
                        logger.info(
                            f"Rate limited, waiting {retry_after} seconds "
                            f"(attempt {attempt}/{self.retry_config.max_retries})"
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    
                    # Calculate delay with jitter
                    delay = self._calculate_retry_delay(attempt)
                    logger.info(
                        f"Retry {attempt}/{self.retry_config.max_retries} "
                        f"in {delay:.2f}s: {last_error}"
                    )
                    await asyncio.sleep(delay)
                else:
                    # Max retries exceeded
                    logger.error(
                        f"Max retries exceeded for {func.__name__}: "
                        f"{last_error}"
                    )
                    return {
                        "success": False,
                        "error": str(last_error),
                        "error_code": last_error_code,
                        "retry_count": attempt,
                    }
        
        return {
            "success": True,
            "result": None,
        }
    
    def _calculate_retry_delay(
        self,
        attempt: int,
    ) -> float:
        """
        Calculate the delay before the next retry attempt.
        
        Args:
            attempt: Current attempt number (1-indexed)
            
        Returns:
            Delay in seconds before next retry
        """
        delay = self.retry_config.initial_delay * (
            self.retry_config.multiplier ** (attempt - 1)
        )
        
        # Apply jitter
        jitter = delay * self.retry_config.jitter
        delay += jitter if jitter > 0 else 0
        
        # Cap at max delay
        delay = min(delay, self.retry_config.max_delay)
        
        return delay
    
    def check_circuit_breaker(
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
        state = self._circuit_breakers.get(provider, CircuitBreakerState())
        
        if state.state == CircuitState.OPEN:
            # Check if we should half-open
            if state.last_failure_time:
                elapsed = (datetime.utcnow() - state.last_failure_time).total_seconds()
                if elapsed >= self.circuit_breaker_config.reset_timeout:
                    state.state = CircuitState.HALF_OPEN
                    state.half_open_requests = 0
                    state.failure_count = 0
                    logger.info(
                        f"Circuit breaker half-open for {provider} "
                        f"(elapsed: {elapsed:.0f}s)"
                    )
        
        return state.state == CircuitState.OPEN
    
    async def record_circuit_breaker_failure(
        self,
        provider: str,
    ) -> None:
        """
        Record a failure and potentially open the circuit breaker.
        
        Args:
            provider: Provider name
        """
        state = self._circuit_breakers.setdefault(provider, CircuitBreakerState())
        
        state.failure_count += 1
        state.last_failure_time = datetime.utcnow()
        
        if state.failure_count >= self.circuit_breaker_config.failure_threshold:
            state.state = CircuitState.OPEN
            logger.warning(
                f"Circuit breaker opened for {provider} after "
                f"{state.failure_count} consecutive failures"
            )
    
    async def record_circuit_breaker_success(
        self,
        provider: str,
    ) -> None:
        """
        Record a success and potentially close the circuit breaker.
        
        Args:
            provider: Provider name
        """
        state = self._circuit_breakers.get(provider)
        if not state:
            return
        
        state.last_success_time = datetime.utcnow()
        
        if state.state == CircuitState.HALF_OPEN:
            state.half_open_requests += 1
            
            if state.half_open_requests >= self.circuit_breaker_config.half_open_requests:
                # Test completed successfully, close circuit
                state.state = CircuitState.CLOSED
                state.failure_count = 0
                state.half_open_requests = 0
                logger.info(
                    f"Circuit breaker closed for {provider} "
                    f"(successful half-open test)"
                )
    
    def get_circuit_breaker_state(
        self,
        provider: str,
    ) -> CircuitBreakerState:
        """
        Get the current circuit breaker state for a provider.
        
        Args:
            provider: Provider name
            
        Returns:
            CircuitBreakerState object
        """
        return self._circuit_breakers.get(provider, CircuitBreakerState())
    
    def reset_circuit_breaker(
        self,
        provider: str,
    ) -> None:
        """
        Manually reset the circuit breaker for a provider.
        
        Args:
            provider: Provider name
        """
        state = self._circuit_breakers.get(provider)
        if state:
            state.state = CircuitState.CLOSED
            state.failure_count = 0
            state.last_failure_time = None
            logger.info(f"Circuit breaker manually reset for {provider}")
    
    def get_error_statistics(
        self,
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get error statistics for a provider or all providers.
        
        Args:
            provider: Provider name (None for all)
            
        Returns:
            Dictionary with error statistics
        """
        stats = {
            "providers": {},
            "total_failures": 0,
            "total_successes": 0,
        }
        
        if provider:
            state = self._circuit_breakers.get(provider)
            if state:
                stats["providers"][provider] = {
                    "state": state.state.value,
                    "failure_count": state.failure_count,
                    "last_failure_time": state.last_failure_time.isoformat() if state.last_failure_time else None,
                    "last_success_time": state.last_success_time.isoformat() if state.last_success_time else None,
                }
        else:
            for provider_name, state in self._circuit_breakers.items():
                stats["providers"][provider_name] = {
                    "state": state.state.value,
                    "failure_count": state.failure_count,
                    "last_failure_time": state.last_failure_time.isoformat() if state.last_failure_time else None,
                    "last_success_time": state.last_success_time.isoformat() if state.last_success_time else None,
                }
        
        return stats
    
    def create_retry_decorator(
        self,
        max_retries: Optional[int] = None,
        initial_delay: Optional[float] = None,
        max_delay: Optional[float] = None,
    ) -> Callable:
        """
        Create a retry decorator for async functions.
        
        Args:
            max_retries: Maximum number of retries (uses default if None)
            initial_delay: Initial delay in seconds (uses default if None)
            max_delay: Maximum delay in seconds (uses default if None)
            
        Returns:
            Decorator function
        """
        config = RetryConfig(
            max_retries=max_retries or self.retry_config.max_retries,
            initial_delay=initial_delay or self.retry_config.initial_delay,
            max_delay=max_delay or self.retry_config.max_delay,
        )
        
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                return await self.execute_with_retry(func, *args, **kwargs)
            return wrapper
        return decorator
    
    def create_circuit_breaker_decorator(
        self,
        provider: str,
    ) -> Callable:
        """
        Create a circuit breaker decorator for async functions.
        
        Args:
            provider: Provider name
            
        Returns:
            Decorator function
        """
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Check circuit breaker
                if self.check_circuit_breaker(provider):
                    logger.warning(
                        f"Circuit breaker open for {provider}, "
                        f"skipping {func.__name__}"
                    )
                    return {
                        "success": False,
                        "error": "Circuit breaker open",
                        "error_code": MCPErrors.SERVICE_UNAVAILABLE,
                    }
                
                try:
                    result = await func(*args, **kwargs)
                    # Record success
                    await self.record_circuit_breaker_success(provider)
                    return result
                except Exception as e:
                    # Record failure
                    await self.record_circuit_breaker_failure(provider)
                    raise
            return wrapper
        return decorator
    
    def handle_notification_error(
        self,
        error: Exception,
        notification_id: str,
        provider: str,
    ) -> Dict[str, Any]:
        """
        Handle an error during notification delivery.
        
        Args:
            error: Exception raised
            notification_id: Notification identifier
            provider: Provider name
            
        Returns:
            Dictionary with error handling information
        """
        error_code = self.map_error(error)
        
        logger.error(
            f"Notification delivery failed for {notification_id}: "
            f"{error} (code: {error_code.value})"
        )
        
        return {
            "success": False,
            "notification_id": notification_id,
            "error": str(error),
            "error_code": error_code,
            "provider": provider,
        }
    
    def handle_provider_error(
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
        asyncio.run(self.record_circuit_breaker_failure(provider))
        
        # Map error to MCP error codes
        mcp_error_code = self.map_error(error, error_code)
        
        logger.error(
            f"Provider error for {provider}: {error} (MCP code: {mcp_error_code.value})"
        )
        
        return {
            "success": False,
            "error": str(error),
            "mcp_error_code": mcp_error_code.value,
            "provider": provider,
            "error_code": error_code,
        }