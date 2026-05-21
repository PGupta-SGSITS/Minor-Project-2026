/*
 * FocusGuard AI — ESP32 + AD8232 ECG Firmware v3
 * 
 * WHAT CHANGED FROM YOUR OLD CODE:
 *  1. Adaptive threshold — moves with your signal automatically
 *  2. Moving average filter — smooths noise before peak detection
 *  3. Peak confirmed on downslope — not on upslope (no double counting)
 *  4. Outlier rejection — ignores BPM spikes >30% from running average
 *  5. Timestamps on every sample — backend gets real RR intervals
 *  6. FreeRTOS dual-core — sampling never interrupted by WiFi
 * 
 * Wiring:
 *   AD8232 GND    → ESP32 GND
 *   AD8232 3.3V   → ESP32 3V3  (NOT 5V)
 *   AD8232 OUTPUT → ESP32 GPIO34
 *   AD8232 LO-    → ESP32 GPIO25
 *   AD8232 LO+    → ESP32 GPIO26
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <HTTPClient.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// ─── WiFi + Server ────────────────────────────────────────────
const char*    ssid      = "Your Wifi Name";
const char*    password  = "Your Wifi Password";
const char*    serverUrl = "http://Your Server IP:8000/api/ecg";
const char*    serverHost = "Your Server IP";
const uint16_t serverPort = 8000;

// ─── Pins ─────────────────────────────────────────────────────
#define ECG_PIN      34
#define LO_MINUS_PIN 25
#define LO_PLUS_PIN  26
const bool ENABLE_LEADS_OFF_DETECTION = true;

// ─── Sampling ─────────────────────────────────────────────────
const int SAMPLE_RATE        = 250;
const int SAMPLE_INTERVAL_MS = 1000 / SAMPLE_RATE;  // 4ms
const int BATCH_SIZE         = 125;                  // 500ms per POST

// Peak detector tuning for AD8232 amplitudes seen after smoothing.
const int   MIN_SIGNAL_RANGE      = 60;    // ADC units
const float THRESHOLD_RANGE_RATIO = 0.45f; // baseline + ratio * range
const int   REFRACTORY_MS         = 300;   // max ~200 BPM

// ─── Moving Average Filter ────────────────────────────────────
// Smooths the raw ADC signal before peak detection.
// Window of 10 samples at 250Hz = 40ms of smoothing.
#define FILTER_SIZE 10
int   filterBuf[FILTER_SIZE];
int   filterIdx  = 0;
long  filterSum  = 0;
bool  filterFull = false;

int applyFilter(int raw) {
  filterSum -= filterBuf[filterIdx];
  filterBuf[filterIdx] = raw;
  filterSum += raw;
  filterIdx = (filterIdx + 1) % FILTER_SIZE;
  if (filterIdx == 0) filterFull = true;
  int count = filterFull ? FILTER_SIZE : filterIdx;
  return (count > 0) ? (filterSum / count) : raw;
}

// ─── Adaptive Threshold State ─────────────────────────────────
// These live in the sampling task and update every sample.
float adBaseline  = 2048.0f;  // tracks the signal floor
float adPeakLevel = 2200.0f;  // tracks recent peak height
int   adThreshold = 2100;     // midpoint — moves automatically

// ─── Peak Detection State ─────────────────────────────────────
bool          aboveThresh    = false;
unsigned long lastDetectMs   = 0;
unsigned long lastPeakMs     = 0;
float         smoothedBPM    = 0.0f;
bool          bpmValid       = false;
float         latestBPM      = 0.0f;
float         latestHRV      = 0.0f;
float         latestRange    = 0.0f;
unsigned long lastDiagLogMs  = 0;

unsigned long rrBuf[10];
int           rrIdx   = 0;
int           rrCount = 0;

float computeHRV() {
  if (rrCount < 2) return 0.0f;
  float sum = 0;
  for (int i = 0; i < rrCount; i++) sum += rrBuf[i];
  float mean = sum / rrCount;
  float var  = 0;
  for (int i = 0; i < rrCount; i++) {
    float d = rrBuf[i] - mean;
    var += d * d;
  }
  return sqrt(var / rrCount);
}

void detectPeak(int filtered, unsigned long nowMs) {
  // Update adaptive baseline (very slow — follows DC drift)
  adBaseline = adBaseline * 0.999f + filtered * 0.001f;

  // Update peak tracker (faster rise, slow decay)
  if (filtered > adPeakLevel) {
    adPeakLevel = adPeakLevel * 0.95f + filtered * 0.05f;
  } else {
    adPeakLevel = adPeakLevel * 0.999f + filtered * 0.001f;
  }

  // Threshold = 60% of the way between baseline and peak
  float range = adPeakLevel - adBaseline;
  adThreshold = (int)(adBaseline + range * THRESHOLD_RANGE_RATIO);
  latestRange = range;

  // Only run detection if signal has meaningful range.
  // Below this = flat noise, not an ECG signal
  if (range < MIN_SIGNAL_RANGE) return;

  // Rising edge: signal crosses threshold upward
  if (filtered > adThreshold && !aboveThresh) {
    // Refractory period prevents double-counting the same beat.
    if (nowMs - lastDetectMs > REFRACTORY_MS) {
      aboveThresh = true;
    }
  }

  // Falling edge: signal drops below threshold → beat is confirmed
  if (filtered < adThreshold && aboveThresh) {
    aboveThresh  = false;
    lastDetectMs = nowMs;

    if (lastPeakMs > 0) {
      unsigned long rr = nowMs - lastPeakMs;

      // Valid RR range: 400–1500ms = 40–150 BPM
      if (rr >= 400 && rr <= 1500) {
        rrBuf[rrIdx] = rr;
        rrIdx = (rrIdx + 1) % 10;
        if (rrCount < 10) rrCount++;

        float instantBPM = 60000.0f / rr;

        if (!bpmValid) {
          smoothedBPM = instantBPM;
          bpmValid    = true;
        } else {
          // Reject outlier: ignore if >30% away from running average
          float diff = fabsf(instantBPM - smoothedBPM) / smoothedBPM;
          if (diff < 0.30f) {
            // Exponential smoothing: 80% old + 20% new
            smoothedBPM = smoothedBPM * 0.8f + instantBPM * 0.2f;
          } else {
            // If detector jumps, move slowly instead of freezing forever.
            smoothedBPM = smoothedBPM * 0.95f + instantBPM * 0.05f;
          }
        }

        latestBPM = smoothedBPM;
        if (rrCount >= 3) latestHRV = computeHRV();
      }
    }
    lastPeakMs = nowMs;
  }
}

// ─── FreeRTOS Queue ───────────────────────────────────────────
QueueHandle_t batchQueue;

struct SampleBatch {
  int           samples[BATCH_SIZE];
  unsigned long timestamps[BATCH_SIZE];
  float         bpm;   // computed BPM at time of batch
  float         hrv;   // computed HRV at time of batch
  bool          leadsOff;
};

// ─── Task 1: Sampling — Core 1, Priority 2 ───────────────────
// Runs at exactly 250Hz. Does filtering + peak detection inline
// so BPM is always computed from the freshest data.
void samplingTask(void* pv) {
  SampleBatch  batch;
  int          idx = 0;
  TickType_t   lastWake = xTaskGetTickCount();
  const TickType_t period = pdMS_TO_TICKS(SAMPLE_INTERVAL_MS);

  // Warm up filter buffer
  for (int i = 0; i < FILTER_SIZE; i++) filterBuf[i] = 2048;
  filterSum = 2048 * FILTER_SIZE;

  for (;;) {
    vTaskDelayUntil(&lastWake, period);  // precise 4ms sleep

    unsigned long now = millis();
    bool leadsOff = false;
    if (ENABLE_LEADS_OFF_DETECTION) {
      leadsOff = (digitalRead(LO_PLUS_PIN) == HIGH ||
                  digitalRead(LO_MINUS_PIN) == HIGH);
    }

    int raw      = leadsOff ? -1 : analogRead(ECG_PIN);
    int filtered = leadsOff ? 2048 : applyFilter(raw);

    if (!leadsOff) {
      detectPeak(filtered, now);
    } else {
      // Reset peak state when leads are off
      aboveThresh = false;
      bpmValid  = false;
      rrCount   = 0;
      rrIdx     = 0;
      latestBPM = 0.0f;
      latestHRV = 0.0f;
      lastPeakMs = 0;
      lastDetectMs = 0;
    }

    if (now - lastDiagLogMs > 2000) {
      lastDiagLogMs = now;
      Serial.print("SIG leadOff=");
      Serial.print(leadsOff ? "1" : "0");
      Serial.print(" raw=");
      Serial.print(raw);
      Serial.print(" filt=");
      Serial.print(filtered);
      Serial.print(" thr=");
      Serial.print(adThreshold);
      Serial.print(" range=");
      Serial.print(latestRange, 1);
      Serial.print(" bpm=");
      Serial.println(latestBPM, 1);
    }

    batch.samples[idx]    = raw;
    batch.timestamps[idx] = now;
    idx++;

    if (idx >= BATCH_SIZE) {
      batch.bpm      = bpmValid ? latestBPM : 0.0f;
      batch.hrv      = latestHRV;
      batch.leadsOff = leadsOff;
      xQueueSend(batchQueue, &batch, 0);  // non-blocking
      idx = 0;
    }
  }
}

// ─── Task 2: WiFi POST — Core 0, Priority 1 ──────────────────
// Receives batches from the queue and sends them to the backend.
// JSON: {"samples":[[ts,val],...], "bpm":72.3, "hrv":45.1, "leads_off":false}
void wifiTask(void* pv) {
  SampleBatch   batch;
  unsigned long lastErrLogMs     = 0;
  unsigned long lastSuccessLogMs = 0;
  unsigned long lastFailMs       = 0;
  unsigned long lastReconnectMs  = 0;

  for (;;) {
    // Backoff 1.5s after a failed POST
    if (WiFi.status() == WL_CONNECTED && lastFailMs != 0 &&
        (millis() - lastFailMs) < 1500) {
      vTaskDelay(pdMS_TO_TICKS(50));
      continue;
    }

    if (!xQueueReceive(batchQueue, &batch, portMAX_DELAY)) continue;

    if (WiFi.status() != WL_CONNECTED) {
      unsigned long now = millis();
      if (now - lastReconnectMs > 5000) {
        Serial.println("WiFi lost — reconnecting...");
        WiFi.reconnect();
        lastReconnectMs = now;
      }
      continue;
    }

    // Build JSON payload
    // Format: {"samples":[[ts,val],...],"bpm":72.3,"hrv":45.1,"leads_off":false}
    String payload = "{\"samples\":[";
    for (int i = 0; i < BATCH_SIZE; i++) {
      payload += "[";
      payload += String(batch.timestamps[i]);
      payload += ",";
      payload += String(batch.samples[i]);
      payload += "]";
      if (i < BATCH_SIZE - 1) payload += ",";
    }
    payload += "],\"bpm\":";
    payload += String(batch.bpm, 1);
    payload += ",\"hrv\":";
    payload += String(batch.hrv, 1);
    payload += ",\"leads_off\":";
    payload += batch.leadsOff ? "true" : "false";
    payload += "}";

    // POST to backend
    WiFiClient client;
    HTTPClient http;
    http.setTimeout(2500);
    http.setReuse(false);
    http.begin(client, serverUrl);
    http.addHeader("Content-Type", "application/json");

    int code = http.POST(payload);
    unsigned long now = millis();

    if (code <= 0) {
      lastFailMs = now;
      if (now - lastErrLogMs > 2000) {
        Serial.print("POST failed: ");
        Serial.println(http.errorToString(code));
        lastErrLogMs = now;
      }
    } else {
      lastFailMs = 0;
      if (now - lastSuccessLogMs > 5000) {
        Serial.print("POST OK ");
        Serial.print(code);
        Serial.print(" | BPM: ");
        Serial.print(batch.bpm, 1);
        Serial.print(" | HRV: ");
        Serial.println(batch.hrv, 1);
        lastSuccessLogMs = now;
      }
    }
    http.end();
  }
}

// ─── Setup ────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(LO_PLUS_PIN,  INPUT);
  pinMode(LO_MINUS_PIN, INPUT);

  analogReadResolution(12);        // 0–4095
  analogSetAttenuation(ADC_11db); // full 0–3.3V range

  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected!");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());
  Serial.print("Posting to: ");
  Serial.println(serverUrl);

  // Queue holds 5 batches = 2.5 sec buffer if WiFi is slow
  batchQueue = xQueueCreate(5, sizeof(SampleBatch));

  xTaskCreatePinnedToCore(samplingTask, "Sampling", 10000, NULL, 2, NULL, 1);
  xTaskCreatePinnedToCore(wifiTask,     "WiFi",     10000, NULL, 1, NULL, 0);
}

void loop() {}  // All work happens in FreeRTOS tasks
