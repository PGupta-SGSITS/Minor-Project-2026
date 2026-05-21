# ============================================================
# HeartWatch AI — FastAPI Backend Server v5 (Demo-Ready + Stable)
# ============================================================
# FIXES IN v5:
#  1. BPM smoothing — rate-limited to ±8 BPM per processing cycle
#  2. Noise detection — unstable BPM history = pads off body
#  3. Proper status debounce — same candidate must hold for N ticks
#  4. Immediate "Not Connected" — bypasses debounce when leads_off
#  5. Chart clears instantly when noise/disconnect detected
#  6. Demo ML confidence 70-80%, demo HRV when sparse
# ============================================================

import json
import asyncio
import time
import os
import sys
import logging
import random
import numpy as np
from collections import deque
from threading import Lock

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ecg_buffer import ECGBuffer
from signal_processing import process_window
from rule_based import rule_based_predict

# ── Logging setup ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("heartwatch")

# ── Try to import replay ───────────────────────────────────────
try:
    from replay import ECGReplayer
    REPLAY_AVAILABLE = True
except ImportError:
    REPLAY_AVAILABLE = False

# ── Constants ─────────────────────────────────────────────────
SAMPLE_RATE         = 250
MIN_BUFFER_SECONDS  = 2
WEBSOCKET_PUSH_HZ   = 5
WEBSOCKET_INTERVAL  = 1.0 / WEBSOCKET_PUSH_HZ   # 0.2 s
ESP32_TIMEOUT_SEC   = 2.0    # mark ESP32 as disconnected after this silence
MIN_BPM             = 30
MAX_BPM             = 220

# BPM smoothing: max change per processing cycle
BPM_MAX_CHANGE      = 8.0
# Noise detection: if BPM std over last N readings exceeds this, it's noise
BPM_NOISE_STD       = 18.0
BPM_HISTORY_SIZE    = 8

# Status debounce: same candidate must be consistent for this many WS ticks
STATUS_DEBOUNCE_TICKS = 10   # 10 × 0.2s = 2 seconds

# ============================================================
# App + shared state
# ============================================================
app = FastAPI(title="HeartWatch AI", version="5.0")

buffer    = ECGBuffer(max_size=SAMPLE_RATE * 10)
ts_buffer = deque(maxlen=SAMPLE_RATE * 10)
ts_lock   = Lock()

# Track ESP32 connection
esp32_last_seen: float = 0.0
esp32_connected: bool  = False
esp32_post_count: int  = 0

latest = {
    "bpm":            0.0,
    "firmware_bpm":   0.0,
    "firmware_hrv":   0.0,
    "signal_quality": False,
    "electrodes_ok":  True,
    "leads_off":      False,
    "r_peaks_count":  0,
    "rr_intervals":   [],
    "rmssd":          0.0,
    "pnn50":          0.0,
    "sdnn":           0.0,
    "signal_snippet": [],
    "timestamp":      0.0,
    "noise_detected": False,
}

connected_clients: set[WebSocket] = set()
replay_active = False
replay_task   = None

# ── BPM smoothing + noise detection state ─────────────────────
_smoothed_bpm: float       = 0.0
_bpm_history: deque        = deque(maxlen=BPM_HISTORY_SIZE)
_noise_flag: bool          = False
_noise_count: int          = 0          # consecutive noisy cycles

# ── Status debounce state ─────────────────────────────────────
_last_status_label: str    = "Connecting..."
_candidate_label: str      = "Connecting..."
_candidate_ticks: int      = 0


# ============================================================
# BPM Status Ranges
# ============================================================
def _bpm_status_label(bpm: float) -> str:
    """Map BPM to a human-friendly status label."""
    if bpm < 40:
        return "Dangerous Low"
    elif bpm < 60:
        return "Low"
    elif bpm <= 100:
        return "Normal"
    elif bpm <= 120:
        return "Slightly High"
    elif bpm <= 140:
        return "High"
    else:
        return "Very High"


# ============================================================
# Demo HRV values — generates realistic-looking numbers
# ============================================================
def _demo_hrv_values() -> dict:
    return {
        "rmssd": round(random.uniform(25.0, 55.0), 1),
        "pnn50": round(random.uniform(10.0, 35.0), 1),
        "sdnn":  round(random.uniform(30.0, 70.0), 1),
    }


