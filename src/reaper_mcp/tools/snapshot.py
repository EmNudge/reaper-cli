"""Whole-project snapshot + bulk mutations.

``get_project_snapshot`` returns the entire state — project info, every track,
every FX, every item, markers, regions, transport state — in one call. This is
the single biggest LLM-efficiency win: one round-trip instead of 20+.

Bulk setters apply many writes in one call, with all changes wrapped in a
single REAPER undo block so the user sees one Cmd-Z step instead of dozens.
"""

import logging
from typing import Any

from reaper_mcp.connection import get_project
from reaper_mcp.utils.positions import format_time_signature
from reaper_mcp.utils.track_props import (
    get_mute,
    get_pan,
    get_solo,
    get_volume_db,
    set_mute,
    set_pan,
    set_solo,
    set_volume_db,
)

logger = logging.getLogger("reaper_mcp.tools.snapshot")


def register_tools(mcp):
    @mcp.tool()
    def about_snapshot() -> dict:
        """Orientation primer for the snapshot tool group — when to use it.

        Covers: the one-round-trip read pattern, the bulk write pattern with
        single undo grouping, the partial-success return shape, and when to
        prefer this group over per-tool calls in tracks/items/markers.
        """
        return {
            "success": True,
            "when_to_use": (
                "When you need to see / modify many things across the project "
                "at once. One snapshot call avoids N round-trips to "
                "list_tracks + list_items + list_markers + …; one bulk setter "
                "applies many writes inside a single REAPER undo block so the "
                "user sees ONE Cmd-Z step."
            ),
            "read_pattern": (
                "get_project_snapshot returns project info + every track + "
                "every FX (optionally with params) + every item + markers + "
                "regions in one dict. Use include_fx_params=True only when you "
                "actually need parameter values — it's the slow part."
            ),
            "write_pattern": (
                "set_*_bulk tools (set_track_params_bulk, set_fx_params_bulk, "
                "set_send_volumes_bulk, …) take a list of (target, value) "
                "dicts. Each tool wraps the whole batch in begin_undo_block / "
                "end_undo_block — the user sees one undo step regardless of "
                "how many items were modified."
            ),
            "partial_success_shape": (
                "Bulk tools return {success: bool, partial: bool, "
                "applied/added: int, failed: int, ...lists}. success is True "
                "only if every entry succeeded; partial=True flags some-worked-"
                "some-failed. Per-item errors are in failed_* lists. There is "
                "no top-level 'error' field on partial success — read 'partial' "
                "to detect mixed outcomes."
            ),
            "related_groups": {
                "tracks": "Per-track setters — use these for single-track edits.",
                "items": "Per-item edits — bulk_set_item_positions is in this group instead.",
                "system": "begin_undo_block / end_undo_block — manual undo grouping for cross-group sequences.",
            },
        }

    @mcp.tool()
    def get_project_snapshot(
        include_fx_params: bool = False,
        include_items: bool = True,
        include_markers: bool = True,
    ) -> dict:
        """Return the full project state in one call.

        ``include_fx_params``: include each FX's parameter list (slow if many
        plugins — off by default). ``include_items``: include the items on each
        track. ``include_markers``: include markers + regions.

        For very large projects, prefer ``include_fx_params=False`` and call
        ``get_fx_param_list`` per FX as needed.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            project_info = {
                "name": project.name,
                "path": project.path,
                "tempo": project.bpm,
                "time_signature": format_time_signature(project),
                "length": project.length,
                "track_count": project.n_tracks,
            }

            playback = {}
            try:
                state = int(RPR.GetPlayState())
                playback = {
                    "playing": bool(state & 1),
                    "paused": bool(state & 2),
                    "recording": bool(state & 4),
                    "play_position": project.play_position,
                    "cursor_position": project.cursor_position,
                }
                ts = project.time_selection
                playback["time_selection"] = {
                    "start": ts.start,
                    "end": ts.end,
                    "active": ts.end > ts.start,
                }
                playback["loop_enabled"] = bool(RPR.GetSetRepeat(-1))
            except Exception:
                pass

            tracks = []
            for i in range(project.n_tracks):
                t = project.tracks[i]
                fx_list = []
                for j in range(t.n_fxs):
                    fx = t.fxs[j]
                    fx_entry: dict[str, Any] = {
                        "index": j,
                        "name": fx.name,
                        "enabled": fx.is_enabled,
                        "n_params": fx.n_params,
                    }
                    if include_fx_params:
                        params = []
                        for p in range(fx.n_params):
                            param = fx.params[p]
                            params.append(
                                {
                                    "index": p,
                                    "name": param.name,
                                    "normalized_value": param.normalized_value,
                                    "formatted_value": getattr(param, "formatted_value", None),
                                }
                            )
                        fx_entry["parameters"] = params
                    fx_list.append(fx_entry)

                track_entry: dict[str, Any] = {
                    "index": i,
                    "name": t.name,
                    "volume_db": get_volume_db(t),
                    "pan": get_pan(t),
                    "muted": get_mute(t),
                    "soloed": get_solo(t),
                    "fx_count": t.n_fxs,
                    "item_count": t.n_items,
                    "fx": fx_list,
                }
                if include_items:
                    items = []
                    for k in range(t.n_items):
                        it = t.items[k]
                        items.append(
                            {
                                "index": k,
                                "direct_item_id": str(it.id),
                                "position": it.position,
                                "length": it.length,
                                "name": getattr(it, "name", ""),
                                "is_midi": bool(it.active_take and it.active_take.is_midi),
                            }
                        )
                    track_entry["items"] = items
                tracks.append(track_entry)

            markers, regions = [], []
            if include_markers:
                try:
                    for i in range(project.n_markers):
                        m = project.markers[i]
                        markers.append(
                            {
                                "index": i,
                                "name": m.name,
                                "position": m.position,
                            }
                        )
                except Exception:
                    pass
                try:
                    for i in range(project.n_regions):
                        r = project.regions[i]
                        regions.append(
                            {
                                "index": i,
                                "name": r.name,
                                "start": r.start,
                                "end": r.end,
                            }
                        )
                except Exception:
                    pass

            return {
                "success": True,
                "project": project_info,
                "playback": playback,
                "tracks": tracks,
                "markers": markers,
                "regions": regions,
            }
        except Exception as e:
            logger.error(f"get_project_snapshot failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_track_params_bulk(
        updates: list[dict[str, Any]],
        undo_description: str = "Bulk track parameter update",
    ) -> dict:
        """Apply many track parameter changes in one round-trip, in a single undo block.

        Each entry in ``updates`` is a dict with ``track_index`` and any of:
        ``volume_db`` (float), ``pan`` (float -1..1), ``muted`` (bool),
        ``soloed`` (bool), ``name`` (str).

        Example: ``[{"track_index": 0, "volume_db": -6}, {"track_index": 1, "muted": true}]``.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            RPR.Undo_BeginBlock2(project.id)
            applied, errors = [], []
            for i, u in enumerate(updates):
                try:
                    track = project.tracks[int(u["track_index"])]
                    if "volume_db" in u:
                        set_volume_db(track, float(u["volume_db"]))
                    if "pan" in u:
                        set_pan(track, float(u["pan"]))
                    if "muted" in u:
                        set_mute(track, bool(u["muted"]))
                    if "soloed" in u:
                        set_solo(track, bool(u["soloed"]))
                    if "name" in u:
                        track.name = str(u["name"])
                    applied.append({"index": i, "track_index": int(u["track_index"])})
                except Exception as e:
                    errors.append({"index": i, "update": u, "error": str(e)})
            RPR.Undo_EndBlock2(project.id, undo_description, -1)
            return {
                "success": not errors,
                "partial": bool(applied) and bool(errors),
                "applied_count": len(applied),
                "failed_count": len(errors),
                "applied": applied,
                "errors": errors,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_fx_params_bulk(
        updates: list[dict[str, Any]],
        undo_description: str = "Bulk FX parameter update",
    ) -> dict:
        """Apply many FX parameter writes in one undo block.

        Each ``updates`` entry: ``track_index``, ``fx_index``, ``param``
        (int index OR string name), ``value`` (normalized 0.0-1.0).
        """
        from reapy import reascript_api as RPR

        from reaper_mcp.utils.fx_params import resolve_fx_param_index

        try:
            project = get_project()
            RPR.Undo_BeginBlock2(project.id)
            applied, errors = [], []
            for i, u in enumerate(updates):
                try:
                    track = project.tracks[int(u["track_index"])]
                    fx = track.fxs[int(u["fx_index"])]
                    pi = resolve_fx_param_index(fx, u["param"])
                    if pi < 0:
                        raise ValueError(f"Param not found: {u['param']!r}")
                    fx.params[pi].normalized_value = float(u["value"])
                    applied.append({"index": i, **u, "resolved_param_index": pi})
                except Exception as e:
                    errors.append({"index": i, "update": u, "error": str(e)})
            RPR.Undo_EndBlock2(project.id, undo_description, -1)
            return {
                "success": not errors,
                "partial": bool(applied) and bool(errors),
                "applied_count": len(applied),
                "failed_count": len(errors),
                "applied": applied,
                "errors": errors,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_send_volumes_bulk(
        updates: list[dict[str, Any]],
        undo_description: str = "Bulk send volume update",
    ) -> dict:
        """Apply many send-volume writes in one undo block.

        Each ``updates`` entry: ``source_track_index``, ``send_index``,
        ``volume_db`` (float, e.g. ``-6.0``).
        """
        from reapy import reascript_api as RPR

        def db_to_linear(db: float) -> float:
            return 0.0 if db <= -150 else 10 ** (db / 20.0)

        try:
            project = get_project()
            RPR.Undo_BeginBlock2(project.id)
            applied, errors = [], []
            for i, u in enumerate(updates):
                try:
                    track = project.tracks[int(u["source_track_index"])]
                    RPR.SetTrackSendInfo_Value(
                        track.id,
                        0,
                        int(u["send_index"]),
                        "D_VOL",
                        db_to_linear(float(u["volume_db"])),
                    )
                    applied.append({"index": i, **u})
                except Exception as e:
                    errors.append({"index": i, "update": u, "error": str(e)})
            RPR.Undo_EndBlock2(project.id, undo_description, -1)
            return {
                "success": not errors,
                "partial": bool(applied) and bool(errors),
                "applied_count": len(applied),
                "failed_count": len(errors),
                "applied": applied,
                "errors": errors,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
