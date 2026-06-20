"""Razor-edit tools — REAPER's modern primary editing paradigm.

A razor edit is a marked rectangle covering a time range plus a track-vertical
slice (which envelope lane or item lane it targets). REAPER stores razor areas
per-track as a string in ``P_RAZOREDITS`` — a whitespace-separated list of
``"start end env_guid"`` triples per area.

Once set, razor areas drive a family of "razor:" actions — cut, copy, paste,
delete, insert, render — that operate on the area rather than the selection.
"""

import logging

from reaper_mcp.connection import get_project
from reaper_mcp.utils.positions import position_to_time, resolve_start

logger = logging.getLogger("reaper_mcp.tools.razor_edits")


def _read_razor_areas(track_id) -> str:
    from reapy import reascript_api as RPR

    result = RPR.GetSetMediaTrackInfo_String(track_id, "P_RAZOREDITS", "", False)
    if isinstance(result, tuple):
        strings = [s for s in result if isinstance(s, str)]
        return strings[-1] if strings else ""
    return str(result) if result else ""


def _parse_razor_areas(raw: str) -> list[dict]:
    """REAPER's razor encoding: triples of ``start end env_guid``, space-separated.

    Empty ``env_guid`` (``""`` literal) means the area targets items rather
    than envelope automation.
    """
    if not raw.strip():
        return []
    parts = raw.split()
    areas = []
    i = 0
    while i + 2 < len(parts):
        try:
            start = float(parts[i])
            end = float(parts[i + 1])
            env_guid_raw = parts[i + 2]
            # REAPER wraps env GUIDs in quotes; "" denotes item area
            env_guid = env_guid_raw.strip('"')
            areas.append(
                {
                    "start": start,
                    "end": end,
                    "envelope_guid": env_guid if env_guid else None,
                    "is_item_area": not env_guid,
                }
            )
        except ValueError:
            pass
        i += 3
    return areas


def _format_razor_area(start: float, end: float, env_guid: str | None) -> str:
    """Encode one area as REAPER expects: ``start end "env_guid_or_empty"``."""
    guid = f'"{env_guid}"' if env_guid else '""'
    return f"{start} {end} {guid}"


def register_tools(mcp):
    @mcp.tool()
    def about_razor_edits() -> dict:
        """Orientation primer for the razor-edit system."""
        return {
            "success": True,
            "concept": (
                "A razor edit is a per-track rectangle marking a time range "
                "plus a target lane (the item lane, or one specific envelope). "
                "Subsequent razor-aware actions (cut/copy/paste/delete/insert) "
                "operate within those rectangles rather than the time- or item-"
                "selection. Multiple non-overlapping areas can coexist per track."
            ),
            "data_model": (
                "Areas live in the per-track P_RAZOREDITS string — "
                "whitespace-separated triples of (start_seconds, end_seconds, "
                "envelope_guid_or_empty)."
            ),
            "common_workflows": {
                "razor_cut": [
                    "add_razor_area(track, start, end)  # item lane",
                    "system run-reaper-action 42112  # Razor edit: Cut area",
                ],
                "razor_paste": [
                    "set_cursor_position(target_time)",
                    "system run-reaper-action 42398  # Razor edit: Paste",
                ],
                "render_just_razor": [
                    "system run-reaper-action 42437  # Render selected razor areas",
                ],
            },
            "useful_action_ids": {
                "42112": "Razor edit: Cut area",
                "42398": "Razor edit: Paste",
                "40699": "Razor edit: Copy area",
                "40058": "Razor edit: Delete area, leaving gap",
                "42406": "Razor edit: Clear all areas",
                "42437": "Render selected razor areas to new tracks",
            },
        }

    @mcp.tool()
    def list_razor_areas(track_index: int) -> dict:
        """Return every razor area defined on a track."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            raw = _read_razor_areas(track.id)
            areas = _parse_razor_areas(raw)
            return {
                "success": True,
                "track_index": track_index,
                "count": len(areas),
                "areas": areas,
                "raw_string": raw,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_razor_area(
        track_index: int,
        start_time: float | None = None,
        end_time: float | None = None,
        start_measure: str | None = None,
        end_measure: str | None = None,
        envelope_guid: str | None = None,
        replace_existing: bool = False,
    ) -> dict:
        """Add a razor edit area on a track.

        Position accepts seconds OR ``M:B,F``. ``envelope_guid`` targets a
        specific envelope (use ``list_envelopes`` and check `envelope.GUID`);
        omit for an item-lane area. ``replace_existing=True`` clears the
        track's other areas first.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            s, _ = resolve_start(start_time, start_measure, project)
            if end_time is not None:
                e = float(end_time)
            elif end_measure is not None:
                e = position_to_time(end_measure, project)
            else:
                return {"success": False, "error": "Provide end_time or end_measure"}
            if e <= s:
                return {"success": False, "error": "end must be > start"}

            current = "" if replace_existing else _read_razor_areas(track.id)
            new_area = _format_razor_area(s, e, envelope_guid)
            combined = (current + " " + new_area).strip() if current else new_area

            ok = RPR.GetSetMediaTrackInfo_String(track.id, "P_RAZOREDITS", combined, True)
            if not ok:
                return {"success": False, "error": "GetSetMediaTrackInfo_String returned False"}
            return {
                "success": True,
                "track_index": track_index,
                "start": s,
                "end": e,
                "envelope_guid": envelope_guid,
                "raw_string": combined,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def clear_razor_areas(track_index: int | None = None) -> dict:
        """Clear every razor area on a track, or on all tracks if ``track_index`` is None."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            cleared = []
            if track_index is None:
                for i in range(project.n_tracks):
                    track = project.tracks[i]
                    RPR.GetSetMediaTrackInfo_String(track.id, "P_RAZOREDITS", "", True)
                    cleared.append(i)
            else:
                track = project.tracks[track_index]
                RPR.GetSetMediaTrackInfo_String(track.id, "P_RAZOREDITS", "", True)
                cleared.append(track_index)
            return {"success": True, "cleared_tracks": cleared}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_all_razor_areas() -> dict:
        """List every razor area across every track in the project."""
        try:
            project = get_project()
            out = []
            for i in range(project.n_tracks):
                track = project.tracks[i]
                raw = _read_razor_areas(track.id)
                areas = _parse_razor_areas(raw)
                if areas:
                    out.append(
                        {
                            "track_index": i,
                            "track_name": track.name,
                            "areas": areas,
                        }
                    )
            return {"success": True, "track_count_with_areas": len(out), "tracks": out}
        except Exception as e:
            return {"success": False, "error": str(e)}
