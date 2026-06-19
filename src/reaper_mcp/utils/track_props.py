"""Track property accessors that work with reapy 0.10+.

In older reapy versions, ``track.volume``, ``track.pan``, ``track.mute``, and
``track.solo`` were direct read/write attributes. In reapy 0.10 they were
removed (or, for mute/solo, repurposed as action methods). The unified package
was originally ported from upstream code that targeted the older API.

These helpers wrap the underlying ``get_info_value`` / ``set_info_value`` calls
plus the new ``is_muted`` / ``is_solo`` read properties, so callers get a
consistent dB/bool/float interface again. ``master_track`` is a ``Track``, so
the same helpers work for it.
"""

from __future__ import annotations

import math


def db_to_linear(db: float) -> float:
    """Convert dB to linear amplitude. ``-150`` dB or lower is treated as zero."""
    if db <= -150:
        return 0.0
    return 10 ** (db / 20.0)


def linear_to_db(linear: float) -> float:
    """Convert linear amplitude to dB. Zero/negative inputs return ``-150``."""
    if linear <= 0:
        return -150.0
    return 20.0 * math.log10(linear)


def get_volume_db(track) -> float:
    return linear_to_db(track.get_info_value("D_VOL"))


def set_volume_db(track, db: float) -> None:
    track.set_info_value("D_VOL", db_to_linear(float(db)))


def get_pan(track) -> float:
    return track.get_info_value("D_PAN")


def set_pan(track, pan: float) -> None:
    track.set_info_value("D_PAN", float(pan))


def get_mute(track) -> bool:
    return bool(track.is_muted)


def set_mute(track, muted: bool) -> None:
    """Use the ``mute()`` / ``unmute()`` action methods (idempotent)."""
    if muted:
        track.mute()
    else:
        track.unmute()


def get_solo(track) -> bool:
    return bool(track.is_solo)


def set_solo(track, soloed: bool) -> None:
    """Use the ``solo()`` / ``unsolo()`` action methods (idempotent)."""
    if soloed:
        track.solo()
    else:
        track.unsolo()
