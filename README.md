# AgentPatch

Zero-dependency Python SDK and CLI for the [AgentPatch](https://agentpatch.ai) tool marketplace. Single file, stdlib only.

## Install

```bash
pip install agentpatch
```

Or with [pipx](https://pipx.pypa.io/) for CLI-only usage:

```bash
pipx install agentpatch
```

Or just copy `src/agentpatch.py` into your project — it has no dependencies beyond Python 3.10+.

## Authentication

Get your API key from [agentpatch.ai/dashboard](https://agentpatch.ai/dashboard), then either:

```bash
# Option 1: Save to config file
ap config set-key

# Option 2: Environment variable
export AGENTPATCH_API_KEY=ap_your_key_here
```

## CLI Usage

```bash
# Search for tools
ap search "image generation"
ap search --max-price 100 --json

# Get tool details
ap info google-search

# Invoke a tool (waits for result by default)
ap run google-search --input '{"query": "best pizza NYC"}'

# Invoke without waiting (for async tools)
ap run generate-image-recraft --input '{"prompt": "a cat"}' --no-poll

# Check async job status
ap job job_abc123
ap job job_abc123 --poll    # wait for completion
```

Every command supports `--json` for scripting:

```bash
ap search "email" --json | jq '.[0].slug'
ap run google-search --input '{"query": "test"}' --json | jq '.output'
```

## SDK Usage

```python
from agentpatch import AgentPatch

ap = AgentPatch()  # uses AGENTPATCH_API_KEY env var or ~/.agentpatch/config.toml

# Search for tools
tools = ap.search("image generation")
for t in tools["tools"]:
    print(f"{t['owner_username']}/{t['slug']} — {t['price_credits_per_call']} credits")

# Get tool details
tool = ap.get_tool("google-search")
print(tool["input_schema"])

# Invoke a tool (auto-polls async jobs)
result = ap.invoke("google-search", {"query": "best pizza NYC"})
print(result["output"])

# Manual async control
result = ap.invoke("generate-image-recraft", {"prompt": "a cat"}, poll=False)
job = ap.get_job(result["job_id"])
```

## Configuration

API key resolution order:
1. `api_key=` parameter (SDK) or `--api-key` flag (CLI)
2. `AGENTPATCH_API_KEY` environment variable
3. `~/.agentpatch/config.toml` file

```bash
ap config set-key    # save API key
ap config show       # show current config
ap config clear      # delete config file
```

## License

MIT
