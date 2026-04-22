"""
Retry decorator utilities for async functions.

This module provides decorators for implementing retry logic with
exponential backoff, jitter, and circuit breaker patterns.
"""

import asyncio
import functools
import logging
import random
from typing import Any, Callable, Optional, Dict

from src.services.error_handler import ErrorHandler, MCPErrors

logger = logging.getLogger(__name__)


def retry(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    multiplier: float = 2.0,
    jitter: float = 0.1,
    retryable_exceptions: tuple = (Exception,),
) -> Callable:
    """
    Decorator for adding retry logic to async functions.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        multiplier: Exponential multiplier for delay calculation
        jitter: Random jitter factor (0-1)
        retryable_exceptions: Tuple of exception types to retry on
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt < max_retries - 1:
                        # Calculate delay
                        delay = initial_delay * (multiplier ** attempt)
                        delay = min(delay, max_delay)
                        
                        # Add jitter
                        jitter_delay = delay * jitter
                        delay += random.uniform(0, jitter_delay)
                        
                        logger.info(
                            f"Retry {attempt + 1}/{max_retries} for "
                            f"{func.__name__} in {delay:.2f}s: {e}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"Max retries exceeded for {func.__name__}: "
                            f"{last_exception}"
                        )
            
            # All retries exhausted
            return {
                "success": False,
                "error": str(last_exception),
                "retry_count": max_retries,
            }
        
        return wrapper
    return decorator


def with_circuit_breaker(
    failure_threshold: int = 5,
    reset_timeout: int = 60,
) -> Callable:
    """
    Decorator for adding circuit breaker pattern to async functions.
    
    Args:
        failure_threshold: Number of failures before opening circuit
        reset_timeout: Seconds to wait before half-opening circuit
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Check circuit breaker state
            # Note: In production, this would use a shared circuit breaker instance
            # For now, we use a simple counter-based approach
            failure_count = getattr(wrapper, '_failure_count', 0)
            
            if failure_count >= failure_threshold:
                logger.warning(
                    f"Circuit breaker open for {func.__name__}, "
                    f"skipping call"
                )
                return {
                    "success": False,
                    "error": "Circuit breaker open",
                    "error_code": MCPErrors.SERVICE_UNAVAILABLE,
                }
            
            try:
                result = await func(*args, **kwargs)
                # Record success
                if hasattr(wrapper, '_failure_count'):
                    wrapper._failure_count = 0
                return result
            except Exception as e:
                # Record failure
                if hasattr(wrapper, '_failure_count'):
                    wrapper._failure_count += 1
                raise
        return wrapper
    return decorator


def rate_limited(
    max_requests: int = 100,
    time_window: int = 60,
) -> Callable:
    """
    Decorator for rate limiting async functions.
    
    Args:
        max_requests: Maximum requests per time window
        time_window: Time window in seconds
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Simple rate limiting using a counter
            # In production, use a proper rate limiter with thread safety
            request_count = getattr(wrapper, '_request_count', 0)
            
            if request_count >= max_requests:
                logger.warning(
                    f"Rate limit exceeded for {func.__name__}"
                )
                return {
                    "success": False,
                    "error": "Rate limit exceeded",
                    "error_code": MCPErrors.RATE_LIMITED,
                }
            
            # Record request
            if hasattr(wrapper, '_request_count'):
                wrapper._request_count += 1
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator