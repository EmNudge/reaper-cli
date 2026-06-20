"""Take-level tools — multi-take items, take FX chain.

REAPER items can hold multiple takes (e.g. multiple recorded passes of a vocal).
The existing ``midi`` and ``audio`` tools only see the active take; these tools
expose every take and per-take FX.
"""

import contextlib
import logging
import os
import time

from reaper_mcp.connection import get_project
from reaper_mcp.utils.items import get_item_by_id_or_index

logger = logging.getLogger("reaper_mcp.tools.takes")


def _get_item(track_index: int, item: int | str):
    project = get_project()
    track = project.tracks[track_index]
    it = get_item_by_id_or_index(track, item)
    if it is None:
        raise ValueError(f"Item not found on track {track_index}")
    return project, track, it


def _unwrap_string(result) -> str:
    """Extract the string out of an RPR tuple return — used for *_GetName /
    *_GetParamName calls where reapy returns ``(retval, …, name_out, …)``."""
    if isinstance(result, tuple):
        names = [s for s in result if isinstance(s, str) and s]
        return names[-1] if names else ""
    return str(result)


def _resolve_take_fx_param_index(take_id, fx_index: int, param) -> int:
    """Resolve a take-FX param int OR name to its int index. -1 if unknown."""
    from reapy import reascript_api as RPR

    if isinstance(param, int):
        return param
    try:
        return int(param)
    except (TypeError, ValueError):
        pass
    n_params = int(RPR.TakeFX_GetNumParams(take_id, fx_index))
    wanted = str(param).lower()
    for pi in range(n_params):
        name = _unwrap_string(RPR.TakeFX_GetParamName(take_id, fx_index, pi, "", 256))
        if name.lower() == wanted:
            return pi
    return -1


def _take_info(take, index: int) -> dict:
    info = {
        "index": index,
        "name": getattr(take, "name", ""),
        "is_midi": getattr(take, "is_midi", False),
        "is_active": False,
        "pitch_semitones": getattr(take, "pitch", 0.0),
        "playback_rate": getattr(take, "playback_rate", 1.0),
    }
    with contextlib.suppress(Exception):
        info["is_active"] = take.is_active
    try:
        info["source_file"] = take.source.filename
    except Exception:
        info["source_file"] = ""
    return info


