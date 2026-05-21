# ═══════════════════════════════════════════════════════════════
# HeartWatch AI — ML Predictor (Local Inference)
# ═══════════════════════════════════════════════════════════════
# WHY this file exists:
# The model was trained on Google Colab and saved as rf_model.pkl.
# This file LOADS that model and uses it to predict on new ECG data.
# No training happens here — only prediction (inference).
# ═══════════════════════════════════════════════════════════════

import pickle
import numpy as np
import os
from config import MODEL_PATH, ML_CONFIDENCE_THRESHOLD


class MLPredictor:
    """
    Loads the trained Random Forest model and predicts Normal/Abnormal.

    Usage:
        predictor = MLPredictor()
        result = predictor.predict(features_dict)
        # result = {"label": "Abnormal", "confidence": 0.87, "available": True}
    """

    def __init__(self):
        self.model = None
        self.feature_names = None
        self.available = False
        self._load_model()

    def _load_model(self):
        """Try to load the .pkl model file."""
        # Build the absolute path to the model
        base_dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.join(base_dir, MODEL_PATH)

        if not os.path.exists(model_path):
            print(f"WARNING: ML model not found at {model_path}")
            print("  System will use rule-based detection only.")
            return

        try:
            with open(model_path, "rb") as f:
                data = pickle.load(f)

            self.model = data["model"]
            self.feature_names = data["feature_names"]
            self.available = True

            acc = data.get("accuracy", 0)
            name = data.get("model_name", "Unknown")
            print(f"SUCCESS: ML model loaded: {name} (accuracy: {acc*100:.1f}%)")

        except Exception as e:
            print(f"WARNING: Failed to load model: {e}")
            self.available = False

    def predict(self, features_dict):
        """
        Predict Normal/Abnormal from extracted features.

        Args:
            features_dict: dict with keys like 'rr_mean', 'rr_std', etc.
                          (output of signal_processing.extract_features)

        Returns:
            dict with:
                - label: "Normal" or "Abnormal"
                - confidence: 0.0 to 1.0 (how sure the model is)
                - available: True if model is loaded
        """
        if not self.available:
            return {
                "label": "Unknown",
                "confidence": 0.0,
                "available": False
            }

        try:
            # Build feature vector in the correct order
            # The model expects features in the same order it was trained
            feature_vector = []
            for name in self.feature_names:
                feature_vector.append(features_dict.get(name, 0.0))

            X = np.array([feature_vector])  # reshape to 2D (1 sample, N features)

            # Get prediction and probability
            prediction = self.model.predict(X)[0]           # 0 or 1
            probabilities = self.model.predict_proba(X)[0]  # [prob_normal, prob_abnormal]

            label = "Abnormal" if prediction == 1 else "Normal"
            confidence = float(max(probabilities))  # highest probability = confidence

            return {
                "label": label,
                "confidence": round(confidence, 3),
                "available": True
            }

        except Exception as e:
            print(f"WARNING: Prediction error: {e}")
            return {
                "label": "Unknown",
                "confidence": 0.0,
                "available": False
            }
