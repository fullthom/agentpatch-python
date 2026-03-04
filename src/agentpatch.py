"""AgentPatch — Python SDK and CLI for the AgentPatch tool marketplace.

Zero-dependency, single-file package. Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

__all__ = ["AgentPatch", "AgentPatchError"]
__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".agentpatch"
CONFIG_FILE = CONFIG_DIR / "config.toml"


def resolve_api_key(explicit: str | None = None) -> str | None:
    """Resolve API key from: explicit param > env var > config file."""
    if explicit:
        return explicit
    from_env = os.environ.get("AGENTPATCH_API_KEY")
    if from_env:
        return from_env
    return _load_from_config()


def _load_from_config() -> str | None:
    """Read API key from ~/.agentpatch/config.toml."""
    if not CONFIG_FILE.exists():
        return None
    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib  # type: ignore[no-redef]
        data = tomllib.loads(CONFIG_FILE.read_text())
        return data.get("api_key")
    except Exception:
        for line in CONFIG_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("api_key"):
                _, _, value = line.partition("=")
                return value.strip().strip('"').strip("'")
        return None


def save_api_key(api_key: str) -> Path:
    """Save API key to ~/.agentpatch/config.toml. Returns the config file path."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(f'api_key = "{api_key}"\n')
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass  # Windows may not support chmod
    return CONFIG_FILE


def clear_config() -> None:
    """Delete the config file."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None = None,
    timeout: float = 120.0,
) -> tuple[int, dict[str, Any]]:
    """Make an HTTP request and return (status_code, parsed_json)."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            return resp.status, data
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            data = {"error": body or f"HTTP {e.code}"}
        return e.code, data


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

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
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers: dict[str, str] = {"User-Agent": f"agentpatch-python/{__version__}"}
        if self._api_key:
            self._headers["Authorization"] = f"Bearer {self._api_key}"

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

        url = f"{self._base_url}/api/tools/{username}/{slug}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        status, data = _request("POST", url, self._headers, json.dumps(input).encode(), self._timeout)

        if status >= 400:
            raise AgentPatchError(data.get("error", "Request failed"), status, data)

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
        url = f"{self._base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        status, data = _request("GET", url, self._headers, timeout=self._timeout)
        if status >= 400:
            raise AgentPatchError(data.get("error", "Request failed"), status, data)
        return data

    def _require_auth(self) -> None:
        """Raise if no API key is configured."""
        if not self._api_key:
            raise AgentPatchError(
                "No API key configured. Set AGENTPATCH_API_KEY env var, "
                "run 'agentpatch config set-key', or pass api_key= to AgentPatch()."
            )

    def close(self) -> None:
        """Close the client (no-op — urllib doesn't need connection management)."""

    def __enter__(self) -> AgentPatch:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

_ANSI = sys.stdout.isatty()


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m" if _ANSI else text


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m" if _ANSI else text


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m" if _ANSI else text


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m" if _ANSI else text


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m" if _ANSI else text


def _print_table(headers: list[str], rows: list[list[str]], title: str | None = None) -> None:
    """Print a simple column-aligned table."""
    if not rows:
        return
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    if title:
        print(f"\n  {title}")

    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    print(f"  {header_line}")
    print(f"  {'  '.join('-' * w for w in col_widths)}")
    for row in rows:
        line = "  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row))
        print(f"  {line}")
    print()


def _output_json(data: Any) -> None:
    """Print raw JSON to stdout."""
    print(json.dumps(data, indent=2))


