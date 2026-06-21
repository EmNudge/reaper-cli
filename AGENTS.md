# AGENTS.md

Notes for contributors and AI agents working on this repo. For install / usage,
see the [README](README.md).

## Driving REAPER from this repo (no install needed)

If the user asks you to *do* something to their REAPER — "add a track", "set the
tempo", "render the project", "list my tracks" — **don't install anything.** This
repo ships a ready-to-use virtualenv at `.venv/` with the package already
installed in editable mode. Run the CLI straight from it:

```bash
.venv/bin/reaper-cli <group> <command> [args]
```

Every command prints the tool's result as JSON on stdout (`{"success": true, ...}`
or `{"success": false, "error": "..."}`). No LLM client, MCP server, or install
step is required — the CLI calls the same tool functions the MCP server does.

### Worked example — "add a new track"

```bash
.venv/bin/reaper-cli tracks create-track --name "Vox" --track-type audio
```

`--track-type` accepts `audio` (default), `midi`, `instrument`, or `folder`.
A `{"success": true, ...}` reply means the track now exists in the running
REAPER project.

### How to find the right command

There are ~300 tools grouped by module. Discover them with `--help` — never guess
a command name:

```bash
.venv/bin/reaper-cli --help                 # list all groups (project, tracks, fx, …)
.venv/bin/reaper-cli tracks --help          # list commands in a group
.venv/bin/reaper-cli tracks create-track --help   # options for one command
```

Group cheat-sheet for common requests: `tracks` (CRUD, mixing, color, freeze),
`project` (create/save/load, tempo, time-sig), `fx` (add/remove/set params),
`midi-notes` / `midi-events` (note + CC editing), `sends` (routing), `render`
(bounce project/stems), `markers`, `system` (the action-list escape hatch, prefs,
undo blocks), `scripting` (run arbitrary Python *inside* live REAPER + live
config vars — the deepest escape hatch, see below), `restart` (apply
restart-only edits via a safe REAPER restart — see below), `offline` (RPP
parsing — works with no REAPER running).

### Prerequisite for *live* tools

Anything that touches the running DAW needs REAPER open with the **distant
python-reapy API** enabled (one-time setup in the [README](README.md) §"Enable
REAPER's distant API"). If a live command hangs or returns
`Cannot connect to REAPER` / `maximum recursion depth exceeded`, that setup
hasn't been done — point the user at the README rather than retrying. Tools under
the `offline` group never need REAPER and never trigger a connection.

### CLI argument conventions

- `Union[int, str]` params (e.g. item identifiers) are passed as plain text; the tool resolves them.
- `list[dict]` params (e.g. `midi-notes add-midi-notes`) take a JSON string: `'[{"pitch":60,"start_measure":"1:1,000","length_measure":"0:1,0"}]'`.
- `list[int]` params (e.g. `render render-stems --track-indices`) use repeated `--flag` syntax.
- Pipe JSON output through `jq` to extract fields: `.venv/bin/reaper-cli tracks list-tracks | jq '.tracks[].name'`.

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

## The deeper escape hatch — running code *inside* REAPER (`scripting`)

`run-reaper-action` can only fire actions that already exist. The `scripting`
group goes one level deeper: it executes **new Python logic on REAPER's main
thread** via the reapy bridge, with the full ReaScript API (`RPR` / `reaper` /
`reapy`) pre-bound. Anything a hand-written Python ReaScript could do, the CLI
can now do live — no need to write, install, and run a `.lua`/`.py` script by
hand.

```bash
# Evaluate one expression
.venv/bin/reaper-cli scripting eval-python "RPR.CountTracks(0)"

# Run statements; assign what you want back to `result`
.venv/bin/reaper-cli scripting run-python \
  'result = [RPR.GetTrackName(RPR.GetTrack(0,i),"",512)[2] for i in range(RPR.CountTracks(0))]'
```

**This is the answer to "I can only change that by quitting REAPER, editing
`reaper.ini`, and relaunching."** `scripting set-config-var <name> <value>`
writes REAPER's *live* config variables (the in-memory backing of `reaper.ini`)
via SWS `SNM_*ConfigVar` and they apply immediately:

```bash
.venv/bin/reaper-cli scripting get-config-var defsplitxfadelen
.venv/bin/reaper-cli scripting set-config-var defsplitxfadelen 0.01
```

Call `scripting about-scripting` first for the full model. Key facts:

- **It runs on REAPER's UI thread** — keep snippets short and synchronous; do
  not start `defer` loops here (they won't yield as expected).
- **Exceptions are returned, not raised** — a bad snippet yields
  `{"success": false, "error": "<traceback>"}` rather than crashing REAPER. A
  segfaulting raw API call can still take REAPER down, same as any ReaScript.
- **Results must be JSON-safe** — non-serializable objects come back as their
  `repr()`.
- **Config-var tools need the SWS extension**; genuinely restart-only settings
  (audio device, plugin rescan) are not config vars and still need a restart.
- **How it works:** the reapy bridge decodes `{module_name, name}` into an
  `import` + call *inside REAPER*, so the helper lives in
  `src/reaper_mcp/inreaper.py` (must stay importable inside REAPER — top-level
  imports are stdlib-only; reapy is imported lazily). `connection.call_in_reaper`
  is the low-level dispatch other tools build on.
  - **Editable-install gotcha:** `reaper_mcp` is installed editable, so it is
    *not* on REAPER's embedded `sys.path` (the `.pth` only runs during normal
    site init, which REAPER skips). `connection._ensure_remote_importable`
    fixes this once per process by `builtins.exec`-ing a bootstrap that injects
    `src/` onto REAPER's path **and** clears cached `reaper_mcp` modules — the
    latter matters because REAPER persists across CLI calls and would otherwise
    keep running a stale `inreaper.py` until you restart it. Localhost only.
  - **SWS functions:** REAPER's shipped `reaper_python.py` has no wrappers for
    SWS/extension functions even when SWS is installed, so reapy can't see them.
    `inreaper.bind_api` builds a ctypes wrapper from the raw pointer in
    `reaper_python._ft` — the general way to reach any extension API (config
    vars use this for `SNM_*ConfigVar`).
  - For editing project files with REAPER **closed**, use the `offline` group.

## What's live-editable vs restart-only (don't re-derive this)

The in-process injection closed a *reachability* gap — anything ReaScript or
ctypes can touch, the `scripting` group can now touch live. It did **not** add
*capabilities REAPER itself lacks*. Some state is loaded once at startup and has
no reload hook anywhere in REAPER's API, so it stays restart-only no matter how
deep the injection goes. Know which side a setting is on before promising "live":

- **Live-editable** — settings backed by a live config var (`SNM_*ConfigVar`,
  i.e. most of `reaper.ini`) or a live API. Use `scripting set-config-var` /
  `run-python`. Applies immediately.
- **Restart-only** — startup-loaded layout/registry files with no reload API:
  - **Toolbars / menus** (`reaper-menu.ini`)
  - **Keymap / action list** (`reaper-kb.ini`)
  - Audio device, plugin re-scan (not config vars)

  Verified 2026-06 against REAPER 7.73: the full native function table (2166
  entries) and the action list contain **no** toolbar/menu mutation or
  config-reload call. `RefreshToolbar`/`RefreshToolbar2` only re-poll toggle
  state and redraw; "Toolbars: Customize…" (action 40905) is a GUI dialog that
  reads *in-memory* state, not the file. So editing these files takes effect
  only on next launch. Don't waste a session re-probing for a live path — there
  isn't one short of GUI automation (Win32 `BR_Win32_*` on Windows; macOS AX API
  otherwise — both fragile) or a native C++ extension.