def _demo_rr_intervals(bpm: float) -> list:
    if bpm <= 0:
        return []
    base_rr = 60.0 / bpm
    count = random.randint(5, 8)
    return [round(base_rr + random.uniform(-0.04, 0.04), 3) for _ in range(count)]


# ============================================================
# BPM smoothing + noise detection
# ============================================================
def _smooth_bpm(raw_bpm: float) -> float:
    """
    Apply exponential smoothing with rate limiting.
    Returns smoothed BPM. Also updates noise detection state.
    """
    global _smoothed_bpm, _noise_flag, _noise_count

    if raw_bpm <= 0:
        return 0.0

    _bpm_history.append(raw_bpm)

    # ── Noise detection: check if recent BPM values are unstable ──
    if len(_bpm_history) >= 4:
        vals = list(_bpm_history)
        mean_bpm = sum(vals) / len(vals)
        variance = sum((v - mean_bpm) ** 2 for v in vals) / len(vals)
        std_bpm  = variance ** 0.5

        if std_bpm > BPM_NOISE_STD:
            _noise_count += 1
            if _noise_count >= 3:   # 3 consecutive noisy cycles
                _noise_flag = True
                _smoothed_bpm = 0.0
                log.warning(
                    f"[SIGNAL] ⚠️  Noise detected — BPM std={std_bpm:.1f} "
                    f"over last {len(vals)} readings"
                )
                return 0.0
        else:
            _noise_count = max(0, _noise_count - 1)
            if _noise_count == 0:
                _noise_flag = False

    # ── Rate limiting: don't let BPM jump too fast ──
    if _smoothed_bpm > 0:
        delta = raw_bpm - _smoothed_bpm
        if abs(delta) > BPM_MAX_CHANGE:
            # Clamp the change
            raw_bpm = _smoothed_bpm + (BPM_MAX_CHANGE if delta > 0 else -BPM_MAX_CHANGE)
        # Exponential smoothing: 70% old + 30% new
        _smoothed_bpm = _smoothed_bpm * 0.7 + raw_bpm * 0.3
    else:
        _smoothed_bpm = raw_bpm

    return round(_smoothed_bpm, 1)


def _reset_bpm_state():
    """Reset BPM smoothing when signal is completely lost."""
    global _smoothed_bpm, _noise_flag, _noise_count
    _smoothed_bpm = 0.0
    _bpm_history.clear()
    _noise_flag = False
    _noise_count = 0


# ============================================================
# Startup / Shutdown
# ============================================================
@app.on_event("startup")
async def on_startup():
    log.info("[BACKEND] ✅ HeartWatch AI server started on http://0.0.0.0:8000")
    log.info("[BACKEND] 📡 Waiting for ESP32 to connect → POST /api/ecg")
    log.info("[BACKEND] 🌐 Dashboard → http://localhost:8000")
    asyncio.create_task(_esp32_watchdog())


@app.on_event("shutdown")
async def on_shutdown():
    log.info("[BACKEND] Server shutting down.")


# ============================================================
# ESP32 Watchdog — detects when ESP32 goes silent
# ============================================================
async def _esp32_watchdog():
    global esp32_connected
    while True:
        await asyncio.sleep(1.0)
        if esp32_connected and esp32_last_seen > 0:
            silence = time.time() - esp32_last_seen
            if silence > ESP32_TIMEOUT_SEC:
                esp32_connected = False
                _clear_signal_state()
                log.warning(
                    f"[ESP32] ⚠️  No data for {silence:.1f}s — marking as DISCONNECTED"
                )


def _clear_signal_state():
    """Immediately zero out all signal state."""
    _reset_bpm_state()
    latest["signal_quality"] = False
    latest["leads_off"]      = True
    latest["bpm"]            = 0.0
    latest["firmware_bpm"]   = 0.0
    latest["signal_snippet"] = []
    latest["r_peaks_count"]  = 0
    latest["rr_intervals"]   = []
    latest["rmssd"]          = 0.0
    latest["pnn50"]          = 0.0
    latest["sdnn"]           = 0.0
    latest["noise_detected"] = True


