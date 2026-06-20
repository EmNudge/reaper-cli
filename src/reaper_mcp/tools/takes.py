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
