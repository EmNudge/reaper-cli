"""Render helpers — shared by the render, analysis, and mastering tool modules."""

from __future__ import annotations

import tempfile

FORMAT_CODES = {"wav": 0, "mp3": 3, "ogg": 4, "flac": 5}
BIT_DEPTH_CODES = {16: 0, 24: 2, 32: 4}


def set_render_settings(
    output_path: str,
    format: str,
    sample_rate: int,
    bit_depth: int,
    channels: int,
    bounds: int,
) -> None:
    """Configure REAPER's render settings.

    ``bounds``: ``0`` = full project, ``1`` = time selection.
    """
    from reapy import reascript_api as RPR

    fmt_code = FORMAT_CODES.get(format.lower(), 0)
    bdepth_code = BIT_DEPTH_CODES.get(bit_depth, 2)
    RPR.GetSetProjectInfo_String(0, "RENDER_FILE", output_path, True)
    RPR.GetSetProjectInfo(0, "RENDER_FORMAT", fmt_code, True)
    RPR.GetSetProjectInfo(0, "RENDER_FORMAT2", bdepth_code, True)
    RPR.GetSetProjectInfo(0, "RENDER_SRATE", float(sample_rate), True)
    RPR.GetSetProjectInfo(0, "RENDER_CHANNELS", float(channels), True)
    RPR.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", float(bounds), True)


def render_to_temp_file(sample_rate: int = 48000) -> str:
    """Render the current project to a temporary WAV and return its path.

    Used by live-analysis and mastering tools. The caller is responsible for
    deleting the file when done.
    """
    import os

    from reapy import reascript_api as RPR

    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    set_render_settings(tmp, "wav", sample_rate, 24, 2, bounds=0)
    RPR.Main_OnCommand(41824, 0)  # File: Render project, using most recent settings
    return tmp