def register_tools(mcp):
    @mcp.tool()
    def list_takes(track_index: int, item: int | str) -> dict:
        """List every take on an item — index, name, MIDI/audio, active flag, pitch, rate."""
        try:
            _, _, it = _get_item(track_index, item)
            takes = []
            for i in range(it.n_takes):
                takes.append(_take_info(it.takes[i], i))
            return {"success": True, "count": len(takes), "takes": takes}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_active_take(track_index: int, item: int | str) -> dict:
        """Return information about the currently active take on an item."""
        try:
            _, _, it = _get_item(track_index, item)
            for i in range(it.n_takes):
                t = it.takes[i]
                try:
                    if t.is_active:
                        return {"success": True, "take": _take_info(t, i)}
                except Exception:
                    pass
            return {"success": False, "error": "No active take found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_active_take(track_index: int, item: int | str, take_index: int) -> dict:
        """Switch the active take on an item to ``take_index``."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            if take_index < 0 or take_index >= it.n_takes:
                return {
                    "success": False,
                    "error": f"take_index {take_index} out of range (item has {it.n_takes} takes)",
                }
            RPR.SetActiveTake(it.takes[take_index].id)
            return {"success": True, "active_take_index": int(take_index)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_take_from_file(track_index: int, item: int | str, file_path: str) -> dict:
        """Add a new take to an item, sourcing audio from ``file_path``.

        The added take becomes the active take. Useful for comping (loading a
        different recorded pass) without creating a new item.
        """
        from reapy import reascript_api as RPR

        try:
            if not os.path.exists(file_path):
                return {"success": False, "error": f"File not found: {file_path}"}
            project, track, it = _get_item(track_index, item)
            # Add a new empty take, then point its source at the file.
            new_take = it.add_take()
            if new_take is None:
                return {"success": False, "error": "Failed to add take"}
            source = RPR.PCM_Source_CreateFromFile(file_path)
            if source:
                RPR.SetMediaItemTake_Source(new_take.id, source)
            RPR.SetActiveTake(new_take.id)
            new_take.name = os.path.basename(file_path)
            # Refresh take count
            return {
                "success": True,
                "track_index": track_index,
                "new_take_index": it.n_takes - 1,
                "file_path": file_path,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_take(track_index: int, item: int | str, take_index: int) -> dict:
        """Delete a take from an item by index.

        If the deleted take was active, REAPER promotes the next take to active.
        """
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            if take_index < 0 or take_index >= it.n_takes:
                return {
                    "success": False,
                    "error": f"take_index {take_index} out of range (item has {it.n_takes} takes)",
                }
            target = it.takes[take_index]
            # Make target active, then call REAPER's "Take: Delete active take" action.
            RPR.SetActiveTake(target.id)
            # action 40129 = "Take: Delete active take from items"
            RPR.Main_OnCommand(40129, 0)
            return {"success": True, "deleted_take_index": int(take_index)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def crop_to_active_take(track_index: int, item: int | str) -> dict:
        """Delete all takes from an item except the active one (item-only action)."""
        from reapy import reascript_api as RPR

        try:
            project, _, it = _get_item(track_index, item)
            # Select only this item, then call "Item: Crop to active take in items"
            project.select_all_items(False)
            RPR.SetMediaItemSelected(it.id, True)
            time.sleep(0.02)
            RPR.Main_OnCommand(40131, 0)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_take_fx(
        track_index: int,
        item: int | str,
        take_index: int,
        fx_name: str,
    ) -> dict:
        """Add an FX plugin to a take's FX chain (independent of track FX)."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            fx_idx = RPR.TakeFX_AddByName(take.id, fx_name, 1)  # 1 = add if missing
            if fx_idx < 0:
                return {"success": False, "error": f"Plugin not found: {fx_name!r}"}
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "fx_index": int(fx_idx),
                "name": fx_name,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_take_fx(track_index: int, item: int | str, take_index: int) -> dict:
        """List every FX on a take's FX chain."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            n = RPR.TakeFX_GetCount(take.id)
            fxs = []
            for i in range(int(n)):
                name_result = RPR.TakeFX_GetFXName(take.id, i, "", 256)
                if isinstance(name_result, tuple):
                    names = [s for s in name_result if isinstance(s, str) and s]
                    name = names[-1] if names else ""
                else:
                    name = str(name_result)
                enabled = bool(RPR.TakeFX_GetEnabled(take.id, i))
                n_params = int(RPR.TakeFX_GetNumParams(take.id, i))
                fxs.append({"index": i, "name": name, "enabled": enabled, "n_params": n_params})
            return {"success": True, "take_index": int(take_index), "fx": fxs}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_take_fx_param(
        track_index: int,
        item: int | str,
        take_index: int,
        fx_index: int,
        param: int | str,
        value: float,
    ) -> dict:
        """Set a normalized parameter (0.0-1.0) on a take-FX plugin.

        ``param`` may be an integer index or a parameter name (case-insensitive).
        """
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            param_index = _resolve_take_fx_param_index(take.id, int(fx_index), param)
            if param_index < 0:
                return {"success": False, "error": f"Take-FX param not found: {param!r}"}
            RPR.TakeFX_SetParamNormalized(take.id, int(fx_index), int(param_index), float(value))
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "fx_index": int(fx_index),
                "param_index": int(param_index),
                "value": float(value),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_take_fx_param(
        track_index: int,
        item: int | str,
        take_index: int,
        fx_index: int,
        param: int | str,
    ) -> dict:
        """Read a normalized parameter (0.0-1.0) on a take-FX plugin.

        ``param`` may be an integer index or a parameter name (case-insensitive).
        """
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            param_index = _resolve_take_fx_param_index(take.id, int(fx_index), param)
            if param_index < 0:
                return {"success": False, "error": f"Take-FX param not found: {param!r}"}
            value = float(RPR.TakeFX_GetParamNormalized(take.id, int(fx_index), int(param_index)))
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "fx_index": int(fx_index),
                "param_index": int(param_index),
                "value": value,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_take_fx_param_list(
        track_index: int, item: int | str, take_index: int, fx_index: int
    ) -> dict:
        """List every parameter on a take-FX plugin (index, name, normalized value)."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            n_params = int(RPR.TakeFX_GetNumParams(take.id, int(fx_index)))
            params = []
            for pi in range(n_params):
                name = _unwrap_string(RPR.TakeFX_GetParamName(take.id, int(fx_index), pi, "", 256))
                value = float(RPR.TakeFX_GetParamNormalized(take.id, int(fx_index), pi))
                params.append({"index": pi, "name": name, "value": value})
            return {
                "success": True,
                "take_index": int(take_index),
                "fx_index": int(fx_index),
                "params": params,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def toggle_take_fx(
        track_index: int,
        item: int | str,
        take_index: int,
        fx_index: int,
        enabled: bool | None = None,
    ) -> dict:
        """Enable / disable / toggle a take-FX plugin. ``enabled=None`` flips state."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            current = bool(RPR.TakeFX_GetEnabled(take.id, int(fx_index)))
            new_state = (not current) if enabled is None else bool(enabled)
            RPR.TakeFX_SetEnabled(take.id, int(fx_index), new_state)
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "fx_index": int(fx_index),
                "enabled": new_state,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def load_take_fx_preset(
        track_index: int,
        item: int | str,
        take_index: int,
        fx_index: int,
        preset_name: str,
    ) -> dict:
        """Load a named preset on a take-FX plugin."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            ok = RPR.TakeFX_SetPreset(take.id, int(fx_index), str(preset_name))
            if not ok:
                return {
                    "success": False,
                    "error": f"Preset not found or could not be loaded: {preset_name!r}",
                    "fx_index": int(fx_index),
                }
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "fx_index": int(fx_index),
                "preset": preset_name,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_take_preserve_pitch(
        track_index: int, item: int | str, take_index: int, preserve: bool
    ) -> dict:
        """Toggle preserve-pitch-when-changing-rate (``B_PPITCH``) on a take.

        When ``True``, playback-rate changes don't pitch-shift the audio (uses
        REAPER's selected stretch algorithm). When ``False``, rate changes act
        like a vinyl varispeed.
        """
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            RPR.SetMediaItemTakeInfo_Value(take.id, "B_PPITCH", 1.0 if preserve else 0.0)
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "preserve_pitch": bool(preserve),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_take_channel_mode(
        track_index: int, item: int | str, take_index: int, mode: int
    ) -> dict:
        """Set the take's channel mode (``I_CHANMODE``).

        Common values: 0 = normal, 1 = reverse stereo, 2 = mono (L+R sum),
        3 = mono L, 4 = mono R. Higher values address specific stereo pairs
        (66/67/... = channels 3+4, 5+6, …) on multichannel sources.
        """
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            RPR.SetMediaItemTakeInfo_Value(take.id, "I_CHANMODE", float(int(mode)))
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "channel_mode": int(mode),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_take_start_offset(
        track_index: int, item: int | str, take_index: int, offset_seconds: float
    ) -> dict:
        """Set the take's source start offset in seconds (``D_STARTOFFS``).

        Shifts which portion of the source plays at the item's beginning —
        positive values skip into the source, negative values pre-roll.
        """
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            RPR.SetMediaItemTakeInfo_Value(take.id, "D_STARTOFFS", float(offset_seconds))
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "start_offset_seconds": float(offset_seconds),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_take_pitch_mode(track_index: int, item: int | str, take_index: int, mode: int) -> dict:
        """Set the take's pitch-shift algorithm (``I_PITCHMODE``).

        ``-1`` (REAPER default) uses the project-level pitch shift setting.
        Other values reference a 16-bit packed (mode << 16) | submode encoding
        for specific algorithms (élastique, Rubber Band, Rrreeeaaa, …). See
        REAPER's preferences → Audio → Playback for the exact mapping; pass
        the same integer REAPER stores in ``D_PITCHMODE`` for a take.
        """
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            RPR.SetMediaItemTakeInfo_Value(take.id, "I_PITCHMODE", float(int(mode)))
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "pitch_mode": int(mode),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def rename_take(track_index: int, item: int | str, take_index: int, name: str) -> dict:
        """Rename a take by index."""
        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            take.name = name
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "name": take.name,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_take_volume(track_index: int, item: int | str, take_index: int, volume: float) -> dict:
        """Set take volume as linear gain (``D_VOL``; 1.0 = unity, 2.0 = +6 dB)."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            RPR.SetMediaItemTakeInfo_Value(take.id, "D_VOL", float(volume))
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "volume": float(volume),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_take_pan(track_index: int, item: int | str, take_index: int, pan: float) -> dict:
        """Set take pan (``D_PAN``; -1.0 left, 0.0 center, 1.0 right)."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            RPR.SetMediaItemTakeInfo_Value(take.id, "D_PAN", float(max(-1.0, min(1.0, pan))))
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "pan": float(pan),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_take_marker(
        track_index: int,
        item: int | str,
        take_index: int,
        src_position_seconds: float,
        name: str = "",
        color: str | None = None,
    ) -> dict:
        """Add a take marker at a take-source position.

        ``src_position_seconds`` is measured from the take's source start
        (NOT project time). ``color`` is an optional ``#RRGGBB`` hex; pass
        ``None`` to leave uncolored.
        """
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            color_v = 0
            if color is not None:
                s = color.lstrip("#")
                if len(s) != 6:
                    return {"success": False, "error": f"Invalid hex color: {color!r}"}
                rv, gv, bv = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
                color_v = int(RPR.ColorToNative(rv, gv, bv)) | 0x1000000
            new_idx = int(
                RPR.SetTakeMarker(take.id, -1, str(name), float(src_position_seconds), color_v)
            )
            if new_idx < 0:
                return {"success": False, "error": "SetTakeMarker returned negative index"}
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "marker_index": new_idx,
                "src_position_seconds": float(src_position_seconds),
                "name": name,
                "color": color,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_take_markers(track_index: int, item: int | str, take_index: int) -> dict:
        """List every take marker on a take."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            count = int(RPR.GetNumTakeMarkers(take.id))
            markers = []
            for i in range(count):
                result = RPR.GetTakeMarker(take.id, i, 0.0, "", 512, 0)
                if not isinstance(result, tuple):
                    continue
                # Reapy returns various tuple shapes — extract by type.
                src_pos = next((v for v in result if isinstance(v, float)), 0.0)
                name = next((v for v in result if isinstance(v, str)), "")
                ints = [v for v in result if isinstance(v, int)]
                color_v = ints[-1] if ints else 0
                markers.append(
                    {
                        "index": i,
                        "src_position_seconds": float(src_pos),
                        "name": name,
                        "color_native": int(color_v),
                    }
                )
            return {"success": True, "count": len(markers), "markers": markers}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_take_marker(
        track_index: int, item: int | str, take_index: int, marker_index: int
    ) -> dict:
        """Delete a take marker by index."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            ok = RPR.DeleteTakeMarker(take.id, int(marker_index))
            if not ok:
                return {
                    "success": False,
                    "error": f"DeleteTakeMarker returned False (marker_index={marker_index})",
                }
            return {"success": True, "deleted_marker_index": int(marker_index)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_stretch_marker(
        track_index: int,
        item: int | str,
        take_index: int,
        position_seconds: float,
        src_position_seconds: float | None = None,
    ) -> dict:
        """Add a stretch marker on a take.

        ``position_seconds`` is the playback-time position (seconds from take
        start). ``src_position_seconds`` is the source-time anchor; pass
        ``None`` to let REAPER compute it (no stretch, just a pin).
        """
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            src = float(src_position_seconds) if src_position_seconds is not None else -1.0
            new_idx = int(RPR.SetTakeStretchMarker(take.id, -1, float(position_seconds), src))
            if new_idx < 0:
                return {"success": False, "error": "SetTakeStretchMarker returned negative index"}
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "marker_index": new_idx,
                "position_seconds": float(position_seconds),
                "src_position_seconds": (
                    float(src_position_seconds) if src_position_seconds is not None else None
                ),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_stretch_markers(track_index: int, item: int | str, take_index: int) -> dict:
        """List every stretch marker on a take, with slopes."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            count = int(RPR.GetTakeNumStretchMarkers(take.id))
            markers = []
            for i in range(count):
                result = RPR.GetTakeStretchMarker(take.id, i, 0.0, 0.0)
                if not isinstance(result, tuple) or len(result) < 3:
                    continue
                # Returns (ok-flag-int, pos, src_pos)
                idx_or_ok = result[0]
                if isinstance(idx_or_ok, int) and idx_or_ok < 0:
                    continue
                floats = [v for v in result if isinstance(v, float)]
                if len(floats) < 2:
                    continue
                pos, src_pos = floats[0], floats[1]
                slope = float(RPR.GetTakeStretchMarkerSlope(take.id, i))
                markers.append(
                    {
                        "index": i,
                        "position_seconds": float(pos),
                        "src_position_seconds": float(src_pos),
                        "slope": slope,
                    }
                )
            return {"success": True, "count": len(markers), "markers": markers}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_stretch_marker_slope(
        track_index: int, item: int | str, take_index: int, marker_index: int, slope: float
    ) -> dict:
        """Set the curve slope of a stretch marker.

        ``slope``: -1.0 (max negative curve) to 1.0 (max positive curve);
        0.0 is straight.
        """
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            slope_clamped = max(-1.0, min(1.0, float(slope)))
            ok = RPR.SetTakeStretchMarkerSlope(take.id, int(marker_index), slope_clamped)
            if not ok:
                return {
                    "success": False,
                    "error": (
                        f"SetTakeStretchMarkerSlope returned False (marker_index={marker_index})"
                    ),
                }
            return {
                "success": True,
                "marker_index": int(marker_index),
                "slope": slope_clamped,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_stretch_marker(
        track_index: int, item: int | str, take_index: int, marker_index: int
    ) -> dict:
        """Delete a stretch marker by index."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            ok = RPR.DeleteTakeStretchMarkers(take.id, int(marker_index), int(marker_index) + 1)
            if not ok:
                return {
                    "success": False,
                    "error": (
                        f"DeleteTakeStretchMarkers returned False (marker_index={marker_index})"
                    ),
                }
            return {"success": True, "deleted_marker_index": int(marker_index)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_take_playback_params(track_index: int, item: int | str, take_index: int) -> dict:
        """Return preserve-pitch, channel mode, start offset, pitch mode, pitch, rate."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "preserve_pitch": bool(RPR.GetMediaItemTakeInfo_Value(take.id, "B_PPITCH")),
                "channel_mode": int(RPR.GetMediaItemTakeInfo_Value(take.id, "I_CHANMODE")),
                "start_offset_seconds": float(
                    RPR.GetMediaItemTakeInfo_Value(take.id, "D_STARTOFFS")
                ),
                "pitch_mode": int(RPR.GetMediaItemTakeInfo_Value(take.id, "I_PITCHMODE")),
                "pitch_semitones": getattr(take, "pitch", 0.0),
                "playback_rate": getattr(take, "playback_rate", 1.0),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def remove_take_fx(track_index: int, item: int | str, take_index: int, fx_index: int) -> dict:
        """Remove an FX from a take's FX chain."""
        from reapy import reascript_api as RPR

        try:
            _, _, it = _get_item(track_index, item)
            take = it.takes[take_index]
            ok = RPR.TakeFX_Delete(take.id, int(fx_index))
            if not ok:
                return {
                    "success": False,
                    "error": f"TakeFX_Delete returned False (fx_index={fx_index} out of range?)",
                    "track_index": track_index,
                    "take_index": int(take_index),
                }
            return {
                "success": True,
                "track_index": track_index,
                "take_index": int(take_index),
                "removed_fx_index": int(fx_index),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