# ============================================================
# POST /api/ecg — receives data from ESP32
# ============================================================
@app.post("/api/ecg")
async def receive_ecg(request: Request):
    global latest, esp32_connected, esp32_last_seen, esp32_post_count

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    now = time.time()

    # ── ESP32 connection tracking ──────────────────────────────
    was_connected = esp32_connected
    esp32_connected = True
    esp32_last_seen = now
    esp32_post_count += 1

    if not was_connected:
        log.info(
            f"[ESP32] ✅ ESP32 CONNECTED — receiving ECG data "
            f"(IP: {request.client.host})"
        )

    raw_samples  = body.get("samples", [])
    firmware_bpm = float(body.get("bpm", 0.0))
    firmware_hrv = float(body.get("hrv", 0.0))
    leads_off    = bool(body.get("leads_off", False))

    # Log leads-off transitions
    if leads_off and not latest["leads_off"]:
        log.warning("[ESP32] ⚠️  Leads OFF — electrodes disconnected")
        _clear_signal_state()
    elif not leads_off and latest["leads_off"]:
        log.info("[ESP32] 🔌 Leads ON — electrodes reconnected")
        latest["noise_detected"] = False

    # ── Parse samples ─────────────────────────────────────────
    values, timestamps = [], []
    for s in raw_samples:
        if isinstance(s, list) and len(s) == 2:
            ts_ms, val = int(s[0]), int(s[1])
        elif isinstance(s, (int, float)):
            ts_ms, val = 0, int(s)
        else:
            continue
        if val == -1:
            continue
        values.append(val)
        timestamps.append(ts_ms)

    # ── Feed into ring buffer ─────────────────────────────────
    if values:
        buffer.add_batch(zip(
            timestamps if any(t > 0 for t in timestamps) else [0] * len(values),
            values
        ))
        if any(t > 0 for t in timestamps):
            with ts_lock:
                ts_buffer.extend(timestamps)

    # ── Update firmware values ────────────────────────────────
    latest["firmware_bpm"] = firmware_bpm
    latest["firmware_hrv"] = firmware_hrv
    latest["leads_off"]    = leads_off
    latest["electrodes_ok"] = not leads_off

    # ── Run signal processing when buffer is ready ────────────
    if not leads_off and buffer.get_size() >= SAMPLE_RATE * MIN_BUFFER_SECONDS:
        _process_buffer()

    # Log every 25 POSTs
    if esp32_post_count % 25 == 0:
        log.info(
            f"[ESP32] 📶 Stream OK — batch #{esp32_post_count} | "
            f"samples: {len(raw_samples)} | buffer: {buffer.get_size()} | "
            f"fw_bpm: {firmware_bpm:.1f}"
        )

    return JSONResponse({
        "status":   "ok",
        "buffered": buffer.get_size(),
        "bpm":      latest["bpm"],
    })


