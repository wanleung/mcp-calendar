"""
Tests for RSVP response operations.

Acceptance Criteria:
- AC-09: Respond to event invitations (accept/decline/tentative)
- Sends notification to event organizer
- Updates attendee response status
"""

import pytest
from datetime import datetime
from unittest.mock import patch

from src.models.notification import NotificationType, NotificationStatus


class TestRespondToEvent:
    """Tests for respond_to_event MCP tool."""
    
    def test_respond_to_event_accepted(self, test_client):
        """Respond to event with accepted status."""
        event_id = "evt_team_001"
        calendar_id = "cal_work_001"
        
        with patch('src.handlers.CalendarProvider.respond_to_event') as mock_respond:
            mock_respond.return_value = {
                "event_id": event_id,
                "response_status": "accepted",
                "notification_sent": True
            }
            
            response = test_client.post(
                "/mcp/tools/respond_to_event",
                json={
                    "event_id": event_id,
                    "calendar_id": calendar_id,
                    "response": "accepted"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["response_status"] == "accepted"
            assert result["notification_sent"] is True
    
    def test_respond_to_event_declined(self, test_client):
        """Respond to event with declined status."""
        with patch('src.handlers.CalendarProvider.respond_to_event') as mock_respond:
            mock_respond.return_value = {
                "event_id": "evt_team_001",
                "response_status": "declined",
                "notification_sent": True
            }
            
            response = test_client.post(
                "/mcp/tools/respond_to_event",
                json={
                    "event_id": "evt_team_001",
                    "calendar_id": "cal_work_001",
                    "response": "declined"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["response_status"] == "declined"
    
    def test_respond_to_event_tentative(self, test_client):
        """Respond to event with tentative status."""
        with patch('src.handlers.CalendarProvider.respond_to_event') as mock_respond:
            mock_respond.return_value = {
                "event_id": "evt_team_001",
                "response_status": "tentative",
                "notification_sent": True
            }
            
            response = test_client.post(
                "/mcp/tools/respond_to_event",
                json={
                    "event_id": "evt_team_001",
                    "calendar_id": "cal_work_001",
                    "response": "tentative"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["response_status"] == "tentative"
    
    def test_respond_to_event_invalid_response(self, test_client):
        """Respond to event with invalid response returns error."""
        with patch('src.handlers.CalendarProvider.respond_to_event') as mock_respond:
            mock_respond.side_effect = Exception("Invalid response status")
            
            response = test_client.post(
                "/mcp/tools/respond_to_event",
                json={
                    "event_id": "evt_team_001",
                    "calendar_id": "cal_work_001",
                    "response": "invalid_response"
                }
            )
            
            assert response.status_code == 400
            assert "Invalid response" in response.json()["error"]["message"]
    
    def test_respond_to_event_sends_notification(self, test_client):
        """Respond to event sends notification to organizer."""
        with patch('src.handlers.CalendarProvider.respond_to_event') as mock_respond:
            mock_respond.return_value = {
                "event_id": "evt_team_001",
                "response_status": "accepted",
                "notification_sent": True,
                "organizer_email": "alice@example.com"
            }
            
            response = test_client.post(
                "/mcp/tools/respond_to_event",
                json={
                    "event_id": "evt_team_001",
                    "calendar_id": "cal_work_001",
                    "response": "accepted"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["notification_sent"] is True
            assert result["organizer_email"] == "alice@example.com"
    
    def test_respond_to_event_google_provider(self, test_client):
        """Respond to event with Google provider."""
        with patch('src.handlers.CalendarProvider.respond_to_event') as mock_respond:
            mock_respond.return_value = {
                "event_id": "evt_google_001",
                "response_status": "accepted",
                "notification_sent": True,
                "provider_id": "google"
            }
            
            response = test_client.post(
                "/mcp/tools/respond_to_event",
                json={
                    "event_id": "evt_google_001",
                    "calendar_id": "cal_google_001",
                    "response": "accepted"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["provider_id"] == "google"
    
    def test_respond_to_event_outlook_provider(self, test_client):
        """Respond to event with Outlook provider."""
        with patch('src.handlers.CalendarProvider.respond_to_event') as mock_respond:
            mock_respond.return_value = {
                "event_id": "evt_outlook_001",
                "response_status": "accepted",
                "notification_sent": True,
                "provider_id": "outlook"
            }
            
            response = test_client.post(
                "/mcp/tools/respond_to_event",
                json={
                    "event_id": "evt_outlook_001",
                    "calendar_id": "cal_outlook_001",
                    "response": "accepted"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["provider_id"] == "outlook"
    
    def test_respond_to_event_nonexistent_event(self, test_client):
        """Respond to non-existent event returns error."""
        with patch('src.handlers.CalendarProvider.respond_to_event') as mock_respond:
            mock_respond.side_effect = Exception("Event not found")
            
            response = test_client.post(
                "/mcp/tools/respond_to_event",
                json={
                    "event_id": "nonexistent_evt",
                    "calendar_id": "cal_work_001",
                    "response": "accepted"
                }
            )
            
            assert response.status_code == 404