"""Envelope tools — FX parameter automation, named envelopes, point reading/writing.

The existing ``mixing.py`` adds points to ``Volume`` and ``Pan`` envelopes only.
This module exposes every envelope on a track (including arbitrary FX-param
envelopes) for both reading and writing.
"""

import logging

from reaper_mcp.connection import get_project

logger = logging.getLogger("reaper_mcp.tools.envelopes")

ENVELOPE_SHAPES = {
    "linear": 0,
    "square": 1,
    "slow_start_end": 2,
    "fast_start": 3,
    "fast_end": 4,
    "bezier": 5,
}


def _resolve_shape(shape: int | str) -> int:
    if isinstance(shape, int):
        return shape
    try:
        return int(shape)
    except (ValueError, TypeError):
        return ENVELOPE_SHAPES.get(str(shape).lower(), 0)


def _get_envelope(track, name: str):
    """Find a named envelope on a track, or None."""
    from reapy import reascript_api as RPR

    env = RPR.GetTrackEnvelopeByName(track.id, name)
    return env if env else None


def register_tools(mcp):
    @mcp.tool()
    def list_envelopes(track_index: int) -> dict:
        """List every envelope on a track — name, point count, FX-param origin if any.

        Use the returned ``name`` (e.g. ``"Volume"``, ``"Pan"``) or ``fx_param``
        info to address envelopes in the other tools.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            n = int(RPR.CountTrackEnvelopes(track.id))
            envelopes = []
            for i in range(n):
                env = RPR.GetTrackEnvelope(track.id, i)
                if not env:
                    continue
                name_result = RPR.GetEnvelopeName(env, "", 256)
                if isinstance(name_result, tuple):
                    names = [s for s in name_result if isinstance(s, str) and s]
                    name = names[-1] if names else ""
                else:
                    name = str(name_result)
                point_count = int(RPR.CountEnvelopePoints(env))
                envelopes.append({"index": i, "name": name, "point_count": point_count})
            return {
                "success": True,
                "track_index": track_index,
                "count": len(envelopes),
                "envelopes": envelopes,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_fx_param_envelope(
        track_index: int,
        fx_index: int,
        param: int | str,
        visible: bool = True,
    ) -> dict:
        """Create (and optionally show) an automation envelope for an FX parameter.

        After this, the envelope is addressable by name like
        ``"<FX name>: <param name>"`` via the other envelope tools.
        """
        from reapy import reascript_api as RPR

        from reaper_mcp.utils.fx_params import resolve_fx_param_index

        try:
            project = get_project()
            track = project.tracks[track_index]
            fx = track.fxs[fx_index]
            param_index = resolve_fx_param_index(fx, param)
            if param_index < 0:
                return {"success": False, "error": f"FX parameter not found: {param!r}"}
            env = RPR.GetFXEnvelope(track.id, int(fx_index), int(param_index), True)
            if not env:
                return {"success": False, "error": "Failed to create envelope"}
            name_result = RPR.GetEnvelopeName(env, "", 256)
            if isinstance(name_result, tuple):
                names = [s for s in name_result if isinstance(s, str) and s]
                name = names[-1] if names else ""
            else:
                name = str(name_result)
            return {
                "success": True,
                "track_index": track_index,
                "fx_index": int(fx_index),
                "param_index": int(param_index),
                "param_name": fx.params[param_index].name,
                "envelope_name": name,
                "visible": bool(visible),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_envelope_points(track_index: int, envelope_name: str) -> dict:
        """Return every point on a named envelope — time, value, shape, tension."""
        from reapy import reascript_api as RPR

        _SHAPE_NAMES = {v: k for k, v in ENVELOPE_SHAPES.items()}
        try:
            project = get_project()
            track = project.tracks[track_index]
            env = _get_envelope(track, envelope_name)
            if not env:
                return {
                    "success": False,
                    "error": f"Envelope not found: {envelope_name!r}",
                }
            n = int(RPR.CountEnvelopePoints(env))
            points = []
            for i in range(n):
                result = RPR.GetEnvelopePoint(env, i, 0, 0, 0, 0, 0)
                if not isinstance(result, tuple) or len(result) < 6:
                    continue
                ok, t, v, shape, tension, selected = result[:6]
                if not ok:
                    continue
                points.append(
                    {
                        "index": i,
                        "time": float(t),
                        "value": float(v),
                        "shape": _SHAPE_NAMES.get(int(shape), str(int(shape))),
                        "tension": float(tension),
                        "selected": bool(selected),
                    }
                )
            return {
                "success": True,
                "track_index": track_index,
                "envelope_name": envelope_name,
                "count": len(points),
                "points": points,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_envelope_point(
        track_index: int,
        envelope_name: str,
        position: float,
        value: float,
        shape: int | str = "linear",
        tension: float = 0.0,
    ) -> dict:
        """Add a point to any named envelope (not just Volume/Pan).

        Use ``list_envelopes`` to discover names, or ``add_fx_param_envelope`` to
        create one for an FX parameter first.
        Values are taken at face value — for FX param envelopes this is normalized
        (0.0-1.0); for volume it's linear amplitude.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            env = _get_envelope(track, envelope_name)
            if not env:
                return {
                    "success": False,
                    "error": f"Envelope not found: {envelope_name!r}",
                }
            shape_int = _resolve_shape(shape)
            RPR.InsertEnvelopePoint(
                env,
                float(position),
                float(value),
                int(shape_int),
                float(tension),
                False,
                True,
            )
            RPR.Envelope_SortPoints(env)
            return {
                "success": True,
                "track_index": track_index,
                "envelope_name": envelope_name,
                "position": float(position),
                "value": float(value),
                "shape": shape,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_envelope_point(track_index: int, envelope_name: str, point_index: int) -> dict:
        """Delete a single envelope point by index. Get indices via ``get_envelope_points``."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            env = _get_envelope(track, envelope_name)
            if not env:
                return {
                    "success": False,
                    "error": f"Envelope not found: {envelope_name!r}",
                }
            ok = RPR.DeleteEnvelopePointEx(env, -1, int(point_index))
            return {
                "success": bool(ok),
                "track_index": track_index,
                "envelope_name": envelope_name,
                "deleted_index": int(point_index),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def clear_envelope(track_index: int, envelope_name: str) -> dict:
        """Remove every point from a named envelope."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            env = _get_envelope(track, envelope_name)
            if not env:
                return {
                    "success": False,
                    "error": f"Envelope not found: {envelope_name!r}",
                }
            n = int(RPR.CountEnvelopePoints(env))
            for i in range(n - 1, -1, -1):
                RPR.DeleteEnvelopePointEx(env, -1, i)
            return {
                "success": True,
                "track_index": track_index,
                "envelope_name": envelope_name,
                "deleted_count": n,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