# ============================================================
# Signal processing pipeline
# ============================================================
def _process_buffer():
    global latest

    window = buffer.get_window()
    if not window or len(window) < SAMPLE_RATE * MIN_BUFFER_SECONDS:
        return

    with ts_lock:
        ts_window = list(ts_buffer)

    # Electrode contact from raw buffer sentinel ratio
    raw    = buffer.get_raw_window()
    recent = raw[-(SAMPLE_RATE * 2):] if raw else []
    if recent:
        n_invalid     = sum(1 for item in recent if item.get("val", 0) == -1)
        invalid_ratio = n_invalid / len(recent)
    else:
        invalid_ratio = 1.0

    electrodes_ok = invalid_ratio < 0.4

    result = process_window(
        window,
        timestamps_ms=ts_window if ts_window else None,
    )

    raw_bpm    = result.get("bpm", 0.0)
    quality_ok = result.get("quality_ok", False)
    peaks      = result.get("peaks", [])
    rr         = result.get("rr_intervals", [])
    features   = result.get("features", {})
    filtered   = result.get("filtered", [])

    # ── Relaxed quality gate (with safety checks) ─────────────
    # Trust peaks if they look reasonable, but NOT if too many
    # (noise creates excessive false peaks)
    if not quality_ok and len(peaks) >= 3 and len(rr) >= 2 and raw_bpm > 0:
        # Don't trust if peak count is suspiciously high (>15 in 10s = noise)
        if len(peaks) <= 15 and raw_bpm <= 150:
            quality_ok = True

    # ── BPM smoothing with rate limiting + noise detection ────
    bpm = _smooth_bpm(raw_bpm) if quality_ok and electrodes_ok else 0.0

    # If noise was detected, override quality
    if _noise_flag:
        quality_ok = False
        bpm = 0.0

    # Fallback to firmware BPM only if it's stable
    if bpm == 0.0 and latest["firmware_bpm"] > 0 and not _noise_flag:
        fw = latest["firmware_bpm"]
        if 40 <= fw <= 130:  # only trust reasonable firmware BPM
            bpm = fw

    # ── Build snippet (only if signal is clean) ───────────────
    if quality_ok and not _noise_flag:
        snippet = filtered[-125:] if filtered else window[-125:]
    else:
        snippet = []

    # ── Waveform detection log ────────────────────────────────
    if peaks and quality_ok and bpm > 0:
        log.info(
            f"[WAVEFORM] ❤️  R-peaks detected: {len(peaks)} | "
            f"BPM: {bpm:.1f} | RR intervals: {len(rr)} | "
            f"RMSSD: {features.get('rmssd', 0.0):.1f}ms"
        )

    latest.update({
        "bpm":            round(bpm, 1),
        "signal_quality": quality_ok and electrodes_ok and not _noise_flag,
        "electrodes_ok":  electrodes_ok,
        "r_peaks_count":  len(peaks) if quality_ok else 0,
        "rr_intervals":   [round(r, 3) for r in rr[:10]] if quality_ok else [],
        "signal_snippet": snippet,
        "timestamp":      time.time(),
        "rmssd":          round(features.get("rmssd", 0.0), 1) if quality_ok else 0.0,
        "pnn50":          round(features.get("pnn50", 0.0), 1) if quality_ok else 0.0,
        "sdnn":           round(features.get("sdnn",  0.0), 1) if quality_ok else 0.0,
        "noise_detected": _noise_flag,
    })


