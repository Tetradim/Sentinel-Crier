"""Local clock continuity for new entries; not a cross-device time authority."""
import math
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class EntryTime:
    effective: float
    wall: float


class ClockUncertain(RuntimeError):
    """Reconnect after correcting device time before starting new entries."""


class EntryClock:
    def __init__(self, wall=time.time, monotonic=time.monotonic):
        self.wall,self.monotonic=wall,monotonic
        self.lock=threading.Lock()
        self.anchor_wall,self.anchor_mono=wall(),monotonic()
        self.high_water=self.anchor_wall

    def read(self):
        with self.lock:
            wall,mono=self.wall(),self.monotonic()
            values=(wall,mono,self.anchor_wall,self.anchor_mono)
            if not all(math.isfinite(v) for v in values): raise ClockUncertain()
            elapsed=mono-self.anchor_mono
            expected=self.anchor_wall+elapsed
            if elapsed<0 or abs(wall-expected)>5: raise ClockUncertain()
            self.high_water=max(self.high_water,wall,expected)
            return EntryTime(self.high_water,wall)

    def now(self):
        return self.read().effective
