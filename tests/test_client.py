"""Tests for the AgentPatch SDK client."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from agentpatch import AgentPatch, AgentPatchError

BASE = "https://agentpatch.ai"

SEARCH_RESPONSE = {
    "tools": [
        {
            "slug": "google-search",
            "name": "Google Search",
            "description": "Search the web",
            "price_credits_per_call": 50,
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            "output_schema": {"type": "object"},
            "owner_username": "agentpatch",
            "success_rate": 0.99,
            "total_calls": 1000,
            "avg_latency_ms": 500,
        }
    ],
    "count": 1,
}

TOOL_DETAIL = {
    "slug": "google-search",
    "name": "Google Search",
    "description": "Search the web via Google",
    "price_credits_per_call": 50,
    "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
    "output_schema": {"type": "object"},
    "owner_username": "agentpatch",
    "success_rate": 0.99,
    "total_calls": 1000,
    "avg_latency_ms": 500,
    "default_timeout_seconds": 60,
    "max_timeout_seconds": 600,
}

INVOKE_SUCCESS = {
    "job_id": "job_123",
    "status": "success",
    "output": {"results": [{"title": "Test"}]},
    "latency_ms": 450,
    "credits_used": 50,
    "credits_remaining": 9950,
}

INVOKE_PENDING = {
    "job_id": "job_456",
    "status": "pending",
    "poll_url": "/api/jobs/job_456",
    "credits_reserved": 800,
    "credits_remaining": 9200,
}

JOB_SUCCESS = {
    "job_id": "job_456",
    "tool_id": "tool_abc",
    "status": "success",
    "output": {"image_url": "https://example.com/img.png"},
    "latency_ms": 12000,
    "credits_used": 800,
    "credits_remaining": 9200,
    "created_at": "2026-03-01T00:00:00Z",
    "completed_at": "2026-03-01T00:00:12Z",
}


def test_search(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/search?limit=20", json=SEARCH_RESPONSE)
    with AgentPatch(api_key="test_key") as ap:
        result = ap.search()
    assert result["count"] == 1
    assert result["tools"][0]["slug"] == "google-search"


def test_search_with_query(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/search?q=image&limit=10", json=SEARCH_RESPONSE)
    with AgentPatch(api_key="test_key") as ap:
        result = ap.search("image", limit=10)
    assert result["count"] == 1


def test_get_tool(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/tools/agentpatch/google-search", json=TOOL_DETAIL)
    with AgentPatch(api_key="test_key") as ap:
        tool = ap.get_tool("agentpatch", "google-search")
    assert tool["name"] == "Google Search"
    assert tool["default_timeout_seconds"] == 60


def test_get_tool_not_found(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/tools/nobody/fake", json={"error": "Tool not found"}, status_code=404)
    with AgentPatch(api_key="test_key") as ap:
        with pytest.raises(AgentPatchError) as exc_info:
            ap.get_tool("nobody", "fake")
    assert exc_info.value.status_code == 404


def test_invoke_sync(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=f"{BASE}/api/tools/agentpatch/google-search", json=INVOKE_SUCCESS)
    with AgentPatch(api_key="test_key") as ap:
        result = ap.invoke("agentpatch", "google-search", {"query": "test"})
    assert result["status"] == "success"
    assert result["output"]["results"][0]["title"] == "Test"


def test_invoke_async_with_poll(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/api/tools/agentpatch/recraft",
        json=INVOKE_PENDING,
        status_code=202,
    )
    httpx_mock.add_response(method="GET", url=f"{BASE}/api/jobs/job_456", json=JOB_SUCCESS)
    with AgentPatch(api_key="test_key") as ap:
        result = ap.invoke("agentpatch", "recraft", {"prompt": "a cat"}, poll_interval=0.01)
    assert result["status"] == "success"
    assert result["output"]["image_url"] == "https://example.com/img.png"


def test_invoke_no_poll(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/api/tools/agentpatch/recraft",
        json=INVOKE_PENDING,
        status_code=202,
    )
    with AgentPatch(api_key="test_key") as ap:
        result = ap.invoke("agentpatch", "recraft", {"prompt": "a cat"}, poll=False)
    assert result["status"] == "pending"
    assert result["job_id"] == "job_456"


def test_invoke_requires_auth() -> None:
    with AgentPatch() as ap:
        with pytest.raises(AgentPatchError, match="No API key"):
            ap.invoke("agentpatch", "google-search", {"query": "test"})


def test_get_job(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/jobs/job_456", json=JOB_SUCCESS)
    with AgentPatch(api_key="test_key") as ap:
        job = ap.get_job("job_456")
    assert job["status"] == "success"
    assert job["credits_used"] == 800


def test_get_job_requires_auth() -> None:
    with AgentPatch() as ap:
        with pytest.raises(AgentPatchError, match="No API key"):
            ap.get_job("job_123")


def test_invoke_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/api/tools/agentpatch/google-search",
        json={"error": "Insufficient credits", "required": 50, "balance": 10},
        status_code=402,
    )
    with AgentPatch(api_key="test_key") as ap:
        with pytest.raises(AgentPatchError) as exc_info:
            ap.invoke("agentpatch", "google-search", {"query": "test"})
    assert exc_info.value.status_code == 402
    assert exc_info.value.body["balance"] == 10
