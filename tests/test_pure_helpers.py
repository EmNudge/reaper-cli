"""Tests for pure helpers — no REAPER, no reapy."""

from __future__ import annotations

from reaper_mcp.offline_support.utils import remove_empty_strings
from reaper_mcp.utils.fx_params import resolve_fx_param_index
from reaper_mcp.utils.items import get_item_by_id_or_index
from reaper_mcp.utils.track_props import db_to_linear, linear_to_db

# ---------- db_to_linear / linear_to_db ----------


def test_db_to_linear_unity():
    """0 dB is unity gain (linear == 1.0)."""
    assert db_to_linear(0.0) == 1.0


def test_db_to_linear_minus_6db():
    """-6 dB is roughly half amplitude."""
    assert abs(db_to_linear(-6.0) - 0.5012) < 0.001


def test_db_to_linear_minus_inf_floor():
    """-150 dB and below is treated as silence (linear 0.0)."""
    assert db_to_linear(-150) == 0.0
    assert db_to_linear(-1000) == 0.0


def test_linear_to_db_inverse_of_db_to_linear():
    for db in (-60, -12, -6, 0, 6):
        round_trip = linear_to_db(db_to_linear(db))
        assert abs(round_trip - db) < 0.001


def test_linear_to_db_zero_returns_floor():
    assert linear_to_db(0.0) == -150.0
    assert linear_to_db(-0.5) == -150.0


# ---------- resolve_fx_param_index ----------


class _StubParam:
    def __init__(self, name):
        self.name = name


class _StubFX:
    def __init__(self, param_names):
        self.params = [_StubParam(n) for n in param_names]
        self.n_params = len(self.params)


def test_resolve_fx_param_index_by_int():
    fx = _StubFX(["Threshold", "Ratio", "Attack"])
    assert resolve_fx_param_index(fx, 0) == 0
    assert resolve_fx_param_index(fx, 2) == 2


def test_resolve_fx_param_index_by_name_exact():
    fx = _StubFX(["Threshold", "Ratio", "Attack"])
    assert resolve_fx_param_index(fx, "Ratio") == 1


def test_resolve_fx_param_index_by_name_case_insensitive():
    fx = _StubFX(["Threshold", "Ratio", "Attack"])
    assert resolve_fx_param_index(fx, "ratio") == 1
    assert resolve_fx_param_index(fx, "ATTACK") == 2


def test_resolve_fx_param_index_int_out_of_range():
    fx = _StubFX(["Threshold"])
    assert resolve_fx_param_index(fx, 5) == -1


def test_resolve_fx_param_index_unknown_name():
    fx = _StubFX(["Threshold"])
    assert resolve_fx_param_index(fx, "Nonexistent") == -1


def test_resolve_fx_param_index_int_as_string():
    """'1' should resolve to index 1 — the int() path comes first."""
    fx = _StubFX(["Threshold", "Ratio"])
    assert resolve_fx_param_index(fx, "1") == 1


# ---------- get_item_by_id_or_index ----------


class _StubItem:
    def __init__(self, item_id):
        self.id = item_id


class _StubTrack:
    def __init__(self, item_ids):
        self.items = [_StubItem(i) for i in item_ids]


def test_get_item_by_index():
    track = _StubTrack(["MediaItem*0xA", "MediaItem*0xB", "MediaItem*0xC"])
    assert get_item_by_id_or_index(track, 0).id == "MediaItem*0xA"
    assert get_item_by_id_or_index(track, 2).id == "MediaItem*0xC"


def test_get_item_by_pointer_string():
    track = _StubTrack(["MediaItem*0xA", "MediaItem*0xB"])
    found = get_item_by_id_or_index(track, "MediaItem*0xB")
    assert found is not None
    assert found.id == "MediaItem*0xB"


def test_get_item_index_out_of_range_returns_none():
    track = _StubTrack(["MediaItem*0xA"])
    assert get_item_by_id_or_index(track, 5) is None


def test_get_item_unknown_pointer_returns_none():
    track = _StubTrack(["MediaItem*0xA"])
    assert get_item_by_id_or_index(track, "MediaItem*0xZ") is None


def test_get_item_numeric_string_treated_as_index():
    track = _StubTrack(["MediaItem*0xA", "MediaItem*0xB"])
    found = get_item_by_id_or_index(track, "1")
    assert found is not None
    assert found.id == "MediaItem*0xB"


# ---------- _parse_chord (midi_notes) ----------


def test_parse_chord_major_triad():
    from reaper_mcp.tools.midi_notes import _parse_chord

    intervals, root = _parse_chord("C")
    assert intervals == [0, 4, 7]
    assert root == 0


def test_parse_chord_minor_triad():
    from reaper_mcp.tools.midi_notes import _parse_chord

    intervals, root = _parse_chord("Am")
    assert intervals == [0, 3, 7]
    assert root == 9  # A = 9 semitones from C


def test_parse_chord_min7():
    from reaper_mcp.tools.midi_notes import _parse_chord

    intervals, root = _parse_chord("Dm7")
    assert intervals == [0, 3, 7, 10]
    assert root == 2  # D


def test_parse_chord_dom7():
    from reaper_mcp.tools.midi_notes import _parse_chord

    intervals, root = _parse_chord("G7")
    assert intervals == [0, 4, 7, 10]
    assert root == 7


def test_parse_chord_sharp_root():
    from reaper_mcp.tools.midi_notes import _parse_chord

    intervals, root = _parse_chord("F#maj7")
    assert intervals == [0, 4, 7, 11]
    assert root == 6


def test_parse_chord_flat_root():
    from reaper_mcp.tools.midi_notes import _parse_chord

    intervals, root = _parse_chord("Bb")
    assert intervals == [0, 4, 7]
    assert root == 10


def test_parse_chord_unknown_quality_falls_back_to_major():
    from reaper_mcp.tools.midi_notes import _parse_chord

    intervals, _ = _parse_chord("Cxyz")
    assert intervals == [0, 4, 7]


# ---------- remove_empty_strings ----------


def test_remove_empty_strings_simple_dict():
    assert remove_empty_strings({"a": 1, "b": ""}) == {"a": 1}


def test_remove_empty_strings_keeps_zero_and_false():
    """Falsy non-string values must survive."""
    assert remove_empty_strings({"a": 0, "b": False, "c": ""}) == {"a": 0, "b": False}


def test_remove_empty_strings_recursive():
    assert remove_empty_strings({"a": {"b": "", "c": 1}, "d": ""}) == {"a": {"c": 1}}


def test_remove_empty_strings_drops_empty_lists():
    assert remove_empty_strings({"a": [], "b": [1]}) == {"b": [1]}


def test_remove_empty_strings_strips_empty_string_list_items():
    assert remove_empty_strings({"a": ["", "x", ""]}) == {"a": ["x"]}


def test_remove_empty_strings_keep_keys_preserves_empty():
    result = remove_empty_strings({"keep_me": "", "drop_me": ""}, keep_keys={"keep_me"})
    assert "keep_me" in result
    assert "drop_me" not in result
