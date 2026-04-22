"""
Tests for Calendar CRUD operations (AC-01 to AC-04).

Acceptance Criteria:
- AC-01: Create Calendar
- AC-02: Update Calendar
- AC-03: Delete Calendar
- AC-04: List Calendars
"""

import pytest
from datetime import datetime
from unittest.mock import patch

from src.models.calendar import Calendar


class TestCreateCalendar:
    """Tests for create_calendar MCP tool."""
    
    def test_ac01_create_calendar_returns_calendar_model(
        self, test_client, test_calendars
    ):
        """AC-01: Create calendar returns Calendar model with metadata."""
        # Arrange
        calendar_data = {
            "name": "Test Calendar",
            "description": "A test calendar",
            "timezone": "America/New_York",
            "color": "#FF0000"
        }
        
        # Mock the provider's create_calendar method
        with patch('src.handlers.CalendarProvider.create_calendar') as mock_create:
            mock_create.return_value = test_calendars["work"]
            
            # Act
            response = test_client.post(
                "/mcp/tools/create_calendar",
                json={"name": "Test Calendar", "description": "A test calendar",
                      "timezone": "America/New_York", "color": "#FF0000"}
            )
            
            # Assert
            assert response.status_code == 200
            result = response.json()
            assert "result" in result
            assert isinstance(result["result"], dict)
            assert "id" in result["result"]
            assert "name" in result["result"]
            assert "description" in result["result"]
            assert "timezone" in result["result"]
            assert "color" in result["result"]
            assert "provider_id" in result["result"]
            assert "created_at" in result["result"]
    
    def test_create_calendar_with_required_fields(self, test_client):
        """Create calendar with all required fields."""
        calendar_data = {
            "name": "My Calendar",
            "description": "My personal calendar",
            "timezone": "UTC",
            "color": "#0000FF"
        }
        
        with patch('src.handlers.CalendarProvider.create_calendar') as mock_create:
            mock_create.return_value = Calendar(
                id="cal_test_001",
                name="My Calendar",
                description="My personal calendar",
                timezone="UTC",
                color="#0000FF",
                provider_id="google"
            )
            
            response = test_client.post(
                "/mcp/tools/create_calendar",
                json=calendar_data
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["name"] == "My Calendar"
    
    def test_create_calendar_with_google_provider(self, test_client):
        """Create calendar with Google provider."""
        with patch('src.handlers.CalendarProvider.create_calendar') as mock_create:
            mock_create.return_value = Calendar(
                id="cal_google_001",
                name="Google Calendar Test",
                description="Test",
                timezone="America/Los_Angeles",
                color="#4285F4",
                provider_id="google"
            )
            
            response = test_client.post(
                "/mcp/tools/create_calendar",
                json={
                    "name": "Google Calendar Test",
                    "description": "Test",
                    "timezone": "America/Los_Angeles",
                    "color": "#4285F4"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["provider_id"] == "google"
    
    def test_create_calendar_with_outlook_provider(self, test_client):
        """Create calendar with Outlook provider."""
        with patch('src.handlers.CalendarProvider.create_calendar') as mock_create:
            mock_create.return_value = Calendar(
                id="cal_outlook_001",
                name="Outlook Calendar Test",
                description="Test",
                timezone="UTC",
                color="#0078D4",
                provider_id="outlook"
            )
            
            response = test_client.post(
                "/mcp/tools/create_calendar",
                json={
                    "name": "Outlook Calendar Test",
                    "description": "Test",
                    "timezone": "UTC",
                    "color": "#0078D4"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["provider_id"] == "outlook"


class TestUpdateCalendar:
    """Tests for update_calendar MCP tool."""
    
    def test_ac02_update_calendar_modifies_fields(self, test_client):
        """AC-02: Update calendar modifies name, description, and color."""
        # Arrange
        calendar_id = "cal_work_001"
        update_data = {
            "name": "Updated Work Calendar",
            "description": "Updated work calendar",
            "color": "#00FF00"
        }
        
        with patch('src.handlers.CalendarProvider.update_calendar') as mock_update:
            mock_update.return_value = Calendar(
                id=calendar_id,
                name="Updated Work Calendar",
                description="Updated work calendar",
                timezone="America/New_York",
                color="#00FF00",
                provider_id="google"
            )
            
            # Act
            response = test_client.post(
                "/mcp/tools/update_calendar",
                json={
                    "calendar_id": calendar_id,
                    "name": "Updated Work Calendar",
                    "description": "Updated work calendar",
                    "color": "#00FF00"
                }
            )
            
            # Assert
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["name"] == "Updated Work Calendar"
            assert result["description"] == "Updated work calendar"
            assert result["color"] == "#00FF00"
    
    def test_update_calendar_partial_update(self, test_client):
        """Partial update only modifies provided fields."""
        with patch('src.handlers.CalendarProvider.update_calendar') as mock_update:
            mock_update.return_value = Calendar(
                id="cal_work_001",
                name="Updated Name",
                description="Original Description",  # Not updated
                timezone="America/New_York",
                color="#00FF00",
                provider_id="google"
            )
            
            response = test_client.post(
                "/mcp/tools/update_calendar",
                json={
                    "calendar_id": "cal_work_001",
                    "name": "Updated Name",
                    "color": "#00FF00"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["name"] == "Updated Name"
            assert response.json()["result"]["description"] == "Original Description"
    
    def test_update_calendar_nonexistent_calendar(self, test_client):
        """Update calendar for non-existent calendar returns error."""
        with patch('src.handlers.CalendarProvider.update_calendar') as mock_update:
            mock_update.side_effect = Exception("Calendar not found")
            
            response = test_client.post(
                "/mcp/tools/update_calendar",
                json={
                    "calendar_id": "nonexistent_cal",
                    "name": "Test"
                }
            )
            
            assert response.status_code == 404
            assert response.json()["error"]["code"] == -32602


class TestDeleteCalendar:
    """Tests for delete_calendar MCP tool."""
    
    def test_ac03_delete_calendar_with_confirmation(self, test_client):
        """AC-03: Delete calendar with confirmation=true succeeds."""
        calendar_id = "cal_work_001"
        
        with patch('src.handlers.CalendarProvider.delete_calendar') as mock_delete:
            mock_delete.return_value = {"status": "deleted", "calendar_id": calendar_id}
            
            # Act
            response = test_client.post(
                "/mcp/tools/delete_calendar",
                json={
                    "calendar_id": calendar_id,
                    "confirmation": True
                }
            )
            
            # Assert
            assert response.status_code == 200
            assert response.json()["result"]["status"] == "deleted"
    
    def test_delete_calendar_without_confirmation(self, test_client):
        """AC-03: Delete calendar without confirmation returns error."""
        calendar_id = "cal_work_001"
        
        with patch('src.handlers.CalendarProvider.delete_calendar') as mock_delete:
            mock_delete.side_effect = Exception("Confirmation required")
            
            # Act
            response = test_client.post(
                "/mcp/tools/delete_calendar",
                json={
                    "calendar_id": calendar_id,
                    "confirmation": False
                }
            )
            
            # Assert
            assert response.status_code == 400
            assert "confirmation" in response.json()["error"]["message"]
    
    def test_delete_calendar_nonexistent(self, test_client):
        """Delete non-existent calendar returns error."""
        with patch('src.handlers.CalendarProvider.delete_calendar') as mock_delete:
            mock_delete.side_effect = Exception("Calendar not found")
            
            response = test_client.post(
                "/mcp/tools/delete_calendar",
                json={
                    "calendar_id": "nonexistent_cal",
                    "confirmation": True
                }
            )
            
            assert response.status_code == 404


class TestListCalendars:
    """Tests for list_calendars MCP tool."""
    
    def test_ac04_list_calendars_returns_paginated_list(self, test_client):
        """AC-04: List calendars returns paginated list with metadata."""
        # Arrange
        calendars = [
            Calendar(
                id="cal_001",
                name="Calendar 1",
                description="Test",
                timezone="UTC",
                color="#000000",
                provider_id="google"
            ),
            Calendar(
                id="cal_002",
                name="Calendar 2",
                description="Test",
                timezone="UTC",
                color="#000000",
                provider_id="google"
            )
        ]
        
        with patch('src.handlers.CalendarProvider.list_calendars') as mock_list:
            mock_list.return_value = {
                "items": calendars,
                "total": 2,
                "page": 1,
                "page_size": 10
            }
            
            # Act
            response = test_client.get(
                "/mcp/tools/list_calendars",
                params={"page": 1, "page_size": 10}
            )
            
            # Assert
            assert response.status_code == 200
            result = response.json()["result"]
            assert "items" in result
            assert "total" in result
            assert "page" in result
            assert "page_size" in result
            assert len(result["items"]) == 2
            assert result["total"] == 2
    
    def test_list_calendars_with_default_pagination(self, test_client):
        """List calendars with default pagination."""
        with patch('src.handlers.CalendarProvider.list_calendars') as mock_list:
            mock_list.return_value = {
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 10
            }
            
            response = test_client.get("/mcp/tools/list_calendars")
            
            assert response.status_code == 200
            assert response.json()["result"]["total"] == 0
    
    def test_list_calendars_google_provider(self, test_client):
        """List calendars for Google provider."""
        with patch('src.handlers.CalendarProvider.list_calendars') as mock_list:
            mock_list.return_value = {
                "items": [
                    Calendar(
                        id="cal_google_001",
                        name="Google Cal",
                        description="Test",
                        timezone="UTC",
                        color="#000000",
                        provider_id="google"
                    )
                ],
                "total": 1,
                "page": 1,
                "page_size": 10
            }
            
            response = test_client.get("/mcp/tools/list_calendars")
            
            assert response.status_code == 200
            assert response.json()["result"]["items"][0]["provider_id"] == "google"
    
    def test_list_calendars_outlook_provider(self, test_client):
        """List calendars for Outlook provider."""
        with patch('src.handlers.CalendarProvider.list_calendars') as mock_list:
            mock_list.return_value = {
                "items": [
                    Calendar(
                        id="cal_outlook_001",
                        name="Outlook Cal",
                        description="Test",
                        timezone="UTC",
                        color="#000000",
                        provider_id="outlook"
                    )
                ],
                "total": 1,
                "page": 1,
                "page_size": 10
            }
            
            response = test_client.get("/mcp/tools/list_calendars")
            
            assert response.status_code == 200
            assert response.json()["result"]["items"][0]["provider_id"] == "outlook"