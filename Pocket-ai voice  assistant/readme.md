# Pocket AI Voice Companion 🎙️🤖

An ESP32-S3 based smart voice assistant that acts as a real-time conversational companion. It captures voice input, processes it using cloud-based AI pipelines, and streams the audio response back through a speaker.

## 🚀 Features
* **Full Voice Pipeline:** Hardware Mic ➔ STT ➔ LLM ➔ TTS ➔ Hardware Speaker.
* **Dual Input Modes:** 1. **Voice Mode:** Hold the BOOT button on the XIAO board to speak.
  2. **Serial Chat Mode:** Type directly into the Arduino Serial Monitor.
* **Audio Feedback:** Smart beeps and tones indicating system statuses (Ready, Recording, Processing, Done, Error).

---

## 🛠️ Hardware Components & Wiring

### 1. Microcontroller
* **Seeed Studio XIAO ESP32-S3** (Make sure to enable PSRAM if available).

### 2. Wiring Connections

| Component | Pin Name | XIAO GPIO Pin | Purpose |
| :--- | :--- | :--- | :--- |
| **INMP441 Mic** | SCK / BCLK | **GPIO44 (D7)** | I2S Bit Clock |
| | WS / LRCK | **GPIO9 (D10)** | I2S Word Select |
| | SD / DOUT | **GPIO1 (D0)** | Audio Data Input |
| | L/R | **GND** | Select Left Channel |
| | VCC / GND | **3.3V / GND** | Power Supply |
| **MAX98357A Amp**| BCLK | **GPIO7 (D8)** | I2S Bit Clock |
| | LRC / LRCK | **GPIO4 (D3)** | I2S Word Select |
| | DIN | **GPIO2 (D1)** | Audio Data Output |
| | VIN / GND | **5V (VBUS) / GND**| Power Supply (5V for high volume) |

---

## ⚙️ AI Pipeline Stack
1. **Speech-to-Text (STT):** [Deepgram Nova-2](https://deepgram.com/) (Processes 16kHz Raw PCM Data).
2. **Brain (LLM):** [Groq Cloud](https://groq.com/) (Powered by `llama-3.1-8b-instant`).
3. **Text-to-Speech (TTS):** [Deepgram Aura-Asteria](https://deepgram.com/) (Outputs 24kHz Linear16 PCM Stream).

---

## 📦 Required Libraries
Before flashing the code, install the following libraries via the **Arduino Library Manager**:
* **ArduinoJson** (by Benoit Blanchon) - Version 6.x or 7.x
* *Built-in ESP32 Libraries:* `WiFi`, `WiFiClientSecure`, `HTTPClient`, `driver/i2s`

---

## 🚦 How To Run
1. Open the project code in Arduino IDE or VS Code (PlatformIO).
2. Configure your `WIFI_SSID` and `WIFI_PASSWORD`.
3. Generate your own API keys from **Groq** and **Deepgram** consoles and paste them into the code.
4. Select board as **XIAO_ESP32S3** and Flash the code.
5. Open the Serial Monitor at **115200 baud rate**.
6. **To Talk:** Hold the **BOOT button**, speak within 4 seconds, and release to hear the response!