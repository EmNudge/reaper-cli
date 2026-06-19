# reaper-mcp-unified

A single REAPER Model Context Protocol (MCP) server built by **tight-merging** three independent upstream projects into one Python package, plus a sibling CLI on the same code. **177 tools** spanning offline `.RPP` analysis, live `python-reapy` DAW control, full MIDI event editing, multi-take + take FX, parameter automation, project snapshots + bulk mutations, track templates, send routing, mastering, audio analysis, transport state, REAPER preferences, project settings, the action-list escape hatch, and undo blocks.

## Upstreams

| Upstream | Contribution |
|---|---|
| [dschuler36/reaper-mcp-server](https://github.com/dschuler36/reaper-mcp-server) | Offline `.RPP` parsing + audio analysis (LUFS, peak, spectral, stereo) — vendored into `src/reaper_mcp/offline_support/` |
| [bonfire-audio/reaper-mcp](https://github.com/bonfire-audio/reaper-mcp) | Live DAW control patterns via `python-reapy`, render/analysis loop, mastering helpers, modular server layout |
| [wegitor/reaper-reapy-mcp](https://github.com/wegitor/reaper-reapy-mcp) | `bar:beat,fraction` position format, dual integer/pointer item identification, region & marker tools |

All three are MIT-licensed. License texts and attribution live in `LICENSES/` and `NOTICE.md`.

## Install

Python 3.10+ required (the unified package targets 3.10/3.11/3.12). REAPER must be running and the **distant python-reapy API** must be enabled for any live tool to work — see "Enable REAPER's distant API" below.

```bash
# create a venv with Python 3.10+
uv venv --python 3.12 .venv          # or python3.12 -m venv .venv
source .venv/bin/activate

# install the unified package
pip install -e .
```

## Run

Two entry points share the same code:

### `reaper-mcp` — MCP stdio server for LLM clients

```bash
reaper-mcp                            # stdio transport — wire into Claude Desktop or Code
# or
python -m reaper_mcp
```

The server is named `reaper-mcp-unified` and registers 177 tools on a single `FastMCP` instance.

### `reaper-cli` — direct command-line access (no LLM required)

The same 177 tools are also exposed as Typer commands grouped by module:

```bash
reaper-cli --help                                       # top-level help
reaper-cli tracks --help                                # list track commands
reaper-cli tracks create-track --name Bass              # invoke a tool

# Offline tools work without REAPER running:
reaper-cli offline find-reaper-projects ~/Music
reaper-cli offline list-installed-fx --plugin-type AU
reaper-cli offline analyze-rpp-audio path/to/song.RPP

# Live tools need REAPER + distant API (see below):
reaper-cli tracks list-tracks
reaper-cli fx add-fx 0 ReaEQ
reaper-cli midi create-midi-item 0 --start-measure 1:1,000 --length-measure 2:1,000
reaper-cli analysis analyze-frequency-spectrum
```

Every command returns the tool's result as JSON on stdout. Pipe into `jq` for human-friendly output:

```bash
reaper-cli tracks list-tracks | jq '.tracks[] | .name'
```

A few notes on the CLI conversion:
- `Union[int, str]` params (like item identifiers) are accepted as text; the underlying function does the right thing.
- `list[dict]` params (e.g. `add-midi-notes`) take a JSON string: `reaper-cli midi add-midi-notes 0 0 '[{"pitch":60,"start_measure":"1:1,000","length_measure":"0:1,0"}]'`.
- `list[int]` params (e.g. `render-stems --track-indices`) use repeated `--flag` syntax.

## Architecture

```
src/reaper_mcp/
├── server.py               one FastMCP instance, calls register_tools() per module
├── cli.py                  Typer CLI — same tool functions, grouped by module
├── connection.py           lazy reapy.connect() — only triggered on first live tool call
├── config.py               persistent user config via platformdirs
├── utils/
│   ├── positions.py        bar:beat ↔ seconds (from wegitor)
│   └── items.py            dual int-index / "MediaItem*0x..." pointer resolver (from wegitor)
├── tools/
│   ├── project.py          create/save/load, tempo, time signature
│   ├── tracks.py           CRUD, volume/pan/mute/solo, color (hex or RGB), list/info
│   ├── master.py           master volume/pan/mute/solo, master FX, mastering presets, loudness, normalize
│   ├── fx.py               add/remove/list, set/get params by index OR name, toggle, presets
│   ├── midi_notes.py       item creation (dual position format), single + batch notes, chord progressions, drum patterns
│   ├── audio.py            import audio file, transport, cursor, pitch/rate, trim/fades
│   ├── items.py            duplicate, set position/length, delete, range query, selected items
│   ├── sends.py            track-to-track, hardware, MIDI sends; send mode/phase
│   ├── markers.py          markers + regions (dual position format)
│   ├── render.py           full project, time selection, stems
│   ├── analysis.py         live render-based: spectrum, dynamics, stereo, clipping, transients
│   ├── system.py           REAPER actions (universal escape hatch), preferences, project settings, undo blocks
│   ├── midi_events.py      CC, pitch bend, program change, channel pressure, sysex, CC curve generator
│   ├── takes.py            multi-take items, take FX chain
│   ├── envelopes.py        FX-param automation, read/write envelope points
│   ├── snapshot.py         get_project_snapshot + bulk parameter setters
│   ├── templates.py        save / apply / list .RTrackTemplate files
│   ├── project_templates.py     save / apply / list / set-default for .RPP project templates
│   ├── fx_chain_templates.py    save / apply / list .RfxChain files
│   ├── render_presets.py        JSON-backed named render configurations
│   ├── themes.py                install / list / activate .ReaperTheme + .ReaperThemeZip files
│   ├── reapack.py               ReaPack state inspection (SQLite registry + INI) + sync/browse shortcuts
│   └── offline.py          .RPP parsing + analysis + plugin cache (no REAPER required)
└── offline_support/        vendored dschuler36 code: rpp_parser, audio_analyzer, fx_finder, dataclasses
```

### How conflicts were resolved

Bonfire and wegitor had ~12 overlapping tool names. The unified version picks the **more featureful** implementation in each case while keeping the union of all unique tools:

- **Positions** — every tool that takes a position accepts EITHER `*_time: float` (seconds) OR `*_measure: str` (`"M:B,F"` format from wegitor). Bonfire's plain-float interface still works; wegitor's musical positions are now available everywhere.
- **Item identification** — every item tool accepts either an integer `track_pos_idx` or a string `direct_item_id` (REAPER's `"MediaItem*0x..."` pointer) via the wegitor dual-id resolver.
- **FX parameters** — `set_fx_param` and `get_fx_param` accept either an integer index (fast) or a string name (readable). Canonical names: `add_fx`, `remove_fx`, `list_fx`, `toggle_fx`, `set_fx_param`, `get_fx_param`, `get_fx_param_list`.
- **Track color** — accepts either a `#RRGGBB` hex string or three R/G/B ints.
- **Time signature** — both `set_project_time_signature` (project-wide) and `set_time_signature(position_time=..., position_measure=...)` (positional) are exposed.
- **Return shape** — every tool returns a flat dict with `success: bool` and either result fields or an `error` string. (Offline tools return JSON strings, matching their dschuler36 origins.)
- **Connection** — single lazy `reapy.connect()` from bonfire, triggered on first live tool call. Offline tools never trigger it.

## Enable REAPER's distant API

Live tools need REAPER's distant python-reapy API. Setup is fully external —
no need to launch ReaScripts from inside REAPER.

1. **Quit REAPER** (the configurator needs exactly one or zero running instances so it can locate the right `reaper.ini`).

2. Run the bundled one-shot:

   ```bash
   .venv/bin/python scripts/setup_reaper_connection.py
   ```

   This calls `reapy.config.configure_reaper()` under the hood, which edits
   `reaper.ini` + `reaper-kb.ini` to enable Python ReaScripts, point REAPER at
   the venv's Python interpreter (so it can find `reapy`), open a web
   interface on port 2307 for reapy connections, and register the
   `activate_reapy_server` ReaScript so REAPER starts the bridge on launch.

3. **Start REAPER** — the bridge auto-activates.

4. Verify from the terminal:

   ```bash
   .venv/bin/reaper-cli audio get-playback-state
   ```

   You should see JSON like
   `{"success": true, "playing": false, "paused": false, "recording": false, "raw_flags": 0}`.
   If you instead get a `"Cannot connect to REAPER"` error, the most common
   causes are: REAPER wasn't fully quit before step 2, or REAPER wasn't
   fully relaunched after.

The older approach (`reapy.config.enable_dist_api()` from inside REAPER's
*Actions → Run ReaScript*) still works but is deprecated since reapy 0.8 and
will be removed in 1.0. Use `configure_reaper` instead.

## Tool surface (177 tools)

- **Project (8)**: create, save, load, info, set/get tempo, set/get project time signature, positional time signature
- **Tracks (19)**: create, delete, rename, volume/pan/mute/solo, set/get color, count, list, info, peak meter, freeze/unfreeze, record input, record monitor, record arm, create bus
- **Master (10)**: get state, volume/pan/mute/solo, add FX, list FX, set FX param, mastering chain, limiter, loudness, normalize
- **FX (8)**: add, remove, set/get param (by index OR name), get param list, list, toggle, load preset
- **MIDI notes (9)**: create item (dual position), add note, add notes (batch), clear, get notes, find by pitch, get selected, chord progressions, drum patterns
- **MIDI events (11)**: CC (single + batch + curve generator), pitch bend, program change, channel pressure, sysex, get CCs, get sysex, delete CC, clear CCs
- **Takes (9)**: list, get/set active, add from file, delete, crop to active, take FX (add/list/set-param/remove)
- **Envelopes (6)**: list envelopes, add FX-param envelope, get/add/delete points, clear
- **Audio (15)**: import, record/stop/play, cursor (get + set), pitch, playback rate, trim/fades, playback state, playhead position, time selection (get/set/clear), loop (get/set)
- **Items (13)**: get properties, set position/length, duplicate, delete, range query, get selected, color, lock, snap offset, group/ungroup, glue
- **Sends (8)**: create, list, remove, set volume; hardware send, MIDI send (with channel mapping), set mode, set phase
- **Markers (6)**: create/delete/list regions, create/delete/list markers
- **Render (3)**: full project, time selection, stems
- **Live analysis (5)**: spectrum, clipping, dynamics, stereo field, transients
- **System (10)**: run REAPER action by ID (universal escape hatch), get action name, lookup named command without running it, search/enumerate all actions (including SWS) with filter, get/set preferences, get/set project settings, begin/end undo block
- **Snapshot + bulk (4)**: get_project_snapshot, set_track_params_bulk, set_fx_params_bulk, set_send_volumes_bulk
- **Templates (3)**: list, save, apply track templates
- **Project templates (4)**: list, save current as template, apply, set default startup template
- **FX chain templates (3)**: list, save, apply
- **Render presets (4)**: list, save current, apply, delete (JSON-backed in user config dir)
- **Themes (4)**: list installed, install from file (handles `.ReaperTheme` and `.ReaperThemeZip`), set active, get active
- **ReaPack (6)**: about-reapack (LLM orientation primer), list repositories, list installed packages, list installed files, sync repositories, open package browser. Reads ReaPack's SQLite `registry.db` and `reapack.ini` to expose state without screen-scraping the GUI.
- **Offline (4)**: find RPPs, parse RPP, analyze RPP audio, list installed FX

### The universal escape hatch

`system run-reaper-action` accepts any integer command ID (1007 = Play, 40012 = Split items at edit cursor, …) or named extension command (`_SWS_AWFADERTOOL`, …). Combined with `get-action-name` for reverse lookup, this unlocks essentially every REAPER menu item even when there is no dedicated tool. Discover IDs in REAPER via **Actions → Show action list**.

## LLM orientation

The server is meant to be driven by an LLM client (Claude Desktop, Claude Code, anything that speaks MCP). Some tool groups carry context that a per-tool `--help` page can't fit but that the model needs before it picks an action — concepts, file layout, what the group *can't* do, common multi-step workflows.

The pattern is: each group that needs this provides an `about_<group>` tool. Calling it returns a structured JSON primer. The LLM should call this **before** the first real operation in that group; it's cheap and stable.

Today the only group rich enough to need this is **ReaPack** (`reapack about-reapack`). The returned blob covers:

- What ReaPack is conceptually (a package manager for REAPER content, akin to brew/apt)
- File layout (`registry.db`, `reapack.ini`, `cache/` — and what each holds)
- The four key concepts (repository, package, file, sync) — not all are obvious from the tool names
- What the group **can** do (state inspection, sync, browse-window)
- What the group **cannot** do — programmatic install, package-catalogue search, and how to fall back when those are needed
- Common multi-step workflows (e.g. update-installed-packages, install-something-new)
- Cross-references to related actions in the `system` group (the `_REAPACK_*` named commands), so the LLM knows the lower-level escape hatches

This pattern generalizes: if you add a future group whose tools need shared cross-cutting context (state files, GUI-only fallbacks, multi-step workflows), add an `about_<group>` tool with the same shape so callers have one place to read for orientation.

Module-level docstrings on each `tools/*.py` file also surface in `reaper-cli <group> --help` and are visible to FastMCP's `list_tools` description, so they're a complementary lower-bandwidth channel for the same kind of context.

## Licensing

All three upstreams are MIT-licensed. Their original `LICENSE` files are preserved in each subdirectory and aggregated under `LICENSES/`. See `NOTICE.md` for attribution.

The unified `src/reaper_mcp/` package is released under MIT as well, with credit to all three upstreams.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

96 tests covering the offline modules (RPP parser, FX cache parsers, audio analyzer), the CLI introspection helpers, the pure utility resolvers (including dB/linear conversion), and structural smoke (imports, no duplicate tool names, `TOOL_MODULES` matches disk layout). Runs in <1 second; no REAPER required.

Live tools that drive `python-reapy` are not exercised by the test suite — they need an actual REAPER instance with the distant API enabled. The smoke tests catch registration drift and import failures, which is the most common refactoring bug class.

## Status

Smoke-tested: imports cleanly under Python 3.12, all 177 tools register without name collisions. The merged code calls `python-reapy` and the offline analysis modules using the same patterns as the upstreams — it should be functionally compatible with each upstream's expected behavior. Live tools have not been driven through REAPER end-to-end here.
