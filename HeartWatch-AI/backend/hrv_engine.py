# FocusGuard AI — HRV Cognitive Load Engine
import numpy as np

# RMSSD zones (milliseconds) — based on published HRV research
# Higher RMSSD = more relaxed / recovered
# Lower RMSSD = more stressed / fatigued
RMSSD_FOCUSED   = 50   # ms — good cognitive state
RMSSD_FATIGUED  = 30   # ms — mental fatigue setting in
RMSSD_BURNOUT   = 20   # ms — needs immediate break

def classify_cognitive_load(rmssd_ms, pnn50, bpm, baseline_rmssd=None):
    """
    Classify cognitive/stress state from HRV metrics.

    Args:
        rmssd_ms: RMSSD in milliseconds (converted from seconds)
        pnn50: percentage of RR diffs > 50ms (0.0 to 1.0)
        bpm: current heart rate
        baseline_rmssd: user's personal resting RMSSD (from calibration)

    Returns:
        dict with label, fuel_level (0-100), color, and advice
    """
    reasons = []

    # If we have a personal baseline, use relative drop instead of fixed zones
    if baseline_rmssd and baseline_rmssd > 0:
        drop_pct = (baseline_rmssd - rmssd_ms) / baseline_rmssd
        if drop_pct > 0.40:
            label = "Burnout Risk"
            fuel  = max(5, int((1 - drop_pct) * 100))
            color = "red"
            reasons.append(f"RMSSD dropped {drop_pct*100:.0f}% from your baseline")
        elif drop_pct > 0.20:
            label = "Fatigued"
            fuel  = max(30, int((1 - drop_pct) * 100))
            color = "amber"
            reasons.append(f"RMSSD dropped {drop_pct*100:.0f}% from your baseline")
        else:
            label = "Focused"
            fuel  = min(100, int((1 - drop_pct/2) * 100))
            color = "green"
            reasons.append("RMSSD near your personal baseline")
    else:
        # Fallback: use absolute thresholds if no baseline yet
        if rmssd_ms < RMSSD_BURNOUT:
            label = "Burnout Risk"
            fuel  = 10
            color = "red"
            reasons.append(f"RMSSD critically low ({rmssd_ms:.1f}ms)")
        elif rmssd_ms < RMSSD_FATIGUED:
            label = "Fatigued"
            fuel  = 35
            color = "amber"
            reasons.append(f"RMSSD below fatigue threshold ({rmssd_ms:.1f}ms)")
        else:
            label = "Focused"
            fuel  = min(100, int(rmssd_ms))
            color = "green"
            reasons.append(f"RMSSD healthy ({rmssd_ms:.1f}ms)")

    # Extra signals
    if bpm > 90:
        reasons.append(f"Elevated HR ({bpm:.0f} BPM) — possible stress response")
    if pnn50 < 0.05:
        reasons.append("Low pNN50 — reduced beat-to-beat variation")

    return {
        "label":      label,
        "fuel_level": fuel,
        "color":      color,
        "rmssd_ms":   round(rmssd_ms, 1),
        "pnn50_pct":  round(pnn50 * 100, 1),
        "reasons":    reasons,
    }