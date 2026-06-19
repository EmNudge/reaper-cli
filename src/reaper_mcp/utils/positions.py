"""Position helpers — accept either seconds (float) or "measure:beat,fraction" strings.

Format: ``"M:B,F"`` where ``M`` is 1-based measure, ``B`` is 1-based beat,
``F`` is fractional beat in milliseconds (e.g. ``"8:1,500"`` = measure 8, beat 1,
half a beat in).
"""

from __future__ import annotations


def position_to_time(position: float | int | str, project=None) -> float:
    """Convert a position (seconds float OR ``M:B,F`` string) to seconds."""
    if isinstance(position, (int, float)):
        return float(position)

    if isinstance(position, str) and (":" in position or "." in position):
        import reapy
        from reapy import reascript_api as RPR

        try:
            if project is None:
                project = reapy.Project()
            if "." in position and ":" not in position:
                parts = position.split(".")
            else:
                parts = position.replace(",", ".").replace(":", ".").split(".")
            if len(parts) != 3:
                raise ValueError(
                    f"Invalid position format: {position!r}. Expected 'measure:beat,fraction'."
                )
            measure = int(parts[0])
            beat = int(parts[1])
            beat_fraction = int(parts[2]) / 1000.0
            full_beat = beat + beat_fraction
            return RPR.TimeMap2_QNToTime(project.id, (measure - 1) * 4 + full_beat - 1)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to convert position {position!r} to time: {e}") from e

    return float(position)


def time_to_measure(time_seconds: float, project=None) -> str:
    """Inverse of ``position_to_time`` — seconds → ``M:B,F`` string."""
    import reapy
    from reapy import reascript_api as RPR

    if project is None:
        project = reapy.Project()
    try:
        qn = RPR.TimeMap2_timeToQN(project.id, time_seconds)
        measure = int(qn // 4) + 1
        full_beat = (qn % 4) + 1
        beat = int(full_beat)
        beat_fraction = int((full_beat - beat) * 1000)
        return f"{measure}:{beat},{beat_fraction:03d}"
    except Exception as e:
        raise ValueError(f"Failed to convert time {time_seconds} to measure: {e}") from e


def get_time_map_info(project=None, time: float = 0.0) -> dict:
    """Return BPM + time-signature numerator/denominator at ``time`` seconds.

    Uses ``TimeMap_GetTimeSigAtTime`` (correct on reapy 0.10+) which returns
    ``(num, denom, bpm)`` — unlike ``project.time_signature`` which returns
    ``(bpm, num)`` and drops the denominator.
    """
    import reapy
    from reapy import reascript_api as RPR

    if project is None:
        project = reapy.Project()
    try:
        result = RPR.TimeMap_GetTimeSigAtTime(project.id, float(time), 0, 0, 0.0)
        # reapy returns [proj_id, time, num, denom, bpm]
        num = int(result[2])
        denom = int(result[3])
        bpm = float(result[4])
        if num <= 0:
            raise ValueError("Invalid time signature values")
        return {"bpm": bpm, "time_sig_num": num, "time_sig_den": denom}
    except Exception as e:
        raise ValueError(f"Failed to get time map info: {e}") from e


def format_time_signature(project=None, time: float = 0.0) -> str:
    """Convenience: ``"4/4"``-style string for the time signature at ``time``."""
    info = get_time_map_info(project, time)
    return f"{info['time_sig_num']}/{info['time_sig_den']}"


def measure_length_to_time(length_measure: str, start_time: float = 0.0, project=None) -> float:
    """Convert a length expressed as ``M:B,F`` to a duration in seconds.

    The duration is measured from ``start_time``, then returned as ``end_time - start_time``
    (with a 0.1s floor to ensure minimum-note-length sanity).
    """
    import reapy

    if project is None:
        project = reapy.Project()
    try:
        curr_measure = time_to_measure(start_time, project)
        curr_measure_num = int(curr_measure.split(":")[0])

        # Parse target length
        length_parts = length_measure.replace(":", ".").split(".")
        if len(length_parts) != 3:
            parts = length_measure.split(":")
            if len(parts) != 2:
                raise ValueError(
                    f"Invalid measure format: {length_measure!r}. "
                    "Expected 'measures:beat,fraction'."
                )
            measure_part = parts[0]
            beat_parts = parts[1].split(",")
            if len(beat_parts) != 2:
                raise ValueError("Invalid beat format")
            length_parts = [measure_part] + beat_parts

        measures = int(length_parts[0])
        beats = int(length_parts[1])
        subdivs = int(length_parts[2])
        target_measure = f"{curr_measure_num + measures}:{beats},{subdivs}"
        end_time = position_to_time(target_measure, project)
        return max(end_time - start_time, 0.1)
    except Exception as e:
        raise ValueError(f"Failed to convert measure length: {e}") from e


def resolve_start(
    start_time: float | None, start_measure: str | None, project=None
) -> tuple[float, str]:
    """Resolve either ``start_time`` or ``start_measure`` to ``(seconds, measure_str)``.

    Raises ``ValueError`` if neither is provided.
    """
    if start_time is not None:
        t = float(start_time)
        return t, time_to_measure(t, project)
    if start_measure is not None:
        t = position_to_time(start_measure, project)
        return t, start_measure
    raise ValueError("Either start_time or start_measure must be provided")


def resolve_length(
    length_time: float | None,
    length_measure: str | None,
    start_seconds: float,
    project=None,
) -> tuple[float, str]:
    """Resolve either ``length_time`` (seconds) or ``length_measure`` (M:B,F) to seconds.

    Returns ``(length_seconds, end_measure_str)``. Raises on invalid input.
    """
    if length_time is not None:
        length = float(length_time)
        if length <= 0:
            raise ValueError("Length must be greater than zero")
        return length, time_to_measure(start_seconds + length, project)
    if length_measure is not None:
        lm = length_measure.strip()
        if lm in ("0:0,0", "0:0.0"):
            raise ValueError("Invalid length_measure: zero length specified")
        # Normalize "M:0,0" to "M+1:1,0" (an off-by-one convenience from upstream)
        if ":0,0" in lm or ":0.0" in lm:
            try:
                m = int(lm.split(":")[0])
                length_measure = f"{m}:1,0"
            except Exception as e:
                raise ValueError(f"Invalid length_measure format: {length_measure}") from e
        length = measure_length_to_time(length_measure, start_seconds, project)
        if length <= 0:
            raise ValueError("Length must be greater than zero")
        return length, time_to_measure(start_seconds + length, project)
    raise ValueError("Either length_time or length_measure must be provided")
