/*
 * ============================================================
 *  Pocket AI Voice Companion
 *  XIAO ESP32-S3
 *
 *  PIPELINE:
 *  [INMP441 Mic] → Deepgram STT → Groq LLM → Deepgram TTS → [MAX98357A Speaker]
 *
 *  WIRING:
 *  ┌─────────────┬──────────────┬────────────────────────────┐
 *  │ INMP441 Pin │ XIAO GPIO    │ Why                        │
 *  ├─────────────┼──────────────┼────────────────────────────┤
 *  │ SCK / BCLK  │ GPIO44 (D7)  │ I2S bit clock (master out) │
 *  │ WS / LRCK   │ GPIO9  (D10) │ I2S word select            │
 *  │ SD / DOUT   │ GPIO1  (D0)  │ Audio data from mic        │
 *  │ VCC         │ 3.3V         │ INMP441 max is 3.3V        │
 *  │ GND         │ GND          │ Common ground              │
 *  │ L/R         │ GND          │ Select LEFT channel        │
 *  ├─────────────┼──────────────┼────────────────────────────┤
 *  │ MAX98357A   │ XIAO GPIO    │ Why                        │
 *  ├─────────────┼──────────────┼────────────────────────────┤
 *  │ BCLK        │ GPIO7  (D8)  │ I2S bit clock (master out) │
 *  │ LRC / LRCK  │ GPIO4  (D3)  │ I2S word select            │
 *  │ DIN         │ GPIO2  (D1)  │ Audio data to amp          │
 *  │ VIN         │ 5V (VBUS)    │ Needs 5V for volume        │
 *  │ GND         │ GND          │ Common ground              │
 *  └─────────────┴──────────────┴────────────────────────────┘
 *
 *  LIBRARIES (install via Library Manager):
 *    - ArduinoJson  by Benoit Blanchon
 *    - WiFiClientSecure  (built-in ESP32)
 *    - HTTPClient        (built-in ESP32)
 *
 *  HOW TO USE:
 *    1. Fill in credentials below
 *    2. Flash to XIAO ESP32-S3
 *    3. Open Serial Monitor at 115200
 *    4. Hold BOOT button → speak → release
 *    5. Wait for reply from speaker
 * ============================================================
 */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <driver/i2s.h>

// ── FILL THESE IN ──────────────────────────────────────────
#define WIFI_SSID        "your wifi name
#define WIFI_PASSWORD    "wifi password
#define GROQ_API_KEY     "your_groq_api_key"      // https://console.groq.com (free tier available)
#define DEEPGRAM_API_KEY "YOUR_DEEPGRAM_API_KEY"   // console.deepgram.com (free tier available)
// ───────────────────────────────────────────────────────────

// ── I2S MIC  (INMP441) ─────────────────────────────────────
#define I2S_MIC_NUM      I2S_NUM_0
#define I2S_MIC_SCK      44    // D7
#define I2S_MIC_WS        9    // D10
#define I2S_MIC_SD        1    // D0

// ── I2S SPEAKER  (MAX98357A) ───────────────────────────────
#define I2S_SPK_NUM      I2S_NUM_1
#define I2S_SPK_BCLK      7    // D8
#define I2S_SPK_LRC       4    // D3
#define I2S_SPK_DIN       2    // D1

// ── AUDIO PARAMS ───────────────────────────────────────────
#define MIC_SAMPLE_RATE  16000          // Deepgram STT expects 16 kHz
#define SPK_SAMPLE_RATE  24000          // Deepgram TTS outputs  24 kHz
#define RECORD_SECONDS   4
#define RECORD_SAMPLES   (MIC_SAMPLE_RATE * RECORD_SECONDS)   // 64000 samples = 128 KB
#define DMA_BUF_COUNT    8
#define DMA_BUF_LEN      512

// ── BOOT BUTTON ────────────────────────────────────────────
#define BOOT_BTN         0

// ── AUDIO BUFFER (allocated in setup) ─────────────────────
int16_t* recBuf = nullptr;
int      recSamples = 0;

// ═══════════════════════════════════════════════════════════
//  I2S INIT
// ═══════════════════════════════════════════════════════════

