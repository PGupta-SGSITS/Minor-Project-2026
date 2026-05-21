# ═══════════════════════════════════════════════════════════════
# HeartWatch AI — ECG Ring Buffer (Thread-Safe)
# ═══════════════════════════════════════════════════════════════
# WHY this file exists:
# ECG data arrives continuously (250 samples/sec from ESP32).
# We need to store the LAST 10 seconds and auto-discard old data.
#
# Think of it like a conveyor belt — new items go on one end,
# old items fall off the other end automatically.
#
# "Thread-safe" means: the ESP32 POST handler can ADD data
# while WebSocket handler READS data — no crash/corruption.
# ═══════════════════════════════════════════════════════════════

from collections import deque
from threading import Lock


class ECGBuffer:
    """
    Sliding window ring buffer for ECG samples.

    Usage:
        buffer = ECGBuffer(max_size=2500)   # 10 sec at 250 Hz
        buffer.add(timestamp, value)         # ESP32 sends data here
        window = buffer.get_window()         # signal processing reads from here
    """

    def __init__(self, max_size=2500):
        # deque with maxlen = automatic old-data removal.
        # When buffer is full, adding a new item removes the oldest.
        self.buffer = deque(maxlen=max_size)

        # Lock prevents two threads from touching the buffer at the same time.
        self.lock = Lock()

        # Lifetime counter — useful for debugging ("how many samples received total?")
        self.total_received = 0

    def add(self, timestamp, value):
        """
        Add ONE ECG sample. Called when ESP32 sends data via HTTP POST.

        Args:
            timestamp: milliseconds from ESP32's millis() clock
            value: ADC reading 0-4095 (or -1 if leads are disconnected)
        """
        with self.lock:
            self.buffer.append({"ts": timestamp, "val": value})
            self.total_received += 1

    def add_batch(self, samples):
        """
        Add multiple samples at once. Each sample = (timestamp, value).
        More efficient than calling add() 50 times in a loop.
        """
        with self.lock:
            for ts, val in samples:
                self.buffer.append({"ts": ts, "val": val})
                self.total_received += 1

    def get_window(self):
        """
        Get current window of VALID ECG values.

        - Skips leads-off markers (value = -1).
        - Returns a plain list of integers for signal processing.
        """
        with self.lock:
            return [item["val"] for item in self.buffer if item["val"] != -1]

    def get_raw_window(self):
        """Get ALL samples including leads-off markers (-1). For debugging."""
        with self.lock:
            return list(self.buffer)

    def get_size(self):
        """How many samples are currently in the buffer."""
        with self.lock:
            return len(self.buffer)

    def clear(self):
        """Empty the buffer completely."""
        with self.lock:
            self.buffer.clear()

    def __len__(self):
        return self.get_size()
