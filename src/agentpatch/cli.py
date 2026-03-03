"""AgentPatch CLI — ap command."""

from __future__ import annotations

import json
import sys
from typing import Any

import click
from rich.console import Console
from rich.json import JSON as RichJSON
from rich.table import Table

from agentpatch.client import AgentPatch, AgentPatchError
from agentpatch.config import CONFIG_FILE, clear_config, save_api_key

console = Console()


def _make_client(api_key: str | None, base_url: str) -> AgentPatch:
    """Create an AgentPatch client from CLI options."""
    return AgentPatch(api_key=api_key, base_url=base_url)


def _output_json(data: Any) -> None:
    """Print raw JSON to stdout."""
    click.echo(json.dumps(data, indent=2))


@click.group()
@click.option("--api-key", envvar="AGENTPATCH_API_KEY", default=None, help="API key (overrides config).")
@click.option("--base-url", default="https://agentpatch.ai", help="API base URL.")
@click.pass_context
def cli(ctx: click.Context, api_key: str | None, base_url: str) -> None:
    """AgentPatch — discover and use AI tools from the command line."""
    ctx.ensure_object(dict)
    ctx.obj["api_key"] = api_key
    ctx.obj["base_url"] = base_url


@cli.command()
@click.argument("query", required=False)
@click.option("--limit", default=20, help="Max results (1-100).")
@click.option("--max-price", type=int, default=None, help="Max price in credits.")
@click.option("--min-rate", type=float, default=None, help="Min success rate (0-1).")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
@click.pass_context
def search(
    ctx: click.Context,
    query: str | None,
    limit: int,
    max_price: int | None,
    min_rate: float | None,
    as_json: bool,
) -> None:
    """Search for tools in the marketplace."""
    client = _make_client(ctx.obj["api_key"], ctx.obj["base_url"])
    try:
        result = client.search(query, limit=limit, max_price_credits=max_price, min_success_rate=min_rate)
    except AgentPatchError as e:
        _error(str(e))

    if as_json:
        _output_json(result)
        return

    tools = result.get("tools", [])
    if not tools:
        console.print("No tools found.")
        return

    table = Table(title=f"Found {result.get('count', len(tools))} tools")
    table.add_column("Tool", style="cyan")
    table.add_column("Description", max_width=50)
    table.add_column("Price", justify="right")
    table.add_column("Success", justify="right")

    for t in tools:
        price = t.get("price_credits_per_call", 0)
        rate = t.get("success_rate")
        rate_str = f"{rate:.0%}" if rate is not None else "-"
        owner = t.get("owner_username", "")
        table.add_row(
            f"{owner}/{t['slug']}",
            t.get("description", "")[:50],
            f"{price} cr",
            rate_str,
        )

    console.print(table)


@cli.command()
@click.argument("username")
@click.argument("slug")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
@click.pass_context
def info(ctx: click.Context, username: str, slug: str, as_json: bool) -> None:
    """Get details about a specific tool."""
    client = _make_client(ctx.obj["api_key"], ctx.obj["base_url"])
    try:
        tool = client.get_tool(username, slug)
    except AgentPatchError as e:
        _error(str(e))

    if as_json:
        _output_json(tool)
        return

    console.print(f"\n[bold]{tool.get('name', slug)}[/bold]")
    console.print(
        f"by {tool.get('owner_username', username)} | "
        f"{tool.get('price_credits_per_call', '?')} credits/call | "
        f"{'%.0f%%' % (tool['success_rate'] * 100) if tool.get('success_rate') else '-'} success rate | "
        f"{tool.get('total_calls', 0) or 0} total calls\n"
    )
    console.print(f"{tool.get('description', '')}\n")

    input_schema = tool.get("input_schema", {})
    if input_schema.get("properties"):
        console.print("[bold]Input Schema:[/bold]")
        console.print(RichJSON(json.dumps(input_schema, indent=2)))


