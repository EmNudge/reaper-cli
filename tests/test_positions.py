"""Tests for utils/positions.py — the M:B,F ↔ seconds converter.

The conversions rely on REAPER's TimeMap functions to handle the time map
correctly, but the math (measure/beat indexing, time-signature scaling, the
``M:B,F`` parser, the ``resolve_*`` helpers) is pure Python. We stub the RPR
calls with a fixed-time-signature, fixed-BPM model so the math is testable.
"""

from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _restore_reapy_modules():
    """Undo the ``sys.modules`` clobbering ``_install_stubs`` does.

    These tests replace the real ``reapy`` package with a fake module to model a
    fixed-tempo project. Without restoring afterward the fake leaks into every
    later test in the session (it is not a real package, so anything importing
    ``reapy.tools`` / ``reapy.is_inside_reaper`` then breaks).
    """
    keys = ("reapy", "reapy.reascript_api", "reaper_mcp.utils.positions")
    saved = {k: sys.modules.get(k) for k in keys}
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

# ---------- RPR / reapy stubs (installed before importing positions) ----------


class _FakeProject:
    id = 0xDEADBEEF


def _install_stubs(num: int, denom: int, bpm: float = 120.0) -> None:
    """Install fake reapy + RPR modules that model a fixed-sig project.

    QN-to-time uses ``60 / bpm`` seconds per quarter note (constant tempo).
    Time-sig is constant ``num/denom`` everywhere.
    """
    sec_per_qn = 60.0 / bpm

    fake_reapy = types.ModuleType("reapy")
    fake_reapy.Project = lambda: _FakeProject()  # type: ignore[attr-defined]

    fake_api = types.ModuleType("reapy.reascript_api")

    def time_map_get_sig(_proj_id, time, _a, _b, _c):
        # Mirror the [proj_id, time, num, denom, bpm] tuple shape the real
        # binding returns. The code reads result[2] and result[3].
        return (_proj_id, time, num, denom, bpm)

    def qn_to_time(_proj_id, qn):
        return float(qn) * sec_per_qn

    def time_to_qn(_proj_id, time):
        return float(time) / sec_per_qn

    fake_api.TimeMap_GetTimeSigAtTime = time_map_get_sig
    fake_api.TimeMap2_QNToTime = qn_to_time
    fake_api.TimeMap2_timeToQN = time_to_qn

    fake_reapy_api_pkg = types.ModuleType("reapy.reascript_api")
    fake_reapy_api_pkg.__dict__.update(fake_api.__dict__)

    sys.modules["reapy"] = fake_reapy
    sys.modules["reapy.reascript_api"] = fake_api


def _clear_positions_cache() -> None:
    sys.modules.pop("reaper_mcp.utils.positions", None)


# ---------- 4/4 — the original baseline ----------


def test_position_to_time_4_4_origin():
    _install_stubs(4, 4, bpm=120.0)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import position_to_time

    assert position_to_time("1:1,000") == pytest.approx(0.0)


def test_position_to_time_4_4_one_measure():
    _install_stubs(4, 4, bpm=120.0)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import position_to_time

    # 4 QN at 120 BPM = 2.0 seconds.
    assert position_to_time("2:1,000") == pytest.approx(2.0)


def test_round_trip_4_4_midway():
    _install_stubs(4, 4, bpm=120.0)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import position_to_time, time_to_measure

    t = position_to_time("3:2,500")
    assert time_to_measure(t) == "3:2,500"


# ---------- 3/4 — exercises the time-sig fix ----------


def test_position_to_time_3_4_one_measure():
    _install_stubs(3, 4, bpm=120.0)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import position_to_time

    # In 3/4 at 120 BPM, one measure = 3 quarter notes = 1.5 seconds.
    # The previous implementation hardcoded 4 QN/measure and would return 2.0s.
    assert position_to_time("2:1,000") == pytest.approx(1.5)


def test_time_to_measure_3_4_inverse():
    _install_stubs(3, 4, bpm=120.0)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import time_to_measure

    # 3 quarter notes (one measure of 3/4) at 120 BPM = 1.5s → start of measure 2.
    assert time_to_measure(1.5) == "2:1,000"


# ---------- 6/8 — denominator != 4 ----------


def test_position_to_time_6_8_one_measure():
    _install_stubs(6, 8, bpm=120.0)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import position_to_time

    # In 6/8: beat = 8th note = 0.5 QN. 6 beats per measure = 3 QN.
    # At 120 BPM, 3 QN = 1.5 seconds.
    assert position_to_time("2:1,000") == pytest.approx(1.5)


def test_position_to_time_6_8_third_beat():
    _install_stubs(6, 8, bpm=120.0)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import position_to_time

    # Beat 3 in measure 1 = 2 eighth-notes in = 1 QN = 0.5s at 120 BPM.
    assert position_to_time("1:3,000") == pytest.approx(0.5)


def test_round_trip_6_8():
    _install_stubs(6, 8, bpm=120.0)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import position_to_time, time_to_measure

    for pos in ("1:1,000", "1:4,500", "2:2,250", "3:6,000"):
        assert time_to_measure(position_to_time(pos)) == pos


# ---------- format_time_signature + get_time_map_info ----------


def test_format_time_signature_reads_stub():
    _install_stubs(7, 8, bpm=140.0)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import format_time_signature

    assert format_time_signature() == "7/8"


def test_get_time_map_info_returns_bpm():
    _install_stubs(4, 4, bpm=137.5)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import get_time_map_info

    info = get_time_map_info()
    assert info["bpm"] == pytest.approx(137.5)
    assert info["time_sig_num"] == 4
    assert info["time_sig_den"] == 4


# ---------- resolve_start / resolve_length ----------


def test_resolve_start_from_time():
    _install_stubs(4, 4, bpm=120.0)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import resolve_start

    t, m = resolve_start(start_time=2.0, start_measure=None)
    assert t == 2.0
    assert m == "2:1,000"


def test_resolve_start_from_measure():
    _install_stubs(4, 4, bpm=120.0)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import resolve_start

    t, m = resolve_start(start_time=None, start_measure="3:1,000")
    assert t == pytest.approx(4.0)  # 8 QN at 120 BPM
    assert m == "3:1,000"


def test_resolve_start_requires_one():
    _install_stubs(4, 4)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import resolve_start

    with pytest.raises(ValueError):
        resolve_start(None, None)


def test_resolve_length_seconds():
    _install_stubs(4, 4, bpm=120.0)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import resolve_length

    length, end_m = resolve_length(length_time=1.0, length_measure=None, start_seconds=0.0)
    assert length == 1.0
    assert end_m == "1:3,000"  # 2 QN in at 120 BPM = beat 3 of measure 1


def test_resolve_length_rejects_zero():
    _install_stubs(4, 4)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import resolve_length

    with pytest.raises(ValueError):
        resolve_length(length_time=None, length_measure="0:0,0", start_seconds=0.0)


# ---------- bad input ----------


def test_position_to_time_passes_float_through():
    _install_stubs(4, 4)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import position_to_time

    assert position_to_time(3.14) == 3.14


def test_position_to_time_rejects_garbage_format():
    _install_stubs(4, 4)
    _clear_positions_cache()
    from reaper_mcp.utils.positions import position_to_time

    with pytest.raises(ValueError):
        position_to_time("not-a-position-string-but-has-colon:")
