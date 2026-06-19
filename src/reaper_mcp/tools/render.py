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
