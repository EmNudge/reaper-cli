"""Master-track tools: volume/pan/mute/solo, master FX, mastering presets, loudness, normalize."""

import logging
import os

from reaper_mcp.connection import get_project
from reaper_mcp.utils.fx_params import resolve_fx_param_index
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

logger = logging.getLogger("reaper_mcp.tools.master")

MASTERING_PRESETS = {
    "default": ["ReaEQ", "ReaComp", "ReaLimit"],
    "loud": ["ReaEQ", "ReaComp", "ReaComp", "ReaLimit"],
    "gentle": ["ReaEQ", "ReaComp", "ReaLimit"],
}


def register_tools(mcp):
    @mcp.tool()
    def get_master_track() -> dict:
        """Return master volume (dB), pan, mute, and solo state."""
        try:
            master = get_project().master_track
            return {
                "success": True,
                "volume_db": get_volume_db(master),
                "pan": get_pan(master),
                "muted": get_mute(master),
                "soloed": get_solo(master),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_master_volume(volume_db: float) -> dict:
        """Set the master track output volume in dB."""
        try:
            master = get_project().master_track
            set_volume_db(master, volume_db)
            return {"success": True, "volume_db": get_volume_db(master)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_master_pan(pan: float) -> dict:
        """Set the master track pan (-1.0 to 1.0)."""
        try:
            master = get_project().master_track
            set_pan(master, pan)
            return {"success": True, "pan": get_pan(master)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def toggle_master_mute(muted: bool | None = None) -> dict:
        """Toggle master mute, or set it explicitly. ``None`` = toggle."""
        try:
            master = get_project().master_track
            new_state = (not get_mute(master)) if muted is None else bool(muted)
            set_mute(master, new_state)
            return {"success": True, "muted": get_mute(master)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def toggle_master_solo(soloed: bool | None = None) -> dict:
        """Toggle master solo, or set it explicitly. ``None`` = toggle."""
        try:
            master = get_project().master_track
            new_state = (not get_solo(master)) if soloed is None else bool(soloed)
            set_solo(master, new_state)
            return {"success": True, "soloed": get_solo(master)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_master_fx(fx_name: str) -> dict:
        """Add an FX plugin to the master track."""
        try:
            project = get_project()
            master = project.master_track
            fx_index = master.add_fx(fx_name)
            if fx_index is None or fx_index < 0:
                return {"success": False, "error": f"Plugin not found: {fx_name!r}"}
            fx = master.fxs[fx_index]
            return {
                "success": True,
                "fx_index": fx_index,
                "name": fx.name,
                "n_params": fx.n_params,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_master_fx() -> dict:
        """List every FX on the master track."""
        try:
            project = get_project()
            master = project.master_track
            fx_list = []
            for i in range(master.n_fxs):
                fx = master.fxs[i]
                fx_list.append(
                    {
                        "index": i,
                        "name": fx.name,
                        "enabled": fx.is_enabled,
                        "n_params": fx.n_params,
                    }
                )
            return {"success": True, "fx": fx_list}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_master_fx_param(fx_index: int, param: int | str, value: float) -> dict:
        """Set a normalized parameter (0.0-1.0) on a master-track FX. ``param`` may be int or name."""
        try:
            project = get_project()
            fx = project.master_track.fxs[fx_index]
            param_index = resolve_fx_param_index(fx, param)
            if param_index < 0:
                return {"success": False, "error": f"FX parameter not found: {param!r}"}
            fx.params[param_index].normalized_value = value
            return {
                "success": True,
                "fx_index": fx_index,
                "param_index": param_index,
                "param_name": fx.params[param_index].name,
                "value": value,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def remove_master_fx(fx_index: int) -> dict:
        """Remove an FX from the master track by index."""
        from reapy import reascript_api as RPR

        try:
            master = get_project().master_track
            ok = RPR.TrackFX_Delete(master.id, int(fx_index))
            if not ok:
                return {
                    "success": False,
                    "error": f"TrackFX_Delete returned False (fx_index={fx_index} out of range?)",
                }
            return {"success": True, "removed_fx_index": int(fx_index)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_master_fx_param(fx_index: int, param: int | str) -> dict:
        """Read a normalized parameter (0.0-1.0) on a master-track FX. ``param`` may be int or name."""
        try:
            fx = get_project().master_track.fxs[fx_index]
            param_index = resolve_fx_param_index(fx, param)
            if param_index < 0:
                return {"success": False, "error": f"FX parameter not found: {param!r}"}
            p = fx.params[param_index]
            return {
                "success": True,
                "fx_index": fx_index,
                "param_index": param_index,
                "param_name": p.name,
                "value": float(p.normalized_value),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_master_fx_param_list(fx_index: int) -> dict:
        """List every parameter on a master-track FX (index, name, current normalized value)."""
        try:
            fx = get_project().master_track.fxs[fx_index]
            params = [
                {
                    "index": i,
                    "name": fx.params[i].name,
                    "value": float(fx.params[i].normalized_value),
                }
                for i in range(fx.n_params)
            ]
            return {"success": True, "fx_index": fx_index, "fx_name": fx.name, "params": params}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def toggle_master_fx(fx_index: int, enabled: bool | None = None) -> dict:
        """Enable / disable / toggle a master-track FX. ``enabled=None`` flips state."""
        try:
            fx = get_project().master_track.fxs[fx_index]
            new_state = (not fx.is_enabled) if enabled is None else bool(enabled)
            fx.is_enabled = new_state
            return {
                "success": True,
                "fx_index": fx_index,
                "name": fx.name,
                "enabled": fx.is_enabled,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def load_master_fx_preset(fx_index: int, preset_name: str) -> dict:
        """Load a named preset on a master-track FX."""
        from reapy import reascript_api as RPR

        try:
            master = get_project().master_track
            ok = RPR.TrackFX_SetPreset(master.id, int(fx_index), str(preset_name))
            if not ok:
                return {
                    "success": False,
                    "error": f"Preset not found or could not be loaded: {preset_name!r}",
                    "fx_index": fx_index,
                }
            return {"success": True, "fx_index": fx_index, "preset": preset_name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def apply_mastering_chain(preset: str = "default") -> dict:
        """Add a standard mastering chain to the master track.

        Presets: ``default`` (EQ→Comp→Limiter), ``loud`` (EQ→2×Comp→Limiter), ``gentle``.
        """
        try:
            if preset not in MASTERING_PRESETS:
                return {
                    "success": False,
                    "error": f"Unknown preset {preset!r}. Available: {list(MASTERING_PRESETS)}",
                }
            project = get_project()
            master = project.master_track
            added = []
            for fx_name in MASTERING_PRESETS[preset]:
                try:
                    fx_index = master.add_fx(fx_name)
                    if fx_index is not None and fx_index >= 0:
                        added.append({"fx_index": fx_index, "name": master.fxs[fx_index].name})
                except Exception:
                    pass
            return {"success": True, "preset": preset, "fx_chain": added}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def apply_limiter() -> dict:
        """Add ReaLimit to the master track. Use ``set_master_fx_param`` to dial in settings."""
        try:
            project = get_project()
            master = project.master_track
            fx_index = master.add_fx("ReaLimit")
            if fx_index is None or fx_index < 0:
                return {"success": False, "error": "ReaLimit not found"}
            fx = master.fxs[fx_index]
            return {
                "success": True,
                "fx_index": fx_index,
                "name": fx.name,
                "hint": (
                    f"ReaLimit added at index {fx_index}. "
                    "Use get_fx_param_list to find threshold/release indices, "
                    "then set_master_fx_param to set them."
                ),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def analyze_loudness() -> dict:
        """Render the project and measure integrated LUFS + sample peak.

        ``integrated_lufs`` is ITU-R BS.1770 loudness via pyloudnorm.
        ``sample_peak_db`` is the maximum absolute sample value across all
        channels — NOT ITU-R BS.1770 true peak (which would require 4×
        oversampling). True peak is typically 0.5-2 dB higher than sample
        peak; treat this as a lower bound when checking for inter-sample
        peaks.
        """
        import numpy as np
        import pyloudnorm as pyln
        import soundfile as sf

        from reaper_mcp.utils.render import render_to_temp_file

        try:
            tmp = render_to_temp_file()
            try:
                data, rate = sf.read(tmp)
                meter = pyln.Meter(rate)
                integrated = meter.integrated_loudness(data)
                peak_linear = float(np.max(np.abs(data)))
                peak_db = float(20 * np.log10(peak_linear)) if peak_linear > 0 else -120.0
                return {
                    "success": True,
                    "integrated_lufs": round(integrated, 1),
                    "sample_peak_db": round(peak_db, 1),
                    "sample_rate": rate,
                }
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except Exception as e:
            logger.error(f"analyze_loudness failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def normalize_project(target_lufs: float = -14.0) -> dict:
        """Measure LUFS then adjust master volume to hit the target.

        Common targets: -14 (streaming), -16 (podcasts), -23 (broadcast).
        """
        import pyloudnorm as pyln
        import soundfile as sf

        from reaper_mcp.utils.render import render_to_temp_file

        try:
            tmp = render_to_temp_file()
            try:
                data, rate = sf.read(tmp)
                meter = pyln.Meter(rate)
                current = meter.integrated_loudness(data)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            import math

            if math.isinf(current) or math.isnan(current):
                return {"success": False, "error": "Project appears to be silent"}
            master = get_project().master_track
            gain_db = target_lufs - current
            new_vol = get_volume_db(master) + gain_db
            set_volume_db(master, new_vol)
            return {
                "success": True,
                "original_lufs": round(current, 1),
                "target_lufs": target_lufs,
                "gain_applied_db": round(gain_db, 1),
                "new_master_volume_db": round(new_vol, 1),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
