"""
Tests for complex recurrence with EXDATE/RDATE support.

Acceptance Criteria:
- AC-18: Support EXDATE (exception dates)
- AC-19: Support RDATE (additional recurrence dates)
- AC-20: Support complex patterns
- AC-21: Update event can modify single instance or entire series
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch


class TestCreateRecurringEvent:
    """Tests for creating recurring events with EXDATE/RDATE."""
    
    def test_create_event_with_exdate(self, test_client):
        """Create event with EXDATE (exception dates)."""
        with patch('src.handlers.CalendarProvider.create_event') as mock_create:
            mock_create.return_value = {
                "id": "evt_recurring_001",
                "calendar_id": "cal_work_001",
                "summary": "Weekly Standup",
                "recurrence_rule": {
                    "freq": "WEEKLY",
                    "interval": 1,
                    "by_day": ["MO"],
                    "exdate": ["2026-04-20T14:00:00Z", "2026-04-27T14:00:00Z"]
                },
                "rdate": [],
                "start": datetime(2026, 4, 19, 14, 0, 0),
                "end": datetime(2026, 4, 19, 15, 0, 0),
                "visibility": "public",
                "transparency": "opaque",
                "attachments": [],
                "conference_data": None,
                "attendees": [],
                "provider_id": "google"
            }
            
            response = test_client.post(
                "/mcp/tools/create_event",
                json={
                    "calendar_id": "cal_work_001",
                    "summary": "Weekly Standup",
                    "start": "2026-04-19T14:00:00Z",
                    "end": "2026-04-19T15:00:00Z",
                    "recurrence_rule": {
                        "freq": "WEEKLY",
                        "interval": 1,
                        "by_day": ["MO"],
                        "exdate": ["2026-04-20T14:00:00Z", "2026-04-27T14:00:00Z"]
                    }
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert "recurrence_rule" in result
            assert "exdate" in result["recurrence_rule"]
            assert len(result["recurrence_rule"]["exdate"]) == 2
    
    def test_create_event_with_rdate(self, test_client):
        """Create event with RDATE (additional recurrence dates)."""
        with patch('src.handlers.CalendarProvider.create_event') as mock_create:
            mock_create.return_value = {
                "id": "evt_recurring_002",
                "calendar_id": "cal_work_001",
                "summary": "Special Meeting",
                "recurrence_rule": {
                    "freq": "WEEKLY",
                    "interval": 1,
                    "by_day": ["FR"]
                },
                "rdate": [
                    "2026-04-25T14:00:00Z",
                    "2026-04-26T14:00:00Z"
                ],
                "start": datetime(2026, 4, 23, 14, 0, 0),
                "end": datetime(2026, 4, 23, 15, 0, 0),
                "visibility": "public",
                "transparency": "opaque",
                "attachments": [],
                "conference_data": None,
                "attendees": [],
                "provider_id": "google"
            }
            
            response = test_client.post(
                "/mcp/tools/create_event",
                json={
                    "calendar_id": "cal_work_001",
                    "summary": "Special Meeting",
                    "start": "2026-04-23T14:00:00Z",
                    "end": "2026-04-23T15:00:00Z",
                    "recurrence_rule": {
                        "freq": "WEEKLY",
                        "interval": 1,
                        "by_day": ["FR"]
                    },
                    "rdate": [
                        "2026-04-25T14:00:00Z",
                        "2026-04-26T14:00:00Z"
                    ]
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert "rdate" in result
            assert len(result["rdate"]) == 2
    
    def test_create_event_complex_pattern_last_friday(self, test_client):
        """Create event with complex pattern: last Friday of month."""
        with patch('src.handlers.CalendarProvider.create_event') as mock_create:
            mock_create.return_value = {
                "id": "evt_recurring_003",
                "calendar_id": "cal_work_001",
                "summary": "Last Friday Meeting",
                "recurrence_rule": {
                    "freq": "MONTHLY",
                    "interval": 1,
                    "by_day": ["FR"],
                    "by_setpos": -1,
                    "description": "Last Friday of month"
                },
                "start": datetime(2026, 4, 24, 14, 0, 0),
                "end": datetime(2026, 4, 24, 15, 0, 0),
                "visibility": "public",
                "transparency": "opaque",
                "attachments": [],
                "conference_data": None,
                "attendees": [],
                "provider_id": "google"
            }
            
            response = test_client.post(
                "/mcp/tools/create_event",
                json={
                    "calendar_id": "cal_work_001",
                    "summary": "Last Friday Meeting",
                    "start": "2026-04-24T14:00:00Z",
                    "end": "2026-04-24T15:00:00Z",
                    "recurrence_rule": {
                        "freq": "MONTHLY",
                        "interval": 1,
                        "by_day": ["FR"],
                        "by_setpos": -1,
                        "description": "Last Friday of month"
                    }
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["recurrence_rule"]["by_setpos"] == -1
            assert result["recurrence_rule"]["description"] == "Last Friday of month"
    
    def test_create_event_every_third_tuesday(self, test_client):
        """Create event with complex pattern: every 3rd Tuesday."""
        with patch('src.handlers.CalendarProvider.create_event') as mock_create:
            mock_create.return_value = {
                "id": "evt_recurring_004",
                "calendar_id": "cal_work_001",
                "summary": "Every 3rd Tuesday",
                "recurrence_rule": {
                    "freq": "MONTHLY",
                    "interval": 1,
                    "by_day": ["TU"],
                    "by_setpos": 3,
                    "description": "Every 3rd Tuesday"
                },
                "start": datetime(2026, 4, 21, 14, 0, 0),
                "end": datetime(2026, 4, 21, 15, 0, 0),
                "visibility": "public",
                "transparency": "opaque",
                "attachments": [],
                "conference_data": None,
                "attendees": [],
                "provider_id": "google"
            }
            
            response = test_client.post(
                "/mcp/tools/create_event",
                json={
                    "calendar_id": "cal_work_001",
                    "summary": "Every 3rd Tuesday",
                    "start": "2026-04-21T14:00:00Z",
                    "end": "2026-04-21T15:00:00Z",
                    "recurrence_rule": {
                        "freq": "MONTHLY",
                        "interval": 1,
                        "by_day": ["TU"],
                        "by_setpos": 3,
                        "description": "Every 3rd Tuesday"
                    }
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["recurrence_rule"]["by_setpos"] == 3


class TestUpdateRecurringEvent:
    """Tests for updating recurring events."""
    
    def test_update_event_modifies_single_instance(self, test_client):
        """Update event modifies single instance of recurring event."""
        with patch('src.handlers.CalendarProvider.update_event') as mock_update:
            mock_update.return_value = {
                "id": "evt_recurring_001",
                "calendar_id": "cal_work_001",
                "summary": "Weekly Standup",
                "recurrence_rule": {
                    "freq": "WEEKLY",
                    "interval": 1,
                    "by_day": ["MO"],
                    "exdate": ["2026-04-20T14:00:00Z", "2026-04-27T14:00:00Z", "2026-04-21T14:00:00Z"]
                },
                "rdate": [],
                "start": datetime(2026, 4, 19, 14, 0, 0),
                "end": datetime(2026, 4, 19, 15, 0, 0),
                "visibility": "public",
                "transparency": "opaque",
                "attachments": [],
                "conference_data": None,
                "attendees": [],
                "provider_id": "google",
                "instance_id": "instance_2026-04-19"
            }
            
            response = test_client.post(
                "/mcp/tools/update_event",
                json={
                    "event_id": "evt_recurring_001",
                    "instance_id": "instance_2026-04-19",
                    "summary": "Weekly Standup - Rescheduled",
                    "start": "2026-04-19T16:00:00Z",
                    "end": "2026-04-19T17:00:00Z"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["summary"] == "Weekly Standup - Rescheduled"
            assert "instance_id" in result
    
    def test_update_event_modifies_entire_series(self, test_client):
        """Update event modifies entire series."""
        with patch('src.handlers.CalendarProvider.update_event') as mock_update:
            mock_update.return_value = {
                "id": "evt_recurring_001",
                "calendar_id": "cal_work_001",
                "summary": "Weekly Standup - Updated",
                "recurrence_rule": {
                    "freq": "WEEKLY",
                    "interval": 1,
                    "by_day": ["MO"],
                    "exdate": ["2026-04-20T14:00:00Z", "2026-04-27T14:00:00Z"]
                },
                "rdate": [],
                "start": datetime(2026, 4, 19, 14, 0, 0),
                "end": datetime(2026, 4, 19, 15, 0, 0),
                "visibility": "public",
                "transparency": "opaque",
                "attachments": [],
                "conference_data": None,
                "attendees": [],
                "provider_id": "google"
            }
            
            response = test_client.post(
                "/mcp/tools/update_event",
                json={
                    "event_id": "evt_recurring_001",
                    "summary": "Weekly Standup - Updated",
                    "visibility": "private"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["summary"] == "Weekly Standup - Updated"
            assert "instance_id" not in result