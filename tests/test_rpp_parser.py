"""Tests for the line-based RPP parser.

The parser is a stateful machine over 240 lines of mixed brackets and prefixes —
the most bug-prone code in the package. These tests pin its behavior against
a hand-written sample project.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reaper_mcp.offline_support.rpp_parser import RPPParser

FIXTURE = Path(__file__).parent / "fixtures" / "sample.RPP"


@pytest.fixture(scope="module")
def parsed():
    return RPPParser(str(FIXTURE)).project


def test_parses_project_name_from_filename(parsed):
    assert parsed.name == "sample"


def test_parses_tempo(parsed):
    assert parsed.tempo == 120.0


def test_parses_time_signature(parsed):
    assert parsed.time_signature == "4/4"


def test_parses_track_count(parsed):
    assert len(parsed.tracks) == 2


def test_parses_track_names(parsed):
    assert parsed.tracks[0].name == "Lead Vocal"
    assert parsed.tracks[1].name == "Drums"


def test_parses_volume_and_pan(parsed):
    assert parsed.tracks[0].volume == 1.0
    assert parsed.tracks[0].pan == 0.0
    assert parsed.tracks[1].volume == pytest.approx(0.85)
    assert parsed.tracks[1].pan == pytest.approx(-0.2)


def test_parses_mute_and_solo(parsed):
    assert parsed.tracks[0].mute is False
    assert parsed.tracks[0].solo is False
    assert parsed.tracks[1].mute is False
    assert parsed.tracks[1].solo is True


def test_parses_fx_chain(parsed):
    """The parser captures BYPASS lines only when they appear inside the
    enclosing <VST ... > block. BYPASS lines elsewhere in the FXCHAIN
    (which is the more common layout in real REAPER files) are silently
    dropped — a known limitation of the vendored upstream parser.
    """
    fx_chain = parsed.tracks[0].fx_chain
    assert len(fx_chain) == 2
    assert fx_chain[0].name == "VST: ReaEQ (Cockos)"
    assert fx_chain[0].bypassed is False
    assert fx_chain[1].name == "VST: ReaComp (Cockos)"
    assert fx_chain[1].bypassed is True


def test_track_without_fx_chain_has_empty_list(parsed):
    assert parsed.tracks[1].fx_chain == []


def test_parses_items(parsed):
    items = parsed.tracks[0].items
    assert len(items) == 2
    assert items[0].position == 0.0
    assert items[0].length == 5.5
    assert items[1].position == 5.5
    assert items[1].length == 3.25


def test_resolves_audio_filepaths_relative_to_rpp(parsed):
    """File paths in <SOURCE WAVE> blocks should be absolutized relative to the .RPP."""
    items = parsed.tracks[0].items
    fixtures_dir = FIXTURE.parent.resolve()
    assert items[0].audio_filepath == str(fixtures_dir / "vocal_take1.wav")
    assert items[1].audio_filepath == str(fixtures_dir / "vocal_take2.wav")


def test_track_without_items_has_empty_list(parsed):
    assert parsed.tracks[1].items == []


def test_encoded_param_truncation():
    """Very long encoded VST data should be truncated to keep the parsed
    structure compact, not silently dropped."""
    long_data = "A" * 2000  # > MAX_ENCODED_DATA_LENGTH (1024)
    rpp_text = (
        "TEMPO 120 4 4\n"
        "<TRACK\n"
        '  NAME "Test"\n'
        "  <FXCHAIN\n"
        '    <VST "VST: Big" big.vst3 0 "" 1\n'
        f"      {long_data}\n"
        "    >\n"
        "    BYPASS 0 0 0\n"
        "  >\n"
        ">\n"
    )
    fixture_dir = FIXTURE.parent
    test_file = fixture_dir / "_truncation_test.RPP"
    test_file.write_text(rpp_text)
    try:
        project = RPPParser(str(test_file)).project
        fx = project.tracks[0].fx_chain[0]
        assert "DATA_TRUNCATED" in fx.encoded_param
        assert "2000" in fx.encoded_param  # original size reported
    finally:
        test_file.unlink()