@cli.command()
@click.argument("username")
@click.argument("slug")
@click.option("--input", "input_json", required=True, help="Tool input as JSON string.")
@click.option("--no-poll", is_flag=True, help="Don't wait for async results.")
@click.option("--timeout", "timeout_seconds", type=int, default=None, help="Server-side timeout (1-3600s).")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
@click.pass_context
def run(
    ctx: click.Context,
    username: str,
    slug: str,
    input_json: str,
    no_poll: bool,
    timeout_seconds: int | None,
    as_json: bool,
) -> None:
    """Invoke a tool with input data."""
    try:
        tool_input = json.loads(input_json)
    except json.JSONDecodeError as e:
        _error(f"Invalid JSON input: {e}")

    client = _make_client(ctx.obj["api_key"], ctx.obj["base_url"])

    try:
        if no_poll:
            result = client.invoke(username, slug, tool_input, timeout_seconds=timeout_seconds, poll=False)
        else:
            with console.status(f"Invoking {username}/{slug}..."):
                result = client.invoke(username, slug, tool_input, timeout_seconds=timeout_seconds)
    except AgentPatchError as e:
        _error(str(e))

    if as_json:
        _output_json(result)
        return

    status = result.get("status", "unknown")
    if status == "success":
        credits = result.get("credits_used", 0)
        latency = result.get("latency_ms")
        meta = f"{credits} credits"
        if latency:
            meta += f", {latency}ms"
        console.print(f"[green]Success[/green] ({meta})\n")
        output = result.get("output")
        if output is not None:
            console.print(RichJSON(json.dumps(output, indent=2, default=str)))
    elif status == "pending":
        console.print(f"[yellow]Job started:[/yellow] {result.get('job_id')}")
        console.print(f"Poll with: ap job {result.get('job_id')}")
    elif status == "failed":
        console.print(f"[red]Failed:[/red] {result.get('error', 'Unknown error')}")
    else:
        _output_json(result)


@cli.command()
@click.argument("job_id")
@click.option("--poll", is_flag=True, help="Poll until job completes.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
@click.pass_context
def job(ctx: click.Context, job_id: str, poll: bool, as_json: bool) -> None:
    """Check the status of an async job."""
    import time

    client = _make_client(ctx.obj["api_key"], ctx.obj["base_url"])

    try:
        if poll:
            with console.status(f"Waiting for {job_id}..."):
                start = time.monotonic()
                while True:
                    result = client.get_job(job_id)
                    if result.get("status") in ("success", "failed", "timeout"):
                        break
                    if time.monotonic() - start > 300:
                        _error("Timed out waiting for job")
                    time.sleep(5)
        else:
            result = client.get_job(job_id)
    except AgentPatchError as e:
        _error(str(e))

    if as_json:
        _output_json(result)
        return

    status = result.get("status", "unknown")
    console.print(f"Job:     {result.get('job_id', job_id)}")
    console.print(f"Status:  {status}")
    if result.get("credits_used") is not None:
        console.print(f"Credits: {result['credits_used']}")
    if result.get("latency_ms") is not None:
        console.print(f"Latency: {result['latency_ms']}ms")

    output = result.get("output")
    if output is not None:
        console.print()
        console.print(RichJSON(json.dumps(output, indent=2, default=str)))

    if result.get("error"):
        console.print(f"\n[red]Error:[/red] {result['error']}")


@cli.group()
def config() -> None:
    """Manage API key and configuration."""
    pass


@config.command("set-key")
def config_set_key() -> None:
    """Save your API key to ~/.agentpatch/config.toml."""
    api_key = click.prompt("Enter your AgentPatch API key", hide_input=True)
    path = save_api_key(api_key)
    console.print(f"API key saved to {path}")
    console.print("Get your key at: https://agentpatch.ai/dashboard")


@config.command("show")
def config_show() -> None:
    """Show current configuration."""
    from agentpatch.config import resolve_api_key

    key = resolve_api_key()
    if key:
        masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "****"
        console.print(f"API key: {masked}")
    else:
        console.print("API key: [dim]not set[/dim]")
    console.print(f"Config:  {CONFIG_FILE}")


@config.command("clear")
def config_clear() -> None:
    """Delete the config file."""
    clear_config()
    console.print("Config cleared.")


def _error(message: str) -> None:
    """Print error and exit."""
    console.print(f"[red]Error:[/red] {message}", highlight=False)
    sys.exit(1)
