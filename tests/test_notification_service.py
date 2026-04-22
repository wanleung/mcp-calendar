"""
Tests for notification service.

Acceptance Criteria:
- AC-13: RSVP notifications to organizers
- AC-14: Webhook notifications for calendar changes
- Retry logic with exponential backoff
- Circuit breaker pattern
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from src.models.notification import NotificationType, NotificationStatus


class TestNotificationService:
    """Tests for notification service."""
    
    def test_send_rsvp_notification(self, test_client, sample_rsvp_payload):
        """Send RSVP notification to organizer."""
        with patch('src.services.notification_service.NotificationService.send_rsvp_notification') as mock_send:
            mock_send.return_value = {
                "status": "sent",
                "notification_id": "notif_123",
                "recipient": "alice@example.com"
            }
            
            response = test_client.post(
                "/mcp/tools/send_rsvp_notification",
                json={
                    "calendar_id": "cal_work_001",
                    "event_id": "evt_team_001",
                    "attendee_email": "bob@example.com",
                    "response_status": "accepted",
                    "organizer_email": "alice@example.com",
                    "event_title": "Team Standup",
                    "event_start": "2026-04-25T14:00:00Z",
                    "event_end": "2026-04-25T15:00:00Z"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["status"] == "sent"
            assert result["notification_id"] == "notif_123"
    
    def test_send_webhook_notification(self, test_client, sample_calendar_change_payload):
        """Send webhook notification for calendar change."""
        with patch('src.services.notification_service.NotificationService.send_webhook_notification') as mock_send:
            mock_send.return_value = {
                "status": "sent",
                "notification_id": "notif_456",
                "webhook_url": "https://example.com/webhook"
            }
            
            response = test_client.post(
                "/mcp/tools/send_webhook_notification",
                json={
                    "calendar_id": "cal_work_001",
                    "event_id": "evt_team_001",
                    "change_type": "updated",
                    "user_id": "user_123",
                    "provider_metadata": {"event": {...}}
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["status"] == "sent"
            assert result["notification_id"] == "notif_456"
    
    def test_retry_notification(self, test_client):
        """Retry failed notification."""
        with patch('src.services.notification_service.NotificationService.retry_notification') as mock_retry:
            mock_retry.return_value = {
                "status": "retrying",
                "notification_id": "notif_789",
                "retry_count": 1,
                "next_retry_at": "2026-04-25T15:00:00Z"
            }
            
            response = test_client.post(
                "/mcp/tools/retry_notification",
                json={
                    "notification_id": "notif_789",
                    "calendar_id": "cal_work_001"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["status"] == "retrying"
            assert result["retry_count"] == 1
    
    def test_notification_with_circuit_breaker(self, test_client):
        """Notification with circuit breaker pattern."""
        with patch('src.services.notification_service.NotificationService.send_notification') as mock_send:
            mock_send.side_effect = Exception("Circuit breaker open")
            
            response = test_client.post(
                "/mcp/tools/send_notification",
                json={
                    "calendar_id": "cal_work_001",
                    "event_id": "evt_team_001",
                    "change_type": "created"
                }
            )
            
            assert response.status_code == 503
            assert "Circuit breaker" in response.json()["error"]["message"]
    
    def test_notification_rate_limiting(self, test_client):
        """Notification with rate limiting."""
        with patch('src.services.notification_service.NotificationService.send_notification') as mock_send:
            mock_send.side_effect = Exception("Rate limit exceeded")
            
            response = test_client.post(
                "/mcp/tools/send_notification",
                json={
                    "calendar_id": "cal_work_001",
                    "event_id": "evt_team_001",
                    "change_type": "created"
                }
            )
            
            assert response.status_code == 429
            assert "Rate limit" in response.json()["error"]["message"]