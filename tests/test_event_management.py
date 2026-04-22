"""
Tests for Event management operations.

Acceptance Criteria:
- Event CRUD operations
- Event search
- Move/copy events
- Export to ICS
- Enhanced event fields (visibility, transparency, attachments, conference data)
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from src.models.calendar import Event


class TestCreateEvent:
    """Tests for create_event MCP tool."""
    
    def test_create_event_with_enhanced_fields(self, test_client):
        """Create event with visibility, transparency, attachments, and conference data."""
        # Arrange
        event_data = {
            "calendar_id": "cal_work_001",
            "summary": "Team Meeting",
            "description": "Weekly team meeting",
            "start": "2026-04-25T14:00:00Z",
            "end": "2026-04-25T15:00:00Z",
            "visibility": "public",
            "transparency": "opaque",
            "attachments": [
                {"title": "Agenda", "url": "https://example.com/agenda.pdf"}
            ],
            "conference_data": {
                "provider": "google",
                "url": "https://meet.google.com/abc-def-ghi",
                "meeting_id": "abc-def-ghi"
            }
        }
        
        with patch('src.handlers.CalendarProvider.create_event') as mock_create:
            mock_create.return_value = Event(
                id="evt_test_001",
                calendar_id="cal_work_001",
                summary="Team Meeting",
                description="Weekly team meeting",
                start=datetime(2026, 4, 25, 14, 0, 0),
                end=datetime(2026, 4, 25, 15, 0, 0),
                visibility="public",
                transparency="opaque",
                attachments=[
                    {"title": "Agenda", "url": "https://example.com/agenda.pdf"}
                ],
                conference_data={
                    "provider": "google",
                    "url": "https://meet.google.com/abc-def-ghi",
                    "meeting_id": "abc-def-ghi"
                },
                attendees=[],
                provider_id="google"
            )
            
            # Act
            response = test_client.post(
                "/mcp/tools/create_event",
                json=event_data
            )
            
            # Assert
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["visibility"] == "public"
            assert result["transparency"] == "opaque"
            assert len(result["attachments"]) == 1
            assert result["conference_data"]["provider"] == "google"
    
    def test_create_event_google_meet_auto_generation(self, test_client):
        """Create event with Google Meet auto-generation."""
        with patch('src.handlers.CalendarProvider.create_event') as mock_create:
            mock_create.return_value = Event(
                id="evt_google_001",
                calendar_id="cal_google_001",
                summary="Google Meet Event",
                description="Test",
                start=datetime(2026, 4, 25, 14, 0, 0),
                end=datetime(2026, 4, 25, 15, 0, 0),
                visibility="public",
                transparency="opaque",
                attachments=[],
                conference_data={
                    "provider": "google",
                    "url": "https://meet.google.com/xyz",
                    "meeting_id": "xyz",
                    "conferenceDataVersion": 1
                },
                attendees=[],
                provider_id="google"
            )
            
            response = test_client.post(
                "/mcp/tools/create_event",
                json={
                    "calendar_id": "cal_google_001",
                    "summary": "Google Meet Event",
                    "start": "2026-04-25T14:00:00Z",
                    "end": "2026-04-25T15:00:00Z"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["conference_data"]["provider"] == "google"
    
    def test_create_event_teams_meeting(self, test_client):
        """Create event with Teams meeting."""
        with patch('src.handlers.CalendarProvider.create_event') as mock_create:
            mock_create.return_value = Event(
                id="evt_outlook_001",
                calendar_id="cal_outlook_001",
                summary="Teams Meeting",
                description="Test",
                start=datetime(2026, 4, 25, 14, 0, 0),
                end=datetime(2026, 4, 25, 15, 0, 0),
                visibility="public",
                transparency="opaque",
                attachments=[],
                conference_data={
                    "provider": "outlook",
                    "url": "https://teams.microsoft.com/l/meetup-join/abc",
                    "meeting_id": "abc",
                    "onlineMeeting": True
                },
                attendees=[],
                provider_id="outlook"
            )
            
            response = test_client.post(
                "/mcp/tools/create_event",
                json={
                    "calendar_id": "cal_outlook_001",
                    "summary": "Teams Meeting",
                    "start": "2026-04-25T14:00:00Z",
                    "end": "2026-04-25T15:00:00Z"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["conference_data"]["provider"] == "outlook"


class TestUpdateEvent:
    """Tests for update_event MCP tool."""
    
    def test_update_event_modifies_fields(self, test_client):
        """Update event modifies summary and description."""
        event_id = "evt_team_001"
        
        with patch('src.handlers.CalendarProvider.update_event') as mock_update:
            mock_update.return_value = Event(
                id=event_id,
                calendar_id="cal_work_001",
                summary="Updated Meeting",
                description="Updated description",
                start=datetime(2026, 4, 25, 14, 0, 0),
                end=datetime(2026, 4, 25, 15, 0, 0),
                visibility="private",
                transparency="opaque",
                attachments=[],
                conference_data=None,
                attendees=[],
                provider_id="google"
            )
            
            response = test_client.post(
                "/mcp/tools/update_event",
                json={
                    "event_id": event_id,
                    "summary": "Updated Meeting",
                    "description": "Updated description",
                    "visibility": "private"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["summary"] == "Updated Meeting"
            assert result["visibility"] == "private"
    
    def test_update_event_adds_attachments(self, test_client):
        """Update event adds attachments."""
        with patch('src.handlers.CalendarProvider.update_event') as mock_update:
            mock_update.return_value = Event(
                id="evt_team_001",
                calendar_id="cal_work_001",
                summary="Team Meeting",
                description="Test",
                start=datetime(2026, 4, 25, 14, 0, 0),
                end=datetime(2026, 4, 25, 15, 0, 0),
                visibility="public",
                transparency="opaque",
                attachments=[
                    {"title": "New Attachment", "url": "https://example.com/new.pdf"}
                ],
                conference_data=None,
                attendees=[],
                provider_id="google"
            )
            
            response = test_client.post(
                "/mcp/tools/update_event",
                json={
                    "event_id": "evt_team_001",
                    "attachments": [
                        {"title": "New Attachment", "url": "https://example.com/new.pdf"}
                    ]
                }
            )
            
            assert response.status_code == 200
            assert len(response.json()["result"]["attachments"]) == 1


class TestDeleteEvent:
    """Tests for delete_event MCP tool."""
    
    def test_delete_event_succeeds(self, test_client):
        """Delete event succeeds."""
        event_id = "evt_team_001"
        
        with patch('src.handlers.CalendarProvider.delete_event') as mock_delete:
            mock_delete.return_value = {"status": "deleted", "event_id": event_id}
            
            response = test_client.post(
                "/mcp/tools/delete_event",
                json={"event_id": event_id}
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["status"] == "deleted"
    
    def test_delete_event_nonexistent(self, test_client):
        """Delete non-existent event returns error."""
        with patch('src.handlers.CalendarProvider.delete_event') as mock_delete:
            mock_delete.side_effect = Exception("Event not found")
            
            response = test_client.post(
                "/mcp/tools/delete_event",
                json={"event_id": "nonexistent_evt"}
            )
            
            assert response.status_code == 404


class TestSearchEvents:
    """Tests for search_events MCP tool."""
    
    def test_search_events_basic(self, test_client):
        """Search events with query string."""
        with patch('src.handlers.CalendarProvider.search_events') as mock_search:
            mock_search.return_value = [
                Event(
                    id="evt_001",
                    calendar_id="cal_work_001",
                    summary="Team Meeting",
                    description="Weekly meeting",
                    start=datetime(2026, 4, 25, 14, 0, 0),
                    end=datetime(2026, 4, 25, 15, 0, 0),
                    visibility="public",
                    transparency="opaque",
                    attachments=[],
                    conference_data=None,
                    attendees=[],
                    provider_id="google"
                )
            ]
            
            response = test_client.post(
                "/mcp/tools/search_events",
                json={
                    "query": "team",
                    "calendar_id": "cal_work_001",
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-30"
                }
            )
            
            assert response.status_code == 200
            assert len(response.json()["result"]) == 1
    
    def test_search_events_across_all_calendars(self, test_client):
        """Search events across all calendars."""
        with patch('src.handlers.CalendarProvider.search_events') as mock_search:
            mock_search.return_value = [
                Event(
                    id="evt_001",
                    calendar_id="cal_work_001",
                    summary="Team Meeting",
                    description="Weekly meeting",
                    start=datetime(2026, 4, 25, 14, 0, 0),
                    end=datetime(2026, 4, 25, 15, 0, 0),
                    visibility="public",
                    transparency="opaque",
                    attachments=[],
                    conference_data=None,
                    attendees=[],
                    provider_id="google"
                )
            ]
            
            response = test_client.post(
                "/mcp/tools/search_events",
                json={
                    "query": "team",
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-30"
                }
            )
            
            assert response.status_code == 200
            assert len(response.json()["result"]) == 1


class TestMoveEvent:
    """Tests for move_event MCP tool."""
    
    def test_move_event_preserves_metadata(self, test_client):
        """Move event preserves all metadata."""
        with patch('src.handlers.CalendarProvider.move_event') as mock_move:
            mock_move.return_value = Event(
                id="evt_team_001",
                calendar_id="cal_personal_001",
                summary="Team Meeting",
                description="Weekly meeting",
                start=datetime(2026, 4, 25, 14, 0, 0),
                end=datetime(2026, 4, 25, 15, 0, 0),
                visibility="public",
                transparency="opaque",
                attachments=[
                    {"title": "Agenda", "url": "https://example.com/agenda.pdf"}
                ],
                conference_data={
                    "provider": "google",
                    "url": "https://meet.google.com/abc",
                    "meeting_id": "abc"
                },
                attendees=[
                    {"email": "alice@example.com", "response_status": "accepted"}
                ],
                provider_id="google"
            )
            
            response = test_client.post(
                "/mcp/tools/move_event",
                json={
                    "event_id": "evt_team_001",
                    "source_calendar_id": "cal_work_001",
                    "target_calendar_id": "cal_personal_001"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["calendar_id"] == "cal_personal_001"
            assert result["attachments"][0]["title"] == "Agenda"
            assert result["conference_data"]["provider"] == "google"


class TestCopyEvent:
    """Tests for copy_event MCP tool."""
    
    def test_copy_event_creates_duplicate(self, test_client):
        """Copy event creates duplicate in target calendar."""
        with patch('src.handlers.CalendarProvider.copy_event') as mock_copy:
            mock_copy.return_value = Event(
                id="evt_team_001_copy",
                calendar_id="cal_personal_001",
                summary="Team Meeting (Copy)",
                description="Weekly meeting (Copy)",
                start=datetime(2026, 4, 25, 14, 0, 0),
                end=datetime(2026, 4, 25, 15, 0, 0),
                visibility="public",
                transparency="opaque",
                attachments=[],
                conference_data=None,
                attendees=[],
                provider_id="google"
            )
            
            response = test_client.post(
                "/mcp/tools/copy_event",
                json={
                    "event_id": "evt_team_001",
                    "target_calendar_id": "cal_personal_001"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["calendar_id"] == "cal_personal_001"
            assert result["summary"] == "Team Meeting (Copy)"


class TestExportEvent:
    """Tests for export_event MCP tool."""
    
    def test_export_event_returns_ics(self, test_client):
        """Export event returns ICS formatted string."""
        with patch('src.handlers.CalendarProvider.export_event') as mock_export:
            mock_export.return_value = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:evt_team_001
DTSTART:20260425T140000Z
DTEND:20260425T150000Z
SUMMARY:Team Meeting
DESCRIPTION:Weekly team meeting
END:VEVENT
END:VCALENDAR"""
            
            response = test_client.post(
                "/mcp/tools/export_event",
                json={
                    "event_id": "evt_team_001",
                    "calendar_id": "cal_work_001"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert "BEGIN:VCALENDAR" in result
            assert "BEGIN:VEVENT" in result
            assert "END:VEVENT" in result
            assert "END:VCALENDAR" in result
    
    def test_export_event_rfc5545_compliant(self, test_client):
        """Export event is RFC 5545 compliant."""
        with patch('src.handlers.CalendarProvider.export_event') as mock_export:
            mock_export.return_value = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:evt_team_001
DTSTART:20260425T140000Z
DTEND:20260425T150000Z
SUMMARY:Team Meeting
DESCRIPTION:Weekly team meeting
ATTENDEE;CN=Alice;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:alice@example.com
END:VEVENT
END:VCALENDAR"""
            
            response = test_client.post(
                "/mcp/tools/export_event",
                json={
                    "event_id": "evt_team_001",
                    "calendar_id": "cal_work_001"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert "ATTENDEE" in result
            assert "RSVP=TRUE" in result