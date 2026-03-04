"""Tests for the AgentPatch SDK and CLI (single-file, zero-dependency version)."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agentpatch import AgentPatch, AgentPatchError, main

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status: int, body: dict[str, Any]) -> MagicMock:
    """Create a mock that simulates urllib.request.urlopen return value."""
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = json.dumps(body).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _mock_http_error(status: int, body: dict[str, Any]) -> Exception:
    """Create a urllib.error.HTTPError with JSON body."""
    import urllib.error

    err = urllib.error.HTTPError(
        url="https://agentpatch.ai/api/test",
        code=status,
        msg="Error",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(json.dumps(body).encode()),
    )
    return err


def _run_cli(argv: list[str]) -> tuple[str, int]:
    """Run the CLI main() capturing stdout. Returns (output, exit_code)."""
    buf = io.StringIO()
    exit_code = 0
    try:
        with contextlib.redirect_stdout(buf):
            main(argv)
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
    return buf.getvalue(), exit_code


# ---------------------------------------------------------------------------
# SDK tests
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search(self) -> None:
        with patch("agentpatch._request", return_value=(200, SEARCH_RESPONSE)):
            with AgentPatch(api_key="test_key") as ap:
                result = ap.search()
        assert result["count"] == 1
        assert result["tools"][0]["slug"] == "google-search"

    def test_search_with_query(self) -> None:
        with patch("agentpatch._request", return_value=(200, SEARCH_RESPONSE)) as mock:
            with AgentPatch(api_key="test_key") as ap:
                result = ap.search("image", limit=10)
        assert result["count"] == 1
        call_url = mock.call_args[0][1]
        assert "q=image" in call_url
        assert "limit=10" in call_url


class TestGetTool:
    def test_get_tool(self) -> None:
        with patch("agentpatch._request", return_value=(200, TOOL_DETAIL)):
            with AgentPatch(api_key="test_key") as ap:
                tool = ap.get_tool("agentpatch", "google-search")
        assert tool["name"] == "Google Search"
        assert tool["default_timeout_seconds"] == 60

    def test_get_tool_not_found(self) -> None:
        with patch("agentpatch._request", return_value=(404, {"error": "Tool not found"})):
            with AgentPatch(api_key="test_key") as ap:
                with pytest.raises(AgentPatchError) as exc_info:
                    ap.get_tool("nobody", "fake")
        assert exc_info.value.status_code == 404


class TestInvoke:
    def test_invoke_sync(self) -> None:
        with patch("agentpatch._request", return_value=(200, INVOKE_SUCCESS)):
            with AgentPatch(api_key="test_key") as ap:
                result = ap.invoke("agentpatch", "google-search", {"query": "test"})
        assert result["status"] == "success"
        assert result["output"]["results"][0]["title"] == "Test"

    def test_invoke_async_with_poll(self) -> None:
        responses = [(202, INVOKE_PENDING), (200, JOB_SUCCESS)]
        call_count = 0

        def fake_request(*args: Any, **kwargs: Any) -> tuple[int, dict[str, Any]]:
            nonlocal call_count
            resp = responses[call_count]
            call_count += 1
            return resp

        with patch("agentpatch._request", side_effect=fake_request), patch("time.sleep"):
            with AgentPatch(api_key="test_key") as ap:
                result = ap.invoke("agentpatch", "recraft", {"prompt": "a cat"}, poll_interval=0.01)
        assert result["status"] == "success"
        assert result["output"]["image_url"] == "https://example.com/img.png"

    def test_invoke_no_poll(self) -> None:
        with patch("agentpatch._request", return_value=(202, INVOKE_PENDING)):
            with AgentPatch(api_key="test_key") as ap:
                result = ap.invoke("agentpatch", "recraft", {"prompt": "a cat"}, poll=False)
        assert result["status"] == "pending"
        assert result["job_id"] == "job_456"

    def test_invoke_requires_auth(self) -> None:
        with AgentPatch() as ap:
            with pytest.raises(AgentPatchError, match="No API key"):
                ap.invoke("agentpatch", "google-search", {"query": "test"})

    def test_invoke_error(self) -> None:
        error_body = {"error": "Insufficient credits", "required": 50, "balance": 10}
        with patch("agentpatch._request", return_value=(402, error_body)):
            with AgentPatch(api_key="test_key") as ap:
                with pytest.raises(AgentPatchError) as exc_info:
                    ap.invoke("agentpatch", "google-search", {"query": "test"})
        assert exc_info.value.status_code == 402
        assert exc_info.value.body["balance"] == 10


class TestGetJob:
    def test_get_job(self) -> None:
        with patch("agentpatch._request", return_value=(200, JOB_SUCCESS)):
            with AgentPatch(api_key="test_key") as ap:
                job = ap.get_job("job_456")
        assert job["status"] == "success"
        assert job["credits_used"] == 800

    def test_get_job_requires_auth(self) -> None:
        with AgentPatch() as ap:
            with pytest.raises(AgentPatchError, match="No API key"):
                ap.get_job("job_123")


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLISearch:
    def test_search_table(self) -> None:
        with patch("agentpatch._request", return_value=(200, SEARCH_RESPONSE)):
            output, code = _run_cli(["--api-key", "test", "search"])
        assert code == 0
        assert "google-search" in output

    def test_search_json(self) -> None:
        with patch("agentpatch._request", return_value=(200, SEARCH_RESPONSE)):
            output, code = _run_cli(["--api-key", "test", "search", "web", "--json"])
        assert code == 0
        data = json.loads(output)
        assert data["count"] == 1


class TestCLIInfo:
    def test_info(self) -> None:
        with patch("agentpatch._request", return_value=(200, TOOL_DETAIL)):
            output, code = _run_cli(["--api-key", "test", "info", "agentpatch", "google-search"])
        assert code == 0
        assert "Google Search" in output


class TestCLIRun:
    def test_run_success(self) -> None:
        with patch("agentpatch._request", return_value=(200, INVOKE_SUCCESS)):
            output, code = _run_cli([
                "--api-key", "test",
                "run", "agentpatch", "google-search",
                "--input", '{"query": "test"}',
            ])
        assert code == 0
        assert "Success" in output

    def test_run_json(self) -> None:
        with patch("agentpatch._request", return_value=(200, INVOKE_SUCCESS)):
            output, code = _run_cli([
                "--api-key", "test",
                "run", "agentpatch", "google-search",
                "--input", '{"query": "test"}',
                "--json",
            ])
        assert code == 0
        data = json.loads(output)
        assert data["status"] == "success"


class TestCLIConfig:
    def test_config_set_key(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        config_file = tmp_path / "config.toml"
        monkeypatch.setattr("agentpatch.CONFIG_FILE", config_file)
        monkeypatch.setattr("agentpatch.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("builtins.input", lambda _: "my_secret_key")

        output, code = _run_cli(["config", "set-key"])
        assert code == 0
        assert "saved" in output
        assert config_file.read_text().strip() == 'api_key = "my_secret_key"'

    def test_config_show_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENTPATCH_API_KEY", raising=False)
        monkeypatch.setattr("agentpatch.CONFIG_FILE", Path("/nonexistent/config.toml"))

        output, code = _run_cli(["config", "show"])
        assert code == 0
        assert "not set" in output or "Config" in output

    def test_config_clear(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('api_key = "test"\n')
        monkeypatch.setattr("agentpatch.CONFIG_FILE", config_file)

        output, code = _run_cli(["config", "clear"])
        assert code == 0
        assert "cleared" in output
        assert not config_file.exists()
