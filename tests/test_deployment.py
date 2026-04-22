"""Deployment smoke tests for Calendar MCP Service.

Tests hit real HTTP endpoints on the running container using httpx.
Each test is stateless and works independently.
"""

import os
import pytest
import httpx

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")


def _mcp_request(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    """Build a JSON-RPC 2.0 MCP request."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }


class TestHealthCheck:
    """Test the health check endpoint."""

    def test_health_returns_200(self):
        response = httpx.get(f"{BASE_URL}/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert "version" in body

    def test_health_content_type(self):
        response = httpx.get(f"{BASE_URL}/health")
        assert "application/json" in response.headers.get("content-type", "")


class TestMCPInitialization:
    """Test MCP protocol initialization via /initialize endpoint."""

    def test_initialize_returns_200(self):
        payload = _mcp_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        })
        response = httpx.post(f"{BASE_URL}/initialize", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body.get("result", {}).get("protocolVersion") == "2024-11-05"
        assert "serverInfo" in body["result"]

    def test_initialize_returns_server_capabilities(self):
        payload = _mcp_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        })
        response = httpx.post(f"{BASE_URL}/initialize", json=payload)
        body = response.json()
        capabilities = body["result"]["capabilities"]
        assert "tools" in capabilities
        assert capabilities["tools"]["list"] is True


class TestMCPToolsList:
    """Test MCP tools/list via /messages endpoint."""

    def test_tools_list_returns_200(self):
        payload = _mcp_request("tools/list")
        response = httpx.post(f"{BASE_URL}/messages", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert "tools" in body["result"]
        assert len(body["result"]["tools"]) > 0

    def test_tools_list_contains_calendar_tools(self):
        payload = _mcp_request("tools/list")
        response = httpx.post(f"{BASE_URL}/messages", json=payload)
        body = response.json()
        tool_names = [t["name"] for t in body["result"]["tools"]]
        assert "list_calendars" in tool_names
        assert "get_events" in tool_names
        assert "create_event" in tool_names


class TestMCPCallUnknownTool:
    """Test calling an unknown tool returns an error."""

    def test_unknown_tool_returns_error(self):
        payload = _mcp_request("tools/call", {
            "name": "nonexistent_tool",
            "arguments": {},
        })
        response = httpx.post(f"{BASE_URL}/messages", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["isError"] is True


class TestNotFound:
    """Test 404 handling for unknown routes."""

    def test_unknown_route_returns_404(self):
        response = httpx.get(f"{BASE_URL}/api/v1/nonexistent")
        assert response.status_code == 404

    def test_unknown_post_route_returns_404(self):
        response = httpx.post(f"{BASE_URL}/api/v1/nonexistent")
        assert response.status_code == 404