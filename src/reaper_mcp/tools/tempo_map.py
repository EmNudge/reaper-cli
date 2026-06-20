"""Tempo-map tools — multi-marker tempo + time-signature changes with curve shapes.

REAPER's tempo map is a list of tempo/time-signature markers placed along the
project timeline. Each marker can set BPM, time signature, or both. Between
markers, the tempo can be constant (``linear=False`` — REAPER calls this
"square") or interpolate linearly to the next marker (``linear=True``).

``project.py`` exposes only the single-point ``set_tempo`` and
``set_project_time_signature`` for convenience. Use this module for any
project that needs more than one tempo or time-signature change.
"""

import logging

from reaper_mcp.connection import get_project
from reaper_mcp.utils.positions import position_to_time, resolve_start, time_to_measure

logger = logging.getLogger("reaper_mcp.tools.tempo_map")


def _read_marker(project_id, idx: int) -> dict | None:
    """Read a tempo/time-sig marker by index. Returns a flat dict, or ``None``."""
    from reapy import reascript_api as RPR

    result = RPR.GetTempoTimeSigMarker(project_id, int(idx), 0.0, 0, 0, 0.0, 0, 0, False)
    if not isinstance(result, tuple) or len(result) < 8:
        return None
    # Expected unpack: (ok, time, measure, beat, bpm, sig_num, sig_den, linear)
    ok = result[0]
    if not ok:
        return None
    time_s, measure, beat, bpm, sig_num, sig_den, linear = result[1:8]
    return {
        "index": int(idx),
        "time_seconds": float(time_s),
        "measure_index": int(measure),
        "beat_in_measure": float(beat),
        "bpm": float(bpm),
        "time_signature": {"numerator": int(sig_num), "denominator": int(sig_den)},
        "linear_curve": bool(linear),
    }


def register_tools(mcp):
    @mcp.tool()
    def add_tempo_marker(
        bpm: float | None = None,
        time_sig_num: int | None = None,
        time_sig_den: int | None = None,
        position_time: float | None = None,
        position_measure: str | None = None,
        linear: bool = False,
    ) -> dict:
        """Add a tempo / time-signature marker to the project.

        Pass ``bpm`` to change the tempo, ``time_sig_num`` + ``time_sig_den``
        to change the time signature, or both. Defaults to position 0 if no
        position given. ``linear=True`` interpolates BPM from this marker to
        the next; default ``False`` holds the BPM constant ("square").
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            if position_time is None and position_measure is None:
                pos, pos_ms = 0.0, "1:1,000"
            else:
                pos, pos_ms = resolve_start(position_time, position_measure, project)
            if bpm is None and (time_sig_num is None or time_sig_den is None):
                return {
                    "success": False,
                    "error": "Provide bpm and/or both time_sig_num + time_sig_den",
                }
            # REAPER convention: 0 = keep current
            bpm_v = float(bpm) if bpm is not None else 0.0
            num_v = int(time_sig_num) if time_sig_num is not None else 0
            den_v = int(time_sig_den) if time_sig_den is not None else 0
            ok = RPR.SetTempoTimeSigMarker(
                project.id, -1, float(pos), -1, -1, bpm_v, num_v, den_v, bool(linear)
            )
            if not ok:
                return {"success": False, "error": "SetTempoTimeSigMarker returned False"}
            # Find the new marker's index — REAPER returns no index from Set, so look it up.
            new_idx = int(RPR.FindTempoTimeSigMarker(project.id, float(pos)))
            return {
                "success": True,
                "marker_index": new_idx,
                "position": {"time": pos, "measure": pos_ms},
                "bpm": bpm if bpm is not None else None,
                "time_signature": (
                    f"{time_sig_num}/{time_sig_den}"
                    if time_sig_num is not None and time_sig_den is not None
                    else None
                ),
                "linear_curve": bool(linear),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def modify_tempo_marker(
        marker_index: int,
        bpm: float | None = None,
        time_sig_num: int | None = None,
        time_sig_den: int | None = None,
        position_time: float | None = None,
        position_measure: str | None = None,
        linear: bool | None = None,
    ) -> dict:
        """Edit an existing tempo / time-sig marker in place.

        Pass only the fields you want to change; everything else is preserved
        from the existing marker.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            cur = _read_marker(project.id, marker_index)
            if cur is None:
                return {"success": False, "error": f"Marker {marker_index} not found"}
            new_bpm = float(bpm) if bpm is not None else cur["bpm"]
            new_num = (
                int(time_sig_num)
                if time_sig_num is not None
                else cur["time_signature"]["numerator"]
            )
            new_den = (
                int(time_sig_den)
                if time_sig_den is not None
                else cur["time_signature"]["denominator"]
            )
            new_linear = bool(linear) if linear is not None else cur["linear_curve"]
            if position_time is not None or position_measure is not None:
                new_pos, new_pos_ms = resolve_start(position_time, position_measure, project)
            else:
                new_pos = cur["time_seconds"]
                new_pos_ms = time_to_measure(new_pos, project)
            ok = RPR.SetTempoTimeSigMarker(
                project.id,
                int(marker_index),
                float(new_pos),
                -1,
                -1,
                new_bpm,
                new_num,
                new_den,
                new_linear,
            )
            if not ok:
                return {"success": False, "error": "SetTempoTimeSigMarker returned False"}
            return {
                "success": True,
                "marker_index": int(marker_index),
                "position": {"time": new_pos, "measure": new_pos_ms},
                "bpm": new_bpm,
                "time_signature": f"{new_num}/{new_den}",
                "linear_curve": new_linear,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_tempo_marker(marker_index: int) -> dict:
        """Delete a tempo / time-sig marker by index."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            ok = RPR.DeleteTempoTimeSigMarker(project.id, int(marker_index))
            if not ok:
                return {
                    "success": False,
                    "error": f"DeleteTempoTimeSigMarker returned False (index {marker_index})",
                }
            return {"success": True, "deleted_marker_index": int(marker_index)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_tempo_markers() -> dict:
        """List every tempo / time-sig marker in the project."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            count = int(RPR.CountTempoTimeSigMarkers(project.id))
            markers = [m for i in range(count) if (m := _read_marker(project.id, i)) is not None]
            return {"success": True, "count": len(markers), "markers": markers}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_tempo_marker(marker_index: int) -> dict:
        """Return one tempo / time-sig marker's full state."""
        try:
            project = get_project()
            marker = _read_marker(project.id, int(marker_index))
            if marker is None:
                return {"success": False, "error": f"Marker {marker_index} not found"}
            return {"success": True, "marker": marker}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_tempo_at(
        position_time: float | None = None,
        position_measure: str | None = None,
    ) -> dict:
        """Return the project tempo (BPM) at a given timeline position.

        Honors interpolation between linear-curve markers. Defaults to the
        edit-cursor position if no time given.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            if position_time is None and position_measure is None:
                t = project.cursor_position
                t_ms = time_to_measure(t, project)
            elif position_time is not None:
                t = float(position_time)
                t_ms = time_to_measure(t, project)
            else:
                t = position_to_time(str(position_measure), project)
                t_ms = position_measure
            bpm = float(RPR.TimeMap_GetDividedBpmAtTime(t))
            return {
                "success": True,
                "position": {"time": t, "measure": t_ms},
                "bpm": bpm,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