void initMic() {
  i2s_config_t cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate          = MIC_SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,   // L/R pin tied to GND
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = DMA_BUF_COUNT,
    .dma_buf_len          = DMA_BUF_LEN,
    .use_apll             = false,
    .tx_desc_auto_clear   = false,
    .fixed_mclk           = 0
  };
  i2s_pin_config_t pins = {
    .bck_io_num   = I2S_MIC_SCK,
    .ws_io_num    = I2S_MIC_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num  = I2S_MIC_SD
  };
  i2s_driver_install(I2S_MIC_NUM, &cfg, 0, NULL);
  i2s_set_pin(I2S_MIC_NUM, &pins);
  i2s_zero_dma_buffer(I2S_MIC_NUM);
  Serial.println("[MIC]  OK  GPIO44=SCK  GPIO9=WS  GPIO1=SD");
}

void initSpeaker() {
  i2s_config_t cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate          = SPK_SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = DMA_BUF_COUNT,
    .dma_buf_len          = DMA_BUF_LEN,
    .use_apll             = false,
    .tx_desc_auto_clear   = true,
    .fixed_mclk           = 0
  };
  i2s_pin_config_t pins = {
    .bck_io_num   = I2S_SPK_BCLK,
    .ws_io_num    = I2S_SPK_LRC,
    .data_out_num = I2S_SPK_DIN,
    .data_in_num  = I2S_PIN_NO_CHANGE
  };
  i2s_driver_install(I2S_SPK_NUM, &cfg, 0, NULL);
  i2s_set_pin(I2S_SPK_NUM, &pins);
  i2s_zero_dma_buffer(I2S_SPK_NUM);
  Serial.println("[SPK]  OK  GPIO7=BCLK  GPIO4=LRC  GPIO2=DIN");
}

// ═══════════════════════════════════════════════════════════
//  STEP 1 — RECORD from INMP441
// ═══════════════════════════════════════════════════════════

void recordAudio() {
  Serial.println("[REC]  Recording " + String(RECORD_SECONDS) + "s — speak now...");
  recSamples = 0;
  size_t bytesRead = 0;

  while (recSamples < RECORD_SAMPLES) {
    int toRead = min((int)(RECORD_SAMPLES - recSamples), DMA_BUF_LEN);
    i2s_read(I2S_MIC_NUM,
             &recBuf[recSamples],
             toRead * sizeof(int16_t),
             &bytesRead,
             portMAX_DELAY);
    recSamples += bytesRead / sizeof(int16_t);
  }
  Serial.println("[REC]  Done — " + String(recSamples) + " samples ("
                 + String(recSamples * 2 / 1024) + " KB)");
}

// Simple voice activity check — skip silence
bool hasSpeech() {
  long sum = 0;
  for (int i = 0; i < recSamples; i++) sum += abs(recBuf[i]);
  long avg = sum / recSamples;
  Serial.println("[REC]  Energy avg = " + String(avg));
  return avg > 300;   // lower = more sensitive; raise if triggers on background noise
}

// ═══════════════════════════════════════════════════════════
//  STEP 2 — DEEPGRAM STT  (audio → text)
// ═══════════════════════════════════════════════════════════

String speechToText() {
  Serial.println("[STT]  Sending audio to Deepgram...");

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  http.begin(client,
    "https://api.deepgram.com/v1/listen"
    "?model=nova-2&language=en&smart_format=true");
  http.addHeader("Authorization", "Token " + String(DEEPGRAM_API_KEY));
  http.addHeader("Content-Type",
    "audio/raw;encoding=linear-pcm;sample_rate=16000;channels=1;bits_per_sample=16");
  http.setTimeout(25000);

  int code = http.POST((uint8_t*)recBuf, recSamples * sizeof(int16_t));
  Serial.println("[STT]  HTTP " + String(code));

  if (code != 200) {
    Serial.println("[STT]  Error: " + http.getString());
    http.end();
    return "";
  }

  DynamicJsonDocument doc(4096);
  if (deserializeJson(doc, http.getString())) {
    Serial.println("[STT]  JSON parse error");
    http.end();
    return "";
  }
  http.end();

  String t = doc["results"]["channels"][0]["alternatives"][0]["transcript"]
             .as<String>();
  t.trim();
  Serial.println("[STT]  Transcript: \"" + t + "\"");
  return t;
}

