"""Project-level tools: create/load/save, tempo, time signature."""

import logging
import os
import time
from pathlib import Path

from reaper_mcp.connection import get_project
from reaper_mcp.utils.positions import (
    format_time_signature,
    get_time_map_info,
    position_to_time,
    time_to_measure,
)

logger = logging.getLogger("reaper_mcp.tools.project")


def register_tools(mcp):
    @mcp.tool()
    def create_project(tempo: float = 120.0, time_signature: str = "4/4", name: str = "") -> dict:
        """Create a new REAPER project with the given tempo and time signature."""
        from reapy import reascript_api as RPR

        try:
            RPR.Main_OnCommand(41929, 0)  # File: New project
            project = get_project()
            project.bpm = tempo
            if time_signature:
                num, denom = (int(x) for x in time_signature.split("/"))
                project.time_signature = (num, denom)
            return {
                "success": True,
                "name": name or f"New Project {time.strftime('%Y-%m-%d %H-%M-%S')}",
                "tempo": project.bpm,
                "time_signature": time_signature,
            }
        except Exception as e:
            logger.error(f"create_project failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def save_project(project_path: str = "") -> dict:
        """Save the current project. Empty path → ~/Documents/REAPER Projects/<name>.rpp."""
        try:
            project = get_project()
            if not project_path:
                proj_name = project.name or f"Project {time.strftime('%Y-%m-%d %H-%M-%S')}"
                default_dir = Path.home() / "Documents" / "REAPER Projects"
                os.makedirs(default_dir, exist_ok=True)
                project_path = str(default_dir / f"{proj_name}.rpp")
            os.makedirs(os.path.dirname(os.path.abspath(project_path)), exist_ok=True)
            project.save(project_path)
            return {"success": True, "project_path": project_path}
        except Exception as e:
            logger.error(f"save_project failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def load_project(project_path: str) -> dict:
        """Open an existing ``.rpp`` file in REAPER."""
        from reapy import reascript_api as RPR

        try:
            if not os.path.exists(project_path):
                return {"success": False, "error": f"File not found: {project_path}"}
            RPR.Main_openProject(project_path)
            project = get_project()
            return {
                "success": True,
                "name": project.name,
                "tempo": project.bpm,
                "time_signature": format_time_signature(project),
                "project_path": project_path,
            }
        except Exception as e:
            logger.error(f"load_project failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_project_info() -> dict:
        """Return name, path, tempo, time signature, length, track count, markers, regions."""
        try:
            project = get_project()
            markers = []
            try:
                for i in range(project.n_markers):
                    m = project.markers[i]
                    markers.append({"index": i, "name": m.name, "position": m.position})
            except Exception:
                pass
            regions = []
            try:
                for i in range(project.n_regions):
                    r = project.regions[i]
                    regions.append({"index": i, "name": r.name, "start": r.start, "end": r.end})
            except Exception:
                pass
            return {
                "success": True,
                "name": project.name,
                "path": project.path,
                "tempo": project.bpm,
                "time_signature": format_time_signature(project),
                "length": project.length,
                "track_count": project.n_tracks,
                "markers": markers,
                "regions": regions,
            }
        except Exception as e:
            logger.error(f"get_project_info failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_tempo(bpm: float) -> dict:
        """Set the project tempo in BPM."""
        try:
            project = get_project()
            project.bpm = float(bpm)
            return {"success": True, "tempo": project.bpm}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_tempo() -> dict:
        """Return the current project tempo in BPM."""
        try:
            project = get_project()
            return {"success": True, "tempo": project.bpm}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_project_time_signature(numerator: int, denominator: int) -> dict:
        """Set the project's default time signature at position 0 (e.g. 4/4, 3/4, 6/8)."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            # SetTempoTimeSigMarker(proj, ptidx, timepos, measurepos, beatpos,
            #                       bpm, num, denom, lineartempo).
            # ptidx=-1 → add a new marker; REAPER merges with any existing marker
            # at the same position. bpm=0 → keep current tempo.
            RPR.SetTempoTimeSigMarker(project.id, -1, 0.0, -1, -1, 0, numerator, denominator, False)
            return {
                "success": True,
                "time_signature": f"{numerator}/{denominator}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_project_time_signature() -> dict:
        """Return the project's default time signature plus BPM."""
        try:
            info = get_time_map_info()
            return {
                "success": True,
                "numerator": info["time_sig_num"],
                "denominator": info["time_sig_den"],
                "bpm": info["bpm"],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_time_signature(
        numerator: int,
        denominator: int,
        position_time: float | None = None,
        position_measure: str | None = None,
    ) -> dict:
        """Set the time signature at a specific position.

        Provide either ``position_time`` (seconds) or ``position_measure`` (``M:B,F``).
        Defaults to position 0 if neither is given.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            if position_time is not None:
                pos = float(position_time)
                measure_pos = time_to_measure(pos)
            elif position_measure is not None:
                pos = position_to_time(position_measure)
                measure_pos = position_measure
            else:
                pos = 0.0
                measure_pos = "1:1,000"
            RPR.SetTempoTimeSigMarker(project.id, -1, pos, -1, -1, 0, numerator, denominator, False)
            return {
                "success": True,
                "time_signature": f"{numerator}/{denominator}",
                "position_seconds": pos,
                "position_measure": measure_pos,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
