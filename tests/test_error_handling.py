"""
Tests for error handling and edge cases.

Acceptance Criteria:
- Error code mapping from HTTP to MCP
- Retry logic with exponential backoff
- Circuit breaker pattern
- Rate limit handling
"""

import pytest
from datetime import datetime
from unittest.mock import patch


class TestErrorHandler:
    """Tests for error handler."""
    
    def test_http_to_mcp_error_mapping(self, test_client):
        """Test HTTP to MCP error code mapping."""
        with patch('src.services.error_handler.ErrorHandler.http_to_mcp_error') as mock_map:
            mock_map.side_effect = {
                400: -32602,
                401: -32003,
                403: -32603,
                404: -32602,
                429: -32001,
                500: -32603,
            }.get
    
            response = test_client.post(
                "/mcp/tools/test_error_mapping",
                json={"status_code": 404}
            )
            
            assert response.status_code == 404
            assert response.json()["error"]["code"] == -32602
    
    def test_retry_logic_exponential_backoff(self, test_client):
        """Test retry logic with exponential backoff."""
        with patch('src.services.error_handler.ErrorHandler.retry_with_backoff') as mock_retry:
            mock_retry.return_value = True
            
            response = test_client.post(
                "/mcp/tools/test_retry",
                json={
                    "operation": "test",
                    "max_retries": 3,
                    "initial_delay": 1.0
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["retries_attempted"] == 3
    
    def test_circuit_breaker_pattern(self, test_client):
        """Test circuit breaker pattern."""
        with patch('src.services.error_handler.ErrorHandler.circuit_breaker_check') as mock_check:
            mock_check.return_value = False
            
            response = test_client.post(
                "/mcp/tools/test_circuit_breaker",
                json={
                    "operation": "test",
                    "circuit_state": "open"
                }
            )
            
            assert response.status_code == 503
            assert response.json()["error"]["code"] == -32002
    
    def test_rate_limit_handling(self, test_client):
        """Test rate limit handling."""
        with patch('src.services.error_handler.ErrorHandler.handle_rate_limit') as mock_handle:
            mock_handle.return_value = {
                "status": "rate_limited",
                "retry_after": 60
            }
            
            response = test_client.post(
                "/mcp/tools/test_rate_limit",
                json={
                    "operation": "test",
                    "retry_after": 60
                }
            )
            
            assert response.status_code == 429
            assert response.json()["error"]["code"] == -32001


class TestEdgeCases:
    """Tests for edge cases."""
    
    def test_create_calendar_with_empty_name(self, test_client):
        """Create calendar with empty name returns error."""
        response = test_client.post(
            "/mcp/tools/create_calendar",
            json={
                "name": "",
                "description": "Test",
                "timezone": "UTC",
                "color": "#000000"
            }
        )
        
        assert response.status_code == 400
        assert "name" in response.json()["error"]["message"]
    
    def test_create_event_with_invalid_dates(self, test_client):
        """Create event with invalid dates returns error."""
        response = test_client.post(
            "/mcp/tools/create_event",
            json={
                "calendar_id": "cal_work_001",
                "summary": "Test Event",
                "start": "invalid_date",
                "end": "invalid_date"
            }
        )
        
        assert response.status_code == 400
        assert "Invalid date" in response.json()["error"]["message"]
    
    def test_create_event_with_end_before_start(self, test_client):
        """Create event with end before start returns error."""
        response = test_client.post(
            "/mcp/tools/create_event",
            json={
                "calendar_id": "cal_work_001",
                "summary": "Test Event",
                "start": "2026-04-25T15:00:00Z",
                "end": "2026-04-25T14:00:00Z"
            }
        )
        
        assert response.status_code == 400
        assert "End time must be after start time" in response.json()["error"]["message"]
    
    def test_create_event_with_invalid_color(self, test_client):
        """Create event with invalid color returns error."""
        response = test_client.post(
            "/mcp/tools/create_calendar",
            json={
                "name": "Test",
                "description": "Test",
                "timezone": "UTC",
                "color": "invalid_color"
            }
        )
        
        assert response.status_code == 400
        assert "Invalid color" in response.json()["error"]["message"]
    
    def test_search_events_with_empty_query(self, test_client):
        """Search events with empty query returns empty list."""
        response = test_client.post(
            "/mcp/tools/search_events",
            json={
                "query": "",
                "start_date": "2026-04-01",
                "end_date": "2026-04-30"
            }
        )
        
        assert response.status_code == 200
        assert response.json()["result"] == []
    
    def test_list_calendars_with_invalid_page(self, test_client):
        """List calendars with invalid page returns error."""
        response = test_client.get(
            "/mcp/tools/list_calendars",
            params={"page": "invalid", "page_size": 10}
        )
        
        assert response.status_code == 400
        assert "Invalid page" in response.json()["error"]["message"]
    
    def test_subscribe_to_calendar_with_invalid_webhook_url(self, test_client):
        """Subscribe to calendar with invalid webhook URL returns error."""
        response = test_client.post(
            "/mcp/tools/subscribe_to_calendar",
            json={
                "webhook_url": "invalid_url",
                "calendar_id": "cal_work_001"
            }
        )
        
        assert response.status_code == 400
        assert "Invalid webhook URL" in response.json()["error"]["message"]
    
    def test_export_event_with_nonexistent_event(self, test_client):
        """Export non-existent event returns error."""
        response = test_client.post(
            "/mcp/tools/export_event",
            json={
                "event_id": "nonexistent_evt",
                "calendar_id": "cal_work_001"
            }
        )
        
        assert response.status_code == 404
        assert "Event not found" in response.json()["error"]["message"]