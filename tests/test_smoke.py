"""Structural smoke tests — catch import errors, registration drift, name collisions.

These tests don't exercise individual tools; they verify the scaffolding is intact.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import reaper_mcp

PKG_ROOT = Path(reaper_mcp.__file__).parent


def _list_tools(mcp):
    return asyncio.run(mcp.list_tools())


def test_server_imports_cleanly():
    """Importing the server module must not raise — catches registration bugs."""
    from reaper_mcp.server import mcp

    assert mcp.name == "reaper-mcp-unified"


def test_cli_imports_cleanly():
    """Importing the CLI must not raise — Typer raises on bad signatures."""
    from reaper_mcp.cli import app

    assert app is not None


def test_tool_count_matches_cli_command_count():
    """Both frontends must register the same number of tools."""
    from reaper_mcp.cli import app
    from reaper_mcp.server import mcp

    def cli_count(t):
        return len(t.registered_commands) + sum(
            cli_count(g.typer_instance) for g in t.registered_groups
        )

    assert len(_list_tools(mcp)) == cli_count(app)


def test_no_duplicate_tool_names():
    """Tool names must be globally unique across all modules."""
    from reaper_mcp.server import mcp

    names = [t.name for t in _list_tools(mcp)]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert not duplicates, f"Duplicate tool names: {duplicates}"


def test_TOOL_MODULES_matches_files_on_disk():
    """Every tool module file is registered; no orphans, no phantoms.

    Catches the "added a module but forgot to register it" and reverse bugs
    that motivated the registry refactor.
    """
    from reaper_mcp.tools import TOOL_MODULES

    on_disk = {p.stem for p in (PKG_ROOT / "tools").glob("*.py") if not p.stem.startswith("_")}
    registered = {name for name, _ in TOOL_MODULES}
    assert on_disk == registered, (
        f"Mismatch — on disk only: {on_disk - registered}, registered only: {registered - on_disk}"
    )


def test_every_tool_module_has_register_tools():
    """Every module in TOOL_MODULES must expose register_tools(adapter)."""
    import importlib

    from reaper_mcp.tools import TOOL_MODULES

    for module_name, _ in TOOL_MODULES:
        module = importlib.import_module(f"reaper_mcp.tools.{module_name}")
        assert hasattr(module, "register_tools"), f"{module_name}.register_tools is missing"
        assert callable(module.register_tools), f"{module_name}.register_tools is not callable"
