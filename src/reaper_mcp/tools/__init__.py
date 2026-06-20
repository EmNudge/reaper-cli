"""Tool modules registered on every server frontend (MCP, CLI, …).

``TOOL_MODULES`` is the single source of truth. Both ``reaper_mcp.server`` and
``reaper_mcp.cli`` iterate it; adding a new tool module is a one-line edit
here.

Each entry is ``(module_name, help_text)``. ``module_name`` is imported as
``reaper_mcp.tools.<module_name>``; the module must expose
``register_tools(adapter)`` matching the FastMCP-style ``adapter.tool()``
decorator-factory protocol.
"""

from __future__ import annotations

TOOL_MODULES: list[tuple[str, str]] = [
    ("project", "Project tools — create/save/load, tempo, time signature"),
    (
        "tempo_map",
        "Tempo-map tools — multi-marker tempo + time-sig changes with curve shapes",
    ),
    ("track_groups", "Track grouping / VCA — 64-group flag system across tracks"),
    ("razor_edits", "Razor-edit areas — REAPER's modern primary edit paradigm"),
    ("lanes", "Fixed item lanes (FIPM) — modern comping workflow"),
    (
        "tracks",
        "Track tools — CRUD, mixing params, color, peak, freeze, record input/monitor/arm, bus",
    ),
    ("master", "Master track tools — FX, mastering, loudness, normalize"),
    ("fx", "FX plugin tools — add/remove/list, set/get parameters"),
    ("midi_notes", "MIDI notes — items, notes (single + batch), chord progressions, drum patterns"),
    ("midi_events", "MIDI events — CC, pitch bend, program change, channel pressure, sysex"),
    ("audio", "Audio file tools — import, transport, cursor, item edits"),
    ("items", "Generic media-item tools — duplicate, set position/length, delete, query"),
    ("sends", "Send routing — track-to-track, hardware, MIDI, send mode/phase"),
    ("envelopes", "Envelopes — FX param automation, read/write points"),
    ("markers", "Marker / region tools"),
    ("render", "Render tools — full project, time selection, stems"),
    ("analysis", "Live analysis — spectrum, dynamics, stereo, clipping, transients"),
    ("system", "System — actions, preferences, project settings, undo blocks"),
    ("takes", "Take ops — multi-take items, take FX"),
    ("snapshot", "Project snapshot + bulk setters"),
    ("templates", "Track templates — save / apply / list .RTrackTemplate"),
    ("project_templates", "Project templates — save / apply / list / set default .RPP templates"),
    ("fx_chain_templates", "FX chain templates — save / apply / list .RfxChain"),
    ("render_presets", "Render presets — save / apply / list / delete JSON-backed presets"),
    ("themes", "Themes — install / list / activate .ReaperTheme + .ReaperThemeZip files"),
    ("reapack", "ReaPack package manager — inspect installed packages, sync repos, browse"),
    ("offline", "Offline tools — RPP parsing, audio analysis, plugin cache (no REAPER required)"),
]


def register_all(adapter) -> None:
    """Call ``register_tools(adapter)`` on every module in ``TOOL_MODULES``."""
    import importlib

    for module_name, _ in TOOL_MODULES:
        module = importlib.import_module(f"reaper_mcp.tools.{module_name}")
        module.register_tools(adapter)
