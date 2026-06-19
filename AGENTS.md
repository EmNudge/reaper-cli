# AGENTS.md

Notes for contributors and AI agents working on this repo. For install / usage,
see the [README](README.md).

## Layout

- `src/reaper_mcp/server.py` — single `FastMCP` instance; calls `register_all()`.
- `src/reaper_mcp/cli.py` — Typer CLI exposing the same tool functions, grouped by module.
- `src/reaper_mcp/tools/<group>.py` — one module per tool group. Each defines tool functions and a `register_tools(adapter)` that decorates them on the FastMCP-style adapter.
- `src/reaper_mcp/tools/__init__.py` — `TOOL_MODULES` is the single source of truth for which modules exist. Both the MCP server and the CLI iterate it; **adding a new group is a one-line edit** there plus the new file in `tools/`.
- `src/reaper_mcp/connection.py` — lazy `reapy.connect()` shared by every live tool. Offline tools never trigger it. Don't call `reapy.connect()` directly from a tool module.
- `src/reaper_mcp/config.py` — persistent user config via `platformdirs`.
- `src/reaper_mcp/utils/positions.py` — `bar:beat,fraction` ↔ seconds (from the wegitor upstream).
- `src/reaper_mcp/utils/items.py` — int-index / `MediaItem*0x...` pointer resolver (from wegitor).
- `src/reaper_mcp/offline_support/` — vendored dschuler36 code: RPP parser, audio analyzer, FX finder, dataclasses.

## API conventions (from the three-way merge)

The bonfire and wegitor upstreams had ~12 overlapping tool names. The unified
version picks the **more featureful** implementation in each case while keeping
the union of unique tools. New tools should follow these conventions so the API
stays coherent:

- **Positions** — every tool that takes a position accepts EITHER `*_time: float` (seconds) OR `*_measure: str` (`"M:B,F"` format). Bonfire's plain-float interface still works; wegitor's musical positions are available everywhere.
- **Item identification** — every item tool accepts either an integer `track_pos_idx` or a string `direct_item_id` (REAPER's `"MediaItem*0x..."` pointer) via the dual-id resolver in `utils/items.py`.
- **FX parameters** — `set_fx_param` and `get_fx_param` accept either an integer index (fast) or a string name (readable). Canonical names: `add_fx`, `remove_fx`, `list_fx`, `toggle_fx`, `set_fx_param`, `get_fx_param`, `get_fx_param_list`.
- **Track color** — accepts either a `#RRGGBB` hex string or three R/G/B ints.
- **Time signature** — both `set_project_time_signature` (project-wide) and `set_time_signature(position_time=..., position_measure=...)` (positional) are exposed.
- **Return shape** — every tool returns a flat dict with `success: bool` and either result fields or an `error` string. (Offline tools return JSON strings, matching their dschuler36 origins.)

## LLM orientation: the `about_<group>` pattern

The MCP server is meant to be driven by an LLM client (Claude Desktop, Claude
Code, anything that speaks MCP). Some tool groups carry context that a per-tool
description can't fit but that the model needs before it picks an action —
concepts, file layout, what the group *can't* do, common multi-step workflows.

Pattern: each group that needs this provides an `about_<group>` tool that
returns a structured JSON primer. The LLM should call it **before** the first
real operation in that group; it's cheap and stable.

Today the only group rich enough to need this is **ReaPack**
(`reapack about-reapack`). The returned blob covers:

- What ReaPack is conceptually (a package manager for REAPER content, akin to brew/apt)
- File layout (`registry.db`, `reapack.ini`, `cache/` — and what each holds)
- The four key concepts (repository, package, file, sync) — not all are obvious from the tool names
- What the group **can** do (state inspection, sync, browse-window)
- What the group **cannot** do — programmatic install, package-catalogue search, and how to fall back
- Common multi-step workflows (e.g. update-installed-packages, install-something-new)
- Cross-references to related actions in the `system` group (the `_REAPACK_*` named commands)

If you add a future group whose tools need shared cross-cutting context
(state files, GUI-only fallbacks, multi-step workflows), add an
`about_<group>` tool with the same shape so callers have one place to read for
orientation.

Module-level docstrings on each `tools/*.py` file also surface in
`reaper-cli <group> --help` and are visible to FastMCP's `list_tools`
description, so they're a complementary lower-bandwidth channel for the same
kind of context.

## The universal escape hatch

`system run-reaper-action` accepts any integer command ID (1007 = Play,
40012 = Split items at edit cursor, …) or named extension command
(`_SWS_AWFADERTOOL`, …). Combined with `get-action-name` for reverse lookup,
this unlocks essentially every REAPER menu item even when there is no
dedicated tool. Discover IDs in REAPER via **Actions → Show action list**.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

96 tests covering the offline modules (RPP parser, FX cache parsers, audio
analyzer), the CLI introspection helpers, the pure utility resolvers
(including dB/linear conversion), and structural smoke (imports, no duplicate
tool names, `TOOL_MODULES` matches disk layout). Runs in <1 second; no REAPER
required.

Live tools that drive `python-reapy` are not exercised by the test suite —
they need an actual REAPER instance with the distant API enabled. The smoke
tests catch registration drift and import failures, which is the most common
refactoring bug class.

## Lint + type check

```bash
ruff check .   # lint (zero issues)
ty check       # static type check (zero diagnostics)
```

`ty` is configured via `[tool.ty.environment]` in `pyproject.toml` to pick up
the stub package under `typings/reapy/` — six lines that mark reapy's public
API as dynamic without disabling type checking for our own code. Real
null-safety issues still surface; the ~170 `RPR.<reaperFunc>` calls (which
reapy installs at import time) don't.

Where the two checkers disagree (notably the `cp.optionxform = str`
configparser idiom and the `wrapper.__signature__ = …` Typer trick), the code
uses `# ty: ignore[<rule>]` inline. ruff and ty don't share a suppression
syntax — ruff uses `# noqa:` and reads it; ty uses `# ty: ignore[…]` and
ignores ruff's. Use the syntax of whichever checker is being silenced.
