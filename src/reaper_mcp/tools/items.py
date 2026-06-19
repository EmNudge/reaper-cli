"""Generic media-item tools — duplicate, set position/length, delete, query, selected, in range."""

import logging
import time
from typing import Any

from reaper_mcp.connection import get_project
from reaper_mcp.utils.items import (
    delete_item as _delete_item,
)
from reaper_mcp.utils.items import (
    get_item_by_id_or_index,
)
from reaper_mcp.utils.items import (
    get_item_properties as _get_item_properties,
)
from reaper_mcp.utils.positions import (
    resolve_length,
    resolve_start,
    time_to_measure,
)

logger = logging.getLogger("reaper_mcp.tools.items")


def register_tools(mcp):
    @mcp.tool()
    def get_item_properties(track_index: int, item: int | str) -> dict:
        """Return the properties of an item — position, length, name, is_audio, file_path."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            return {"success": True, "properties": _get_item_properties(it)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_item_position(
        track_index: int,
        item: int | str,
        position_time: float | None = None,
        position_measure: str | None = None,
    ) -> dict:
        """Set an item's position. Accept seconds OR ``M:B,F`` string."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            pos, pos_ms = resolve_start(position_time, position_measure, project)
            it.position = pos
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "position": {"time": pos, "measure": pos_ms},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_item_length(
        track_index: int,
        item: int | str,
        length_time: float | None = None,
        length_measure: str | None = None,
    ) -> dict:
        """Set an item's length from its current position. Accept seconds OR ``M:B,F``."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            length_s, end_ms = resolve_length(length_time, length_measure, it.position, project)
            it.length = length_s
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "length": length_s,
                "end_measure": end_ms,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def duplicate_item(
        track_index: int,
        item: int | str,
        new_time: float | None = None,
        new_measure: str | None = None,
    ) -> dict:
        """Duplicate an item via REAPER's ``Item: Duplicate items`` command.

        Defaults to placing the duplicate immediately after the original. Use
        ``new_time`` or ``new_measure`` to override.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            orig_pos, orig_len = it.position, it.length
            if new_time is not None or new_measure is not None:
                target_pos, target_ms = resolve_start(new_time, new_measure, project)
            else:
                target_pos = orig_pos + orig_len
                target_ms = time_to_measure(target_pos, project)

            project.select_all_items(False)
            RPR.SetMediaItemSelected(it.id, True)
            RPR.Main_OnCommand(41295, 0)  # Item: Duplicate items
            time.sleep(0.05)

            dup = None
            for ti in track.items:
                if ti.id == it.id:
                    continue
                if abs(ti.length - orig_len) < 0.001 and ti.position >= orig_pos:
                    dup = ti
                    break
            if dup is None:
                for ti in track.items:
                    if ti.id != it.id and abs(ti.length - orig_len) < 0.001:
                        dup = ti
                        break
            if dup is None:
                return {"success": False, "error": "Could not locate the duplicated item"}
            dup.position = target_pos
            new_index = -1
            for i, ti in enumerate(track.items):
                if ti.id == dup.id:
                    new_index = i
                    break
            return {
                "success": True,
                "track_index": track_index,
                "new_item_index": new_index,
                "new_direct_item_id": str(dup.id),
                "position": {"time": target_pos, "measure": target_ms},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_item(track_index: int, item: int | str) -> dict:
        """Delete a media item from a track."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            if _delete_item(it):
                return {"success": True, "track_index": track_index, "deleted": str(item)}
            return {"success": False, "error": "Delete failed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_items_in_time_range(
        track_index: int,
        start_time: float | None = None,
        end_time: float | None = None,
        start_measure: str | None = None,
        end_measure: str | None = None,
    ) -> dict:
        """List items on a track that overlap a time range.

        Each entry includes both ``track_pos_idx`` (int) and ``direct_item_id`` (string),
        either of which can be used in subsequent tool calls.
        """
        try:
            project = get_project()
            track = project.tracks[track_index]
            s, s_ms = resolve_start(start_time, start_measure, project)
            if end_time is not None:
                e = float(end_time)
                e_ms = time_to_measure(e, project)
            elif end_measure is not None:
                from reaper_mcp.utils.positions import position_to_time

                e = position_to_time(end_measure, project)
                e_ms = end_measure
            else:
                return {"success": False, "error": "Provide end_time or end_measure"}
            items = []
            for i, it in enumerate(track.items):
                if it.position + it.length >= s and it.position <= e:
                    items.append(
                        {
                            "track_pos_idx": i,
                            "direct_item_id": str(it.id),
                            "position": it.position,
                            "length": it.length,
                        }
                    )
            return {
                "success": True,
                "count": len(items),
                "items": items,
                "range": {
                    "start": {"time": s, "measure": s_ms},
                    "end": {"time": e, "measure": e_ms},
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_item_color(
        track_index: int,
        item: int | str,
        color: str | None = None,
        r: int | None = None,
        g: int | None = None,
        b: int | None = None,
    ) -> dict:
        """Set an item's color. Accept either a hex string (``#FF0000``) or RGB ints (0-255)."""
        from reapy import reascript_api as RPR

        try:
            if color is not None:
                s = color.lstrip("#")
                if len(s) != 6:
                    return {"success": False, "error": f"Invalid hex color: {color!r}"}
                rv, gv, bv = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
            elif r is not None and g is not None and b is not None:
                rv, gv, bv = int(r), int(g), int(b)
            else:
                return {
                    "success": False,
                    "error": "Provide either a hex 'color' or r/g/b integers",
                }
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            native = RPR.ColorToNative(rv, gv, bv) | 0x1000000
            RPR.SetMediaItemInfo_Value(it.id, "I_CUSTOMCOLOR", native)
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "color": f"#{rv:02X}{gv:02X}{bv:02X}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_item_locked(track_index: int, item: int | str, locked: bool) -> dict:
        """Lock or unlock an item — locked items can't be moved or trimmed."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            RPR.SetMediaItemInfo_Value(it.id, "C_LOCK", 1.0 if locked else 0.0)
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "locked": bool(locked),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_item_snap_offset(track_index: int, item: int | str, offset_seconds: float) -> dict:
        """Set an item's snap offset — the point within the item that snaps to grid.

        Useful when you want a downbeat in the middle of an audio clip (e.g. a
        sample with silence at the front) to snap to a bar line.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            RPR.SetMediaItemInfo_Value(it.id, "D_SNAPOFFSET", float(offset_seconds))
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "snap_offset_seconds": float(offset_seconds),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def group_items(items: list[dict[str, Any]]) -> dict:
        """Group multiple items together. Each entry: ``{"track_index": int, "item": int|str}``.

        Grouped items move/trim together. Use ``ungroup_items`` to dissolve.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            project.select_all_items(False)
            selected = 0
            for entry in items:
                track = project.tracks[int(entry["track_index"])]
                it = get_item_by_id_or_index(track, entry["item"])
                if it is None:
                    continue
                RPR.SetMediaItemSelected(it.id, True)
                selected += 1
            if selected < 2:
                return {
                    "success": False,
                    "error": "Need at least 2 valid items to group",
                }
            RPR.Main_OnCommand(40032, 0)  # Item: Group items
            return {"success": True, "grouped_count": selected}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def ungroup_items(items: list[dict[str, Any]]) -> dict:
        """Dissolve item groups containing any of the listed items."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            project.select_all_items(False)
            selected = 0
            for entry in items:
                track = project.tracks[int(entry["track_index"])]
                it = get_item_by_id_or_index(track, entry["item"])
                if it is None:
                    continue
                RPR.SetMediaItemSelected(it.id, True)
                selected += 1
            if selected == 0:
                return {"success": False, "error": "No valid items"}
            RPR.Main_OnCommand(40033, 0)  # Item: Remove items from group
            return {"success": True, "ungrouped_count": selected}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def glue_items(items: list[dict[str, Any]]) -> dict:
        """Glue (consolidate) multiple items into one rendered audio item.

        Useful for committing a multi-take edit or freezing a tail. Each entry:
        ``{"track_index": int, "item": int|str}``.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            project.select_all_items(False)
            selected = 0
            for entry in items:
                track = project.tracks[int(entry["track_index"])]
                it = get_item_by_id_or_index(track, entry["item"])
                if it is None:
                    continue
                RPR.SetMediaItemSelected(it.id, True)
                selected += 1
            if selected == 0:
                return {"success": False, "error": "No valid items"}
            RPR.Main_OnCommand(41588, 0)  # Item: Glue items
            return {"success": True, "glued_count": selected}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_selected_items() -> dict:
        """Return every selected media item in the project, across all tracks."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            out = []
            for ti, track in enumerate(project.tracks):
                for ii, item in enumerate(track.items):
                    if RPR.IsMediaItemSelected(item.id):
                        props = _get_item_properties(item)
                        props.update(
                            {
                                "track_index": ti,
                                "item_index": ii,
                                "direct_item_id": str(item.id),
                                "is_midi": bool(item.active_take and item.active_take.is_midi),
                            }
                        )
                        out.append(props)
            return {"success": True, "count": len(out), "items": out}
        except Exception as e:
            return {"success": False, "error": str(e)}