def _error(message: str) -> None:
    """Print error and exit."""
    print(f"{_red('Error:')} {message}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# CLI subcommands
# ---------------------------------------------------------------------------

def _cmd_search(args: argparse.Namespace) -> None:
    """Handle 'search' subcommand."""
    client = AgentPatch(api_key=args.api_key, base_url=args.base_url)
    try:
        result = client.search(
            args.query,
            limit=args.limit,
            max_price_credits=args.max_price,
            min_success_rate=args.min_rate,
        )
    except AgentPatchError as e:
        _error(str(e))

    if args.json:
        _output_json(result)
        return

    tools = result.get("tools", [])
    if not tools:
        print("No tools found.")
        return

    rows: list[list[str]] = []
    for t in tools:
        price = t.get("price_credits_per_call", 0)
        rate = t.get("success_rate")
        rate_str = f"{rate:.0%}" if rate is not None else "-"
        owner = t.get("owner_username", "")
        rows.append([
            f"{owner}/{t['slug']}",
            t.get("description", "")[:50],
            f"{price} cr",
            rate_str,
        ])

    _print_table(
        ["Tool", "Description", "Price", "Success"],
        rows,
        title=f"Found {result.get('count', len(tools))} tools",
    )


def _cmd_info(args: argparse.Namespace) -> None:
    """Handle 'info' subcommand."""
    client = AgentPatch(api_key=args.api_key, base_url=args.base_url)
    try:
        tool = client.get_tool(args.username, args.slug)
    except AgentPatchError as e:
        _error(str(e))

    if args.json:
        _output_json(tool)
        return

    rate = tool.get("success_rate")
    rate_str = f"{rate * 100:.0f}%" if rate else "-"
    print(f"\n{_bold(tool.get('name', args.slug))}")
    print(
        f"by {tool.get('owner_username', args.username)} | "
        f"{tool.get('price_credits_per_call', '?')} credits/call | "
        f"{rate_str} success rate | "
        f"{tool.get('total_calls', 0) or 0} total calls\n"
    )
    print(f"{tool.get('description', '')}\n")

    input_schema = tool.get("input_schema", {})
    if input_schema.get("properties"):
        print(f"{_bold('Input Schema:')}")
        print(json.dumps(input_schema, indent=2))


def _cmd_run(args: argparse.Namespace) -> None:
    """Handle 'run' subcommand."""
    try:
        tool_input = json.loads(args.input)
    except json.JSONDecodeError as e:
        _error(f"Invalid JSON input: {e}")

    client = AgentPatch(api_key=args.api_key, base_url=args.base_url)

    try:
        result = client.invoke(
            args.username,
            args.slug,
            tool_input,
            timeout_seconds=args.timeout,
            poll=not args.no_poll,
        )
    except AgentPatchError as e:
        _error(str(e))

    if args.json:
        _output_json(result)
        return

    status = result.get("status", "unknown")
    if status == "success":
        credits = result.get("credits_used", 0)
        latency = result.get("latency_ms")
        meta = f"{credits} credits"
        if latency:
            meta += f", {latency}ms"
        print(f"{_green('Success')} ({meta})\n")
        output = result.get("output")
        if output is not None:
            print(json.dumps(output, indent=2, default=str))
    elif status == "pending":
        print(f"{_yellow('Job started:')} {result.get('job_id')}")
        print(f"Poll with: agentpatch job {result.get('job_id')}")
    elif status == "failed":
        print(f"{_red('Failed:')} {result.get('error', 'Unknown error')}")
    else:
        _output_json(result)


def _cmd_job(args: argparse.Namespace) -> None:
    """Handle 'job' subcommand."""
    client = AgentPatch(api_key=args.api_key, base_url=args.base_url)

    try:
        if args.poll:
            start = time.monotonic()
            while True:
                result = client.get_job(args.job_id)
                if result.get("status") in ("success", "failed", "timeout"):
                    break
                if time.monotonic() - start > 300:
                    _error("Timed out waiting for job")
                time.sleep(5)
        else:
            result = client.get_job(args.job_id)
    except AgentPatchError as e:
        _error(str(e))

    if args.json:
        _output_json(result)
        return

    status = result.get("status", "unknown")
    print(f"Job:     {result.get('job_id', args.job_id)}")
    print(f"Status:  {status}")
    if result.get("credits_used") is not None:
        print(f"Credits: {result['credits_used']}")
    if result.get("latency_ms") is not None:
        print(f"Latency: {result['latency_ms']}ms")

    output = result.get("output")
    if output is not None:
        print()
        print(json.dumps(output, indent=2, default=str))

    if result.get("error"):
        print(f"\n{_red('Error:')} {result['error']}")


def _cmd_config_set_key(args: argparse.Namespace) -> None:
    """Handle 'config set-key' subcommand."""
    api_key = input("Enter your AgentPatch API key: ")
    path = save_api_key(api_key)
    print(f"API key saved to {path}")
    print("Get your key at: https://agentpatch.ai/dashboard")


def _cmd_config_show(args: argparse.Namespace) -> None:
    """Handle 'config show' subcommand."""
    key = resolve_api_key()
    if key:
        masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "****"
        print(f"API key: {masked}")
    else:
        print(f"API key: {_dim('not set')}")
    print(f"Config:  {CONFIG_FILE}")


def _cmd_config_clear(args: argparse.Namespace) -> None:
    """Handle 'config clear' subcommand."""
    clear_config()
    print("Config cleared.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _detect_prog() -> str:
    """Detect whether the user invoked 'agentpatch' or 'ap'."""
    if sys.argv and sys.argv[0]:
        name = Path(sys.argv[0]).name
        if name.startswith("agentpatch"):
            return "agentpatch"
    return "ap"


def main(argv: list[str] | None = None) -> None:
    """CLI entry point. Pass argv for testing, or None to use sys.argv."""
    prog = _detect_prog()

    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "AgentPatch — a tool marketplace for AI agents.\n\n"
            "Search and invoke 25+ tools (web search, image generation, email,\n"
            "Google Maps, YouTube transcripts, and more) from the command line.\n"
            "One API key, no extra accounts needed.\n\n"
            "Get started:  pip install agentpatch\n"
            f"              {prog} config set-key\n"
            f"              {prog} search \"web search\"\n\n"
            "Sign up for free at https://agentpatch.ai (10,000 credits included)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--api-key", default=os.environ.get("AGENTPATCH_API_KEY"), help="API key (overrides config).")
    parser.add_argument("--base-url", default="https://agentpatch.ai", help="API base URL.")

    subparsers = parser.add_subparsers(dest="command")

    # search
    p_search = subparsers.add_parser("search", help="Search for tools in the marketplace.")
    p_search.add_argument("query", nargs="?", default=None, help="Search query (omit to browse all tools).")
    p_search.add_argument("--limit", type=int, default=20, help="Max results (1-100).")
    p_search.add_argument("--max-price", type=int, default=None, help="Max price in credits per call.")
    p_search.add_argument("--min-rate", type=float, default=None, help="Min success rate (0.0-1.0).")
    p_search.add_argument("--json", action="store_true", help="Output raw JSON.")
    p_search.set_defaults(func=_cmd_search)

    # info
    p_info = subparsers.add_parser("info", help="Get details about a specific tool (schema, pricing, stats).")
    p_info.add_argument("username", help="Tool owner's username.")
    p_info.add_argument("slug", help="Tool slug.")
    p_info.add_argument("--json", action="store_true", help="Output raw JSON.")
    p_info.set_defaults(func=_cmd_info)

    # run
    p_run = subparsers.add_parser("run", help="Invoke a tool and get results.")
    p_run.add_argument("username", help="Tool owner's username.")
    p_run.add_argument("slug", help="Tool slug.")
    p_run.add_argument("--input", required=True, help="Tool input as a JSON string.")
    p_run.add_argument("--no-poll", action="store_true", help="Return immediately without waiting for async results.")
    p_run.add_argument("--timeout", type=int, default=None, help="Server-side timeout in seconds (1-3600).")
    p_run.add_argument("--json", action="store_true", help="Output raw JSON.")
    p_run.set_defaults(func=_cmd_run)

    # job
    p_job = subparsers.add_parser("job", help="Check the status of an async job.")
    p_job.add_argument("job_id", help="Job ID returned by a previous invocation.")
    p_job.add_argument("--poll", action="store_true", help="Poll until the job completes.")
    p_job.add_argument("--json", action="store_true", help="Output raw JSON.")
    p_job.set_defaults(func=_cmd_job)

    # config (with sub-subcommands)
    p_config = subparsers.add_parser("config", help="Manage API key and configuration.")
    config_sub = p_config.add_subparsers(dest="config_command")

    p_set_key = config_sub.add_parser("set-key", help="Save your API key.")
    p_set_key.set_defaults(func=_cmd_config_set_key)

    p_show = config_sub.add_parser("show", help="Show current configuration.")
    p_show.set_defaults(func=_cmd_config_show)

    p_clear = config_sub.add_parser("clear", help="Delete the config file.")
    p_clear.set_defaults(func=_cmd_config_clear)

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "config" and not args.config_command:
        p_config.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
