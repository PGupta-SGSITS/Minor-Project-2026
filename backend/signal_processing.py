# ═══════════════════════════════════════════════════════════════
# FocusGuard AI — Signal Processing Pipeline v2
# 
# WHAT CHANGED FROM v1:
#  1. detect_r_peaks: threshold dropped from 85th to 75th percentile
#  2. detect_r_peaks: min_distance increased from 0.25s to 0.33s
#  3. calculate_rr_from_timestamps: uses real ESP32 millis() timestamps
#     instead of assuming perfect 250Hz delivery over WiFi
#  4. process_window: accepts optional timestamps array
# ═══════════════════════════════════════════════════════════════

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks


SAMPLE_RATE          = 250
MIN_BPM              = 40
MAX_BPM              = 180
MIN_SIGNAL_STD       = 10
SATURATION_THRESHOLD = 4080
SATURATION_RATIO     = 0.50


# ── Bandpass Filter ───────────────────────────────────────────
def bandpass_filter(signal, lowcut=0.5, highcut=45.0, fs=250, order=3):
    nyq  = 0.5 * fs
    b, a = butter(order, [lowcut / nyq, highcut / nyq], btype='band')
    return filtfilt(b, a, signal)


# ── R-Peak Detection ──────────────────────────────────────────
def detect_r_peaks(filtered_signal, fs=250):
    if len(filtered_signal) < int(0.8 * fs):
        return np.array([], dtype=int)

    # FIX: was int(0.25 * fs) = 62 samples.
    # 0.33s = 82 samples prevents the downslope of one R-peak
    # being mis-detected as a second peak (double-counting).
    min_distance = int(0.33 * fs)

    signal = filtered_signal
    if np.abs(np.min(signal)) > np.abs(np.max(signal)):
        signal = -signal

    std = np.std(signal)

    # FIX: was percentile(85) — too aggressive for AD8232 noise.
    # 75th percentile gives the detector enough room to catch
    # real R-peaks without triggering on baseline noise.
    threshold    = np.percentile(signal, 75)
    min_prom     = max(0.3 * std, 1.0)

    peaks, _ = find_peaks(
        signal,
        distance=min_distance,
        height=threshold,
        prominence=min_prom,
    )
    return peaks


# ── RR Intervals from real timestamps ────────────────────────
def calculate_rr_from_timestamps(peaks, timestamps_ms):
    """
    Use real ESP32 millis() timestamps instead of sample indices.
    This eliminates BPM error caused by WiFi packet jitter.
    
    Args:
        peaks: array of sample indices where R-peaks were found
        timestamps_ms: list of millis() values, one per sample
    
    Returns:
        list of RR intervals in seconds
    """
    if len(peaks) < 2 or timestamps_ms is None:
        return []

    ts = np.array(timestamps_ms)
    rr = []
    for i in range(1, len(peaks)):
        dt_ms = float(ts[peaks[i]] - ts[peaks[i - 1]])
        dt_s  = dt_ms / 1000.0
        # Only keep physiologically valid RR intervals
        if 60.0 / MAX_BPM <= dt_s <= 60.0 / MIN_BPM:
            rr.append(dt_s)
    return rr


# ── RR Intervals from sample indices (fallback) ───────────────
def calculate_rr_intervals(peaks, fs=250):
    if len(peaks) < 2:
        return []
    rr    = np.diff(peaks) / fs
    valid = rr[(rr >= 60.0 / MAX_BPM) & (rr <= 60.0 / MIN_BPM)]
    return valid.tolist()


# ── BPM from RR intervals ─────────────────────────────────────
def calculate_bpm(rr_intervals):
    if len(rr_intervals) == 0:
        return 0.0
    median_rr = np.median(rr_intervals)
    if median_rr <= 0:
        return 0.0
    bpm = 60.0 / median_rr
    return round(bpm, 1) if MIN_BPM <= bpm <= MAX_BPM else 0.0


# ── Signal Quality ────────────────────────────────────────────
def check_signal_quality(signal, fs=250):
    if len(signal) < fs:
        return False
    if np.std(signal) < MIN_SIGNAL_STD:
        return False
    arr = np.array(signal)
    if (np.mean(arr == 0) > SATURATION_RATIO or
            np.mean(arr >= SATURATION_THRESHOLD) > SATURATION_RATIO):
        return False
    return True


# ── HRV Feature Extraction ────────────────────────────────────
def extract_hrv_features(rr_intervals):
    """
    Compute HRV metrics used by FocusGuard cognitive load engine.
    
    Returns dict with:
      rmssd   — beat-to-beat variability (main stress indicator)
      pnn50   — % of RR diffs > 50ms (parasympathetic activity)
      sdnn    — overall HRV (standard deviation of RR)
      rr_mean — average RR interval
      bpm     — heart rate
    """
    rr = np.array(rr_intervals)
    if len(rr) < 2:
        return {k: 0.0 for k in
                ["rmssd", "pnn50", "sdnn", "rr_mean",
                 "rr_std", "rr_min", "rr_max", "rr_range",
                 "rr_median", "bpm", "num_peaks"]}

    successive_diffs = np.diff(rr)
    rmssd = float(np.sqrt(np.mean(successive_diffs ** 2))) * 1000  # ms
    pnn50 = float(np.mean(np.abs(successive_diffs) > 0.05))

    return {
        "rmssd":    round(rmssd, 2),   # milliseconds
        "pnn50":    round(pnn50 * 100, 1),  # percentage
        "sdnn":     round(float(np.std(rr)) * 1000, 2),  # ms
        "rr_mean":  round(float(np.mean(rr)), 4),
        "rr_std":   round(float(np.std(rr)), 4),
        "rr_min":   round(float(np.min(rr)), 4),
        "rr_max":   round(float(np.max(rr)), 4),
        "rr_range": round(float(np.max(rr) - np.min(rr)), 4),
        "rr_median":round(float(np.median(rr)), 4),
        "bpm":      calculate_bpm(rr_intervals),
        "num_peaks":len(rr) + 1,
    }


# ── Full Pipeline ─────────────────────────────────────────────
def process_window(raw_values, fs=250, timestamps_ms=None):
    """
    Main entry point. Called by the FastAPI server on every batch.

    Args:
        raw_values:    list of ADC integers (leads-off samples already removed)
        fs:            sample rate (default 250)
        timestamps_ms: optional list of ESP32 millis() values (same length as raw_values)

    Returns dict with filtered signal, peaks, RR intervals, BPM, HRV features.
    """
    signal = np.array(raw_values, dtype=float)
    signal = signal[np.isfinite(signal)]

    empty = {
        "filtered": [], "peaks": [], "rr_intervals": [],
        "bpm": 0.0, "features": {}, "quality_ok": False,
    }

    if len(signal) < fs:
        return empty

    quality_ok = check_signal_quality(signal, fs)
    filtered   = bandpass_filter(signal, fs=fs)
    peaks      = detect_r_peaks(filtered, fs=fs)

    # Use real timestamps when available, fall back to sample-index math
    if timestamps_ms is not None and len(timestamps_ms) == len(raw_values):
        rr = calculate_rr_from_timestamps(peaks, timestamps_ms)
    else:
        rr = calculate_rr_intervals(peaks, fs=fs)

    bpm      = calculate_bpm(rr)
    features = extract_hrv_features(rr)

    if quality_ok and (len(peaks) < 3 or len(rr) < 2 or bpm <= 0):
        quality_ok = False

    return {
        "filtered":    filtered.tolist(),
        "peaks":       peaks.tolist(),
        "rr_intervals":rr,
        "bpm":         bpm,
        "features":    features,
        "quality_ok":  quality_ok,
    }