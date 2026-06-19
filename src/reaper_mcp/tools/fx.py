"""FX (plugin) tools — add/remove/list, set/get parameters (by index OR name), toggle, presets.

Canonical names: ``add_fx``, ``remove_fx``, ``list_fx``, ``set_fx_param``, ``get_fx_param``,
``get_fx_param_list``, ``toggle_fx``, ``load_fx_preset``. Tools accept either an integer
parameter index (fast) OR a string parameter name (more readable but slower).
"""

import logging
import time

from reaper_mcp.connection import get_project
from reaper_mcp.utils.fx_params import resolve_fx_param_index

logger = logging.getLogger("reaper_mcp.tools.fx")


def register_tools(mcp):
    @mcp.tool()
    def add_fx(track_index: int, fx_name: str) -> dict:
        """Add an FX plugin to a track. Works for instruments (VSTi) and effects.

        Use the exact plugin name as shown in REAPER's FX browser. If the original name fails,
        a stripped variant (e.g. ``"ReaEQ"`` from ``"ReaEQ (Cockos)"``) is tried.
        """
        try:
            project = get_project()
            track = project.tracks[track_index]
            try:
                fx_index = track.add_fx(fx_name)
            except Exception:
                fx_index = -1
            if fx_index is None or fx_index < 0:
                base = fx_name.split(" [")[0] if " [" in fx_name else fx_name
                try:
                    fx_index = track.add_fx(base)
                except Exception:
                    fx_index = -1
            if fx_index is None or fx_index < 0:
                return {"success": False, "error": f"Plugin not found: {fx_name!r}"}
            fx = track.fxs[fx_index]
            return {
                "success": True,
                "track_index": track_index,
                "fx_index": fx_index,
                "name": fx.name,
                "n_params": fx.n_params,
            }
        except Exception as e:
            logger.error(f"add_fx failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def remove_fx(track_index: int, fx_index: int) -> dict:
        """Remove an FX from a track by index."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            name = track.fxs[fx_index].name
            RPR.TrackFX_Delete(track.id, fx_index)
            return {"success": True, "track_index": track_index, "removed": name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_fx_param(track_index: int, fx_index: int, param: int | str, value: float) -> dict:
        """Set a normalized FX parameter value (0.0-1.0).

        ``param`` may be an integer index or a parameter name (case-insensitive).
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            fx = track.fxs[fx_index]
            param_index = resolve_fx_param_index(fx, param)
            if param_index < 0:
                return {"success": False, "error": f"FX parameter not found: {param!r}"}
            try:
                fx.params[param_index].normalized_value = value
            except Exception:
                RPR.TrackFX_SetParamNormalized(track.id, fx_index, param_index, value)
                time.sleep(0.05)
            return {
                "success": True,
                "track_index": track_index,
                "fx_index": fx_index,
                "param_index": param_index,
                "param_name": fx.params[param_index].name,
                "value": value,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_fx_param(track_index: int, fx_index: int, param: int | str) -> dict:
        """Get a single FX parameter's normalized value and formatted display."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            fx = track.fxs[fx_index]
            param_index = resolve_fx_param_index(fx, param)
            if param_index < 0:
                return {"success": False, "error": f"FX parameter not found: {param!r}"}
            p = fx.params[param_index]
            return {
                "success": True,
                "track_index": track_index,
                "fx_index": fx_index,
                "param_index": param_index,
                "param_name": p.name,
                "normalized_value": p.normalized_value,
                "formatted_value": getattr(p, "formatted_value", None),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_fx_param_list(track_index: int, fx_index: int) -> dict:
        """List every parameter on an FX plugin with current normalized value and display string."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            fx = track.fxs[fx_index]
            params = []
            for i in range(fx.n_params):
                p = fx.params[i]
                params.append(
                    {
                        "index": i,
                        "name": p.name,
                        "normalized_value": p.normalized_value,
                        "formatted_value": getattr(p, "formatted_value", None),
                    }
                )
            return {
                "success": True,
                "track_index": track_index,
                "fx_index": fx_index,
                "fx_name": fx.name,
                "parameters": params,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_fx(track_index: int) -> dict:
        """List every FX on a track with enabled state and parameter count."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            fx_list = []
            for i in range(track.n_fxs):
                fx = track.fxs[i]
                fx_list.append(
                    {
                        "index": i,
                        "name": fx.name,
                        "enabled": fx.is_enabled,
                        "n_params": fx.n_params,
                    }
                )
            return {"success": True, "track_index": track_index, "fx": fx_list}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def toggle_fx(track_index: int, fx_index: int, enable: bool | None = None) -> dict:
        """Toggle an FX bypass state, or set it explicitly. ``None`` = toggle."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            fx = track.fxs[fx_index]
            if enable is None:
                fx.is_enabled = not fx.is_enabled
            else:
                fx.is_enabled = bool(enable)
            return {
                "success": True,
                "track_index": track_index,
                "fx_index": fx_index,
                "fx_name": fx.name,
                "enabled": fx.is_enabled,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def load_fx_preset(track_index: int, fx_index: int, preset_name: str) -> dict:
        """Load an existing saved preset by name on an FX plugin."""
        try:
            project = get_project()
            track = project.tracks[track_index]
            fx = track.fxs[fx_index]
            fx.preset_name = preset_name
            return {
                "success": True,
                "track_index": track_index,
                "fx_index": fx_index,
                "fx_name": fx.name,
                "preset": fx.preset_name,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
