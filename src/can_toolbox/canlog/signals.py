"""Signal time series and the catalog of decodable signals in a log (Qt-free)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from can_toolbox.canlog.decode import MessageCodec, rows_by_message
from can_toolbox.canlog.refs import SignalRef
from can_toolbox.canlog.view import LogView

__all__ = ["CatalogEntry", "SignalRef", "SignalSeries", "SignalSource"]

# Half a microsecond: closer than any CAN timestamp, so a cursor sitting exactly
# on a change still steps to the next one.
_CHANGE_EPSILON = 5e-7


@dataclass(frozen=True)
class SignalSeries:
    ref: SignalRef
    # Seconds relative to the view origin (the first frame), like the trace.
    time: np.ndarray
    values: np.ndarray
    unit: str = ""
    choices: dict[int, str] = field(default_factory=dict)
    minimum: float | None = None
    maximum: float | None = None
    scale: float = 1.0
    offset: float = 0.0

    def value_at(self, seconds: float) -> float | None:
        """Sample-and-hold value at ``seconds``; ``None`` before the first sample."""
        index = int(np.searchsorted(self.time, seconds, side="right")) - 1
        return None if index < 0 or not len(self.values) else float(self.values[index])

    def extrema(self, low: float, high: float) -> tuple[float, float] | None:
        """Smallest and largest held value between ``low`` and ``high``.

        Sample-and-hold means the sample before ``low`` is still on screen, so
        it counts. ``None`` when the signal has no sample at or before ``high``.
        """
        if not len(self.time) or high < low:
            return None
        start = max(int(np.searchsorted(self.time, low, side="right")) - 1, 0)
        stop = int(np.searchsorted(self.time, high, side="right"))
        if stop <= start:
            return None
        window = self.values[start:stop]
        return (float(np.min(window)), float(np.max(window)))

    def change_times(self) -> np.ndarray:
        """Times at which the held value changes, the first sample included."""
        if not len(self.time):
            return np.zeros(0)
        changed = np.flatnonzero(self.values[1:] != self.values[:-1]) + 1
        return np.concatenate(([self.time[0]], self.time[changed]))

    def next_change(self, seconds: float, *, forward: bool = True) -> float | None:
        """The next (or previous) time this signal takes a new value.

        ``None`` when there is none in that direction, so a cursor at the last
        change stays where it is.
        """
        times = self.change_times()
        if not len(times):
            return None
        if forward:
            later = times[times > seconds + _CHANGE_EPSILON]
            return float(later[0]) if len(later) else None
        earlier = times[times < seconds - _CHANGE_EPSILON]
        return float(earlier[-1]) if len(earlier) else None

    def text_at(self, seconds: float) -> str:
        value = self.value_at(seconds)
        if value is None:
            return ""
        if self.choices:
            # Value tables are keyed by raw value. The named value is the whole text:
            # the number behind it has its own column.
            raw = round((value - self.offset) / self.scale) if self.scale else None
            if raw in self.choices:
                return str(self.choices[raw])
        return f"{value:.6g} {self.unit}".rstrip()


@dataclass(frozen=True)
class CatalogEntry:
    channel: int
    key: int
    message: str
    frames: int
    signals: tuple[str, ...]


class SignalSource:
    """Decode signals of a :class:`LogView` on demand, one message at a time.

    All signals of a message are decoded together and cached, so adding a
    second signal of the same message to a graph costs nothing.
    """

    def __init__(self, view: LogView) -> None:
        self.view = view
        self._groups: dict[int, np.ndarray] | None = None
        self._decoded: dict[tuple[int, int], dict[str, tuple[np.ndarray, np.ndarray]]] = {}

    def _rows(self) -> dict[int, np.ndarray]:
        if self._groups is None:
            self._groups = rows_by_message(self.view.frames)
        return self._groups

    def catalog(self) -> list[CatalogEntry]:
        """Messages present in the log that a DBC describes, by channel and ID."""
        frames = self.view.frames
        entries = []
        for key, rows in sorted(self._rows().items()):
            channels, counts = np.unique(frames.channel[rows], return_counts=True)
            for channel, count in zip(channels.tolist(), counts.tolist()):
                codec = self.view.database.codec(key, channel)
                if codec is None:
                    continue
                names = tuple(signal.name for signal in codec.message.signals)
                entries.append(CatalogEntry(channel, key, codec.name, count, names))
        entries.sort(key=lambda entry: (entry.channel, entry.message.casefold(), entry.key))
        return entries

    def series(self, ref: SignalRef) -> SignalSeries:
        codec = self.view.database.codec(ref.key, ref.channel)
        if codec is None or codec.name != ref.message:
            raise KeyError(f"No DBC message {ref.message} for ID key {ref.key:#x} on CAN {ref.channel}")
        decoded = self._decode(codec, ref.channel)
        if ref.signal not in {signal.name for signal in codec.message.signals}:
            raise KeyError(f"{ref.message} has no signal {ref.signal}")
        rows, values = decoded.get(ref.signal, (np.zeros(0, np.int64), np.zeros(0)))
        frames = self.view.frames
        times = (frames.time_ns[rows] - self.view.origin_ns) / 1e9
        if len(times) > 1 and not bool(np.all(times[1:] >= times[:-1])):
            order = np.argsort(times, kind="stable")
            times, values = times[order], values[order]
        signal = codec.message.get_signal_by_name(ref.signal)
        choices = {int(raw): str(text) for raw, text in (signal.conversion.choices or {}).items()}
        return SignalSeries(
            ref=ref,
            time=times,
            values=values,
            unit=signal.unit or "",
            choices=choices,
            minimum=signal.minimum,
            maximum=signal.maximum,
            scale=float(signal.scale),
            offset=float(signal.offset),
        )

    def _decode(self, codec: MessageCodec, channel: int) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        cache_key = (codec.key, channel)
        if cache_key not in self._decoded:
            rows = self._rows().get(codec.key, np.zeros(0, np.int64))
            rows = rows[self.view.frames.channel[rows] == channel]
            self._decoded[cache_key] = codec.decode(self.view.frames, rows)
        return self._decoded[cache_key]
