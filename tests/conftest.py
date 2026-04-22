"""
Shared fixtures for Calendar MCP Service tests.

This module provides common fixtures for testing the Calendar MCP Service,
including test app instances, mock services, and test data.
"""

import pytest
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from src.app import create_app
from src.models.calendar import Calendar, Event, CalendarShare
from src.models.notification import NotificationType, NotificationStatus
from src.auth.oauth_manager import OAuthManager
from src.services.rate_limiter import RateLimiter
from src.services.error_handler import ErrorHandler, CircuitBreakerConfig, RetryConfig
from src.services.webhook_manager import WebhookManager
from src.services.notification_service import NotificationService
from src.services.scheduling_service import SchedulingService
from src.services.event_normalizer import EventNormalizer


@pytest.fixture
def mock_oauth_manager() -> OAuthManager:
    """Mock OAuth manager for testing."""
    mock = MagicMock(spec=OAuthManager)
    mock.get_token = MagicMock(return_value={
        "access_token": "test_access_token",
        "refresh_token": "test_refresh_token",
        "expires_in": 3600,
        "token_type": "Bearer"
    })
    mock.validate_token = MagicMock(return_value=True)
    mock.refresh_token = MagicMock(return_value={
        "access_token": "new_access_token",
        "expires_in": 3600
    })
    return mock


@pytest.fixture
def mock_rate_limiter() -> RateLimiter:
    """Mock rate limiter for testing."""
    mock = MagicMock(spec=RateLimiter)
    mock.check_rate_limit = MagicMock(return_value=True)
    mock.wait_for_rate_limit = MagicMock()
    return mock


@pytest.fixture
def mock_error_handler() -> ErrorHandler:
    """Mock error handler for testing."""
    mock = MagicMock(spec=ErrorHandler)
    mock.http_to_mcp_error = MagicMock(side_effect=lambda status_code: {
        400: -32602,
        401: -32003,
        403: -32603,
        404: -32602,
        429: -32001,
        500: -32603,
    }.get(status_code, -32603))
    return mock


@pytest.fixture
def mock_webhook_manager() -> WebhookManager:
    """Mock webhook manager for testing."""
    mock = MagicMock(spec=WebhookManager)
    mock.subscribe = MagicMock(return_value={"subscription_id": "test_sub_123"})
    mock.unsubscribe = MagicMock(return_value=True)
    mock.get_subscriptions = MagicMock(return_value=[])
    return mock


@pytest.fixture
def mock_notification_service() -> NotificationService:
    """Mock notification service for testing."""
    mock = MagicMock(spec=NotificationService)
    mock.send_rsvp_notification = MagicMock(return_value={"status": "sent"})
    mock.send_webhook_notification = MagicMock(return_value={"status": "sent"})
    mock.retry_notification = MagicMock(return_value={"status": "retrying"})
    return mock


@pytest.fixture
def mock_scheduling_service() -> SchedulingService:
    """Mock scheduling service for testing."""
    mock = MagicMock(spec=SchedulingService)
    mock.find_meeting_time = MagicMock(return_value={
        "suggested_slots": [
            {
                "start_time": "2026-04-25T14:00:00Z",
                "end_time": "2026-04-25T15:00:00Z",
                "attendee_availability": {
                    "alice@example.com": "available",
                    "bob@example.com": "available"
                },
                "conflicts": []
            }
        ]
    })
    return mock


@pytest.fixture
def mock_event_normalizer() -> EventNormalizer:
    """Mock event normalizer for testing."""
    mock = MagicMock(spec=EventNormalizer)
    mock.normalize_event = MagicMock(return_value={
        "id": "test_event_id",
        "summary": "Test Event",
        "description": "Test Description",
        "start": {"dateTime": "2026-04-25T14:00:00Z", "timeZone": "UTC"},
        "end": {"dateTime": "2026-04-25T15:00:00Z", "timeZone": "UTC"},
        "attendees": [],
        "visibility": "public",
        "transparency": "opaque",
        "attachments": [],
        "conference_data": None
    })
    return mock


@pytest.fixture
def test_calendars() -> Dict[str, Calendar]:
    """Test calendar data."""
    return {
        "work": Calendar(
            id="cal_work_001",
            name="Work Calendar",
            description="Work-related events",
            timezone="America/New_York",
            color="#4285F4",
            provider_id="google"
        ),
        "personal": Calendar(
            id="cal_personal_001",
            name="Personal Calendar",
            description="Personal events",
            timezone="America/New_York",
            color="#34A853",
            provider_id="google"
        ),
        "family": Calendar(
            id="cal_family_001",
            name="Family Calendar",
            description="Family events",
            timezone="America/New_York",
            color="#EA4335",
            provider_id="google"
        )
    }


