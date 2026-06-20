"""Rendering tools — full project, time selection, stems.

The temp-file render helper used by analysis/mastering tools lives in
``reaper_mcp.utils.render``.
"""

import logging
import os
from pathlib import Path

from reaper_mcp.connection import get_project
from reaper_mcp.utils.positions import resolve_start
from reaper_mcp.utils.render import set_render_settings
from reaper_mcp.utils.track_props import set_solo

logger = logging.getLogger("reaper_mcp.tools.render")


def register_tools(mcp):
    @mcp.tool()
    def about_render() -> dict:
        """Orientation primer for the render tool group — call before first use.

        Covers: REAPER's render settings model (config blobs vs numeric keys),
        the format-blob FOURCC requirement, the relationship between this
        group and ``render_presets``, and the always-fixed mechanism that
        actually triggers a render (action 41824).
        """
        return {
            "success": True,
            "how_render_runs": (
                "Every render in this group works by (1) writing settings into "
                "REAPER's project info keys, then (2) firing action 41824 "
                "(File: Render project, using most recent settings). REAPER "
                "renders synchronously to the path in RENDER_FILE."
            ),
            "format_blob_warning": (
                "RENDER_FORMAT and RENDER_FORMAT2 are NOT numeric — they are "
                "opaque FOURCC-prefixed blobs set via GetSetProjectInfo_String. "
                "We construct a valid WAV blob in-process; for MP3/OGG/FLAC, "
                "callers must first configure the format in REAPER's GUI, "
                "save_render_preset, then apply_render_preset before rendering. "
                "Format/bit-depth args on render_project for non-WAV formats "
                "will raise rather than silently rendering as the GUI's last "
                "format."
            ),
            "bounds_flag": {
                "0": "render entire project",
                "1": "render time selection",
                "note": "render_project uses 0; render_time_selection sets time-selection then uses 1.",
            },
            "presets_workflow": [
                "1. Configure desired settings in REAPER's GUI (Render dialog).",
                "2. Call save_render_preset(name) to snapshot all RENDER_* keys.",
                "3. Later: apply_render_preset(name) → render_project / render_time_selection.",
                "Presets live in our config dir (not REAPER's), JSON-backed, version-safe.",
            ],
            "stems": (
                "render_stems solos each requested track in turn and renders "
                "individually. It restores solo state in a finally block. Stem "
                "files are named after the track name (sanitised) under "
                "output_directory."
            ),
            "related_groups": {
                "render_presets": "Save/apply/list/delete named render configurations.",
                "analysis": "Live spectrum/dynamics analysis — also uses temp renders internally.",
                "master": "analyze_loudness / normalize_project — render once, measure LUFS.",
            },
        }

    @mcp.tool()
    def render_project(
        output_path: str,
        format: str = "wav",
        sample_rate: int = 48000,
        bit_depth: int = 24,
        channels: int = 2,
    ) -> dict:
        """Render the entire project to a file.

        ``format``: wav | flac | mp3 (needs LAME) | ogg.
        ``bit_depth``: 16 | 24 | 32 (WAV only; ignored for mp3/ogg/flac).
        ``channels``: 1 (mono) or 2 (stereo).
        """
        from reapy import reascript_api as RPR

        try:
            output_path = str(Path(output_path).expanduser().resolve())
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            set_render_settings(output_path, format, sample_rate, bit_depth, channels, bounds=0)
            RPR.Main_OnCommand(41824, 0)
            if not os.path.exists(output_path):
                return {
                    "success": False,
                    "error": "Render command completed but output file not found",
                }
            return {
                "success": True,
                "output_path": output_path,
                "format": format,
                "sample_rate": sample_rate,
                "bit_depth": bit_depth,
                "channels": channels,
                "file_size_bytes": os.path.getsize(output_path),
            }
        except Exception as e:
            logger.error(f"render_project failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def render_time_selection(
        output_path: str,
        start_time: float | None = None,
        end_time: float | None = None,
        start_measure: str | None = None,
        end_measure: str | None = None,
        format: str = "wav",
        sample_rate: int = 48000,
        bit_depth: int = 24,
        channels: int = 2,
    ) -> dict:
        """Render a time range. Accept seconds or ``M:B,F`` for both ends."""
        from reapy import reascript_api as RPR

        try:
            output_path = str(Path(output_path).expanduser().resolve())
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            project = get_project()
            s, _ = resolve_start(start_time, start_measure, project)
            if end_time is not None:
                e = float(end_time)
            elif end_measure is not None:
                from reaper_mcp.utils.positions import position_to_time

                e = position_to_time(end_measure, project)
            else:
                return {"success": False, "error": "Provide end_time or end_measure"}

            project.time_selection = (s, e)
            set_render_settings(output_path, format, sample_rate, bit_depth, channels, bounds=1)
            RPR.Main_OnCommand(41824, 0)
            if not os.path.exists(output_path):
                return {"success": False, "error": "Render completed but output file not found"}
            return {
                "success": True,
                "output_path": output_path,
                "start": s,
                "end": e,
                "format": format,
                "file_size_bytes": os.path.getsize(output_path),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def set_region_render_matrix(region_index: int, track_index: int, include: bool) -> dict:
        """Mark a track as included / excluded in a region's stem render matrix.

        REAPER's "Region render matrix" lets you map regions to a subset of
        tracks; rendering "regions via matrix" then writes one stem per
        region with only the marked tracks summed.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            track = project.tracks[track_index]
            # SetRegionRenderMatrix(proj, regionindex, track, addorremove)
            # addorremove: 0 = clear all, 1 = add this track, -1 = remove this track
            RPR.SetRegionRenderMatrix(project.id, int(region_index), track.id, 1 if include else -1)
            return {
                "success": True,
                "region_index": int(region_index),
                "track_index": int(track_index),
                "included": bool(include),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_region_render_matrix(region_index: int) -> dict:
        """Return every track included in a region's stem render matrix.

        Enumerates by render-slot via ``EnumRegionRenderMatrix(proj,
        region_idx, slot)``; each slot returns one track pointer or ``None``
        when the matrix runs out.
        """
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            included: list[dict] = []
            slot = 0
            # Cache track ids for O(N×M) → O(N+M) lookup.
            track_ids = {str(project.tracks[ti].id): ti for ti in range(project.n_tracks)}
            while True:
                t_ptr = RPR.EnumRegionRenderMatrix(project.id, int(region_index), slot)
                if not t_ptr:
                    break
                key = str(t_ptr)
                if key in track_ids:
                    ti = track_ids[key]
                    included.append({"index": ti, "name": project.tracks[ti].name})
                slot += 1
                if slot > 1000:
                    break  # safety
            return {
                "success": True,
                "region_index": int(region_index),
                "track_count": len(included),
                "tracks": included,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def clear_region_render_matrix(region_index: int) -> dict:
        """Clear every track entry from a region's stem render matrix."""
        from reapy import reascript_api as RPR

        try:
            project = get_project()
            # Iterate slots and remove each. The matrix shrinks as we go, so
            # repeatedly reading slot 0 is correct.
            removed = 0
            while True:
                t_ptr = RPR.EnumRegionRenderMatrix(project.id, int(region_index), 0)
                if not t_ptr:
                    break
                RPR.SetRegionRenderMatrix(project.id, int(region_index), t_ptr, -1)
                removed += 1
                if removed > 1000:  # safety stop
                    break
            return {
                "success": True,
                "region_index": int(region_index),
                "removed_tracks": removed,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def queue_render() -> dict:
        """Add the current project to REAPER's render queue (action 41823).

        Use ``process_render_queue`` to render every queued project, or open
        REAPER's "File → Render queue…" dialog to inspect.
        """
        from reapy import reascript_api as RPR

        try:
            RPR.Main_OnCommand(41823, 0)
            return {"success": True, "message": "Added project to render queue"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def process_render_queue() -> dict:
        """Render every project currently in REAPER's render queue (action 41207)."""
        from reapy import reascript_api as RPR

        try:
            RPR.Main_OnCommand(41207, 0)
            return {"success": True, "message": "Render queue processed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def render_regions_via_matrix(output_directory: str) -> dict:
        """Render each region using its render matrix (action 42230).

        Set up the per-region track inclusion with ``set_region_render_matrix``
        first. Output naming is controlled by REAPER's ``RENDER_PATTERN`` —
        use ``save_render_preset`` / ``apply_render_preset`` from
        ``render_presets`` to configure it.
        """
        from reapy import reascript_api as RPR

        try:
            output_directory = str(Path(output_directory).expanduser().resolve())
            os.makedirs(output_directory, exist_ok=True)
            project = get_project()
            # Set RENDER_FILE to the target directory; REAPER appends per-region.
            RPR.GetSetProjectInfo_String(project.id, "RENDER_FILE", output_directory, True)
            # 42230 = "File: Render project, all regions, via Region Render Matrix"
            RPR.Main_OnCommand(42230, 0)
            return {
                "success": True,
                "output_directory": output_directory,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def render_stems(
        output_directory: str,
        track_indices: list[int] | None = None,
        format: str = "wav",
        sample_rate: int = 48000,
        bit_depth: int = 24,
    ) -> dict:
        """Render each track as a separate stem file by soloing tracks individually.

        ``track_indices``: list of indices, or ``None`` to render every track.
        Files are named after the track names in ``output_directory``.
        """
        from reapy import reascript_api as RPR

        try:
            output_directory = str(Path(output_directory).expanduser().resolve())
            os.makedirs(output_directory, exist_ok=True)
            project = get_project()
            indices = track_indices if track_indices is not None else list(range(project.n_tracks))
            rendered = []
            try:
                for idx in indices:
                    t = project.tracks[idx]
                    name = t.name or f"Track_{idx}"
                    for j in range(project.n_tracks):
                        set_solo(project.tracks[j], j == idx)
                    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
                    stem_path = os.path.join(output_directory, f"{safe}.{format}")
                    set_render_settings(stem_path, format, sample_rate, bit_depth, 2, bounds=0)
                    RPR.Main_OnCommand(41824, 0)
                    rendered.append(
                        {
                            "track_index": idx,
                            "track_name": name,
                            "output_path": stem_path,
                            "exists": os.path.exists(stem_path),
                        }
                    )
            finally:
                for j in range(project.n_tracks):
                    set_solo(project.tracks[j], False)
            return {
                "success": True,
                "output_directory": output_directory,
                "stems": rendered,
            }
        except Exception as e:
            logger.error(f"render_stems failed: {e}")
            return {"success": False, "error": str(e)}
