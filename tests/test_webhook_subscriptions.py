"""
Tests for webhook subscription management.

Acceptance Criteria:
- AC-10: Subscribe to calendar change notifications
- AC-11: List subscriptions
- AC-12: Unsubscribe from calendar
"""

import pytest
from datetime import datetime
from unittest.mock import patch


class TestSubscribeToCalendar:
    """Tests for subscribe_to_calendar MCP tool."""
    
    def test_subscribe_to_calendar_succeeds(self, test_client):
        """Subscribe to calendar change notifications succeeds."""
        with patch('src.handlers.WebhookManager.subscribe') as mock_subscribe:
            mock_subscribe.return_value = {
                "subscription_id": "sub_123",
                "webhook_url": "https://example.com/webhook",
                "calendar_id": "cal_work_001",
                "status": "active",
                "created_at": datetime.utcnow()
            }
            
            response = test_client.post(
                "/mcp/tools/subscribe_to_calendar",
                json={
                    "webhook_url": "https://example.com/webhook",
                    "calendar_id": "cal_work_001"
                }
            )
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["subscription_id"] == "sub_123"
            assert result["status"] == "active"
    
    def test_subscribe_to_calendar_invalid_url(self, test_client):
        """Subscribe with invalid webhook URL returns error."""
        with patch('src.handlers.WebhookManager.subscribe') as mock_subscribe:
            mock_subscribe.side_effect = Exception("Invalid webhook URL")
            
            response = test_client.post(
                "/mcp/tools/subscribe_to_calendar",
                json={
                    "webhook_url": "invalid_url",
                    "calendar_id": "cal_work_001"
                }
            )
            
            assert response.status_code == 400
            assert "Invalid webhook URL" in response.json()["error"]["message"]
    
    def test_subscribe_to_calendar_google_provider(self, test_client):
        """Subscribe with Google provider."""
        with patch('src.handlers.WebhookManager.subscribe') as mock_subscribe:
            mock_subscribe.return_value = {
                "subscription_id": "sub_google_123",
                "webhook_url": "https://example.com/webhook",
                "calendar_id": "cal_google_001",
                "status": "active",
                "created_at": datetime.utcnow(),
                "provider_id": "google"
            }
            
            response = test_client.post(
                "/mcp/tools/subscribe_to_calendar",
                json={
                    "webhook_url": "https://example.com/webhook",
                    "calendar_id": "cal_google_001"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["provider_id"] == "google"
    
    def test_subscribe_to_calendar_outlook_provider(self, test_client):
        """Subscribe with Outlook provider."""
        with patch('src.handlers.WebhookManager.subscribe') as mock_subscribe:
            mock_subscribe.return_value = {
                "subscription_id": "sub_outlook_123",
                "webhook_url": "https://example.com/webhook",
                "calendar_id": "cal_outlook_001",
                "status": "active",
                "created_at": datetime.utcnow(),
                "provider_id": "outlook"
            }
            
            response = test_client.post(
                "/mcp/tools/subscribe_to_calendar",
                json={
                    "webhook_url": "https://example.com/webhook",
                    "calendar_id": "cal_outlook_001"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["provider_id"] == "outlook"


class TestListSubscriptions:
    """Tests for list_subscriptions MCP tool."""
    
    def test_list_subscriptions_returns_list(self, test_client):
        """List subscriptions returns list of active subscriptions."""
        with patch('src.handlers.WebhookManager.get_subscriptions') as mock_list:
            mock_list.return_value = [
                {
                    "subscription_id": "sub_123",
                    "webhook_url": "https://example.com/webhook",
                    "calendar_id": "cal_work_001",
                    "status": "active",
                    "created_at": datetime.utcnow()
                },
                {
                    "subscription_id": "sub_456",
                    "webhook_url": "https://example.com/webhook2",
                    "calendar_id": "cal_personal_001",
                    "status": "active",
                    "created_at": datetime.utcnow()
                }
            ]
            
            response = test_client.get("/mcp/tools/list_subscriptions")
            
            assert response.status_code == 200
            result = response.json()["result"]
            assert len(result) == 2
            assert result[0]["subscription_id"] == "sub_123"
            assert result[1]["subscription_id"] == "sub_456"
    
    def test_list_subscriptions_empty(self, test_client):
        """List subscriptions with no active subscriptions."""
        with patch('src.handlers.WebhookManager.get_subscriptions') as mock_list:
            mock_list.return_value = []
            
            response = test_client.get("/mcp/tools/list_subscriptions")
            
            assert response.status_code == 200
            assert response.json()["result"] == []
    
    def test_list_subscriptions_google_provider(self, test_client):
        """List subscriptions for Google provider."""
        with patch('src.handlers.WebhookManager.get_subscriptions') as mock_list:
            mock_list.return_value = [
                {
                    "subscription_id": "sub_google_123",
                    "webhook_url": "https://example.com/webhook",
                    "calendar_id": "cal_google_001",
                    "status": "active",
                    "created_at": datetime.utcnow(),
                    "provider_id": "google"
                }
            ]
            
            response = test_client.get("/mcp/tools/list_subscriptions")
            
            assert response.status_code == 200
            assert response.json()["result"][0]["provider_id"] == "google"


class TestUnsubscribeFromCalendar:
    """Tests for unsubscribe_from_calendar MCP tool."""
    
    def test_unsubscribe_succeeds(self, test_client):
        """Unsubscribe from calendar notifications succeeds."""
        with patch('src.handlers.WebhookManager.unsubscribe') as mock_unsubscribe:
            mock_unsubscribe.return_value = True
            
            response = test_client.post(
                "/mcp/tools/unsubscribe_from_calendar",
                json={
                    "subscription_id": "sub_123"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"] is True
    
    def test_unsubscribe_nonexistent_subscription(self, test_client):
        """Unsubscribe non-existent subscription returns error."""
        with patch('src.handlers.WebhookManager.unsubscribe') as mock_unsubscribe:
            mock_unsubscribe.side_effect = Exception("Subscription not found")
            
            response = test_client.post(
                "/mcp/tools/unsubscribe_from_calendar",
                json={
                    "subscription_id": "nonexistent_sub"
                }
            )
            
            assert response.status_code == 404
            assert "Subscription not found" in response.json()["error"]["message"]
    
    def test_unsubscribe_google_provider(self, test_client):
        """Unsubscribe from Google provider subscription."""
        with patch('src.handlers.WebhookManager.unsubscribe') as mock_unsubscribe:
            mock_unsubscribe.return_value = True
            
            response = test_client.post(
                "/mcp/tools/unsubscribe_from_calendar",
                json={
                    "subscription_id": "sub_google_123"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"] is True