"""Marker / region tools."""

import logging
from typing import Any

from reaper_mcp.connection import get_project
from reaper_mcp.utils.positions import position_to_time, resolve_start, time_to_measure

logger = logging.getLogger("reaper_mcp.tools.markers")


def _find_marker_by_index(project, target_index: int, is_region: bool):
    """Return the marker/region object with ``target_index``, or ``None``.

    REAPER's marker/region indices are stable within a project — but a single
    iteration index returned by ``enumerate(project.markers)`` is NOT the
    same number, so always match on ``.index``.
    """
    items = project.regions if is_region else project.markers
    for m in items:
        if getattr(m, "index", None) == target_index:
            return m
    return None


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

    @mcp.tool()
    def rename_marker(marker_index: int, name: str) -> dict:
        """Change the displayed name of a marker without moving it."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            m = _find_marker_by_index(project, marker_index, is_region=False)
            if m is None:
                return {"success": False, "error": f"Marker {marker_index} not found"}
            # SetProjectMarker3(proj, idx, is_region, pos, end, name, color);
            # is_region=False keeps it a marker, end is ignored, color=0 means unchanged.
            ok = RPR.SetProjectMarker3(project.id, marker_index, False, m.position, 0.0, name, 0)
            if not ok:
                return {
                    "success": False,
                    "error": f"SetProjectMarker3 returned False for marker {marker_index}",
                }
            return {"success": True, "marker_index": marker_index, "name": name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def move_marker(
        marker_index: int,
        position_time: float | None = None,
        position_measure: str | None = None,
    ) -> dict:
        """Move a marker to a new position. Accept seconds or ``M:B,F``."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            m = _find_marker_by_index(project, marker_index, is_region=False)
            if m is None:
                return {"success": False, "error": f"Marker {marker_index} not found"}
            pos, pos_ms = resolve_start(position_time, position_measure, project)
            ok = RPR.SetProjectMarker3(
                project.id, marker_index, False, pos, 0.0, getattr(m, "name", ""), 0
            )
            if not ok:
                return {
                    "success": False,
                    "error": f"SetProjectMarker3 returned False for marker {marker_index}",
                }
            return {
                "success": True,
                "marker_index": marker_index,
                "position": {"time": pos, "measure": pos_ms},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def goto_marker(marker_index: int) -> dict:
        """Move the edit cursor to a marker's position."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            m = _find_marker_by_index(project, marker_index, is_region=False)
            if m is None:
                return {"success": False, "error": f"Marker {marker_index} not found"}
            # SetEditCurPos(time, moveview, seekplay)
            RPR.SetEditCurPos(m.position, True, False)
            return {
                "success": True,
                "marker_index": marker_index,
                "position_seconds": float(m.position),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_markers(markers: list[dict[str, Any]]) -> dict:
        """Create multiple markers in one call.

        Each entry: ``name`` (str), plus one of ``position_time`` (float) or
        ``position_measure`` (``M:B,F`` string).
        """
        try:
            project = get_project()
            created: list[dict] = []
            errors: list[dict] = []
            for i, spec in enumerate(markers):
                try:
                    name = str(spec.get("name", ""))
                    if "position_time" in spec and spec["position_time"] is not None:
                        pos = float(spec["position_time"])
                    elif "position_measure" in spec and spec["position_measure"] is not None:
                        pos = position_to_time(str(spec["position_measure"]), project)
                    else:
                        raise ValueError("Provide position_time or position_measure")
                    marker = project.add_marker(pos, name)
                    created.append(
                        {
                            "index": i,
                            "marker_index": marker.index,
                            "name": name,
                            "position_seconds": pos,
                        }
                    )
                except Exception as e:
                    errors.append({"index": i, "spec": spec, "error": str(e)})
            return {
                "success": not errors,
                "partial": bool(created) and bool(errors),
                "added": len(created),
                "failed": len(errors),
                "successful_markers": created,
                "failed_markers": errors,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def rename_region(region_index: int, name: str) -> dict:
        """Change the displayed name of a region without moving it."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            r = _find_marker_by_index(project, region_index, is_region=True)
            if r is None:
                return {"success": False, "error": f"Region {region_index} not found"}
            ok = RPR.SetProjectMarker3(project.id, region_index, True, r.start, r.end, name, 0)
            if not ok:
                return {
                    "success": False,
                    "error": f"SetProjectMarker3 returned False for region {region_index}",
                }
            return {"success": True, "region_index": region_index, "name": name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def move_region(
        region_index: int,
        start_time: float | None = None,
        end_time: float | None = None,
        start_measure: str | None = None,
        end_measure: str | None = None,
    ) -> dict:
        """Move a region to a new start/end. Accept seconds or ``M:B,F`` for either end."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            r = _find_marker_by_index(project, region_index, is_region=True)
            if r is None:
                return {"success": False, "error": f"Region {region_index} not found"}
            # Pull in current values then override whichever end the caller provided.
            new_start = float(r.start)
            new_end = float(r.end)
            if start_time is not None:
                new_start = float(start_time)
            elif start_measure is not None:
                new_start = position_to_time(start_measure, project)
            if end_time is not None:
                new_end = float(end_time)
            elif end_measure is not None:
                new_end = position_to_time(end_measure, project)
            if new_end <= new_start:
                return {
                    "success": False,
                    "error": f"Region end ({new_end}) must be after start ({new_start})",
                }
            ok = RPR.SetProjectMarker3(
                project.id, region_index, True, new_start, new_end, getattr(r, "name", ""), 0
            )
            if not ok:
                return {
                    "success": False,
                    "error": f"SetProjectMarker3 returned False for region {region_index}",
                }
            return {
                "success": True,
                "region_index": region_index,
                "start_seconds": new_start,
                "end_seconds": new_end,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def goto_region(region_index: int) -> dict:
        """Move the edit cursor to a region's start."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            r = _find_marker_by_index(project, region_index, is_region=True)
            if r is None:
                return {"success": False, "error": f"Region {region_index} not found"}
            RPR.SetEditCurPos(r.start, True, False)
            return {
                "success": True,
                "region_index": region_index,
                "start_seconds": float(r.start),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def add_regions(regions: list[dict[str, Any]]) -> dict:
        """Create multiple regions in one call.

        Each entry: ``name`` (str), plus one of ``start_time`` (float) or
        ``start_measure`` (``M:B,F`` string), plus one of ``end_time`` /
        ``end_measure``.
        """
        try:
            project = get_project()
            created: list[dict] = []
            errors: list[dict] = []
            for i, spec in enumerate(regions):
                try:
                    name = str(spec.get("name", ""))
                    if "start_time" in spec and spec["start_time"] is not None:
                        s = float(spec["start_time"])
                    elif "start_measure" in spec and spec["start_measure"] is not None:
                        s = position_to_time(str(spec["start_measure"]), project)
                    else:
                        raise ValueError("Provide start_time or start_measure")
                    if "end_time" in spec and spec["end_time"] is not None:
                        e_pos = float(spec["end_time"])
                    elif "end_measure" in spec and spec["end_measure"] is not None:
                        e_pos = position_to_time(str(spec["end_measure"]), project)
                    else:
                        raise ValueError("Provide end_time or end_measure")
                    region = project.add_region(s, e_pos, name)
                    created.append(
                        {
                            "index": i,
                            "region_index": region.index,
                            "name": name,
                            "start_seconds": s,
                            "end_seconds": e_pos,
                        }
                    )
                except Exception as ex:
                    errors.append({"index": i, "spec": spec, "error": str(ex)})
            return {
                "success": not errors,
                "partial": bool(created) and bool(errors),
                "added": len(created),
                "failed": len(errors),
                "successful_regions": created,
                "failed_regions": errors,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
