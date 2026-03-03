"""API key resolution and config file management."""

from __future__ import annotations

import os
import sys
from pathlib import Path

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
        # Fall back to simple line parsing if tomli not installed
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
