"""
Webhook subscription and event models for Calendar MCP Service.

This module defines data structures for webhook subscriptions,
calendar change events, and subscription management.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class ChangeType(Enum):
    """Types of calendar changes that trigger webhook notifications."""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    CALENDAR_CREATED = "calendar_created"
    CALENDAR_UPDATED = "calendar_updated"
    CALENDAR_DELETED = "calendar_deleted"


class SubscriptionStatus(Enum):
    """Status of a webhook subscription."""
    ACTIVE = "active"
    EXPIRING = "expiring"
    EXPIRED = "expired"
    FAILED = "failed"
    SUSPENDED = "suspended"


@dataclass
class CalendarChangeEvent:
    """
    Calendar change event payload for webhook notifications.
    
    This model represents a normalized calendar change event that is
    sent to webhook subscribers when calendar events are created,
    updated, or deleted.
    
    Attributes:
        calendar_id: The calendar identifier
        event_id: The event identifier (None for calendar-level changes)
        change_type: Type of change ("created", "updated", "deleted")
        user_id: The user who triggered the change
        timestamp: When the change occurred
        provider_metadata: Raw provider payload for debugging
    """
    calendar_id: str
    event_id: Optional[str] = None
    change_type: str = ChangeType.CREATED.value
    user_id: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    provider_metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "calendar_id": self.calendar_id,
            "event_id": self.event_id,
            "change_type": self.change_type,
            "user_id": self.user_id,
            "timestamp": self.timestamp.isoformat(),
            "provider_metadata": self.provider_metadata,
        }


@dataclass
class WebhookSubscription:
    """
    Webhook subscription for calendar change notifications.
    
    This model represents a subscription to receive webhook notifications
    for calendar changes on a specific calendar or event.
    
    Attributes:
        subscription_id: Unique identifier for the subscription
        webhook_url: URL to send notifications to
        calendar_id: The calendar being monitored
        event_id: The event being monitored (None for calendar-level)
        change_types: List of change types to monitor
        created_at: When the subscription was created
        expires_at: When the subscription expires
        last_sent_at: Last time a notification was sent
        last_retry_at: Last time a retry was attempted
        retry_after: Seconds to wait before retrying (None if not retrying)
        status: Current subscription status
        user_id: User who owns the subscription
        provider: Provider name (google, outlook)
    """
    subscription_id: str
    webhook_url: str
    calendar_id: str
    event_id: Optional[str] = None
    change_types: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime
    last_sent_at: Optional[datetime] = None
    last_retry_at: Optional[datetime] = None
    retry_after: Optional[int] = None
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    user_id: str = ""
    provider: str = "google"
    
    def is_expiring_soon(self, hours: int = 48) -> bool:
        """
        Check if subscription is expiring within the specified hours.
        
        Args:
            hours: Number of hours to check
            
        Returns:
            True if subscription is expiring soon
        """
        from datetime import timedelta
        threshold = datetime.utcnow() + timedelta(hours=hours)
        return self.expires_at <= threshold
    
    def is_active(self) -> bool:
        """
        Check if subscription is active.
        
        Returns:
            True if subscription is active
        """
        return self.status == SubscriptionStatus.ACTIVE
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "subscription_id": self.subscription_id,
            "webhook_url": self.webhook_url,
            "calendar_id": self.calendar_id,
            "event_id": self.event_id,
            "change_types": self.change_types,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "last_sent_at": self.last_sent_at.isoformat() if self.last_sent_at else None,
            "last_retry_at": self.last_retry_at.isoformat() if self.last_retry_at else None,
            "retry_after": self.retry_after,
            "status": self.status.value,
            "user_id": self.user_id,
            "provider": self.provider,
        }


@dataclass
class WebhookSubscriptionResult:
    """
    Result of a webhook subscription operation.
    
    Attributes:
        success: Whether the operation succeeded
        subscription_id: Subscription identifier if created
        error_message: Error message if operation failed
        retry_count: Number of retry attempts made
    """
    success: bool
    subscription_id: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0


@dataclass
class WebhookDeliveryResult:
    """
    Result of a webhook delivery attempt.
    
    Attributes:
        success: Whether the delivery succeeded
        subscription_id: Subscription identifier
        event_id: Event identifier for the change event
        error_message: Error message if delivery failed
        retry_count: Number of retry attempts made
        status_code: HTTP status code from response (if applicable)
    """
    success: bool
    subscription_id: str
    event_id: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    status_code: Optional[int] = None


@dataclass
class SubscriptionAlert:
    """
    Alert for subscription events (expiration, failure, etc.).
    
    Attributes:
        alert_id: Unique identifier for the alert
        subscription_id: Subscription identifier
        alert_type: Type of alert (EXPIRING, FAILED, etc.)
        message: Alert message
        severity: Severity level (INFO, WARNING, ERROR)
        timestamp: When the alert was created
        metadata: Additional metadata
    """
    alert_id: str
    subscription_id: str
    alert_type: str
    message: str
    severity: str = "INFO"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WebhookConfig:
    """
    Configuration for webhook subscriptions.
    
    Attributes:
        max_retries: Maximum retry attempts for failed deliveries
        retry_delay: Base delay for retries in seconds
        expiration_window: Hours before expiration to alert
        renewal_window: Hours before expiration to auto-renew
        max_subscriptions: Maximum concurrent subscriptions per user
    """
    max_retries: int = 3
    retry_delay: float = 1.0
    expiration_window: int = 48
    renewal_window: int = 48
    max_subscriptions: int = 100