**Toolbar/menu edit recipe** (since there's no live API and no dedicated tool
beyond `system add-toolbar-item`, which refuses while REAPER runs):

- Section `[Main toolbar]` (or `[Floating toolbar N]`, `[MIDI piano roll
  toolbar]`, …) in `reaper-menu.ini`. Items are `item_N=<cmdID|_namedcmd>
  <label>`; an icon is a **separate** line `icon_N=<basename.png>` with the
  *same* index N. `item_N=-1` is a separator.
- Icons resolve by basename from `Data/toolbar_icons/` (user resource dir first,
  then the bundle's `InstallFiles/Data/toolbar_icons/`, which also holds `150/`
  and `200/` HiDPI variants). Browse stock names there — they are descriptive
  (e.g. `toolbar_preroll_clock_record.png`).
- **`reaper-menu.ini` is only rewritten when toolbars/menus are edited in the
  GUI — not on normal exit** (confirmed: the file's mtime survives launch/quit
  cycles). So a live file edit persists to next launch, *provided the user does
  not open Customize Toolbars and save before restarting* (that would flush
  stale in-memory state over the edit). Back the file up before editing.

## Applying restart-only edits safely (`restart`)

`restart restart-reaper` automates the one path that restart-only edits
(toolbars, keymap) actually need — a REAPER restart — **without losing work or
committing anything unintended**. It is a CLI-side orchestrator (in
`tools/restart.py`), not an in-REAPER tool, because it has to keep running while
REAPER quits and relaunches (the bridge drops in between; `connection.reconnect`
re-establishes it). Validated end-to-end against REAPER 7.73.

Mechanism ("approach C", all primitives validated live):

1. Pre-flight via the bridge (`inreaper.get_session_state`). Aborts if more than
   one tab is open (v1) or if the active project is **untitled + dirty** (asks
   the user to Save-As first — an untitled project can't be restored as untitled
   across a restart; `GetSetProjectInfo_String("PROJECT_NAME")` is a no-op).
2. Snapshot the protected config files (`reaper-menu.ini`, `reaper-kb.ini`,
   `reaper.ini` by default) to `.bak`s — their *pre-quit on-disk* state is the
   declared edit to preserve.
3. For a dirty (titled) project: back up the on-disk baseline, then real-save
   the in-memory edits to the project file (`Main_SaveProject(0, false)` — this
   clears dirty so the quit won't prompt; note `Main_SaveProjectEx(p, path, 0)`
   is a *non-destructive copy* that does NOT clear dirty, used only for stashing).
4. Quit (the bridge drop is expected/caught) → wait for exit.
5. Restore the config snapshots (reverting REAPER's exit-flush of incidental
   changes — including live `set-config-var` edits) → relaunch with the project
   → reconnect.
6. Restore the baseline over the on-disk project file and `MarkProjectDirty`.
   Net: memory = edits, disk = baseline, marked unsaved.

Prerequisite: the reapy bridge must auto-start so the orchestrator can reconnect
after relaunch. That's a `Scripts/__startup.lua` in the REAPER resource dir that
runs the registered `activate_reapy_server` action by its named command — a
standing change (the server listens every session). It is **not** in this repo;
it lives in the user's REAPER config and was added with consent. Without it,
reconnect fails and the tool can't finish.

Safety/recovery: backups (`*.reaper-cli-restart.bak`, `*.reaper-cli-baseline.bak`)
and a manifest are written in the resource dir before quitting and removed on
success; restoring each `.bak` over its original recovers a interrupted run. Use
`--dry-run` to preview the plan. macOS only so far (quit/relaunch are
platform-specific); other platforms return a clear error. Multi-tab is a
documented fast-follow.

## Tests

```bash
uv sync          # installs the dev dependency group
uv run pytest
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
