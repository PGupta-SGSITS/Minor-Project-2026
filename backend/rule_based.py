# ═══════════════════════════════════════════════════════════════
# HeartWatch AI — Rule-Based Arrhythmia Detector
# ═══════════════════════════════════════════════════════════════
# WHY this file exists:
# ML models can fail on noisy real-world sensor data.
# This rule-based detector uses simple clinical thresholds
# that are ALWAYS reliable. It acts as a safety net.
#
# Rules are based on standard cardiology guidelines:
# - Normal resting HR: 60-100 BPM
# - Bradycardia: < 50 BPM (heart too slow)
# - Tachycardia: > 100 BPM (heart too fast)
# - Irregular rhythm: RR intervals vary too much
# ═══════════════════════════════════════════════════════════════

import numpy as np
from config import (
    MIN_BPM, MAX_BPM, BRADYCARDIA_BPM, TACHYCARDIA_BPM,
    RR_IRREGULARITY_THRESHOLD, MISSED_BEAT_FACTOR
)

def rule_based_predict(bpm, rr_intervals):
    """
    Detect arrhythmia using simple medical thresholds.

    Args:
        bpm: calculated heart rate (beats per minute)
        rr_intervals: list of time gaps between consecutive beats (seconds)

    Returns:
        dict with:
            - label: "Normal" or "Abnormal"
            - reasons: list of strings explaining WHY it's abnormal
    """
    reasons = []

    # ── Rule 1: Bradycardia (heart too slow) ──
    # Below 50 BPM at rest = heart isn't pumping enough
    if bpm < BRADYCARDIA_BPM:
        reasons.append(f"Bradycardia (BPM={bpm:.0f} < {BRADYCARDIA_BPM})")

    # ── Rule 2: Tachycardia (heart too fast) ──
    # Above 100 BPM at rest = heart is overworking
    elif bpm > TACHYCARDIA_BPM:
        reasons.append(f"Tachycardia (BPM={bpm:.0f} > {TACHYCARDIA_BPM})")

    # ── Rule 3: Physiologically impossible ──
    # Below 30 or above 220 = almost certainly sensor noise
    if bpm < MIN_BPM or bpm > MAX_BPM:
        reasons.append(f"BPM out of physiological range ({bpm:.0f})")

    # ── Rule 4: Irregular rhythm (RR variability) ──
    # Coefficient of Variation (CV) = std / mean
    # CV > 20% means beats are unevenly spaced = possible arrhythmia
    if len(rr_intervals) >= 3:
        rr = np.array(rr_intervals)
        rr_cv = np.std(rr) / (np.mean(rr) + 1e-8)  # +1e-8 prevents divide by zero
        if rr_cv > RR_IRREGULARITY_THRESHOLD:
            reasons.append(f"Irregular RR intervals (CV={rr_cv:.2f})")

    # ── Rule 5: Missed beats ──
    # If one gap is 1.5x longer than the median, a beat was likely skipped
    if len(rr_intervals) >= 3:
        median_rr = np.median(rr_intervals)
        long_pauses = sum(1 for rr in rr_intervals if rr > MISSED_BEAT_FACTOR * median_rr)
        if long_pauses > 0:
            reasons.append(f"Possible missed beats ({long_pauses} long pauses)")

    # ── Final Decision ──
    if reasons:
        return {"label": "Abnormal", "reasons": reasons}
    else:
        return {"label": "Normal", "reasons": ["All parameters within normal range"]}