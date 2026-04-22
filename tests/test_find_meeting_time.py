"""
Tests for find_meeting_time scheduling assistance.

Acceptance Criteria:
- AC-17: Find optimal meeting times across multiple participants
- Returns up to 5 suggested time slots
- Respects working hours
- Uses free/busy API for Google, event queries for Outlook
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch


class TestFindMeetingTime:
    """Tests for find_meeting_time MCP tool."""
    
    def test_find_meeting_time_returns_slots(self, test_client):
        """Find meeting time returns up to 5 suggested slots."""
        with patch('src.handlers.SchedulingService.find_meeting_time') as mock_find:
            mock_find.return_value = {
                "suggested_slots": [
                    {
                        "start_time": "2026-04-25T14:00:00Z",
                        "end_time": "2026-04-25T15:00:00Z",
                        "attendee_availability": {
                            "alice@example.com": "available",
                            "bob@example.com": "available"
                        },
                        "conflicts": []
                    },
                    {
                        "start_time": "2026-04-25T15:00:00Z",
                        "end_time": "2026-04-25T16:00:00Z",
                        "attendee_availability": {
                            "alice@example.com": "available",
                            "bob@example.com": "available"
                        },
                        "conflicts": []
                    }
                ],
                "total_slots": 2
            }
            
            response = test_client.post(
                "/mcp/tools/find_meeting_time",
                json={
                    "attendee_emails": ["alice@example.com", "bob@example.com"],
                    "duration_minutes": 60,
                    "start_date": "2026-04-25",
                    "end_date": "2026-04-26"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert len(result["suggested_slots"]) == 2
            assert result["total_slots"] == 2
    
    def test_find_meeting_time_with_constraints(self, test_client):
        """Find meeting time with optional constraints."""
        with patch('src.handlers.SchedulingService.find_meeting_time') as mock_find:
            mock_find.return_value = {
                "suggested_slots": [
                    {
                        "start_time": "2026-04-25T14:00:00Z",
                        "end_time": "2026-04-25T15:00:00Z",
                        "attendee_availability": {
                            "alice@example.com": "available",
                            "bob@example.com": "available"
                        },
                        "conflicts": [],
                        "constraints": {
                            "working_hours": True,
                            "timezone": "America/New_York"
                        }
                    }
                ],
                "total_slots": 1
            }
            
            response = test_client.post(
                "/mcp/tools/find_meeting_time",
                json={
                    "attendee_emails": ["alice@example.com", "bob@example.com"],
                    "duration_minutes": 60,
                    "start_date": "2026-04-25",
                    "end_date": "2026-04-26",
                    "constraints": {
                        "working_hours": True,
                        "timezone": "America/New_York"
                    }
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["suggested_slots"][0]["constraints"]["working_hours"] is True
    
    def test_find_meeting_time_google_provider(self, test_client):
        """Find meeting time with Google provider."""
        with patch('src.handlers.SchedulingService.find_meeting_time') as mock_find:
            mock_find.return_value = {
                "suggested_slots": [
                    {
                        "start_time": "2026-04-25T14:00:00Z",
                        "end_time": "2026-04-25T15:00:00Z",
                        "attendee_availability": {
                            "alice@example.com": "available"
                        },
                        "conflicts": [],
                        "provider": "google"
                    }
                ],
                "total_slots": 1
            }
            
            response = test_client.post(
                "/mcp/tools/find_meeting_time",
                json={
                    "attendee_emails": ["alice@example.com"],
                    "duration_minutes": 60,
                    "start_date": "2026-04-25",
                    "end_date": "2026-04-26"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["suggested_slots"][0]["provider"] == "google"
    
    def test_find_meeting_time_outlook_provider(self, test_client):
        """Find meeting time with Outlook provider."""
        with patch('src.handlers.SchedulingService.find_meeting_time') as mock_find:
            mock_find.return_value = {
                "suggested_slots": [
                    {
                        "start_time": "2026-04-25T14:00:00Z",
                        "end_time": "2026-04-25T15:00:00Z",
                        "attendee_availability": {
                            "alice@example.com": "available"
                        },
                        "conflicts": [],
                        "provider": "outlook"
                    }
                ],
                "total_slots": 1
            }
            
            response = test_client.post(
                "/mcp/tools/find_meeting_time",
                json={
                    "attendee_emails": ["alice@example.com"],
                    "duration_minutes": 60,
                    "start_date": "2026-04-25",
                    "end_date": "2026-04-26"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["suggested_slots"][0]["provider"] == "outlook"
    
    def test_find_meeting_time_no_available_slots(self, test_client):
        """Find meeting time with no available slots."""
        with patch('src.handlers.SchedulingService.find_meeting_time') as mock_find:
            mock_find.return_value = {
                "suggested_slots": [],
                "total_slots": 0,
                "conflicts": [
                    {
                        "attendee_email": "alice@example.com",
                        "conflicting_event": "Team Meeting",
                        "start_time": "2026-04-25T14:00:00Z",
                        "end_time": "2026-04-25T15:00:00Z"
                    }
                ]
            }
            
            response = test_client.post(
                "/mcp/tools/find_meeting_time",
                json={
                    "attendee_emails": ["alice@example.com"],
                    "duration_minutes": 60,
                    "start_date": "2026-04-25",
                    "end_date": "2026-04-26"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert len(result["suggested_slots"]) == 0
            assert len(result["conflicts"]) == 1