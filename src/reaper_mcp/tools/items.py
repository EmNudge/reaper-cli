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
    def set_item_mute(track_index: int, item: int | str, muted: bool) -> dict:
        """Mute or unmute a media item (per-item, separate from track mute)."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            RPR.SetMediaItemInfo_Value(it.id, "B_MUTE", 1.0 if muted else 0.0)
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "muted": bool(muted),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_item_volume(track_index: int, item: int | str, volume: float) -> dict:
        """Set an item's gain (linear scale; 1.0 = unity, 2.0 = +6 dB, 0.5 = -6 dB).

        Distinct from take volume — this is the item-level gain knob applied
        AFTER the take(s) play back.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            RPR.SetMediaItemInfo_Value(it.id, "D_VOL", float(volume))
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "volume": float(volume),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def split_item(
        track_index: int,
        item: int | str,
        position_time: float | None = None,
        position_measure: str | None = None,
    ) -> dict:
        """Split an item at a position. The right half becomes a new item.

        Returns the new (right-side) item's ``direct_item_id`` and its index on
        the track. Position must lie strictly inside the item's bounds.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            pos, pos_ms = resolve_start(position_time, position_measure, project)
            item_start = it.position
            item_end = item_start + it.length
            if pos <= item_start or pos >= item_end:
                return {
                    "success": False,
                    "error": (
                        f"Split position {pos} is outside item bounds [{item_start}, {item_end})"
                    ),
                }
            new_item_ptr = RPR.SplitMediaItem(it.id, pos)
            if not new_item_ptr:
                return {"success": False, "error": "SplitMediaItem returned NULL"}
            new_index = -1
            for i, ti in enumerate(track.items):
                if str(ti.id) == str(new_item_ptr):
                    new_index = i
                    break
            return {
                "success": True,
                "track_index": track_index,
                "original_item": str(item),
                "new_item_index": new_index,
                "new_direct_item_id": str(new_item_ptr),
                "split_position": {"time": pos, "measure": pos_ms},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_item_auto_fade(
        track_index: int,
        item: int | str,
        auto_fade_in_length: float | None = None,
        auto_fade_out_length: float | None = None,
    ) -> dict:
        """Set automatic crossfade lengths for an item (``D_FADEINLEN_AUTO`` / ``D_FADEOUTLEN_AUTO``).

        Auto-fades apply only when overlapping a neighbour; pass either or
        both values in seconds. Set to ``0.0`` to disable that side's auto-fade.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            if auto_fade_in_length is not None:
                RPR.SetMediaItemInfo_Value(it.id, "D_FADEINLEN_AUTO", float(auto_fade_in_length))
            if auto_fade_out_length is not None:
                RPR.SetMediaItemInfo_Value(it.id, "D_FADEOUTLEN_AUTO", float(auto_fade_out_length))
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "auto_fade_in_length": auto_fade_in_length,
                "auto_fade_out_length": auto_fade_out_length,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def select_items_in_range(
        track_index: int | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        start_measure: str | None = None,
        end_measure: str | None = None,
        exclusive: bool = True,
    ) -> dict:
        """Select every item overlapping a time range.

        ``track_index=None`` searches every track; otherwise restricts to that
        track. ``exclusive=True`` (default) deselects items outside the range
        before selecting.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            s, _ = resolve_start(start_time, start_measure, project)
            if end_time is not None:
                e = float(end_time)
            elif end_measure is not None:
                from reaper_mcp.utils.positions import position_to_time

                e = position_to_time(end_measure, project)
            else:
                return {"success": False, "error": "Provide end_time or end_measure"}
            if exclusive:
                project.select_all_items(False)
            selected = []
            track_range = (
                [track_index] if track_index is not None else list(range(project.n_tracks))
            )
            for ti in track_range:
                track = project.tracks[ti]
                for ii, it in enumerate(track.items):
                    if it.position + it.length >= s and it.position <= e:
                        RPR.SetMediaItemSelected(it.id, True)
                        selected.append(
                            {"track_index": ti, "item_index": ii, "direct_item_id": str(it.id)}
                        )
            return {"success": True, "count": len(selected), "selected": selected}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_item_notes(track_index: int, item: int | str) -> dict:
        """Return the per-item notes string (``P_NOTES``)."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            result = RPR.GetSetMediaItemInfo_String(it.id, "P_NOTES", "", False)
            if isinstance(result, tuple):
                strings = [s for s in result if isinstance(s, str)]
                notes = strings[-1] if strings else ""
            else:
                notes = str(result) if result else ""
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "notes": notes,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_item_notes(track_index: int, item: int | str, notes: str) -> dict:
        """Set the per-item notes string (``P_NOTES``)."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            ok = RPR.GetSetMediaItemInfo_String(it.id, "P_NOTES", str(notes), True)
            if not ok:
                return {"success": False, "error": "GetSetMediaItemInfo_String returned False"}
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "notes": notes,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_item_fade(
        track_index: int,
        item: int | str,
        fade_in_length: float | None = None,
        fade_out_length: float | None = None,
        fade_in_shape: int | None = None,
        fade_out_shape: int | None = None,
        fade_in_dir: float | None = None,
        fade_out_dir: float | None = None,
    ) -> dict:
        """Configure an item's fade in / fade out.

        ``fade_*_length`` is in seconds. ``fade_*_shape`` is an integer 0-6
        (0 = linear, 1 = fast start, 2 = fast end, 3 = fast start/end,
        4 = slow start/end, 5 = bezier, 6 = S-curve). ``fade_*_dir`` is the
        curve direction (-1.0 to 1.0; 0.0 = neutral). Pass ``None`` for any
        field to leave it unchanged.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            if fade_in_length is not None:
                RPR.SetMediaItemInfo_Value(it.id, "D_FADEINLEN", float(fade_in_length))
            if fade_out_length is not None:
                RPR.SetMediaItemInfo_Value(it.id, "D_FADEOUTLEN", float(fade_out_length))
            if fade_in_shape is not None:
                if not 0 <= int(fade_in_shape) <= 6:
                    return {"success": False, "error": "fade_in_shape must be 0-6"}
                RPR.SetMediaItemInfo_Value(it.id, "C_FADEINSHAPE", float(int(fade_in_shape)))
            if fade_out_shape is not None:
                if not 0 <= int(fade_out_shape) <= 6:
                    return {"success": False, "error": "fade_out_shape must be 0-6"}
                RPR.SetMediaItemInfo_Value(it.id, "C_FADEOUTSHAPE", float(int(fade_out_shape)))
            if fade_in_dir is not None:
                RPR.SetMediaItemInfo_Value(
                    it.id, "D_FADEINDIR", max(-1.0, min(1.0, float(fade_in_dir)))
                )
            if fade_out_dir is not None:
                RPR.SetMediaItemInfo_Value(
                    it.id, "D_FADEOUTDIR", max(-1.0, min(1.0, float(fade_out_dir)))
                )
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "fade_in_length": fade_in_length,
                "fade_out_length": fade_out_length,
                "fade_in_shape": fade_in_shape,
                "fade_out_shape": fade_out_shape,
                "fade_in_dir": fade_in_dir,
                "fade_out_dir": fade_out_dir,
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
    def select_item(track_index: int, item: int | str, exclusive: bool = False) -> dict:
        """Select a media item.

        ``exclusive=True`` deselects every other item in the project first —
        useful when you want exactly this item selected for an action.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            if exclusive:
                project.select_all_items(False)
            RPR.SetMediaItemSelected(it.id, True)
            return {
                "success": True,
                "track_index": track_index,
                "item": str(item),
                "exclusive": bool(exclusive),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def deselect_item(track_index: int, item: int | str) -> dict:
        """Deselect a media item."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            it = get_item_by_id_or_index(track, item)
            if it is None:
                return {"success": False, "error": "Item not found"}
            RPR.SetMediaItemSelected(it.id, False)
            return {"success": True, "track_index": track_index, "item": str(item)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def clear_item_selection() -> dict:
        """Deselect every media item in the project."""
        try:
            project = get_project()
            project.select_all_items(False)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def select_all_items() -> dict:
        """Select every media item in the project."""
        try:
            project = get_project()
            project.select_all_items(True)
            return {"success": True}
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
