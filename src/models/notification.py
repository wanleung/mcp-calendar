"""
Notification data models for RSVP and webhook notifications.

This module defines the data structures used for notification payloads,
event responses, and webhook subscription events.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


class NotificationType(Enum):
    """Types of notifications that can be sent."""
    RSVP_RESPONSE = "rsvp_response"
    CALENDAR_CHANGE = "calendar_change"
    EVENT_CREATED = "event_created"
    EVENT_UPDATED = "event_updated"
    EVENT_DELETED = "event_deleted"
    ORGANIZER_ALERT = "organizer_alert"


class NotificationStatus(Enum):
    """Status of a notification delivery attempt."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class NotificationPayload:
    """
    Base notification payload structure.
    
    Attributes:
        calendar_id: The calendar identifier
        event_id: The event identifier (None for calendar-level changes)
        change_type: Type of change ("created", "updated", "deleted")
        user_id: The user who triggered the notification
        timestamp: When the notification was created
        provider_metadata: Raw provider payload for debugging
        notification_type: Type of notification
        status: Delivery status
        error_message: Error message if delivery failed
    """
    calendar_id: str
    user_id: str
    event_id: Optional[str] = None
    change_type: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    provider_metadata: Dict[str, Any] = field(default_factory=dict)
    notification_type: NotificationType = NotificationType.CALENDAR_CHANGE
    status: NotificationStatus = NotificationStatus.PENDING
    error_message: Optional[str] = None


@dataclass(kw_only=True)
class RSVPNotificationPayload(NotificationPayload):
    """
    RSVP response notification payload.
    
    Attributes:
        attendee_email: Email of the attendee responding
        response_status: The response status ("accepted", "declined", "tentative")
        organizer_email: Email of the event organizer
        event_title: Title of the event
        event_start: Start time of the event
        event_end: End time of the event
    """
    attendee_email: str
    response_status: str
    organizer_email: Optional[str] = None
    event_title: Optional[str] = None
    event_start: Optional[datetime] = None
    event_end: Optional[datetime] = None


@dataclass
class CalendarChangeEventPayload(NotificationPayload):
    """
    Calendar change event payload for webhook notifications.
    
    Attributes:
        calendar_id: The calendar identifier
        event_id: The event identifier (None for calendar-level changes)
        change_type: Type of change ("created", "updated", "deleted")
        user_id: The user who triggered the notification
        timestamp: When the notification was created
        provider_metadata: Raw provider payload for debugging
    """
    pass


@dataclass
class NotificationDeliveryResult:
    """
    Result of a notification delivery attempt.
    
    Attributes:
        success: Whether the notification was successfully delivered
        notification_id: Unique identifier for the notification
        error_message: Error message if delivery failed
        retry_count: Number of retry attempts made
        last_error: Last error encountered
    """
    success: bool
    notification_id: str
    error_message: Optional[str] = None
    retry_count: int = 0
    last_error: Optional[str] = None


@dataclass
class WebhookSubscription:
    """
    Webhook subscription for calendar change notifications.
    
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
    """
    subscription_id: str
    webhook_url: str
    calendar_id: str
    expires_at: datetime
    event_id: Optional[str] = None
    change_types: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_sent_at: Optional[datetime] = None
    last_retry_at: Optional[datetime] = None
    retry_after: Optional[int] = None
    status: str = "active"


@dataclass
class NotificationEvent:
    """
    Event emitted when a notification is sent or fails.
    
    Attributes:
        event_type: Type of notification event
        notification_id: Unique identifier for the notification
        status: Delivery status
        error_message: Error message if applicable
        timestamp: When the event occurred
    """
    event_type: str
    notification_id: str
    status: NotificationStatus
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
