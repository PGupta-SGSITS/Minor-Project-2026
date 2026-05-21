# ═══════════════════════════════════════════════════════════════
# HeartWatch AI — Configuration Constants
# ═══════════════════════════════════════════════════════════════
# WHY this file exists:
# All numbers/thresholds in ONE place. If you need to change
# sampling rate or BPM threshold, change HERE — not in 10 files.
# ═══════════════════════════════════════════════════════════════

# ── ECG Sampling ──
# ESP32 reads the AD8232 sensor at this rate.
# 250 Hz = 250 readings per second = medical standard for ECG.
SAMPLE_RATE = 250

# How many samples to keep in memory at once.
# 2500 samples ÷ 250 Hz = 10 seconds of ECG data visible.
WINDOW_SIZE = 2500

# ── BPM Thresholds ──
# Normal resting heart rate = 60-100 BPM.
# Below 30 or above 220 = probably sensor noise, not real heartbeat.
MIN_BPM = 30
MAX_BPM = 220

# Clinical thresholds for flagging abnormal rhythm:
BRADYCARDIA_BPM = 50    # Heart beating too SLOW
TACHYCARDIA_BPM = 100   # Heart beating too FAST

# ── ML Model ──
# If ML model is less than 65% sure, we don't trust it.
# We fall back to rule-based detection instead.
ML_CONFIDENCE_THRESHOLD = 0.65

# Path to the trained model file (created in Google Colab).
MODEL_PATH = "models/rf_model.pkl"

# ── Rule-Based Detection ──
# Coefficient of Variation (CV) of RR intervals.
# CV > 20% means heartbeats are irregularly spaced = possible arrhythmia.
RR_IRREGULARITY_THRESHOLD = 0.20

# If one RR gap is 1.5x longer than the median, it might be a missed beat.
MISSED_BEAT_FACTOR = 1.5
# ── Signal Quality ──
# If the signal barely changes (std < 10), electrodes are probably off.
MIN_SIGNAL_STD = 10

# ESP32 ADC max = 4095. If signal is stuck near max, it's saturated (bad).
SATURATION_THRESHOLD = 4090
SATURATION_RATIO = 0.5  # More than 50% of samples saturated = reject signal

# ── Server ──
SERVER_HOST = "0.0.0.0"    # Listen on all network interfaces
SERVER_PORT = 8000          # http://localhost:8000
WS_UPDATE_INTERVAL = 0.2   # Send update to browser every 0.2 sec (5 times/sec)
MIN_BUFFER_SECONDS = 2     # Need at least 2 sec of data before we start analysis