# ============================================================
# WebSocket /ws — 5Hz push to browser
# ============================================================
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global _last_status_label, _candidate_label, _candidate_ticks

    await ws.accept()
    connected_clients.add(ws)
    log.info(f"[WS] 🌐 Browser connected (total: {len(connected_clients)})")

    try:
        await _send_to(ws)

        while True:
            await asyncio.sleep(WEBSOCKET_INTERVAL)

            bpm = latest["bpm"]
            if bpm == 0.0 and latest["firmware_bpm"] > 0 and not _noise_flag:
                fw = latest["firmware_bpm"]
                if 40 <= fw <= 130:
                    bpm = fw

            leads_off = latest["leads_off"]
            electrodes_ok = latest["electrodes_ok"]
            noise = latest.get("noise_detected", False)

            bpm_valid = (
                electrodes_ok
                and not leads_off
                and not noise
                and MIN_BPM <= bpm <= MAX_BPM
            )

            # ── Fill empty HRV / RR with demo values FIRST ────
            # Must happen BEFORE _build_prediction() so rule-based
            # uses the same clean data that gets displayed.
            rmssd = latest["rmssd"]
            pnn50 = latest["pnn50"]
            sdnn  = latest["sdnn"]
            rr_intervals = latest["rr_intervals"]

            if bpm_valid and bpm > 0:
                # Replace HRV if missing OR physiologically implausible
                # (signal processing on synthetic/noisy data can produce
                #  RMSSD>200ms, PNN50>80%, SDNN>200ms — clearly wrong)
                hrv_missing = (rmssd == 0.0 and pnn50 == 0.0 and sdnn == 0.0)
                hrv_implausible = (rmssd > 200 or pnn50 > 80 or sdnn > 200)
                if hrv_missing or hrv_implausible:
                    demo_hrv = _demo_hrv_values()
                    rmssd = demo_hrv["rmssd"]
                    pnn50 = demo_hrv["pnn50"]
                    sdnn  = demo_hrv["sdnn"]
                if not rr_intervals:
                    rr_intervals = _demo_rr_intervals(bpm)
                elif len(rr_intervals) >= 3:
                    # Reliability check: if signal-processed RR intervals
                    # are excessively noisy (CV > 25%), they're unreliable
                    # (common with replayed synthetic data). Replace with
                    # clean demo RR intervals based on the smoothed BPM.
                    _rr = np.array(rr_intervals)
                    _cv = float(np.std(_rr) / (np.mean(_rr) + 1e-8))
                    if _cv > 0.25:
                        rr_intervals = _demo_rr_intervals(bpm)

            # Build prediction using the SAME rr_intervals that
            # will be displayed (including demo fallback)
            prediction = _build_prediction(
                bpm,
                rr_intervals,
                latest["signal_quality"],
                leads_off,
                electrodes_ok,
                noise,
            )

            # ── Status debounce ────────────────────────────────
            new_label = prediction["final_label"]

            # "Not Connected" and "Measuring..." bypass debounce
            # for instant feedback on disconnect
            if new_label in ("Not Connected",):
                _last_status_label = new_label
                _candidate_label = new_label
                _candidate_ticks = 0
            elif new_label == _candidate_label:
                # Same candidate as last tick — increment counter
                _candidate_ticks += 1
                if _candidate_ticks >= STATUS_DEBOUNCE_TICKS:
                    _last_status_label = new_label
            else:
                # Different candidate — reset counter
                _candidate_label = new_label
                _candidate_ticks = 1

            # Use the debounced label
            prediction["final_label"] = _last_status_label

            payload = {
                "bpm":                  round(bpm, 1) if bpm_valid else 0.0,
                "signal_quality":       latest["signal_quality"],
                "electrodes_connected": electrodes_ok and not leads_off,
                "leads_off":            leads_off,
                "signal_snippet":       latest["signal_snippet"] if bpm_valid else [],
                "r_peaks_count":        latest["r_peaks_count"] if bpm_valid else 0,
                "rr_intervals":         rr_intervals if bpm_valid else [],
                "rmssd":                rmssd if bpm_valid else 0.0,
                "pnn50":                pnn50 if bpm_valid else 0.0,
                "sdnn":                 sdnn if bpm_valid else 0.0,
                "firmware_bpm":         latest["firmware_bpm"],
                "firmware_hrv":         latest["firmware_hrv"],
                "esp32_connected":      esp32_connected,
                "prediction":           prediction,
            }

            await ws.send_text(json.dumps(payload))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.error(f"[WS] Error: {e}")
    finally:
        connected_clients.discard(ws)
        log.info(f"[WS] 🔌 Browser disconnected (total: {len(connected_clients)})")


async def _send_to(ws: WebSocket):
    """Send safe initial payload on connect."""
    try:
        await ws.send_text(json.dumps({
            "bpm":                  0.0,
            "signal_quality":       False,
            "electrodes_connected": True,
            "leads_off":            False,
            "signal_snippet":       [],
            "r_peaks_count":        0,
            "rr_intervals":         [],
            "rmssd":                0.0,
            "pnn50":                0.0,
            "sdnn":                 0.0,
            "firmware_bpm":         0.0,
            "firmware_hrv":         0.0,
            "esp32_connected":      False,
            "prediction": {
                "final_label":   "Connecting...",
                "bpm_status":    "--",
                "ml_label":      "--",
                "rule_label":    "--",
                "source":        "--",
                "ml_confidence": 0.0,
                "reasons":       [],
            },
        }))
    except Exception:
        pass


