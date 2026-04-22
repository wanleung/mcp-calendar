"""
Tests for OAuth2 persistence and multi-user support.

Acceptance Criteria:
- AC-13: Interactive OAuth2 authorization endpoints
- AC-14: Token persistence via database
- AC-15: User identification via unique user_id
- AC-16: Token revocation endpoint
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock


class TestOAuthAuthorization:
    """Tests for OAuth2 authorization flow."""
    
    def test_auth_google_authorize_endpoint(self, test_client):
        """Google OAuth2 authorize endpoint."""
        # Mock the authorization flow
        with patch('src.handlers.OAuthProvider.google_authorize') as mock_auth:
            mock_auth.return_value = {
                "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?...",
                "state": "test_state_123"
            }
            
            response = test_client.get("/auth/google/authorize")
            
            assert response.status_code == 200
            assert "authorization_url" in response.json()
            assert "state" in response.json()
    
    def test_auth_google_callback(self, test_client):
        """Google OAuth2 callback endpoint."""
        with patch('src.handlers.OAuthProvider.google_callback') as mock_callback:
            mock_callback.return_value = {
                "access_token": "test_access_token",
                "refresh_token": "test_refresh_token",
                "expires_in": 3600,
                "user_id": "user_123"
            }
            
            response = test_client.post(
                "/auth/google/callback",
                json={
                    "code": "auth_code_123",
                    "state": "test_state_123"
                }
            )
            
            assert response.status_code == 200
            result = response.json()
            assert result["access_token"] == "test_access_token"
            assert result["user_id"] == "user_123"
    
    def test_auth_outlook_authorize_endpoint(self, test_client):
        """Outlook OAuth2 authorize endpoint."""
        with patch('src.handlers.OAuthProvider.outlook_authorize') as mock_auth:
            mock_auth.return_value = {
                "authorization_url": "https://login.microsoftonline.com/...",
                "state": "test_state_456"
            }
            
            response = test_client.get("/auth/outlook/authorize")
            
            assert response.status_code == 200
            assert "authorization_url" in response.json()
    
    def test_auth_outlook_callback(self, test_client):
        """Outlook OAuth2 callback endpoint."""
        with patch('src.handlers.OAuthProvider.outlook_callback') as mock_callback:
            mock_callback.return_value = {
                "access_token": "test_access_token",
                "refresh_token": "test_refresh_token",
                "expires_in": 3600,
                "user_id": "user_456"
            }
            
            response = test_client.post(
                "/auth/outlook/callback",
                json={
                    "code": "auth_code_456",
                    "state": "test_state_456"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["access_token"] == "test_access_token"


class TestTokenPersistence:
    """Tests for token persistence."""
    
    def test_token_persistence_database(self, test_client):
        """Token persistence via database."""
        with patch('src.handlers.OAuthProvider.save_token') as mock_save:
            mock_save.return_value = True
            
            response = test_client.post(
                "/mcp/tools/test_token_persistence",
                json={
                    "user_id": "user_123",
                    "access_token": "test_token",
                    "refresh_token": "test_refresh",
                    "expires_in": 3600
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"] is True
    
    def test_token_persistence_with_user_id(self, test_client):
        """Token persistence includes user_id."""
        with patch('src.handlers.OAuthProvider.save_token') as mock_save:
            mock_save.return_value = True
            
            response = test_client.post(
                "/mcp/tools/test_token_persistence",
                json={
                    "user_id": "user_123",
                    "access_token": "test_token",
                    "refresh_token": "test_refresh",
                    "expires_in": 3600
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["user_id"] == "user_123"


class TestTokenRevocation:
    """Tests for token revocation."""
    
    def test_revoke_token_succeeds(self, test_client):
        """Revoke token succeeds."""
        with patch('src.handlers.OAuthProvider.revoke_token') as mock_revoke:
            mock_revoke.return_value = True
            
            response = test_client.post(
                "/auth/revoke",
                json={
                    "user_id": "user_123",
                    "access_token": "test_token"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"] is True
    
    def test_revoke_token_nonexistent(self, test_client):
        """Revoke non-existent token returns error."""
        with patch('src.handlers.OAuthProvider.revoke_token') as mock_revoke:
            mock_revoke.side_effect = Exception("Token not found")
            
            response = test_client.post(
                "/auth/revoke",
                json={
                    "user_id": "user_123",
                    "access_token": "nonexistent_token"
                }
            )
            
            assert response.status_code == 404
            assert "Token not found" in response.json()["error"]["message"]


class TestMultiUserSupport:
    """Tests for multi-user support."""
    
    def test_multi_user_operations(self, test_client):
        """Operations work for multiple users."""
        with patch('src.handlers.OAuthProvider.get_token') as mock_get:
            mock_get.side_effect = [
                {"access_token": "token_1", "user_id": "user_1"},
                {"access_token": "token_2", "user_id": "user_2"}
            ]
            
            response = test_client.post(
                "/mcp/tools/test_multi_user",
                json={
                    "user_id": "user_1",
                    "operation": "list_calendars"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["user_id"] == "user_1"
    
    def test_multi_user_isolation(self, test_client):
        """User operations are isolated."""
        with patch('src.handlers.OAuthProvider.get_token') as mock_get:
            mock_get.side_effect = [
                {"access_token": "token_1", "user_id": "user_1"},
                {"access_token": "token_2", "user_id": "user_2"}
            ]
            
            response = test_client.post(
                "/mcp/tools/test_multi_user",
                json={
                    "user_id": "user_1",
                    "operation": "list_calendars"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["user_id"] == "user_1"
            
            response = test_client.post(
                "/mcp/tools/test_multi_user",
                json={
                    "user_id": "user_2",
                    "operation": "list_calendars"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["result"]["user_id"] == "user_2"