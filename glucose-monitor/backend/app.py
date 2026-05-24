from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import logging

from ppg_extraction import (
    extract_frames,
    extract_ppg_signal,
    remove_motion_artifacts,
    adaptive_bandpass_filter,
    smooth_signal,
    normalize_signal,
    detect_peaks,
    calculate_heart_rate,
    generate_plot_base64,
    assess_signal_quality,
    SignalQuality,
    DEFAULT_FPS
)

from lstm_model import predict_glucose
from database import create_table, add_user, validate_user

logger = logging.getLogger(__name__)

# -------------------------------
# 🔥 INIT APP
# -------------------------------
app = Flask(__name__)
CORS(app)

# 🔥 FIX 413 ERROR (increase upload limit)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize DB
create_table()

# ===============================
# Validation Constants
# ===============================
MIN_VIDEO_DURATION_SEC = 3.0    # Reject videos shorter than 3 seconds
MIN_FRAMES_REQUIRED = 45       # Absolute minimum frames needed
LOW_FPS_THRESHOLD = 10         # Warn if effective FPS < 10

# -------------------------------
# HOME
# -------------------------------
@app.route("/")
def home():
    return "🚀 Glucose Monitoring API Running"

# -------------------------------
# SIGNUP
# -------------------------------
@app.route("/signup", methods=["POST"])
def signup():
    data = request.json

    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Missing fields"}), 400

    if add_user(email, password):
        return jsonify({"message": "User created successfully"})
    else:
        return jsonify({"error": "User already exists"}), 400

# -------------------------------
# LOGIN
# -------------------------------
@app.route("/login", methods=["POST"])
def login():
    data = request.json

    email = data.get("email")
    password = data.get("password")

    if validate_user(email, password):
        return jsonify({"message": "Login successful"})
    else:
        return jsonify({"error": "Invalid credentials"}), 401

# -------------------------------
# 🔥 PREDICT API
# -------------------------------
@app.route("/predict", methods=["POST"])
def predict():

    if "video" not in request.files:
        return jsonify({"error": "No video uploaded"}), 400

    video = request.files["video"]

    if video.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    video_path = os.path.join(UPLOAD_FOLDER, video.filename)
    video.save(video_path)

    try:
        warnings = []

        # -------------------------------
        # EXTRACT FRAMES (with effective FPS)
        # -------------------------------
        frames, effective_fps = extract_frames(video_path)

        if len(frames) == 0:
            return jsonify({"error": "Could not read video. The file may be corrupted or in an unsupported format."}), 400

        # -------------------------------
        # VIDEO DURATION VALIDATION
        # -------------------------------
        duration_sec = len(frames) / effective_fps if effective_fps > 0 else 0

        if len(frames) < MIN_FRAMES_REQUIRED:
            return jsonify({
                "error": f"Video too short ({len(frames)} frames). Please record at least {MIN_VIDEO_DURATION_SEC:.0f} seconds of video."
            }), 400

        if duration_sec < MIN_VIDEO_DURATION_SEC:
            return jsonify({
                "error": f"Video too short ({duration_sec:.1f}s). Please record at least {MIN_VIDEO_DURATION_SEC:.0f} seconds of video."
            }), 400

        if effective_fps < LOW_FPS_THRESHOLD:
            warnings.append(f"Low video frame rate ({effective_fps:.0f} FPS). Results may be less accurate.")

        # -------------------------------
        # PROCESS PPG SIGNAL (pass FPS)
        # -------------------------------
        signal = extract_ppg_signal(frames)
        signal = remove_motion_artifacts(signal, fps=effective_fps)
        signal = adaptive_bandpass_filter(signal, fps=effective_fps)
        signal = smooth_signal(signal)
        signal = normalize_signal(signal)

        # -------------------------------
        # SIGNAL QUALITY ASSESSMENT
        # -------------------------------
        diagnostics = assess_signal_quality(signal, fps=effective_fps)
        signal_quality = diagnostics.quality.value

        if diagnostics.quality == SignalQuality.UNUSABLE:
            warnings.append("Signal quality is very poor. Please ensure your fingertip covers the camera lens with the flash ON.")
        elif diagnostics.quality == SignalQuality.POOR:
            warnings.append("Signal quality is low. Try recording with better lighting and steady finger pressure.")

        if diagnostics.is_flatline:
            warnings.append("The signal appears flat — the camera may not be detecting blood flow. Ensure your finger fully covers the lens.")

        if diagnostics.is_saturated:
            warnings.append("Signal saturation detected. Try reducing camera exposure or pressing slightly lighter.")

        if diagnostics.motion_artifact_ratio > 0.15:
            warnings.append("Significant motion artifacts detected. Please hold your finger steady during recording.")

        # Add any notes from diagnostics
        for note in diagnostics.notes:
            if note not in warnings:
                logger.info(f"Signal note: {note}")

        # -------------------------------
        # HEART RATE (with spectral fallback)
        # -------------------------------
        peaks = detect_peaks(signal, fps=effective_fps)
        heart_rate = calculate_heart_rate(
            peaks, len(frames), fps=effective_fps, signal=signal
        )

        if heart_rate == 0:
            warnings.append("Heart rate could not be detected. The video may not contain a clear PPG signal from the fingertip.")

        # -------------------------------
        # GLUCOSE PREDICTION
        # -------------------------------
        glucose = predict_glucose(signal)

        # -------------------------------
        # GRAPH (with peaks, HR, quality)
        # -------------------------------
        graph = generate_plot_base64(
            signal, peaks=peaks, heart_rate=heart_rate if heart_rate > 0 else None,
            quality=diagnostics.quality
        )

        # -------------------------------
        # FINAL RESPONSE
        # -------------------------------
        return jsonify({
            "heart_rate": round(heart_rate, 2),
            "glucose": round(glucose, 2),
            "status": "Experimental AI Prediction",
            "graph": graph,
            "signal_quality": signal_quality,
            "warnings": warnings,
        })

    except Exception as e:
        logger.exception(f"Prediction failed: {e}")
        return jsonify({"error": str(e)}), 500

    finally:
        # 🔥 DELETE VIDEO AFTER PROCESSING
        if os.path.exists(video_path):
            os.remove(video_path)

# -------------------------------
# RUN
# -------------------------------
if __name__ == "__main__":
    app.run(debug=True)