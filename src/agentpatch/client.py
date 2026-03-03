"""AgentPatch SDK client — thin wrapper over the REST API."""

from __future__ import annotations

import time
from typing import Any

import httpx

from agentpatch.config import resolve_api_key

DEFAULT_BASE_URL = "https://agentpatch.ai"
DEFAULT_TIMEOUT = 120.0
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_POLL_TIMEOUT = 300.0


class AgentPatchError(Exception):
    """Base exception for AgentPatch API errors."""

    def __init__(self, message: str, status_code: int | None = None, body: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class AgentPatch:
    """Client for the AgentPatch tool marketplace.

    Args:
        api_key: API key. Falls back to AGENTPATCH_API_KEY env var, then ~/.agentpatch/config.toml.
        base_url: API base URL (default: https://agentpatch.ai).
        timeout: HTTP request timeout in seconds (default: 120).
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = resolve_api_key(api_key)
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        self._http = httpx.Client(base_url=base_url, headers=headers, timeout=timeout)

    def search(
        self,
        query: str | None = None,
        *,
        min_success_rate: float | None = None,
        max_price_credits: int | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search the marketplace for tools. Returns {"tools": [...], "count": N}."""
        params: dict[str, Any] = {"limit": limit}
        if query is not None:
            params["q"] = query
        if min_success_rate is not None:
            params["min_success_rate"] = min_success_rate
        if max_price_credits is not None:
            params["max_price_credits"] = max_price_credits
        return self._get("/api/search", params=params)

    def get_tool(self, username: str, slug: str) -> dict[str, Any]:
        """Get detailed information about a specific tool."""
        return self._get(f"/api/tools/{username}/{slug}")

    def invoke(
        self,
        username: str,
        slug: str,
        input: dict[str, Any],
        *,
        timeout_seconds: int | None = None,
        poll: bool = True,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
    ) -> dict[str, Any]:
        """Invoke a tool. Auto-polls async jobs to completion by default.

        Pass poll=False to return immediately with job_id for manual polling.
        """
        self._require_auth()
        params: dict[str, Any] = {}
        if timeout_seconds is not None:
            params["timeout_seconds"] = timeout_seconds

        resp = self._http.post(f"/api/tools/{username}/{slug}", json=input, params=params)
        data = resp.json()

        if resp.status_code >= 400:
            raise AgentPatchError(data.get("error", "Request failed"), resp.status_code, data)

        if not poll or data.get("status") != "pending":
            return data

        # Poll until completion
        job_id = data["job_id"]
        start = time.monotonic()
        while time.monotonic() - start < poll_timeout:
            time.sleep(poll_interval)
            job = self.get_job(job_id)
            if job["status"] in ("success", "failed", "timeout"):
                return job
        raise AgentPatchError(f"Job {job_id} did not complete within {poll_timeout}s")

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Check the status of an async job."""
        self._require_auth()
        return self._get(f"/api/jobs/{job_id}")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request and return parsed JSON."""
        resp = self._http.get(path, params=params)
        data = resp.json()
        if resp.status_code >= 400:
            raise AgentPatchError(data.get("error", "Request failed"), resp.status_code, data)
        return data

    def _require_auth(self) -> None:
        """Raise if no API key is configured."""
        if not self._api_key:
            raise AgentPatchError(
                "No API key configured. Set AGENTPATCH_API_KEY env var, "
                "run 'ap config set-key', or pass api_key= to AgentPatch()."
            )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> AgentPatch:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
