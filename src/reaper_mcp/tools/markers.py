"""Marker / region tools."""

import logging

from reaper_mcp.connection import get_project
from reaper_mcp.utils.positions import resolve_start, time_to_measure

logger = logging.getLogger("reaper_mcp.tools.markers")


def register_tools(mcp):
    @mcp.tool()
    def create_region(
        name: str,
        start_time: float | None = None,
        end_time: float | None = None,
        start_measure: str | None = None,
        end_measure: str | None = None,
    ) -> dict:
        """Create a region. Accept seconds or ``M:B,F`` for both ends."""
        try:
            project = get_project()
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
            region = project.add_region(s, e, name)
            return {
                "success": True,
                "region_index": region.index,
                "name": name,
                "start": {"time": s, "measure": s_ms},
                "end": {"time": e, "measure": e_ms},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_region(region_index: int) -> dict:
        """Delete a region by its index."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            for region in project.regions:
                if region.index == region_index:
                    region.delete()
                    return {"success": True, "region_index": region_index}
            if RPR.DeleteProjectMarker(0, region_index, True):
                return {"success": True, "region_index": region_index}
            return {"success": False, "error": f"Region {region_index} not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_regions() -> dict:
        """List every region in the project."""
        try:
            project = get_project()
            regions = []
            for i, r in enumerate(project.regions):
                regions.append(
                    {
                        "index": getattr(r, "index", i),
                        "name": getattr(r, "name", ""),
                        "start": r.start,
                        "end": r.end,
                    }
                )
            return {"success": True, "count": len(regions), "regions": regions}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def create_marker(
        name: str,
        position_time: float | None = None,
        position_measure: str | None = None,
    ) -> dict:
        """Create a marker at a position. Accept seconds or ``M:B,F``."""
        try:
            project = get_project()
            pos, pos_ms = resolve_start(position_time, position_measure, project)
            marker = project.add_marker(pos, name)
            return {
                "success": True,
                "marker_index": marker.index,
                "name": name,
                "position": {"time": pos, "measure": pos_ms},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def delete_marker(marker_index: int) -> dict:
        """Delete a marker by its index."""
        try:
            project = get_project()
            for marker in project.markers:
                if marker.index == marker_index:
                    marker.delete()
                    return {"success": True, "marker_index": marker_index}
            return {"success": False, "error": f"Marker {marker_index} not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_markers() -> dict:
        """List every marker in the project."""
        try:
            project = get_project()
            markers = []
            for i, m in enumerate(project.markers):
                markers.append(
                    {
                        "index": getattr(m, "index", i),
                        "name": getattr(m, "name", ""),
                        "position": m.position,
                    }
                )
            return {"success": True, "count": len(markers), "markers": markers}
        except Exception as e:
            return {"success": False, "error": str(e)}
