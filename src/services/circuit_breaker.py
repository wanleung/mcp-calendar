"""
Circuit breaker implementation for provider API calls.

This module provides a standalone circuit breaker implementation
that can be used independently or integrated with the error handler.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from enum import Enum

from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker pattern."""
    failure_threshold: int = 5
    reset_timeout: int = 60
    half_open_requests: int = 3
    success_threshold: int = 2


@dataclass
class CircuitBreakerState:
    """State tracking for a circuit breaker."""
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    half_open_requests: int = 0


class CircuitBreaker:
    """
    Circuit breaker implementation for protecting against cascading failures.
    
    The circuit breaker pattern helps prevent cascading failures by:
    - Opening the circuit after N consecutive failures
    - Waiting for a reset timeout before testing again
    - Closing the circuit after successful half-open tests
    
    Attributes:
        config: Circuit breaker configuration
        state: Current circuit breaker state
    """
    
    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
    ):
        """
        Initialize the circuit breaker.
        
        Args:
            config: Circuit breaker configuration
        """
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitBreakerState()
    
    @property
    def state_str(self) -> str:
        """Get string representation of current state."""
        return self.state.state.value
    
    def is_open(self) -> bool:
        """
        Check if the circuit is open.
        
        Returns:
            True if circuit is open
        """
        return self.state.state == CircuitState.OPEN
    
    def is_closed(self) -> bool:
        """
        Check if the circuit is closed.
        
        Returns:
            True if circuit is closed
        """
        return self.state.state == CircuitState.CLOSED
    
    def is_half_open(self) -> bool:
        """
        Check if the circuit is half-open.
        
        Returns:
            True if circuit is half-open
        """
        return self.state.state == CircuitState.HALF_OPEN
    
    def record_success(self) -> None:
        """
        Record a successful call.
        
        If in half-open state, count towards success threshold.
        """
        self.state.success_count += 1
        self.state.last_success_time = datetime.utcnow()
        
        if self.state.state == CircuitState.HALF_OPEN:
            self.state.half_open_requests += 1
            
            if self.state.success_count >= self.config.success_threshold:
                self._close_circuit()
    
    def record_failure(self) -> None:
        """
        Record a failed call.
        
        If in half-open state, reset success count.
        If failure threshold reached, open the circuit.
        """
        self.state.failure_count += 1
        self.state.last_failure_time = datetime.utcnow()
        
        if self.state.state == CircuitState.HALF_OPEN:
            self.state.success_count = 0
            self.state.half_open_requests = 0
            self.state.state = CircuitState.OPEN
            logger.warning(
                f"Circuit breaker opened after half-open test failure"
            )
        elif self.state.failure_count >= self.config.failure_threshold:
            self.state.state = CircuitState.OPEN
            logger.warning(
                f"Circuit breaker opened after {self.state.failure_count} "
                f"consecutive failures"
            )
    
    def _close_circuit(self) -> None:
        """Close the circuit breaker."""
        self.state.state = CircuitState.CLOSED
        self.state.failure_count = 0
        self.state.success_count = 0
        self.state.half_open_requests = 0
        logger.info("Circuit breaker closed")
    
    def _half_open_circuit(self) -> None:
        """Transition to half-open state."""
        self.state.state = CircuitState.HALF_OPEN
        self.state.half_open_requests = 0
        logger.info(
            f"Circuit breaker half-open (timeout: "
            f"{self.config.reset_timeout}s)"
        )
    
    def should_allow_request(self) -> bool:
        """
        Check if a request should be allowed.
        
        Returns:
            True if request should proceed
        """
        if self.state.state == CircuitState.CLOSED:
            return True
        
        if self.state.state == CircuitState.OPEN:
            # Check if we should transition to half-open
            if self.state.last_failure_time:
                elapsed = (datetime.utcnow() - self.state.last_failure_time).total_seconds()
                if elapsed >= self.config.reset_timeout:
                    self._half_open_circuit()
                    return True
        
        return False
    
    def reset(self) -> None:
        """
        Manually reset the circuit breaker.
        """
        self.state.state = CircuitState.CLOSED
        self.state.failure_count = 0
        self.state.success_count = 0
        self.state.last_failure_time = None
        logger.info("Circuit breaker manually reset")
    
    def get_state(self) -> Dict[str, Any]:
        """
        Get the current circuit breaker state.
        
        Returns:
            Dictionary with state information
        """
        return {
            "state": self.state.state.value,
            "failure_count": self.state.failure_count,
            "success_count": self.state.success_count,
            "last_failure_time": self.state.last_failure_time.isoformat() if self.state.last_failure_time else None,
            "last_success_time": self.state.last_success_time.isoformat() if self.state.last_success_time else None,
            "half_open_requests": self.state.half_open_requests,
        }
    
    def __repr__(self) -> str:
        """String representation of the circuit breaker."""
        return f"CircuitBreaker(state={self.state.state.value}, failures={self.state.failure_count})"


class CircuitBreakerManager:
    """
    Manager for multiple circuit breakers (one per provider).
    
    This class manages circuit breakers for different providers
    (Google, Outlook, etc.) and provides a unified interface.
    """
    
    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
    ):
        """
        Initialize the circuit breaker manager.
        
        Args:
            config: Circuit breaker configuration (applied to all breakers)
        """
        self.config = config or CircuitBreakerConfig()
        self._breakers: Dict[str, CircuitBreaker] = {}
    
    def get_breaker(
        self,
        provider: str,
    ) -> CircuitBreaker:
        """
        Get or create a circuit breaker for a provider.
        
        Args:
            provider: Provider name
            
        Returns:
            CircuitBreaker instance
        """
        if provider not in self._breakers:
            self._breakers[provider] = CircuitBreaker(config=self.config)
        return self._breakers[provider]
    
    def record_success(
        self,
        provider: str,
    ) -> None:
        """
        Record a successful call for a provider.
        
        Args:
            provider: Provider name
        """
        breaker = self.get_breaker(provider)
        breaker.record_success()
    
    def record_failure(
        self,
        provider: str,
    ) -> None:
        """
        Record a failed call for a provider.
        
        Args:
            provider: Provider name
        """
        breaker = self.get_breaker(provider)
        breaker.record_failure()
    
    def should_allow_request(
        self,
        provider: str,
    ) -> bool:
        """
        Check if a request should be allowed for a provider.
        
        Args:
            provider: Provider name
            
        Returns:
            True if request should proceed
        """
        breaker = self.get_breaker(provider)
        return breaker.should_allow_request()
    
    def get_breaker_state(
        self,
        provider: str,
    ) -> Dict[str, Any]:
        """
        Get the circuit breaker state for a provider.
        
        Args:
            provider: Provider name
            
        Returns:
            Dictionary with state information
        """
        breaker = self.get_breaker(provider)
        return breaker.get_state()
    
    def reset_all(self) -> None:
        """
        Reset all circuit breakers.
        """
        for breaker in self._breakers.values():
            breaker.reset()
        logger.info("All circuit breakers reset")
    
    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """
        Get the state of all circuit breakers.
        
        Returns:
            Dictionary mapping provider names to state information
        """
        return {
            provider: breaker.get_state()
            for provider, breaker in self._breakers.items()
        }