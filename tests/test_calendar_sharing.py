"""
Tests for Calendar sharing operations (AC-05 to AC-08).

Acceptance Criteria:
- AC-05: Share Calendar
- AC-06: List Calendar Shares
- AC-07: Update Share Permission
- AC-08: Remove Share
"""

import pytest
from datetime import datetime
from unittest.mock import patch

from src.models.calendar import CalendarShare


class TestShareCalendar:
    """Tests for share_calendar MCP tool."""
    
    def test_ac05_share_calendar_valid_role(self, test_client):
        """AC-05: Share calendar with valid role succeeds."""
        # Arrange
        calendar_id = "cal_work_001"
        email = "bob@example.com"
        role = "editor"
        
        with patch('src.handlers.CalendarProvider.share_calendar') as mock_share:
            mock_share.return_value = {
                "calendar_id": calendar_id,
                "email": email,
                "role": role,
                "granted_at": datetime.utcnow()
            }
            
            # Act
            response = test_client.post(
                "/mcp/tools/share_calendar",
                json={
                    "calendar_id": calendar_id,
                    "email": email,
                    "role": role
                }
            )
            
            # Assert
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["email"] == email
            assert result["role"] == role
    
    def test_share_calendar_invalid_role(self, test_client):
        """AC-05: Share calendar with invalid role returns error."""
        with patch('src.handlers.CalendarProvider.share_calendar') as mock_share:
            mock_share.side_effect = Exception("Invalid role")
            
            response = test_client.post(
                "/mcp/tools/share_calendar",
                json={
                    "calendar_id": "cal_work_001",
                    "email": "bob@example.com",
                    "role": "invalid_role"
                }
            )
            
            assert response.status_code == 400
            assert "Invalid role" in response.json()["error"]["message"]
    
    def test_share_calendar_google_provider(self, test_client):
        """Share calendar with Google provider."""
        with patch('src.handlers.CalendarProvider.share_calendar') as mock_share:
            mock_share.return_value = {
                "calendar_id": "cal_google_001",
                "email": "bob@example.com",
                "role": "reader",
                "granted_at": datetime.utcnow()
            }
            
            response = test_client.post(
                "/mcp/tools/share_calendar",
                json={
                    "calendar_id": "cal_google_001",
                    "email": "bob@example.com",
                    "role": "reader"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["role"] == "reader"
    
    def test_share_calendar_outlook_provider(self, test_client):
        """Share calendar with Outlook provider."""
        with patch('src.handlers.CalendarProvider.share_calendar') as mock_share:
            mock_share.return_value = {
                "calendar_id": "cal_outlook_001",
                "email": "bob@example.com",
                "role": "writer",
                "granted_at": datetime.utcnow()
            }
            
            response = test_client.post(
                "/mcp/tools/share_calendar",
                json={
                    "calendar_id": "cal_outlook_001",
                    "email": "bob@example.com",
                    "role": "writer"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["role"] == "writer"
    
    def test_share_calendar_missing_email(self, test_client):
        """Share calendar without email returns error."""
        with patch('src.handlers.CalendarProvider.share_calendar') as mock_share:
            mock_share.side_effect = Exception("Email required")
            
            response = test_client.post(
                "/mcp/tools/share_calendar",
                json={
                    "calendar_id": "cal_work_001",
                    "role": "editor"
                }
            )
            
            assert response.status_code == 400
            assert "email" in response.json()["error"]["message"]


class TestListCalendarShares:
    """Tests for list_calendar_shares MCP tool."""
    
    def test_ac06_list_shares_returns_share_objects(self, test_client):
        """AC-06: List shares returns list of Share objects with metadata."""
        # Arrange
        shares = [
            CalendarShare(
                calendar_id="cal_work_001",
                email="bob@example.com",
                role="editor",
                granted_at=datetime(2026, 4, 20, 10, 0, 0)
            ),
            CalendarShare(
                calendar_id="cal_work_001",
                email="alice@example.com",
                role="reader",
                granted_at=datetime(2026, 4, 21, 10, 0, 0)
            )
        ]
        
        with patch('src.handlers.CalendarProvider.list_shares') as mock_list:
            mock_list.return_value = shares
            
            # Act
            response = test_client.get(
                "/mcp/tools/list_calendar_shares",
                params={"calendar_id": "cal_work_001"}
            )
            
            # Assert
            assert response.status_code == 200
            result = response.json()["result"]
            assert "shares" in result
            assert len(result["shares"]) == 2
            assert result["shares"][0]["email"] == "bob@example.com"
            assert result["shares"][0]["role"] == "editor"
    
    def test_list_shares_nonexistent_calendar(self, test_client):
        """List shares for non-existent calendar returns empty list."""
        with patch('src.handlers.CalendarProvider.list_shares') as mock_list:
            mock_list.return_value = []
            
            response = test_client.get(
                "/mcp/tools/list_calendar_shares",
                params={"calendar_id": "nonexistent_cal"}
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["shares"] == []
    
    def test_list_shares_google_provider(self, test_client):
        """List shares for Google provider."""
        with patch('src.handlers.CalendarProvider.list_shares') as mock_list:
            mock_list.return_value = [
                CalendarShare(
                    calendar_id="cal_google_001",
                    email="bob@example.com",
                    role="editor",
                    granted_at=datetime.utcnow()
                )
            ]
            
            response = test_client.get(
                "/mcp/tools/list_calendar_shares",
                params={"calendar_id": "cal_google_001"}
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["shares"][0]["calendar_id"] == "cal_google_001"
    
    def test_list_shares_outlook_provider(self, test_client):
        """List shares for Outlook provider."""
        with patch('src.handlers.CalendarProvider.list_shares') as mock_list:
            mock_list.return_value = [
                CalendarShare(
                    calendar_id="cal_outlook_001",
                    email="bob@example.com",
                    role="writer",
                    granted_at=datetime.utcnow()
                )
            ]
            
            response = test_client.get(
                "/mcp/tools/list_calendar_shares",
                params={"calendar_id": "cal_outlook_001"}
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["shares"][0]["calendar_id"] == "cal_outlook_001"


class TestUpdateSharePermission:
    """Tests for update_share_permission MCP tool."""
    
    def test_ac07_update_share_validates_role(self, test_client):
        """AC-07: Update share permission validates role."""
        # Arrange
        calendar_id = "cal_work_001"
        email = "bob@example.com"
        new_role = "reader"
        
        with patch('src.handlers.CalendarProvider.update_share') as mock_update:
            mock_update.return_value = {
                "calendar_id": calendar_id,
                "email": email,
                "role": new_role,
                "granted_at": datetime.utcnow()
            }
            
            # Act
            response = test_client.post(
                "/mcp/tools/update_share_permission",
                json={
                    "calendar_id": calendar_id,
                    "email": email,
                    "role": new_role
                }
            )
            
            # Assert
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["role"] == new_role
    
    def test_update_share_invalid_role(self, test_client):
        """AC-07: Update share with invalid role returns error."""
        with patch('src.handlers.CalendarProvider.update_share') as mock_update:
            mock_update.side_effect = Exception("Invalid role")
            
            response = test_client.post(
                "/mcp/tools/update_share_permission",
                json={
                    "calendar_id": "cal_work_001",
                    "email": "bob@example.com",
                    "role": "invalid_role"
                }
            )
            
            assert response.status_code == 400
            assert "Invalid role" in response.json()["error"]["message"]
    
    def test_update_share_nonexistent_share(self, test_client):
        """Update non-existent share returns error."""
        with patch('src.handlers.CalendarProvider.update_share') as mock_update:
            mock_update.side_effect = Exception("Share not found")
            
            response = test_client.post(
                "/mcp/tools/update_share_permission",
                json={
                    "calendar_id": "cal_work_001",
                    "email": "bob@example.com",
                    "role": "reader"
                }
            )
            
            assert response.status_code == 404


class TestRemoveShare:
    """Tests for remove_share MCP tool."""
    
    def test_remove_share_succeeds(self, test_client):
        """Remove share succeeds with confirmation."""
        calendar_id = "cal_work_001"
        email = "bob@example.com"
        
        with patch('src.handlers.CalendarProvider.remove_share') as mock_remove:
            mock_remove.return_value = {"status": "removed", "calendar_id": calendar_id}
            
            response = test_client.post(
                "/mcp/tools/remove_share",
                json={
                    "calendar_id": calendar_id,
                    "email": email,
                    "confirmation": True
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["status"] == "removed"
    
    def test_remove_share_without_confirmation(self, test_client):
        """Remove share without confirmation returns error."""
        with patch('src.handlers.CalendarProvider.remove_share') as mock_remove:
            mock_remove.side_effect = Exception("Confirmation required")
            
            response = test_client.post(
                "/mcp/tools/remove_share",
                json={
                    "calendar_id": "cal_work_001",
                    "email": "bob@example.com",
                    "confirmation": False
                }
            )
            
            assert response.status_code == 400
            assert "confirmation" in response.json()["error"]["message"]
    
    def test_remove_share_nonexistent(self, test_client):
        """Remove non-existent share returns error."""
        with patch('src.handlers.CalendarProvider.remove_share') as mock_remove:
            mock_remove.side_effect = Exception("Share not found")
            
            response = test_client.post(
                "/mcp/tools/remove_share",
                json={
                    "calendar_id": "cal_work_001",
                    "email": "bob@example.com",
                    "confirmation": True
                }
            )
            
            assert response.status_code == 404