"""Offline audio analysis — LUFS, peak/RMS, frequency bands, stereo width, dynamics (vendored from dschuler36)."""

import os

import numpy as np
import soundfile as sf

try:
    import pyloudnorm as pyln

    HAS_PYLOUDNORM = True
except ImportError:
    HAS_PYLOUDNORM = False

from .dataclasses import (
    AudioAnalysisResult,
    DynamicsAnalysis,
    FrequencyAnalysis,
    LevelAnalysis,
    StereoAnalysis,
)


class AudioAnalyzer:
    """Analyze a single audio file and produce mixing feedback."""

    def __init__(self, audio_path: str):
        self.audio_path = audio_path

    def analyze(self) -> AudioAnalysisResult:
        try:
            if not os.path.exists(self.audio_path):
                return self._empty_result(f"File not found: {self.audio_path}")
            data, sr = sf.read(self.audio_path, always_2d=True)
            duration = len(data) / sr
            channels = data.shape[1]

            level = self._analyze_levels(data, sr)
            freq = self._analyze_frequency(data, sr)
            stereo = self._analyze_stereo(data, sr)
            dynamics = self._analyze_dynamics(data, sr)
            warnings = self._generate_warnings(level, freq, stereo, dynamics)

            return AudioAnalysisResult(
                file_path=self.audio_path,
                sample_rate=sr,
                duration_seconds=duration,
                channels=channels,
                level=level,
                frequency=freq,
                stereo=stereo,
                dynamics=dynamics,
                warnings=warnings,
                error=None,
            )
        except sf.LibsndfileError as e:
            return self._empty_result(f"Corrupted or invalid audio file: {e}")
        except Exception as e:
            return self._empty_result(f"Analysis failed: {e}")

    def _empty_result(self, error: str) -> AudioAnalysisResult:
        return AudioAnalysisResult(
            file_path=self.audio_path,
            sample_rate=0,
            duration_seconds=0.0,
            channels=0,
            level=LevelAnalysis(0.0, 0.0, False, 0),
            frequency=FrequencyAnalysis(0.0, 0.0, 0.0, 0.0),
            stereo=StereoAnalysis(False, 0.0, 0.0, False),
            dynamics=DynamicsAnalysis(0.0, 0.0, 0.0),
            warnings=[],
            error=error,
        )

    def _analyze_levels(self, data: np.ndarray, sr: int) -> LevelAnalysis:
        # Peak / clipping must come from the original samples, not the mono
        # mean — for out-of-phase stereo (L = +x, R = -x), the mean is silent
        # while both channels clip.
        peak_linear = float(np.max(np.abs(data)))
        peak_db = self._linear_to_db(peak_linear) if peak_linear > 0 else -np.inf
        # RMS across all samples & channels (energy domain).
        rms_linear = float(np.sqrt(np.mean(data**2)))
        rms_db = self._linear_to_db(rms_linear) if rms_linear > 0 else -np.inf
        clipping_threshold = 0.9999
        clipped = int(np.sum(np.abs(data) >= clipping_threshold))
        return LevelAnalysis(
            peak_db=float(peak_db),
            rms_db=float(rms_db),
            clipping_detected=clipped > 0,
            clipped_samples_count=clipped,
        )

    def _analyze_frequency(self, data: np.ndarray, sr: int) -> FrequencyAnalysis:
        mono = np.mean(data, axis=1) if data.shape[1] > 1 else data[:, 0]
        fft = np.fft.rfft(mono)
        freqs = np.fft.rfftfreq(len(mono), 1 / sr)
        magnitude = np.maximum(np.abs(fft), 1e-10)
        spectral_centroid = np.sum(freqs * magnitude) / np.sum(magnitude)
        cumsum = np.cumsum(magnitude)
        rolloff_threshold = 0.85 * cumsum[-1]
        rolloff_idx = np.where(cumsum >= rolloff_threshold)[0]
        _ = freqs[rolloff_idx[0]] if len(rolloff_idx) > 0 else sr / 2

        def band_energy(lo: float, hi: float) -> float:
            mask = (freqs >= lo) & (freqs <= hi)
            band_mag = magnitude[mask]
            if len(band_mag) == 0:
                return -np.inf
            # band_mag is FFT magnitude (linear amplitude). band_mag**2 is
            # power per bin; mean(power) is mean power, which converts to dB
            # via 10·log10 — NOT 20·log10 (which would assume amplitude).
            mean_power = float(np.mean(band_mag**2))
            return 10.0 * float(np.log10(mean_power)) if mean_power > 0 else -np.inf

        return FrequencyAnalysis(
            spectral_centroid_hz=float(spectral_centroid),
            low_freq_energy_db=float(band_energy(20, 200)),
            mid_freq_energy_db=float(band_energy(200, 2000)),
            high_freq_energy_db=float(band_energy(2000, 20000)),
        )

    def _analyze_stereo(self, data: np.ndarray, sr: int) -> StereoAnalysis:
        is_stereo = data.shape[1] == 2
        if not is_stereo:
            return StereoAnalysis(False, 0.0, 1.0, True)
        L, R = data[:, 0], data[:, 1]
        if len(L) == 0 or len(R) == 0 or np.std(L) == 0 or np.std(R) == 0:
            # corrcoef is undefined (NaN) when either channel has zero variance
            # (silent / DC-only). Treat that case as "perfectly correlated" so
            # mono_compatible stays True and we don't emit a bogus phase warning.
            phase_coherence = 1.0
        else:
            phase_coherence = float(np.corrcoef(L, R)[0, 1])
        stereo_width = 1.0 - abs(phase_coherence)
        return StereoAnalysis(
            is_stereo=True,
            stereo_width=float(stereo_width),
            phase_coherence=phase_coherence,
            mono_compatible=phase_coherence > 0.5,
        )

    def _analyze_dynamics(self, data: np.ndarray, sr: int) -> DynamicsAnalysis:
        if HAS_PYLOUDNORM and len(data) > 0:
            try:
                meter = pyln.Meter(sr)
                lufs_integrated = meter.integrated_loudness(data)
            except Exception:
                lufs_integrated = -23.0
        else:
            lufs_integrated = -23.0
        # True/sample peak and RMS computed across all channels — see
        # `_analyze_levels` for the rationale (out-of-phase stereo cancels in
        # a mono mean and would falsely report "no peak / no clipping").
        # NOTE: this is sample peak, not ITU-R BS.1770 true peak (which would
        # need 4× oversampling); the field name is kept for API compatibility.
        peak_linear = float(np.max(np.abs(data)))
        true_peak_db = self._linear_to_db(peak_linear) if peak_linear > 0 else -np.inf
        rms_linear = float(np.sqrt(np.mean(data**2)))
        crest_db = self._linear_to_db(peak_linear / rms_linear) if rms_linear > 0 else 0.0
        return DynamicsAnalysis(
            lufs_integrated=float(lufs_integrated),
            true_peak_db=float(true_peak_db),
            crest_factor_db=float(crest_db),
        )

    def _generate_warnings(
        self,
        level: LevelAnalysis,
        frequency: FrequencyAnalysis,
        stereo: StereoAnalysis,
        dynamics: DynamicsAnalysis,
    ) -> list[str]:
        warnings: list[str] = []
        if level.peak_db > -0.3:
            warnings.append(f"Peak level very hot: {level.peak_db:.1f} dBFS (risk of clipping)")
        if level.clipping_detected:
            warnings.append(f"Clipping detected: {level.clipped_samples_count} clipped samples")
        if frequency.low_freq_energy_db > -6.0:
            warnings.append(
                f"Excessive low frequency energy: {frequency.low_freq_energy_db:.1f} dB (muddy mix)"
            )
        if frequency.spectral_centroid_hz < 500:
            warnings.append(
                f"Spectral centroid very low: {frequency.spectral_centroid_hz:.0f} Hz (dark mix)"
            )
        if stereo.is_stereo and not stereo.mono_compatible:
            warnings.append(
                f"Phase issues (coherence: {stereo.phase_coherence:.2f}); may cancel in mono"
            )
        if stereo.is_stereo and stereo.stereo_width < 0.1:
            warnings.append(f"Narrow stereo image (width: {stereo.stereo_width:.2f}); mostly mono")
        if dynamics.lufs_integrated > -8.0:
            warnings.append(
                f"Very loud for streaming: {dynamics.lufs_integrated:.1f} LUFS (target -14 for Spotify)"
            )
        if dynamics.crest_factor_db < 6.0:
            warnings.append(
                f"Low crest factor: {dynamics.crest_factor_db:.1f} dB (possibly over-compressed)"
            )
        return warnings

    @staticmethod
    def _linear_to_db(linear_value: float) -> float:
        if linear_value <= 0:
            return -np.inf
        return 20 * np.log10(linear_value)
