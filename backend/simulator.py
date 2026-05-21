# ═══════════════════════════════════════════════════════════════
# HeartWatch AI — ECG Simulator
# ═══════════════════════════════════════════════════════════════
# WHY this file exists:
# No hardware yet? This generates realistic fake ECG data so
# we can test the entire system (backend + frontend) end-to-end.
#
# Generates 3 types:
# 1. Normal sinus rhythm (~75 BPM, regular)
# 2. Tachycardia (~120 BPM, fast)
# 3. Irregular rhythm (varying RR intervals)
# ═══════════════════════════════════════════════════════════════

import numpy as np
import time
import csv
import os
from config import SAMPLE_RATE


def generate_ecg_beat(fs=250):
    """
    Generate one realistic ECG beat waveform (PQRST complex).

    A real ECG beat has 5 waves:
    P wave (atrial contraction) → QRS complex (ventricular contraction) → T wave (recovery)

    We approximate this with Gaussian pulses at the right positions.
    """
    # One beat duration (will be stretched based on heart rate)
    t = np.linspace(0, 1, fs)

    # P wave: small bump at ~0.2s
    p_wave = 0.15 * np.exp(-((t - 0.2) ** 2) / (2 * 0.01 ** 2))

    # QRS complex: tall sharp spike at ~0.35s
    q_wave = -0.1 * np.exp(-((t - 0.32) ** 2) / (2 * 0.005 ** 2))
    r_wave = 1.0 * np.exp(-((t - 0.35) ** 2) / (2 * 0.005 ** 2))
    s_wave = -0.15 * np.exp(-((t - 0.38) ** 2) / (2 * 0.005 ** 2))

    # T wave: medium bump at ~0.55s
    t_wave = 0.3 * np.exp(-((t - 0.55) ** 2) / (2 * 0.02 ** 2))

    beat = p_wave + q_wave + r_wave + s_wave + t_wave
    return beat


def generate_ecg_signal(duration_sec=30, bpm=75, irregular=False, fs=250):
    """
    Generate a multi-beat ECG signal.

    Args:
        duration_sec: how many seconds of ECG to generate
        bpm: heart rate in beats per minute
        irregular: if True, vary the RR intervals randomly
        fs: sampling rate

    Returns:
        tuple of (signal_values, timestamps)
    """
    total_samples = int(duration_sec * fs)
    signal = np.zeros(total_samples)
    beat_template = generate_ecg_beat(fs)
    beat_len = len(beat_template)

    # Calculate samples per beat
    samples_per_beat = int((60.0 / bpm) * fs)

    # Place beats along the signal
    pos = 0
    while pos + beat_len < total_samples:
        # Add the beat waveform
        signal[pos:pos + beat_len] += beat_template

        # Move to next beat
        if irregular:
            # Vary RR interval by +/- 30% for irregular rhythm
            variation = np.random.uniform(0.7, 1.3)
            step = int(samples_per_beat * variation)
        else:
            # Regular rhythm with tiny natural variation (+/- 3%)
            variation = np.random.uniform(0.97, 1.03)
            step = int(samples_per_beat * variation)

        pos += step

    # Scale to ADC-like range (0-4095) similar to ESP32 output
    # Shift baseline and scale
    signal = signal * 500 + 2048  # center around 2048
    signal += np.random.normal(0, 15, total_samples)  # add realistic noise
    signal = np.clip(signal, 0, 4095).astype(int)

    # Generate timestamps (milliseconds)
    timestamps = np.arange(total_samples) * (1000.0 / fs)

    return signal.tolist(), timestamps.tolist()


def save_recording(filename, signal, timestamps):
    """Save ECG signal to CSV file for replay later."""
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp_ms', 'value'])
        for ts, val in zip(timestamps, signal):
            writer.writerow([round(ts, 1), val])
    print(f"  Saved: {filename} ({len(signal)} samples)")


if __name__ == "__main__":
    print("Generating sample ECG recordings...\n")

    # Normal rhythm
    sig1, ts1 = generate_ecg_signal(duration_sec=30, bpm=75, irregular=False)
    save_recording("recordings/normal_75bpm.csv", sig1, ts1)

    # Tachycardia
    sig2, ts2 = generate_ecg_signal(duration_sec=30, bpm=120, irregular=False)
    save_recording("recordings/tachycardia_120bpm.csv", sig2, ts2)

    # Irregular rhythm
    sig3, ts3 = generate_ecg_signal(duration_sec=30, bpm=80, irregular=True)
    save_recording("recordings/irregular_80bpm.csv", sig3, ts3)

    print(f"\nDone! 3 recordings saved to recordings/ folder.")
