"""Vectorized DBC signal decoding over a :class:`FrameTable`.

Results match ``cantools.Message.decode(data, decode_choices=False,
scaling=True, allow_truncated=False)`` frame by frame: a frame shorter than
the message length, or one whose multiplexer selects an id the DBC does not
define, yields no value for any signal of that message. Raw values wider
than 53 bits are converted to ``float64`` with ordinary rounding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from can_toolbox.canlog.jit import njit
from can_toolbox.canlog.table import FLAG_ERROR, FLAG_EXTENDED, FLAG_REMOTE, FrameTable

_DATA_FRAME_MASK = FLAG_ERROR | FLAG_REMOTE


def message_key(frame_id: int, is_extended: bool) -> int:
    return int(frame_id) | (0x80000000 if is_extended else 0)


def frame_keys(table: FrameTable) -> np.ndarray:
    """Per-frame ``message_key``; error and remote frames get ``-1``."""
    keys = table.arbitration_id.astype(np.int64)
    keys |= np.where(table.has_flag(FLAG_EXTENDED), np.int64(0x80000000), np.int64(0))
    keys[(table.flags & _DATA_FRAME_MASK) != 0] = -1
    return keys


def rows_by_message(table: FrameTable) -> dict[int, np.ndarray]:
    """Group data-frame row indices by ``message_key``, each group in file order."""
    keys = frame_keys(table)
    order = np.argsort(keys, kind="stable")
    sorted_keys = keys[order]
    bounds = np.flatnonzero(np.diff(sorted_keys)) + 1
    groups = np.split(order, bounds)
    starts = np.concatenate(([0], bounds)) if len(order) else np.zeros(0, np.int64)
    return {int(sorted_keys[start]): group for start, group in zip(starts, groups) if sorted_keys[start] >= 0}


@dataclass(frozen=True)
class SignalLayout:
    name: str
    start: int
    length: int
    big_endian: bool
    signed: bool
    is_float: bool
    scale: float
    offset: float

    @classmethod
    def from_signal(cls, signal: Any) -> SignalLayout:
        big_endian = signal.byte_order == "big_endian"
        start = int(signal.start)
        if big_endian:
            start = 8 * (start // 8) + 7 - start % 8
        return cls(
            name=signal.name,
            start=start,
            length=int(signal.length),
            big_endian=big_endian,
            signed=bool(signal.is_signed),
            is_float=bool(signal.is_float),
            scale=float(signal.scale),
            offset=float(signal.offset),
        )

    def physical(self, matrix: np.ndarray) -> np.ndarray:
        raw = _extract_raw(matrix, self.start, self.length, self.big_endian)
        if self.is_float:
            if self.length == 32:
                with np.errstate(invalid="ignore"):
                    values = raw.astype(np.uint32).view(np.float32).astype(np.float64)
            else:
                values = raw.view(np.float64).copy()
        elif self.signed and self.length < 64:
            sign = np.uint64(1) << np.uint64(self.length - 1)
            values = ((raw ^ sign).astype(np.int64) - np.int64(sign)).astype(np.float64)
        elif self.signed:
            values = raw.view(np.int64).astype(np.float64)
        else:
            values = raw.astype(np.float64)
        if self.scale != 1.0 or self.offset != 0.0:
            values = values * self.scale + self.offset
        return values


@dataclass(frozen=True)
class _Node:
    signals: tuple[SignalLayout, ...]
    # multiplexer signal name -> {multiplexer id -> child node}
    multiplexers: tuple[tuple[str, tuple[tuple[int, _Node], ...]], ...]


class MessageCodec:
    """Decode every signal of one DBC message over many frames at once."""

    def __init__(self, message: Any) -> None:
        self.message = message
        self.name: str = message.name
        self.frame_id = int(message.frame_id)
        self.is_extended = bool(message.is_extended_frame)
        self.key = message_key(self.frame_id, self.is_extended)
        self.length = int(message.length)
        self._root = _build_node(list(message.signals), None, None)
        # cantools cannot decode a message whose signals overrun its length.
        self.decodable = all(
            layout.start + layout.length <= 8 * self.length
            for layout in (SignalLayout.from_signal(signal) for signal in message.signals)
        )

    def decode(
        self, table: FrameTable, rows: np.ndarray, names: set[str] | None = None
    ) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        """Decode ``rows`` (frames of this message); return ``{signal: (rows, values)}``.

        ``names`` limits the result; multiplexer signals are always evaluated.
        """
        rows = np.asarray(rows, np.int64)
        if not self.decodable:
            return {}
        rows = rows[table.lengths()[rows] >= self.length]
        matrix = table.payload_matrix(rows, self.length)
        ok = np.ones(len(rows), np.bool_)
        found: dict[str, tuple[list[np.ndarray], list[np.ndarray]]] = {}
        self._evaluate(self._root, matrix, np.ones(len(rows), np.bool_), ok, names, found)
        result = {}
        for name, (masks, values) in found.items():
            mask = np.zeros(len(rows), np.bool_)
            merged = np.zeros(len(rows), np.float64)
            for part_mask, part_values in zip(masks, values):
                merged[part_mask] = part_values[part_mask]
                mask |= part_mask
            mask &= ok
            result[name] = (rows[mask], merged[mask])
        return result

    def _evaluate(self, node, matrix, active, ok, names, found) -> None:
        if not active.any():
            return
        computed: dict[str, np.ndarray] = {}
        mux_names = {name for name, _ in node.multiplexers}
        for layout in node.signals:
            if names is not None and layout.name not in names and layout.name not in mux_names:
                continue
            values = layout.physical(matrix)
            computed[layout.name] = values
            if names is None or layout.name in names:
                masks, parts = found.setdefault(layout.name, ([], []))
                masks.append(active)
                parts.append(values)
        for mux_name, children in node.multiplexers:
            selector = np.trunc(computed[mux_name])
            known = np.zeros(len(selector), np.bool_)
            for child_id, child in children:
                hit = active & (selector == child_id)
                known |= selector == child_id
                self._evaluate(child, matrix, hit, ok, names, found)
            ok &= ~(active & ~known)


def _build_node(signals: list[Any], parent: str | None, mux_id: int | None) -> _Node:
    members = []
    multiplexers = []
    for signal in signals:
        if signal.multiplexer_signal != parent:
            continue
        if mux_id is not None and (signal.multiplexer_ids is None or mux_id not in signal.multiplexer_ids):
            continue
        if signal.is_multiplexer:
            child_ids: set[int] = set()
            for other in signals:
                if other.multiplexer_signal == signal.name and other.multiplexer_ids is not None:
                    child_ids.update(other.multiplexer_ids)
            if signal.conversion.choices:
                child_ids.update(signal.conversion.choices.keys())
            if child_ids:
                children = tuple((int(cid), _build_node(signals, signal.name, cid)) for cid in sorted(child_ids))
                multiplexers.append((signal.name, children))
        members.append(SignalLayout.from_signal(signal))
    return _Node(tuple(members), tuple(multiplexers))


def _extract_raw(matrix: np.ndarray, start: int, length: int, big_endian: bool) -> np.ndarray:
    if not len(matrix):
        return np.zeros(0, np.uint64)
    return _extract_kernel(np.ascontiguousarray(matrix), start, length, big_endian)


@njit
def _extract_kernel(matrix, start, length, big_endian):
    rows = matrix.shape[0]
    out = np.zeros(rows, np.uint64)
    one = np.uint64(1)
    for r in range(rows):
        value = np.uint64(0)
        if big_endian:
            for j in range(length):
                pos = start + j
                bit = (matrix[r, pos >> 3] >> (7 - (pos & 7))) & 1
                value = (value << one) | np.uint64(bit)
        else:
            for j in range(length):
                pos = start + j
                bit = (matrix[r, pos >> 3] >> (pos & 7)) & 1
                value = value | (np.uint64(bit) << np.uint64(j))
        out[r] = value
    return out
