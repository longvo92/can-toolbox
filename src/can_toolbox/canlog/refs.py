"""Light identifiers shared by the engine and the GUI (no NumPy or Numba import)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SignalRef:
    """One DBC signal as seen on one bus channel."""

    channel: int
    key: int
    message: str
    signal: str

    @property
    def label(self) -> str:
        return f"{self.signal} ({self.message}, CAN {self.channel})"