@pytest.fixture
def test_events() -> Dict[str, Event]:
    """Test event data."""
    return {
        "team_meeting": Event(
            id="evt_team_001",
            calendar_id="cal_work_001",
            summary="Team Standup",
            description="Daily team standup meeting",
            start=datetime(2026, 4, 25, 14, 0, 0),
            end=datetime(2026, 4, 25, 15, 0, 0),
            attendees=[
                {"email": "alice@example.com", "response_status": "accepted"},
                {"email": "bob@example.com", "response_status": "accepted"}
            ],
            visibility="public",
            transparency="opaque",
            provider_id="google"
        ),
        "birthday_party": Event(
            id="evt_birthday_001",
            calendar_id="cal_personal_001",
            summary="Alice's Birthday",
            description="Alice's 30th birthday party",
            start=datetime(2026, 5, 15, 18, 0, 0),
            end=datetime(2026, 5, 15, 22, 0, 0),
            attendees=[
                {"email": "bob@example.com", "response_status": "tentative"}
            ],
            visibility="private",
            transparency="opaque",
            provider_id="google"
        )
    }


@pytest.fixture
def test_shares() -> Dict[str, CalendarShare]:
    """Test share data."""
    return {
        "work_share_1": CalendarShare(
            calendar_id="cal_work_001",
            email="bob@example.com",
            role="editor",
            granted_at=datetime(2026, 4, 20, 10, 0, 0)
        ),
        "work_share_2": CalendarShare(
            calendar_id="cal_work_001",
            email="alice@example.com",
            role="reader",
            granted_at=datetime(2026, 4, 21, 10, 0, 0)
        )
    }


@pytest.fixture
def test_subscriptions() -> Dict[str, Any]:
    """Test subscription data."""
    return {
        "sub_1": {
            "subscription_id": "sub_123",
            "webhook_url": "https://example.com/webhook",
            "calendar_id": "cal_work_001",
            "status": "active",
            "created_at": datetime(2026, 4, 20, 10, 0, 0)
        }
    }


@pytest.fixture
def test_app(mock_oauth_manager, mock_rate_limiter, mock_error_handler,
               mock_webhook_manager, mock_notification_service,
               mock_scheduling_service, mock_event_normalizer) -> TestClient:
    """Create test FastAPI app with mocked dependencies."""
    
    # Create app with mocked dependencies
    app = create_app(
        oauth_manager=mock_oauth_manager,
        rate_limiter=mock_rate_limiter,
        error_handler=mock_error_handler,
        webhook_manager=mock_webhook_manager,
        notification_service=mock_notification_service,
        scheduling_service=mock_scheduling_service,
        event_normalizer=mock_event_normalizer
    )
    
    return TestClient(app)


@pytest.fixture
def test_client(test_app) -> TestClient:
    """Convenience fixture for test client."""
    return test_app


@pytest.fixture
def sample_notification_payload() -> NotificationPayload:
    """Sample notification payload for testing."""
    return NotificationPayload(
        calendar_id="cal_work_001",
        event_id="evt_team_001",
        change_type="updated",
        user_id="user_123",
        timestamp=datetime.utcnow(),
        provider_metadata={"original_event": {...}}
    )


@pytest.fixture
def sample_rsvp_payload() -> RSVPNotificationPayload:
    """Sample RSVP notification payload."""
    return RSVPNotificationPayload(
        calendar_id="cal_work_001",
        event_id="evt_team_001",
        change_type="updated",
        user_id="user_123",
        attendee_email="bob@example.com",
        response_status="accepted",
        organizer_email="alice@example.com",
        event_title="Team Standup",
        event_start=datetime(2026, 4, 25, 14, 0, 0),
        event_end=datetime(2026, 4, 25, 15, 0, 0)
    )


@pytest.fixture
def sample_calendar_change_payload() -> CalendarChangeEventPayload:
    """Sample calendar change event payload."""
    return CalendarChangeEventPayload(
        calendar_id="cal_work_001",
        event_id="evt_team_001",
        change_type="created",
        user_id="user_123",
        timestamp=datetime.utcnow(),
        provider_metadata={"event": {...}}
    )