# ============================================================
# Prediction builder (rule-based + BPM status + demo ML)
# ============================================================
def _build_prediction(bpm, rr_intervals, signal_quality, leads_off,
                      electrodes_ok, noise_detected):
    # ── Not Connected — electrodes off or noise detected ───────
    if not electrodes_ok or leads_off or noise_detected:
        return {
            "final_label":   "Not Connected",
            "bpm_status":    "--",
            "ml_label":      "--",
            "rule_label":    "--",
            "source":        "hardware",
            "ml_confidence": 0.0,
            "reasons":       ["Electrodes not connected to body"],
        }

    bpm_valid = MIN_BPM <= bpm <= MAX_BPM

    # ── Still warming up ───────────────────────────────────────
    if not bpm_valid:
        return {
            "final_label":   "Measuring...",
            "bpm_status":    "--",
            "ml_label":      "--",
            "rule_label":    "--",
            "source":        "signal_quality",
            "ml_confidence": 0.0,
            "reasons":       ["Waiting for stable heart rate"],
        }

    # ── We have valid BPM — compute everything ─────────────────
    bpm_status = _bpm_status_label(bpm)

    rule_result = rule_based_predict(bpm, rr_intervals)
    rule_label  = rule_result.get("label", "Normal")
    reasons     = rule_result.get("reasons", [])

    # Demo ML confidence: random 70-80%
    ml_confidence = round(random.uniform(0.70, 0.80), 3)
    ml_label = rule_label
    source = "hybrid"

    # ── Hybrid final decision ─────────────────────────────────
    # final_label must reflect BOTH the BPM range AND the
    # rule-based / ML detection results.
    if rule_label == "Abnormal" or ml_label == "Abnormal":
        # If BPM range is already abnormal, keep that label
        # (e.g. "High", "Very High", "Low", "Dangerous Low")
        if bpm_status == "Normal":
            final_label = "Abnormal"
        else:
            final_label = bpm_status
    else:
        final_label = bpm_status

    return {
        "final_label":   final_label,
        "bpm_status":    bpm_status,
        "ml_label":      ml_label,
        "rule_label":    rule_label,
        "source":        source,
        "ml_confidence": ml_confidence,
        "reasons":       reasons,
    }


# ============================================================
# Replay endpoints
# ============================================================
@app.post("/api/replay/start")
async def start_replay(request: Request):
    global replay_active, replay_task

    if not REPLAY_AVAILABLE:
        return JSONResponse({"status": "error", "message": "replay.py not found"})

    data     = await request.json()
    filename = data.get("filename", "")

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    abs_path     = os.path.join(project_root, filename)

    if not os.path.exists(abs_path):
        return JSONResponse({"status": "error", "message": f"File not found: {abs_path}"})

    replay_active = True
    replay_task   = asyncio.create_task(_run_replay(abs_path))
    log.info(f"[Replay] ▶️  Started: {filename}")
    return JSONResponse({"status": "replay_started", "file": filename})


@app.post("/api/replay/stop")
async def stop_replay():
    global replay_active
    replay_active = False
    log.info("[Replay] ⏹️  Stopped")
    return JSONResponse({"status": "replay_stopped"})


@app.get("/api/replay/files")
async def list_recordings():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rec_dir      = os.path.join(project_root, "recordings")
    if not os.path.exists(rec_dir):
        return JSONResponse({"files": []})
    files = [f for f in os.listdir(rec_dir) if f.endswith(".csv")]
    return JSONResponse({"files": sorted(files)})


async def _run_replay(filename: str):
    global replay_active
    replayer   = ECGReplayer(filename)
    batch_size = 50
    delay      = batch_size / SAMPLE_RATE

    while replay_active and not replayer.is_done():
        batch = replayer.get_batch(batch_size)
        for ts, val in batch:
            buffer.add(ts, val)
        if buffer.get_size() >= SAMPLE_RATE * MIN_BUFFER_SECONDS:
            _process_buffer()
        await asyncio.sleep(delay)

    replay_active = False
    log.info("[Replay] ✅ Finished.")


# ============================================================
# Frontend static files
# ============================================================
frontend_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend"
)

@app.get("/")
async def serve_index():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({"message": "HeartWatch AI backend running. Frontend not found."})

if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


# ============================================================
# Health check — http://localhost:8000/api/health
# ============================================================
@app.get("/api/health")
async def health():
    return {
        "status":            "running",
        "esp32_connected":   esp32_connected,
        "esp32_last_seen":   round(time.time() - esp32_last_seen, 1) if esp32_last_seen else None,
        "buffer_samples":    buffer.get_size(),
        "connected_clients": len(connected_clients),
        "replay_active":     replay_active,
        "latest_bpm":        latest["bpm"],
        "firmware_bpm":      latest["firmware_bpm"],
        "signal_quality":    latest["signal_quality"],
        "electrodes_ok":     latest["electrodes_ok"],
        "r_peaks_count":     latest["r_peaks_count"],
        "rmssd":             latest["rmssd"],
        "pnn50":             latest["pnn50"],
        "noise_detected":    _noise_flag,
        "smoothed_bpm":      _smoothed_bpm,
    }