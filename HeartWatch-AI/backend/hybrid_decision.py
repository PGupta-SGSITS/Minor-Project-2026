# ═══════════════════════════════════════════════════════════════
# HeartWatch AI — Hybrid Decision Module
# ═══════════════════════════════════════════════════════════════
# WHY this file exists:
# ML and rule-based detectors each have strengths/weaknesses.
# This module combines both into a FINAL decision using this logic:
#
# 1. Bad signal quality   → use rules only (ML can't work on garbage)
# 2. ML model not loaded  → use rules only (graceful fallback)
# 3. ML confidence < 65%  → use rules only (ML is unsure)
# 4. Both agree           → use that answer (high confidence)
# 5. They disagree        → trust rules (rules are clinically reliable)
# ═══════════════════════════════════════════════════════════════

from config import ML_CONFIDENCE_THRESHOLD


def hybrid_predict(ml_result, rule_result, signal_quality):
    """
    Combine ML prediction + rule-based prediction into a final decision.

    Args:
        ml_result: dict from MLPredictor.predict()
            {"label": "Normal"/"Abnormal", "confidence": 0.92, "available": True}
        rule_result: dict from rule_based_predict()
            {"label": "Normal"/"Abnormal", "reasons": [...]}
        signal_quality: bool from check_signal_quality()

    Returns:
        dict with:
            - final_label: "Normal" or "Abnormal"
            - source: which detector was trusted
            - ml_label, rule_label: individual predictions
            - ml_confidence: ML's confidence level
            - reasons: explanation of why this decision was made
    """
    result = {
        "ml_label": ml_result.get("label", "Unknown"),
        "ml_confidence": ml_result.get("confidence", 0.0),
        "ml_available": ml_result.get("available", False),
        "rule_label": rule_result.get("label", "Unknown"),
        "rule_reasons": rule_result.get("reasons", []),
        "signal_quality": signal_quality,
    }

    # ── Case 1: Bad signal quality ──
    # If electrodes are off or signal is garbage, ML features are meaningless.
    # Only rules (BPM thresholds) can still give useful info.
    if not signal_quality:
        result["final_label"] = rule_result["label"]
        result["source"] = "rules_only"
        result["reasons"] = ["Poor signal quality - using rules only"]
        return result

    # ── Case 2: ML model not available ──
    # Model file missing or failed to load. System still works via rules.
    if not ml_result.get("available", False):
        result["final_label"] = rule_result["label"]
        result["source"] = "rules_only"
        result["reasons"] = ["ML model not available - using rules only"]
        return result

    # ── Case 3: ML confidence too low ──
    # Model is loaded but unsure (< 65%). Don't trust an uncertain model.
    ml_conf = ml_result.get("confidence", 0.0)
    if ml_conf < ML_CONFIDENCE_THRESHOLD:
        result["final_label"] = rule_result["label"]
        result["source"] = "rules_low_confidence"
        result["reasons"] = [f"ML confidence too low ({ml_conf:.1%}) - using rules"]
        return result

    # ── Case 4: Both agree ──
    # Best case — ML and rules say the same thing. High reliability.
    if ml_result["label"] == rule_result["label"]:
        result["final_label"] = ml_result["label"]
        result["source"] = "both_agree"
        result["reasons"] = ["ML and rules agree"]
        return result

    # ── Case 5: They disagree ──
    # ML says one thing, rules say another.
    # In medical context: trust rules (clinically validated thresholds).
    # Exception: if ML is VERY confident (>90%), consider it.
    if ml_conf > 0.90 and ml_result["label"] == "Abnormal":
        # ML is very confident it's abnormal — take it seriously
        result["final_label"] = "Abnormal"
        result["source"] = "ml_high_confidence"
        result["reasons"] = [
            f"ML strongly predicts Abnormal ({ml_conf:.1%})",
            f"Rules say: {rule_result['label']}",
            "Trusting ML due to high confidence on Abnormal"
        ]
        return result

    # Default: trust rules when in doubt
    result["final_label"] = rule_result["label"]
    result["source"] = "rules_override"
    result["reasons"] = [
        f"ML says {ml_result['label']} ({ml_conf:.1%})",
        f"Rules say {rule_result['label']}",
        "Trusting rules (clinically validated)"
    ]
    return result
