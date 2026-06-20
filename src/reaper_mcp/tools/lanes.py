"""Fixed item lanes (FIPM) — REAPER's modern comping workflow.

A track in "free item positioning" (FIPM) mode lets items occupy any vertical
strip within the track, with each item's vertical position and height set
independently. This is the foundation of REAPER's "fixed lanes" comping mode
where multiple takes live on parallel lanes you can A/B between.

Track-level: ``B_FREEMODE`` enables FIPM. ``I_FREEMODE`` chooses the variant
(0 = off, 1 = free positioning, 2 = fixed lanes).

Item-level: ``F_FREEMODE_Y`` sets vertical position (0.0 top, 1.0 bottom),
``F_FREEMODE_H`` sets height (0.0–1.0 as a fraction of track height).
"""

import logging

from reaper_mcp.connection import get_project
from reaper_mcp.utils.items import get_item_by_id_or_index

logger = logging.getLogger("reaper_mcp.tools.lanes")


_MODE_NAMES = {0: "off", 1: "free_positioning", 2: "fixed_lanes"}
_MODE_VALUES = {v: k for k, v in _MODE_NAMES.items()}


def register_tools(mcp):
    @mcp.tool()
    def set_track_lane_mode(track_index: int, mode: str) -> dict:
        """Set a track's lane mode.

        ``mode``:
        - ``"off"`` — normal single-lane track.
        - ``"free_positioning"`` — items can be placed at any Y position.
        - ``"fixed_lanes"`` — parallel lanes for comping multiple takes.
        """
        from reapy import reascript_api as RPR

        if mode not in _MODE_VALUES:
            return {
                "success": False,
                "error": f"Unknown mode {mode!r}. Use: {sorted(_MODE_VALUES)}",
            }
        try:
            project = get_project()
            track = project.tracks[track_index]
            value = _MODE_VALUES[mode]
            RPR.SetMediaTrackInfo_Value(track.id, "I_FREEMODE", float(value))
            # B_FREEMODE is kept in sync — older REAPER versions read it.
            RPR.SetMediaTrackInfo_Value(track.id, "B_FREEMODE", 0.0 if value == 0 else 1.0)
            return {
                "success": True,
                "track_index": track_index,
                "mode": mode,
                "raw_value": value,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_track_lane_mode(track_index: int) -> dict:
        """Return a track's current lane mode."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            value = int(RPR.GetMediaTrackInfo_Value(track.id, "I_FREEMODE"))
            return {
                "success": True,
                "track_index": track_index,
                "mode": _MODE_NAMES.get(value, f"unknown_{value}"),
                "raw_value": value,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_item_lane_position(
        track_index: int,
        item: int | str,
        y: float | None = None,
        height: float | None = None,
    ) -> dict:
        """Set a single item's vertical position and/or height within a FIPM track.

        ``y`` (0.0 top, 1.0 bottom) and ``height`` (0.0–1.0 fraction of track
        height) are both normalized. Track must be in ``free_positioning`` or
        ``fixed_lanes`` mode for these values to take visual effect.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            if y is not None:
                RPR.SetMediaItemInfo_Value(it.id, "F_FREEMODE_Y", float(max(0.0, min(1.0, y))))
            if height is not None:
                RPR.SetMediaItemInfo_Value(it.id, "F_FREEMODE_H", float(max(0.0, min(1.0, height))))
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "y": y,
                "height": height,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_item_lane_position(track_index: int, item: int | str) -> dict:
        """Return a single item's vertical position + height within a FIPM track."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            y = float(RPR.GetMediaItemInfo_Value(it.id, "F_FREEMODE_Y"))
            h = float(RPR.GetMediaItemInfo_Value(it.id, "F_FREEMODE_H"))
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "y": y,
                "height": h,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
