"""A filtered, time-ordered view of a log for trace windows and statistics (Qt-free)."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from can_toolbox.canlog.database import LogDatabase
from can_toolbox.canlog.decode import frame_keys
from can_toolbox.canlog.reader import LogFile
from can_toolbox.canlog.table import (
    FLAG_BRS,
    FLAG_ERROR,
    FLAG_EXTENDED,
    FLAG_FD,
    FLAG_REMOTE,
    FLAG_RX,
    FrameTable,
)

_HEX_ID = re.compile(r"^(?:0x)?([0-9a-f]+)(x?)$", re.IGNORECASE)


@dataclass(frozen=True)
class IdMatch:
    low: int
    high: int
    # None matches standard and extended identifiers.
    extended: bool | None = None


@dataclass(frozen=True)
class FrameQuery:
    """Identifiers, ID ranges and message-name fragments; a frame matching any term passes.

    Text syntax, terms separated by commas or spaces: ``100`` (hex ID),
    ``18FF0001x`` (extended, CANoe notation), ``100-1FF`` (range) and any
    other word as a case-insensitive message-name fragment.
    """

    ids: tuple[IdMatch, ...] = ()
    names: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> FrameQuery:
        ids: list[IdMatch] = []
        names: list[str] = []
        for term in re.split(r"[,\s;]+", text.strip()):
            if not term:
                continue
            bounds = term.split("-", 1)
            parsed = [_HEX_ID.match(part) for part in bounds]
            if all(parsed) and len(bounds) in (1, 2):
                values = [int(match.group(1), 16) for match in parsed]
                if all(value <= 0x1FFFFFFF for value in values):
                    extended = True if any(match.group(2) for match in parsed) else None
                    ids.append(IdMatch(min(values), max(values), extended))
                    continue
            names.append(term.casefold())
        return cls(tuple(ids), tuple(names))

    def __bool__(self) -> bool:
        return bool(self.ids or self.names)

    def mask(self, table: FrameTable, rows: np.ndarray, names: dict[tuple[int, int], str]) -> np.ndarray:
        """Boolean mask over ``rows``; ``names`` maps (channel, message key) to a message name."""
        if not self:
            return np.ones(len(rows), np.bool_)
        ids = table.arbitration_id[rows]
        extended = table.has_flag(FLAG_EXTENDED)[rows]
        hit = np.zeros(len(rows), np.bool_)
        for match in self.ids:
            term = (ids >= match.low) & (ids <= match.high)
            if match.extended is not None:
                term &= extended == match.extended
            hit |= term
        if self.names:
            pairs = pair_keys(table, rows)
            unique, inverse = np.unique(pairs, return_inverse=True)
            wanted = np.asarray(
                [
                    any(fragment in names.get(_split_pair(int(pair)), "").casefold() for fragment in self.names)
                    for pair in unique
                ],
                np.bool_,
            )
            hit |= wanted[inverse] if len(unique) else np.zeros(len(rows), np.bool_)
        return hit


@dataclass(frozen=True)
class FrameFilter:
    query: FrameQuery = FrameQuery()
    channels: frozenset[int] = frozenset()
    # "all", "rx" or "tx"
    direction: str = "all"
    include_errors: bool = True
    include_remote: bool = True

    def mask(self, table: FrameTable, rows: np.ndarray, names: dict[tuple[int, int], str]) -> np.ndarray:
        flags = table.flags[rows]
        keep = self.query.mask(table, rows, names)
        if self.channels:
            keep &= np.isin(table.channel[rows], np.fromiter(self.channels, np.int64))
        if self.direction == "rx":
            keep &= (flags & FLAG_RX) != 0
        elif self.direction == "tx":
            keep &= (flags & FLAG_RX) == 0
        if not self.include_errors:
            keep &= (flags & FLAG_ERROR) == 0
        if not self.include_remote:
            keep &= (flags & FLAG_REMOTE) == 0
        return keep


def pair_keys(table: FrameTable, rows: np.ndarray | None = None) -> np.ndarray:
    """``channel << 33 | message key`` per frame: one value per (channel, ID, IDE)."""
    channel = table.channel if rows is None else table.channel[rows]
    ids = table.arbitration_id if rows is None else table.arbitration_id[rows]
    extended = table.has_flag(FLAG_EXTENDED) if rows is None else table.has_flag(FLAG_EXTENDED)[rows]
    return (channel.astype(np.int64) << 33) | ids.astype(np.int64) | (extended.astype(np.int64) << 31)


def _split_pair(pair: int) -> tuple[int, int]:
    return pair >> 33, pair & 0xFFFFFFFF


@dataclass(frozen=True)
class MessageStats:
    channel: int
    key: int
    name: str
    count: int
    first_s: float
    last_s: float
    cycle_min_ms: float | None
    cycle_avg_ms: float | None
    cycle_max_ms: float | None


class LogView:
    """Time-ordered rows of a log with an optional filter.

    ``order`` sorts frames by timestamp (stable, so equal stamps keep file
    order); ``rows`` is the filtered subset that a trace window lists.
    """

    def __init__(self, log: LogFile, database: LogDatabase | None = None) -> None:
        self.log = log
        self.frames = log.frames
        self.database = database or LogDatabase()
        times = self.frames.time_ns
        if len(times) < 2 or bool(np.all(times[1:] >= times[:-1])):
            self.order = np.arange(len(times), dtype=np.int64)
        else:
            self.order = np.argsort(times, kind="stable").astype(np.int64)
        self._pairs = pair_keys(self.frames)
        self._names: dict[tuple[int, int], str] = {}
        self.set_database(self.database)
        self.filter = FrameFilter()
        self.rows = self.order

    @property
    def origin_ns(self) -> int:
        return int(self.frames.time_ns[self.order[0]]) if len(self.order) else 0

    def set_database(self, database: LogDatabase) -> None:
        self.database = database
        self._names = {}
        for pair in np.unique(self._pairs):
            channel, key = _split_pair(int(pair))
            name = database.message_name(key, channel) if database else ""
            if name:
                self._names[(channel, key)] = name

    def message_name(self, row: int) -> str:
        channel, key = _split_pair(int(self._pairs[row]))
        return self._names.get((channel, key), "")

    def apply(self, frame_filter: FrameFilter) -> np.ndarray:
        self.filter = frame_filter
        self.rows = self.order[frame_filter.mask(self.frames, self.order, self._names)]
        return self.rows

    def find(self, query: FrameQuery, start: int, forward: bool = True) -> int:
        """Position in :attr:`rows` of the next match after ``start`` (wrapping), or -1."""
        if not query or not len(self.rows):
            return -1
        hits = np.flatnonzero(query.mask(self.frames, self.rows, self._names))
        if not len(hits):
            return -1
        if forward:
            later = hits[hits > start]
            return int(later[0] if len(later) else hits[0])
        earlier = hits[hits < start]
        return int(earlier[-1] if len(earlier) else hits[-1])

    def position_at_time(self, time_ns: int) -> int:
        """Position in :attr:`rows` of the last frame at or before ``time_ns`` (0 when none)."""
        times = self.frames.time_ns[self.rows]
        return max(int(np.searchsorted(times, time_ns, side="right")) - 1, 0)

    def latest_per_message(self, upto_ns: int | None = None) -> np.ndarray:
        """Rows of the newest frame per (channel, ID) for a fixed-position trace, sorted by channel and ID."""
        rows = self.rows
        if upto_ns is not None:
            rows = rows[self.frames.time_ns[rows] <= upto_ns]
        if not len(rows):
            return rows
        # np.unique returns pairs sorted by channel, IDE and ID; on the reversed
        # rows its first occurrence is the newest frame.
        _, first = np.unique(self._pairs[rows][::-1], return_index=True)
        return rows[::-1][first]

    def statistics(self) -> list[MessageStats]:
        rows = self.rows
        if not len(rows):
            return []
        data_rows = rows[frame_keys(self.frames)[rows] >= 0]
        pairs = self._pairs[data_rows]
        order = np.lexsort((self.frames.time_ns[data_rows], pairs))
        sorted_rows = data_rows[order]
        sorted_pairs = pairs[order]
        times = self.frames.time_ns[sorted_rows]
        bounds = np.flatnonzero(np.diff(sorted_pairs)) + 1
        starts = np.concatenate(([0], bounds))
        ends = np.concatenate((bounds, [len(sorted_rows)]))
        origin = self.origin_ns
        result = []
        for start, end in zip(starts, ends):
            channel, key = _split_pair(int(sorted_pairs[start]))
            span = times[start:end]
            gaps = np.diff(span) / 1e6
            result.append(
                MessageStats(
                    channel=channel,
                    key=key,
                    name=self._names.get((channel, key), ""),
                    count=int(end - start),
                    first_s=(int(span[0]) - origin) / 1e9,
                    last_s=(int(span[-1]) - origin) / 1e9,
                    cycle_min_ms=float(gaps.min()) if len(gaps) else None,
                    cycle_avg_ms=float(gaps.mean()) if len(gaps) else None,
                    cycle_max_ms=float(gaps.max()) if len(gaps) else None,
                )
            )
        return result


def format_id(arbitration_id: int, extended: bool) -> str:
    """Hex identifier in CANoe notation: extended IDs carry an ``x`` suffix."""
    return f"{arbitration_id:X}x" if extended else f"{arbitration_id:X}"


def format_key(key: int) -> str:
    return format_id(key & 0x1FFFFFFF, bool(key & 0x80000000))


def format_data(data: bytes) -> str:
    return data.hex(" ").upper()


def frame_type(flags: int) -> str:
    if flags & FLAG_ERROR:
        return "Error"
    if flags & FLAG_REMOTE:
        return "Remote"
    if flags & FLAG_FD:
        return "CAN FD BRS" if flags & FLAG_BRS else "CAN FD"
    return "CAN"
