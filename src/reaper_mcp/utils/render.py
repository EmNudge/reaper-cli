"""Render helpers — shared by the render, analysis, and mastering tool modules.

REAPER stores ``RENDER_FORMAT`` / ``RENDER_FORMAT2`` as opaque binary blobs
(FOURCC + codec-specific data) set via ``GetSetProjectInfo_String``. The
numeric ``GetSetProjectInfo`` path does NOT affect the actual render output —
an older version of this helper used that path and silently rendered with
whatever format was last selected in REAPER's GUI.

For WAV (the only format whose blob layout is stable enough to construct
in-process) we build a minimal ``"evaw"`` + bit-depth blob. For MP3 / OGG /
FLAC, callers must supply a pre-captured ``format_blob`` (see
``save_render_preset`` — capture from REAPER's GUI once, replay forever).
"""

from __future__ import annotations

import tempfile

# WAV bit-depth codes inside the FOURCC blob (int32 LE following b"evaw").
# Code 0 = 8-bit, 1 = 16-bit, 2 = 24-bit, 3 = 32-bit int, 4 = 32-bit float,
# 5 = 64-bit float. We only expose the three common integer depths.
_WAV_BIT_DEPTH_CODE = {16: 1, 24: 2, 32: 3}


def build_wav_format_blob(bit_depth: int) -> str:
    """Build a minimal WAV ``RENDER_FORMAT`` blob (FOURCC + bit depth + flags).

    Returned as a Latin-1 string because REAPER's ``GetSetProjectInfo_String``
    binding is ``char*``-typed — Latin-1 round-trips every byte 1:1.
    """
    code = _WAV_BIT_DEPTH_CODE.get(bit_depth, 2)
    blob = b"evaw" + code.to_bytes(4, "little") + (0).to_bytes(4, "little")
    return blob.decode("latin-1")


def set_render_settings(
    output_path: str,
    format: str,
    sample_rate: int,
    bit_depth: int,
    channels: int,
    bounds: int,
    *,
    format_blob: str | None = None,
) -> None:
    """Configure REAPER's render settings.

    ``bounds``: ``0`` = entire project, ``1`` = time selection.

    For WAV, the format blob is built in-process from ``bit_depth``. For other
    formats, pass ``format_blob`` — a string previously captured by reading
    ``RENDER_FORMAT`` via ``GetSetProjectInfo_String`` (typically via a render
    preset). Without ``format_blob``, non-WAV ``format`` arguments raise
    ``ValueError`` rather than silently rendering as the GUI's last format.
    """
    from reapy import reascript_api as RPR

    fmt = format.lower()
    if format_blob is None:
        if fmt != "wav":
            raise ValueError(
                f"set_render_settings cannot construct a {fmt!r} format blob; "
                "either set bit_depth + format='wav', or capture a "
                "RENDER_FORMAT blob via save_render_preset and pass it as "
                "format_blob=..."
            )
        format_blob = build_wav_format_blob(bit_depth)

    RPR.GetSetProjectInfo_String(0, "RENDER_FILE", output_path, True)
    RPR.GetSetProjectInfo_String(0, "RENDER_FORMAT", format_blob, True)
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
