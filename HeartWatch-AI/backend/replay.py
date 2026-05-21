# ============================================================
# HeartWatch AI - Replay System
# ============================================================
# WHY: Replay saved CSV recordings through the system
# as if they were live data from the sensor.
# Great for demos and testing without hardware.
# ============================================================

import csv
import time
import os
from config import SAMPLE_RATE


class ECGRecorder:
    """Records live ECG data to CSV for later replay."""

    def __init__(self, filename):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        self.filename = filename
        self.samples = []

    def add_sample(self, timestamp, value):
        self.samples.append((timestamp, value))

    def save(self):
        with open(self.filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp_ms', 'value'])
            for ts, val in self.samples:
                writer.writerow([round(ts, 1), val])
        print(f"Recording saved: {self.filename} ({len(self.samples)} samples)")


class ECGReplayer:
    """Replays a saved CSV recording."""

    def __init__(self, filename, fs=250):
        self.filename = filename
        self.fs = fs
        self.samples = []
        self.index = 0
        self._load()

    def _load(self):
        """Load CSV into memory."""
        if not os.path.exists(self.filename):
            print(f"File not found: {self.filename}")
            return

        with open(self.filename, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.samples.append({
                    'ts': float(row['timestamp_ms']),
                    'val': int(row['value'])
                })
        print(f"Loaded {len(self.samples)} samples from {self.filename}")

    def get_batch(self, batch_size=50):
        """Get next batch of samples (simulates ESP32 sending 50 at a time)."""
        if self.index >= len(self.samples):
            self.index = 0  # loop back to start

        end = min(self.index + batch_size, len(self.samples))
        batch = self.samples[self.index:end]
        self.index = end

        return [(s['ts'], s['val']) for s in batch]

    def is_done(self):
        return self.index >= len(self.samples)

    def reset(self):
        self.index = 0

    def get_total_duration(self):
        if not self.samples:
            return 0
        return self.samples[-1]['ts'] / 1000.0  # seconds
