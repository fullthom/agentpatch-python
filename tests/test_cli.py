"""Tests for the AgentPatch CLI."""

from __future__ import annotations

import json

from click.testing import CliRunner
from pytest_httpx import HTTPXMock

from agentpatch.cli import cli

BASE = "https://agentpatch.ai"

SEARCH_RESPONSE = {
    "tools": [
        {
            "slug": "google-search",
            "name": "Google Search",
            "description": "Search the web",
            "price_credits_per_call": 50,
            "owner_username": "agentpatch",
            "success_rate": 0.99,
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
}

INVOKE_SUCCESS = {
    "job_id": "job_123",
    "status": "success",
    "output": {"results": [{"title": "Test"}]},
    "latency_ms": 450,
    "credits_used": 50,
    "credits_remaining": 9950,
}


def test_search_table(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/search?limit=20", json=SEARCH_RESPONSE)
    runner = CliRunner()
    result = runner.invoke(cli, ["--api-key", "test", "search"])
    assert result.exit_code == 0
    assert "google-search" in result.output


def test_search_json(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/search?q=web&limit=20", json=SEARCH_RESPONSE)
    runner = CliRunner()
    result = runner.invoke(cli, ["--api-key", "test", "search", "web", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["count"] == 1


def test_info(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE}/api/tools/agentpatch/google-search", json=TOOL_DETAIL)
    runner = CliRunner()
    result = runner.invoke(cli, ["--api-key", "test", "info", "agentpatch", "google-search"])
    assert result.exit_code == 0
    assert "Google Search" in result.output


def test_run_success(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=f"{BASE}/api/tools/agentpatch/google-search", json=INVOKE_SUCCESS)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--api-key",
            "test",
            "run",
            "agentpatch",
            "google-search",
            "--input",
            '{"query": "test"}',
        ],
    )
    assert result.exit_code == 0
    assert "Success" in result.output


def test_run_json(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=f"{BASE}/api/tools/agentpatch/google-search", json=INVOKE_SUCCESS)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--api-key",
            "test",
            "run",
            "agentpatch",
            "google-search",
            "--input",
            '{"query": "test"}',
            "--json",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"


def test_config_set_key(tmp_path, monkeypatch) -> None:
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("agentpatch.cli.CONFIG_FILE", config_file)
    monkeypatch.setattr("agentpatch.config.CONFIG_FILE", config_file)
    monkeypatch.setattr("agentpatch.config.CONFIG_DIR", tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["config", "set-key"], input="my_secret_key\n")
    assert result.exit_code == 0
    assert "saved" in result.output
    assert config_file.read_text().strip() == 'api_key = "my_secret_key"'


def test_config_show_no_key() -> None:
    runner = CliRunner(env={"AGENTPATCH_API_KEY": ""})
    result = runner.invoke(cli, ["config", "show"])
    assert result.exit_code == 0
    assert "not set" in result.output or "Config" in result.output