// ═══════════════════════════════════════════════════════════
//  STEP 3 — GROQ LLM  (text → text)
//  Same logic as your working serial-chat sketch
// ═══════════════════════════════════════════════════════════

String askGroq(const String& question) {
  Serial.println("[LLM]  Asking Groq: \"" + question + "\"");

  if (WiFi.status() != WL_CONNECTED) return "No WiFi.";

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  http.begin(client, "https://api.groq.com/openai/v1/chat/completions");
  http.addHeader("Authorization", "Bearer " + String(GROQ_API_KEY));
  http.addHeader("Content-Type",  "application/json");
  http.setTimeout(20000);

  // Escape any quotes in input to avoid breaking JSON
  String safe = question;
  safe.replace("\"", "'");
  safe.replace("\n", " ");

  String body = "{";
  body += "\"model\":\"llama-3.1-8b-instant\",";
  body += "\"max_tokens\":120,";
  body += "\"messages\":[";
  body += "{\"role\":\"system\",\"content\":\"You are a helpful voice assistant. "
          "Reply in 1-2 short sentences only. No markdown, no bullet points.\"},";
  body += "{\"role\":\"user\",\"content\":\"" + safe + "\"}";
  body += "]}";

  int code = http.POST(body);
  Serial.println("[LLM]  HTTP " + String(code));

  String reply = "(error)";
  if (code == 200) {
    DynamicJsonDocument doc(4096);
    if (!deserializeJson(doc, http.getString())) {
      const char* c = doc["choices"][0]["message"]["content"];
      if (c) reply = String(c);
    }
  } else {
    Serial.println("[LLM]  Error: " + http.getString());
  }
  http.end();

  reply.trim();
  Serial.println("[LLM]  Reply: \"" + reply + "\"");
  return reply;
}

// ═══════════════════════════════════════════════════════════
//  STEP 4 — DEEPGRAM TTS  (text → audio → speaker)
//  Streams PCM bytes directly to MAX98357A via I2S
// ═══════════════════════════════════════════════════════════

void textToSpeech(const String& text) {
  Serial.println("[TTS]  Sending to Deepgram TTS...");

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  http.begin(client,
    "https://api.deepgram.com/v1/speak"
    "?model=aura-asteria-en&encoding=linear16&sample_rate=24000");
  http.addHeader("Authorization", "Token " + String(DEEPGRAM_API_KEY));
  http.addHeader("Content-Type",  "application/json");
  http.setTimeout(30000);

  String safe = text;
  safe.replace("\"", "'");
  int code = http.POST("{\"text\":\"" + safe + "\"}");
  Serial.println("[TTS]  HTTP " + String(code));

  if (code != 200) {
    Serial.println("[TTS]  Error: " + http.getString());
    http.end();
    return;
  }

  // Stream response bytes → I2S → speaker (no full buffer needed)
  WiFiClient* stream = http.getStreamPtr();
  uint8_t chunk[1024];
  size_t written = 0;
  int total = 0;

  Serial.println("[TTS]  Playing...");

  while (true) {
    int avail = stream->available();
    if (avail > 0) {
      int n = stream->readBytes(chunk, min(avail, (int)sizeof(chunk)));
      if (n > 0) {
        i2s_write(I2S_SPK_NUM, chunk, n, &written, portMAX_DELAY);
        total += n;
      }
    } else if (!http.connected()) {
      break;
    } else {
      delay(2);
    }
  }

  http.end();
  Serial.println("[TTS]  Done — played " + String(total / 1024) + " KB");
}

// ═══════════════════════════════════════════════════════════
//  FEEDBACK BEEPS  (so you know what's happening)
// ═══════════════════════════════════════════════════════════

void beep(int hz, int ms) {
  int n = (SPK_SAMPLE_RATE * ms) / 1000;
  size_t w;
  for (int i = 0; i < n; i++) {
    int16_t s = (int16_t)(7000 * sin(2.0 * PI * hz * i / (float)SPK_SAMPLE_RATE));
    i2s_write(I2S_SPK_NUM, &s, sizeof(s), &w, portMAX_DELAY);
  }
}

