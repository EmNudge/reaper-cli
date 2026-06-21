# reaper-cli

A single REAPER Model Context Protocol (MCP) server built by **tight-merging**
three independent upstream projects into one Python package, plus a sibling
CLI on the same code. 299 tools spanning offline `.RPP` analysis, live
`python-reapy` DAW control, full MIDI event editing, multi-take + take FX,
parameter automation, project snapshots + bulk mutations, track templates,
send routing, mastering, audio analysis, transport state, REAPER preferences,
project settings, the action-list escape hatch, and undo blocks.

See [AGENTS.md](AGENTS.md) for architecture, API conventions, the
`about_<group>` LLM-orientation pattern, and the lint/type-check workflow.

## Install

Python 3.10+ required (the unified package targets 3.10/3.11/3.12). REAPER
must be running and the **distant python-reapy API** must be enabled for any
live tool to work — see "Enable REAPER's distant API" below.

```bash
# create the venv and install the unified package (+ dev tools) in one step
uv sync --python 3.12

# or, if you manage the venv yourself:
uv venv --python 3.12 .venv && source .venv/bin/activate && uv pip install -e .
```

## Run

Two entry points share the same code.

### `reaper-mcp` — MCP stdio server for LLM clients

```bash
reaper-mcp                            # stdio transport — wire into Claude Desktop or Code
# or
python -m reaper_mcp
```

The server is named `reaper-mcp-unified` and registers 299 tools on a single
`FastMCP` instance.

### `reaper-cli` — direct command-line access (no LLM required)

The same 299 tools are exposed as Typer commands grouped by module. Explore
with `reaper-cli --help` and `reaper-cli <group> --help`.

```bash
reaper-cli offline find-reaper-projects ~/Music    # offline tools work without REAPER
reaper-cli tracks list-tracks                       # live tools need REAPER + distant API
reaper-cli tracks list-tracks | jq '.tracks[] | .name'
```

Every command returns the tool's result as JSON on stdout.

A few CLI conversion notes:

- `Union[int, str]` params (like item identifiers) are accepted as text; the underlying function does the right thing.
- `list[dict]` params (e.g. `add-midi-notes`) take a JSON string: `reaper-cli midi-notes add-midi-notes 0 0 '[{"pitch":60,"start_measure":"1:1,000","length_measure":"0:1,0"}]'`.
- `list[int]` params (e.g. `render-stems --track-indices`) use repeated `--flag` syntax.

## Enable REAPER's distant API

Live tools need REAPER's distant python-reapy API. Setup is fully external —
no need to launch ReaScripts from inside REAPER.

1. **Quit REAPER**. The configurator edits `reaper.ini` and `reaper-kb.ini`
   directly; REAPER overwrites them on shutdown, so any concurrent edit is
   lost.

2. Run the bundled one-shot:

   ```bash
   .venv/bin/python scripts/setup_reaper_connection.py
   ```

   This calls `reapy.config.configure_reaper()` under the hood, which edits
   `reaper.ini` + `reaper-kb.ini` to enable Python ReaScripts, point REAPER at
   the venv's Python interpreter (so it can find `reapy`), open a web
   interface on port 2307 for reapy connections, and register the
   `activate_reapy_server` ReaScript as a Custom action. The wrapper also
   defensively repairs a known reapy bug where `configure_reaper` glues
   appended `SCR …` entries onto the previous line in `reaper-kb.ini` when
   that file has no trailing newline.

3. **Start REAPER.**

4. **First-time only — manually run the bridge action.** `configure_reaper`
   only *registers* the bridge ReaScript; it does not mark it as a startup
   action. Inside REAPER:

   - Open the **Actions** menu → **Show action list…**
   - Search `activate_reapy`
   - Select **Custom: activate_reapy_server.py** (verify the **Path** column
     points to *this* repo's `.venv` — stale entries from previous reapy
     installs may also appear) → click **Run**
   - Right-click → **Run on REAPER startup** to persist across launches.
     Without this, you'll need to repeat the Run step every time REAPER
     starts.

5. Verify from the terminal:

   ```bash
   .venv/bin/reaper-cli audio get-playback-state
   ```

   You should see JSON like
   `{"success": true, "playing": false, "paused": false, "recording": false, "raw_flags": 0}`.

### Troubleshooting

- **`maximum recursion depth exceeded`, or the command hangs** on the first
  live tool call. REAPER's web interface is up on port 2307 (you can confirm
  with `lsof -nP -iTCP:2307`) but the bridge ReaScript hasn't been run inside
  REAPER. Do step 4 above.
- **`activate_reapy_server.py` doesn't appear in the action list** after
  setup. The `SCR` line in `reaper-kb.ini` is likely glued onto the previous
  line (reapy bug — see step 2). Quit REAPER, re-run the setup script (the
  defensive normalizer will split it), then restart REAPER.
- **Multiple `Custom: activate_reapy_server.py` entries** appear in the
  action list. Old reapy installs from prior projects leave their entries
  behind. Quit REAPER, manually delete the stale `SCR …` lines in
  `~/Library/Application Support/REAPER/reaper-kb.ini` (keep only the one
  whose path points at this repo's `.venv`), then restart.
- **`Cannot connect to REAPER`** (rather than a hang). REAPER isn't running,
  or its web interface isn't listening — re-check that step 2 finished
  without errors and that REAPER was actually relaunched after.

The older approach (`reapy.config.enable_dist_api()` from inside REAPER's
*Actions → Run ReaScript*) still works but is deprecated since reapy 0.8 and
will be removed in 1.0. Use `configure_reaper` instead.

## Tests

```bash
uv sync          # installs the dev dependency group
uv run pytest
```

96 tests covering offline modules, CLI helpers, pure utilities, and
structural smoke. Runs in <1 second; no REAPER required. See
[AGENTS.md](AGENTS.md) for coverage details and the lint / type-check setup.

## Status

Smoke-tested: imports cleanly under Python 3.12, all 299 tools register
without name collisions. The merged code calls `python-reapy` and the offline
analysis modules using the same patterns as the upstreams — it should be
functionally compatible with each upstream's expected behavior. Live tools
have not been driven through REAPER end-to-end here.

## Licensing

Released under MIT. Started as a merge of three MIT-licensed upstreams —
[dschuler36/reaper-mcp-server](https://github.com/dschuler36/reaper-mcp-server),
[bonfire-audio/reaper-mcp](https://github.com/bonfire-audio/reaper-mcp), and
[wegitor/reaper-reapy-mcp](https://github.com/wegitor/reaper-reapy-mcp) — though
the code has diverged substantially since. Their original `LICENSE` files are
preserved under `LICENSES/`; see `NOTICE.md` for attribution.
