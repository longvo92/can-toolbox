"""Columnar storage for CAN and CAN FD frames.

One NumPy array per field keeps millions of frames in a compact, vectorizable
form. Payloads of all frames share one flat ``uint8`` buffer addressed through
``offsets`` so classic frames do not pay for 64-byte CAN FD rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

FLAG_EXTENDED = 0x01
FLAG_FD = 0x02
FLAG_BRS = 0x04
FLAG_ESI = 0x08
FLAG_REMOTE = 0x10
FLAG_ERROR = 0x20
FLAG_RX = 0x40

_FD_LENGTHS = np.asarray([0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64], dtype=np.uint8)


def dlc_to_length(dlc: np.ndarray | int) -> np.ndarray | int:
    """Map CAN FD DLC codes 0-15 to payload byte counts."""
    if isinstance(dlc, (int, np.integer)):
        return int(_FD_LENGTHS[min(int(dlc), 15)])
    return _FD_LENGTHS[np.minimum(np.asarray(dlc), 15)]


@dataclass(frozen=True, eq=False)
class FrameTable:
    """Frames in file order.

    ``time_ns`` counts nanoseconds from ``start_time`` (epoch seconds, ``0.0``
    when the log does not record a wall-clock start). ``channel`` is the bus
    channel as Vector tools number it, starting at 1; ``0`` means unknown.
    ``dlc`` is the raw DLC code; :meth:`lengths` gives the stored payload size.
    """

    time_ns: np.ndarray
    arbitration_id: np.ndarray
    channel: np.ndarray
    dlc: np.ndarray
    flags: np.ndarray
    offsets: np.ndarray
    payload: np.ndarray
    start_time: float = 0.0

    def __post_init__(self) -> None:
        n = len(self.time_ns)
        columns = (self.arbitration_id, self.channel, self.dlc, self.flags)
        if any(len(column) != n for column in columns) or len(self.offsets) != n + 1:
            raise ValueError("FrameTable columns must have the same length")
        if n and int(self.offsets[-1]) != len(self.payload):
            raise ValueError("FrameTable offsets do not cover the payload buffer")

    @classmethod
    def empty(cls, start_time: float = 0.0) -> FrameTable:
        return cls(
            time_ns=np.zeros(0, np.int64),
            arbitration_id=np.zeros(0, np.uint32),
            channel=np.zeros(0, np.uint16),
            dlc=np.zeros(0, np.uint8),
            flags=np.zeros(0, np.uint8),
            offsets=np.zeros(1, np.int64),
            payload=np.zeros(0, np.uint8),
            start_time=start_time,
        )

    @classmethod
    def concat(cls, tables: Sequence[FrameTable], start_time: float | None = None) -> FrameTable:
        if not tables:
            return cls.empty(start_time or 0.0)
        if len(tables) == 1 and start_time is None:
            return tables[0]
        base = tables[0].start_time if start_time is None else start_time
        shifted = []
        for table in tables:
            delta_ns = round((table.start_time - base) * 1e9) if table.start_time != base else 0
            shifted.append(table.time_ns + np.int64(delta_ns))
        payload_sizes = np.cumsum([0] + [len(table.payload) for table in tables[:-1]])
        offsets = [np.zeros(1, np.int64)]
        offsets += [table.offsets[1:] + size for table, size in zip(tables, payload_sizes)]
        return cls(
            time_ns=np.concatenate(shifted),
            arbitration_id=np.concatenate([table.arbitration_id for table in tables]),
            channel=np.concatenate([table.channel for table in tables]),
            dlc=np.concatenate([table.dlc for table in tables]),
            flags=np.concatenate([table.flags for table in tables]),
            offsets=np.concatenate(offsets),
            payload=np.concatenate([table.payload for table in tables]),
            start_time=base,
        )

    def __len__(self) -> int:
        return len(self.time_ns)

    @property
    def nbytes(self) -> int:
        arrays = (self.time_ns, self.arbitration_id, self.channel, self.dlc, self.flags, self.offsets, self.payload)
        return sum(array.nbytes for array in arrays)

    def lengths(self) -> np.ndarray:
        return np.diff(self.offsets)

    def seconds(self) -> np.ndarray:
        """Seconds since ``start_time``."""
        return self.time_ns / 1e9

    def timestamps(self) -> np.ndarray:
        """Absolute timestamps in epoch seconds, as python-can reports them."""
        return self.start_time + self.time_ns / 1e9

    def has_flag(self, flag: int) -> np.ndarray:
        return (self.flags & flag) != 0

    def data(self, index: int) -> bytes:
        return self.payload[self.offsets[index] : self.offsets[index + 1]].tobytes()

    def take(self, indices: np.ndarray) -> FrameTable:
        """Return the frames at ``indices`` (an index array or boolean mask), in that order."""
        indices = np.asarray(indices)
        if indices.dtype == np.bool_:
            indices = np.flatnonzero(indices)
        lengths = self.lengths()[indices]
        offsets = np.zeros(len(indices) + 1, np.int64)
        np.cumsum(lengths, out=offsets[1:])
        return FrameTable(
            time_ns=self.time_ns[indices],
            arbitration_id=self.arbitration_id[indices],
            channel=self.channel[indices],
            dlc=self.dlc[indices],
            flags=self.flags[indices],
            offsets=offsets,
            payload=self.payload[_gather_ranges(self.offsets[indices], lengths)],
            start_time=self.start_time,
        )

    def payload_matrix(self, indices: np.ndarray, width: int) -> np.ndarray:
        """Payloads of ``indices`` as a zero-padded ``(len(indices), width)`` matrix."""
        indices = np.asarray(indices)
        matrix = np.zeros((len(indices), width), np.uint8)
        if not len(indices):
            return matrix
        lengths = np.minimum(self.lengths()[indices], width)
        starts = self.offsets[indices]
        rows = np.repeat(np.arange(len(indices)), lengths)
        cols = np.arange(int(lengths.sum())) - np.repeat(np.cumsum(lengths) - lengths, lengths)
        matrix[rows, cols] = self.payload[np.repeat(starts, lengths) + cols]
        return matrix


def _gather_ranges(starts: np.ndarray, lengths: np.ndarray) -> np.ndarray:
    """Concatenate ``range(start, start + length)`` for every pair, vectorized."""
    total = int(lengths.sum())
    if not total:
        return np.zeros(0, np.int64)
    ends = np.cumsum(lengths)
    return np.repeat(starts - (ends - lengths), lengths) + np.arange(total)
