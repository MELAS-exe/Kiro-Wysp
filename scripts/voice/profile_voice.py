"""Pitch and loudness profile of a speech clip, to compare voices: median F0, spread, voiced share, brightness."""

from __future__ import annotations

import sys

import numpy as np
import soundfile as sf


def profile(path: str, max_seconds: float = 30.0) -> dict:
    d, sr = sf.read(path, always_2d=True)
    x = d.mean(axis=1)[: int(sr * max_seconds)].astype(np.float64)
    if sr != 16000:  # cheap resample by decimation of an integer ratio is not exact: use linear interpolation
        n = int(len(x) * 16000 / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
        sr = 16000
    frame, hop = int(0.040 * sr), int(0.010 * sr)
    f0s, rms_all = [], []
    lo, hi = int(sr / 400), int(sr / 70)
    for i in range(0, len(x) - frame, hop):
        w = x[i : i + frame] * np.hanning(frame)
        rms = float(np.sqrt((w**2).mean()))
        rms_all.append(rms)
        if rms < 0.02:
            continue
        ac = np.correlate(w, w, mode="full")[frame - 1 :]
        ac /= ac[0] + 1e-9
        seg = ac[lo:hi]
        k = int(seg.argmax())
        if seg[k] > 0.45:
            f0s.append(sr / (lo + k))
    f0 = np.array(f0s)
    spec = np.abs(np.fft.rfft(x[: sr * 20] if len(x) > sr * 20 else x))
    freqs = np.fft.rfftfreq(len(x[: sr * 20] if len(x) > sr * 20 else x), 1 / sr)
    centroid = float((freqs * spec).sum() / (spec.sum() + 1e-9))
    return {
        "seconds": round(len(x) / sr, 1),
        "f0_median": round(float(np.median(f0)), 1) if f0.size else None,
        "f0_p10": round(float(np.percentile(f0, 10)), 1) if f0.size else None,
        "f0_p90": round(float(np.percentile(f0, 90)), 1) if f0.size else None,
        "voiced_share": round(len(f0) / max(1, len(rms_all)), 2),
        "centroid_hz": round(centroid),
    }


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(p, profile(p))
