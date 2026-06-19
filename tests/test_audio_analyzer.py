"""Tests for AudioAnalyzer — runs against generated WAV files.

We synthesize known signals (silence, a sine at known dBFS, a stereo file)
and assert the analyzer returns numbers in the expected ranges. This catches
regressions in the numeric pipeline.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import soundfile as sf

from reaper_mcp.offline_support.audio_analyzer import AudioAnalyzer

SR = 48000


def _write_wav(path, data, samplerate=SR):
    sf.write(str(path), data, samplerate)


# ---------- error handling ----------


def test_missing_file_returns_error(tmp_path):
    result = AudioAnalyzer(str(tmp_path / "nonexistent.wav")).analyze()
    assert result.error is not None
    assert "not found" in result.error.lower()


# ---------- level analysis ----------


def test_silence_has_minimum_levels(tmp_path):
    p = tmp_path / "silence.wav"
    _write_wav(p, np.zeros(SR))  # 1 second of silence
    result = AudioAnalyzer(str(p)).analyze()
    assert result.error is None
    assert result.level.peak_db == -math.inf
    assert result.level.rms_db == -math.inf
    assert result.level.clipping_detected is False


def test_sine_at_known_amplitude_reports_correct_peak(tmp_path):
    """A 440 Hz sine at 0.5 amplitude has peak = -6.02 dBFS."""
    p = tmp_path / "sine.wav"
    t = np.arange(SR) / SR
    data = 0.5 * np.sin(2 * np.pi * 440 * t)
    _write_wav(p, data)
    result = AudioAnalyzer(str(p)).analyze()
    assert result.error is None
    assert result.level.peak_db == pytest.approx(-6.02, abs=0.1)


def test_clipping_detected(tmp_path):
    """Samples at full scale should be flagged as clipped."""
    p = tmp_path / "clipped.wav"
    data = np.ones(SR) * 0.99999
    _write_wav(p, data)
    result = AudioAnalyzer(str(p)).analyze()
    assert result.level.clipping_detected is True
    assert result.level.clipped_samples_count > 0


def test_subclip_not_flagged(tmp_path):
    p = tmp_path / "loud_but_clean.wav"
    data = np.ones(SR) * 0.9  # well below 0.9999 threshold
    _write_wav(p, data)
    result = AudioAnalyzer(str(p)).analyze()
    assert result.level.clipping_detected is False


# ---------- stereo analysis ----------


def test_mono_file_marked_not_stereo(tmp_path):
    p = tmp_path / "mono.wav"
    _write_wav(p, np.zeros(SR))
    result = AudioAnalyzer(str(p)).analyze()
    assert result.stereo.is_stereo is False
    assert result.stereo.mono_compatible is True


def test_identical_L_R_is_mono_compatible(tmp_path):
    """L == R → correlation 1, width 0, mono-compatible."""
    p = tmp_path / "stereo_mono.wav"
    t = np.arange(SR) / SR
    sine = 0.3 * np.sin(2 * np.pi * 440 * t)
    data = np.column_stack([sine, sine])
    _write_wav(p, data)
    result = AudioAnalyzer(str(p)).analyze()
    assert result.stereo.is_stereo is True
    assert result.stereo.phase_coherence == pytest.approx(1.0, abs=0.001)
    assert result.stereo.stereo_width == pytest.approx(0.0, abs=0.001)
    assert result.stereo.mono_compatible is True


def test_inverted_L_R_is_not_mono_compatible(tmp_path):
    """L == -R → correlation -1, width 2, not mono-compatible (phase issue)."""
    p = tmp_path / "stereo_inverted.wav"
    t = np.arange(SR) / SR
    sine = 0.3 * np.sin(2 * np.pi * 440 * t)
    data = np.column_stack([sine, -sine])
    _write_wav(p, data)
    result = AudioAnalyzer(str(p)).analyze()
    assert result.stereo.phase_coherence == pytest.approx(-1.0, abs=0.001)
    assert result.stereo.mono_compatible is False


# ---------- warnings ----------


def test_clipping_produces_warning(tmp_path):
    p = tmp_path / "hot.wav"
    data = np.ones(SR) * 0.99999
    _write_wav(p, data)
    result = AudioAnalyzer(str(p)).analyze()
    assert any("clipping" in w.lower() for w in result.warnings)


def test_phase_issue_produces_warning(tmp_path):
    p = tmp_path / "phase.wav"
    t = np.arange(SR) / SR
    sine = 0.3 * np.sin(2 * np.pi * 440 * t)
    data = np.column_stack([sine, -sine])
    _write_wav(p, data)
    result = AudioAnalyzer(str(p)).analyze()
    assert any("phase" in w.lower() for w in result.warnings)


# ---------- frequency analysis ----------


def test_bass_sine_dominates_low_band(tmp_path):
    """A 100 Hz sine should have low_freq_energy > mid_freq_energy."""
    p = tmp_path / "bass.wav"
    t = np.arange(SR) / SR
    data = 0.5 * np.sin(2 * np.pi * 100 * t)
    _write_wav(p, data)
    result = AudioAnalyzer(str(p)).analyze()
    assert result.frequency.low_freq_energy_db > result.frequency.mid_freq_energy_db


def test_treble_sine_dominates_high_band(tmp_path):
    """A 8 kHz sine should have high_freq_energy > low_freq_energy."""
    p = tmp_path / "treble.wav"
    t = np.arange(SR) / SR
    data = 0.5 * np.sin(2 * np.pi * 8000 * t)
    _write_wav(p, data)
    result = AudioAnalyzer(str(p)).analyze()
    assert result.frequency.high_freq_energy_db > result.frequency.low_freq_energy_db
