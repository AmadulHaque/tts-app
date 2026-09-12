"""Tests for audio_processor: silence insertion, concatenation, normalization."""

import numpy as np

from app.core import audio_processor as ap


def test_silence_length():
    s = ap.silence(1.0, sr=24000)
    assert len(s) == 24000
    assert not np.any(s)


def test_insert_silence_appends():
    a = np.ones(12000, dtype=np.float32)
    out = ap.insert_silence(a, 0.5, sr=24000)
    assert len(out) == 12000 + 12000
    assert np.all(out[:12000] == 1.0)
    assert np.all(out[12000:] == 0.0)


def test_build_audio_offsets_and_pauses():
    a1 = np.ones(24000, dtype=np.float32)      # 1 s
    a2 = np.ones(24000, dtype=np.float32)      # 1 s
    out, offsets = ap.build_audio([a1, a2], ["Alex", "Mia"],
                                  pause_between_lines=0.5, pause_between_speakers=0.8)
    # 1 + 0.8 + 1
    assert len(out) == int((1.0 + 0.8 + 1.0) * 24000)
    assert offsets[0] == (0.0, 1.0)
    assert offsets[1] == (1.0 + 0.8, 2.0 + 0.8)

    out_same, _ = ap.build_audio([a1, a2], ["Alex", "Alex"],
                                 pause_between_lines=0.5, pause_between_speakers=0.8)
    assert len(out_same) == int((1.0 + 0.5 + 1.0) * 24000)


def test_build_audio_per_line_override():
    a1 = np.ones(24000, dtype=np.float32)
    a2 = np.ones(24000, dtype=np.float32)
    # Override on line 0 replaces the pause *after* line 0.
    out, _ = ap.build_audio([a1, a2], ["Alex", "Mia"],
                            pause_between_lines=0.5, pause_between_speakers=0.8,
                            line_pause_overrides=[2.0, None])
    assert len(out) == int((1.0 + 2.0 + 1.0) * 24000)


def test_peak_normalize_to_target():
    a = np.array([0.1, -0.2, 0.4], dtype=np.float32)
    out = ap.peak_normalize(a, target_db=-1.0)
    expected_peak = 10 ** (-1.0 / 20.0)
    # The largest sample is scaled up to the target…
    assert abs(out.max() - expected_peak) < 1e-6
    # …and every other sample scales by the same factor (linear gain, no peak clipping).
    ratio = out[2] / a[2]
    assert abs(out[0] - a[0] * ratio) < 1e-6
    assert abs(out[1] - a[1] * ratio) < 1e-6
    assert out.max() <= 1.0


def test_peak_normalize_silence_unchanged():
    a = np.zeros(100, dtype=np.float32)
    out = ap.peak_normalize(a)
    assert np.all(out == 0.0)


def test_normalize_off_identity():
    a = np.array([0.5, -0.5], dtype=np.float32)
    assert np.array_equal(ap.normalize(a, "off"), a)


def test_concatenate():
    a = np.ones(3, dtype=np.float32)
    b = np.zeros(4, dtype=np.float32)
    out = ap.concatenate([a, b])
    assert len(out) == 7
    assert out.dtype == np.float32


def test_duration_seconds():
    assert ap.duration_seconds(np.zeros(48000), sr=24000) == 2.0