void beepReady()   { beep(880,100); delay(50); beep(1175,100); }   // ↑ two tones = ready
void beepStart()   { beep(1047,80); }                               // one tone  = recording
void beepSend()    { beep(1319,70); delay(35); beep(1319,70); }    // double    = sending
void beepDone()    { beep(1047,80); delay(35); beep(1319,80);
                     delay(35);     beep(1568,130); }               // C-E-G     = done
void beepError()   { beep(330,250); delay(80); beep(330,250); }    // low double = error

// ═══════════════════════════════════════════════════════════
//  SETUP
// ═══════════════════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  delay(1500);

  Serial.println("\n╔══════════════════════════════════════╗");
  Serial.println("║  Pocket AI Voice Companion            ║");
  Serial.println("║  XIAO ESP32-S3                        ║");
  Serial.println("║  Deepgram STT + Groq + Deepgram TTS   ║");
  Serial.println("╚══════════════════════════════════════╝\n");

  pinMode(BOOT_BTN, INPUT_PULLUP);

  // ── Allocate audio buffer ──────────────────────────────
  size_t bufBytes = RECORD_SAMPLES * sizeof(int16_t);
  recBuf = psramFound()
           ? (int16_t*)ps_malloc(bufBytes)
           : (int16_t*)malloc(bufBytes);

  if (!recBuf) {
    Serial.println("[MEM]  FATAL: cannot allocate " + String(bufBytes/1024) + " KB");
    while (1) delay(1000);
  }
  Serial.println("[MEM]  " + String(bufBytes/1024) + " KB in "
                 + (psramFound() ? "PSRAM" : "heap"));

  // ── WiFi ───────────────────────────────────────────────
  Serial.printf("[WIFI] Connecting to %s ", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.println("\n[WIFI] Connected  IP: " + WiFi.localIP().toString());

  // ── I2S ────────────────────────────────────────────────
  initMic();
  initSpeaker();

  beepReady();

  Serial.println("\n[READY] Hold BOOT button → speak → release");
  Serial.println("        Serial Monitor also works: type and press Enter\n");
}

// ═══════════════════════════════════════════════════════════
//  LOOP — two input modes:
//   1. BOOT button  → mic → full voice pipeline
//   2. Serial input → text → Groq only (like your working sketch)
// ═══════════════════════════════════════════════════════════

void loop() {

  // ── MODE 1: Voice (BOOT button) ───────────────────────
  if (digitalRead(BOOT_BTN) == LOW) {
    delay(50);
    if (digitalRead(BOOT_BTN) != LOW) return;   // debounce

    Serial.println("\n─── VOICE PIPELINE ───────────────────");

    // 1. Record
    beepStart();
    recordAudio();

    if (!hasSpeech()) {
      Serial.println("[WARN] No speech detected — try again");
      beepError();
      while (digitalRead(BOOT_BTN) == LOW) delay(10);
      delay(300);
      return;
    }

    // 2. STT
    beepSend();
    String transcript = speechToText();
    if (transcript.isEmpty()) {
      Serial.println("[WARN] Empty transcript — aborting");
      beepError();
      while (digitalRead(BOOT_BTN) == LOW) delay(10);
      delay(300);
      return;
    }

    // 3. LLM
    String reply = askGroq(transcript);

    // 4. TTS → speaker
    textToSpeech(reply);

    beepDone();
    Serial.println("─── DONE ─────────────────────────────\n");

    while (digitalRead(BOOT_BTN) == LOW) delay(10);
    delay(300);
  }

  // ── MODE 2: Serial text (same as your working sketch) ─
  if (Serial.available()) {
    String input = Serial.readStringUntil('\n');
    input.trim();
    if (input.length() == 0) return;

    Serial.println("\n─── TEXT PIPELINE ────────────────────");
    Serial.printf("You: %s\n", input.c_str());

    String reply = askGroq(input);
    Serial.println("AI:  " + reply);

    // also speak the reply
    textToSpeech(reply);

    beepDone();
    Serial.println("─── DONE ─────────────────────────────\n");
  }
}
