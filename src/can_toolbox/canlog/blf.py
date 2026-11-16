"""Fast reader for Vector BLF logs into a :class:`FrameTable`.

The object layout follows python-can's ``BLFReader`` (itself based on Toby
Lorenz' Vector BLF library) and yields the same frames, but decompressed
containers are scanned by a compiled kernel instead of one Python object per
frame. Object types other than CAN, CAN FD and CAN error frames are counted in
:attr:`BlfInfo.skipped_objects` rather than silently dropped.
"""

from __future__ import annotations

import datetime
import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from can_toolbox.canlog.jit import njit
from can_toolbox.canlog.table import (
    FLAG_BRS,
    FLAG_ERROR,
    FLAG_ESI,
    FLAG_EXTENDED,
    FLAG_FD,
    FLAG_REMOTE,
    FLAG_RX,
    FrameTable,
)

_FILE_HEADER = struct.Struct("<4sLBBBBBBBBQQLL8H8H")
_OBJ_HEADER_BASE = struct.Struct("<4sHHLL")
_LOG_CONTAINER = struct.Struct("<H6xL4x")

LOG_CONTAINER = 10
_NO_COMPRESSION = 0
_ZLIB_DEFLATE = 2

# Decompressed bytes handed to the kernel at once: large enough to amortize the
# call, small enough to keep the per-chunk scratch arrays modest.
_CHUNK_BYTES = 32 * 1024 * 1024
_MIN_FRAME_OBJECT = 48
_TYPE_SLOTS = 1024

OBJECT_TYPE_NAMES = {
    1: "CAN message",
    10: "log container",
    65: "app text",
    73: "CAN error",
    86: "CAN message",
    96: "global marker",
    100: "CAN FD message",
    101: "CAN FD message",
}

ProgressCallback = Callable[[int, int], None]
CancelCallback = Callable[[], bool]


class BlfError(RuntimeError):
    """The file is not a readable BLF log."""


class ReadCancelled(RuntimeError):
    """The caller asked to stop reading."""


@dataclass(frozen=True)
class BlfInfo:
    application_id: int
    application_version: tuple[int, int, int]
    start_time: float
    stop_time: float
    object_count: int
    file_size: int
    skipped_objects: dict[int, int] = field(default_factory=dict)
    trailing_bytes: int = 0

    def skipped_summary(self) -> str:
        parts = [
            f"{count} {OBJECT_TYPE_NAMES.get(kind, f'type {kind}')}"
            for kind, count in sorted(self.skipped_objects.items())
        ]
        return ", ".join(parts)


def _systemtime_to_timestamp(values: tuple[int, ...]) -> float:
    try:
        moment = datetime.datetime(
            values[0], values[1], values[3], values[4], values[5], values[6], values[7] * 1000,
            tzinfo=datetime.timezone.utc,
        )
    except ValueError:
        return 0.0
    return moment.timestamp()


def _read_header(stream, path: Path) -> tuple[BlfInfo, int]:
    raw = stream.read(_FILE_HEADER.size)
    if len(raw) < _FILE_HEADER.size:
        raise BlfError(f"Not a BLF file (header too short): {path}")
    header = _FILE_HEADER.unpack(raw)
    if header[0] != b"LOGG":
        raise BlfError(f"Not a BLF file (missing LOGG signature): {path}")
    info = BlfInfo(
        application_id=header[2],
        application_version=(header[3], header[4], header[5]),
        start_time=_systemtime_to_timestamp(header[14:22]),
        stop_time=_systemtime_to_timestamp(header[22:30]),
        object_count=header[12],
        file_size=header[10],
    )
    return info, header[1]


def read_blf(
    path: Path,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> tuple[FrameTable, BlfInfo]:
    """Read every CAN, CAN FD and CAN error frame of ``path`` in file order.

    ``progress(done_bytes, total_bytes)`` reports file position; ``cancel()``
    returning true raises :class:`ReadCancelled`.
    """
    path = Path(path)
    total = path.stat().st_size
    chunks: list[FrameTable] = []
    skipped = np.zeros(_TYPE_SLOTS, np.int64)
    pending: list[bytes] = []
    pending_size = 0
    tail = b""

    with open(path, "rb") as stream:
        info, header_size = _read_header(stream, path)
        stream.seek(header_size)

        def flush() -> None:
            nonlocal tail, pending_size
            if not pending and not tail:
                return
            buffer = np.frombuffer(b"".join([tail, *pending]), dtype=np.uint8)
            pending.clear()
            pending_size = 0
            table, consumed = _scan_buffer(buffer, info.start_time, skipped, path)
            if len(table):
                chunks.append(table)
            tail = buffer[consumed:].tobytes()

        while True:
            if cancel is not None and cancel():
                raise ReadCancelled(f"Reading cancelled: {path}")
            raw = stream.read(_OBJ_HEADER_BASE.size)
            if not raw:
                break
            if len(raw) < _OBJ_HEADER_BASE.size:
                break
            signature, _, _, obj_size, obj_type = _OBJ_HEADER_BASE.unpack(raw)
            if signature != b"LOBJ":
                raise BlfError(f"Corrupt BLF: expected an object at byte {stream.tell() - len(raw)} of {path}")
            body = stream.read(obj_size - _OBJ_HEADER_BASE.size)
            stream.read(obj_size % 4)
            if obj_type != LOG_CONTAINER:
                skipped[min(obj_type, _TYPE_SLOTS - 1)] += 1
                continue
            method, _ = _LOG_CONTAINER.unpack_from(body)
            data = body[_LOG_CONTAINER.size :]
            if method == _ZLIB_DEFLATE:
                data = zlib.decompressobj().decompress(data)
            elif method != _NO_COMPRESSION:
                skipped[LOG_CONTAINER] += 1
                continue
            pending.append(data)
            pending_size += len(data)
            if pending_size >= _CHUNK_BYTES:
                flush()
                if progress is not None:
                    progress(stream.tell(), total)
        flush()

    if progress is not None:
        progress(total, total)
    kinds = {int(kind): int(count) for kind, count in enumerate(skipped) if count}
    info = BlfInfo(
        application_id=info.application_id,
        application_version=info.application_version,
        start_time=info.start_time,
        stop_time=info.stop_time,
        object_count=info.object_count,
        file_size=info.file_size,
        skipped_objects=kinds,
        trailing_bytes=len(tail),
    )
    return FrameTable.concat(chunks, start_time=info.start_time) if chunks else FrameTable.empty(info.start_time), info


def _scan_buffer(buffer: np.ndarray, start_time: float, skipped: np.ndarray, path: Path) -> tuple[FrameTable, int]:
    capacity = len(buffer) // _MIN_FRAME_OBJECT + 1
    time_ns = np.empty(capacity, np.int64)
    ids = np.empty(capacity, np.uint32)
    channel = np.empty(capacity, np.uint16)
    dlc = np.empty(capacity, np.uint8)
    flags = np.empty(capacity, np.uint8)
    offsets = np.empty(capacity + 1, np.int64)
    payload = np.empty(len(buffer), np.uint8)
    consumed, count, status = _scan_objects(buffer, time_ns, ids, channel, dlc, flags, offsets, payload, skipped)
    if status:
        raise BlfError(f"Corrupt BLF: no object signature near decompressed byte {consumed} of {path}")
    used = int(offsets[count])
    table = FrameTable(
        time_ns=time_ns[:count].copy(),
        arbitration_id=ids[:count].copy(),
        channel=channel[:count].copy(),
        dlc=dlc[:count].copy(),
        flags=flags[:count].copy(),
        offsets=offsets[: count + 1].copy(),
        payload=payload[:used].copy(),
        start_time=start_time,
    )
    return table, consumed


@njit
def _u16(buf, p):
    return np.int64(buf[p]) | (np.int64(buf[p + 1]) << 8)


@njit
def _u32(buf, p):
    return _u16(buf, p) | (_u16(buf, p + 2) << 16)


@njit
def _u64(buf, p):
    return _u32(buf, p) | (_u32(buf, p + 4) << 32)


@njit
def _find_signature(buf, pos, n):
    # python-can accepts up to four padding bytes before the next "LOBJ".
    for candidate in range(pos, min(pos + 5, n - 3)):
        if buf[candidate] == 76 and buf[candidate + 1] == 79 and buf[candidate + 2] == 66 and buf[candidate + 3] == 74:
            return candidate
    return -1


@njit
def _scan_objects(buf, time_ns, ids, channel, dlc, flags, offsets, payload, skipped):
    """Scan concatenated container data; return (consumed, frames, status)."""
    n = len(buf)
    pos = 0
    count = 0
    used = 0
    offsets[0] = 0
    while True:
        start = pos
        found = _find_signature(buf, pos, n)
        if found < 0:
            if pos + 8 > n:
                return start, count, 0
            return start, count, 1
        pos = found
        if pos + 16 > n:
            return start, count, 0
        header_size = _u16(buf, pos + 4)
        header_version = _u16(buf, pos + 6)
        obj_size = _u32(buf, pos + 8)
        obj_type = _u32(buf, pos + 12)
        next_pos = pos + obj_size
        if next_pos > n:
            return start, count, 0
        p = pos + 16
        if header_version == 1:
            time_flags = _u32(buf, p)
            stamp = _u64(buf, p + 8)
            p += 16
        elif header_version == 2:
            time_flags = _u32(buf, p)
            stamp = _u64(buf, p + 8)
            p += 24
        else:
            skipped[min(obj_type, len(skipped) - 1)] += 1
            pos = next_pos
            continue
        ns = stamp * 10000 if time_flags == 1 else stamp

        if obj_type == 1 or obj_type == 86:
            if p + 16 > n:
                return start, count, 0
            raw_dlc = buf[p + 3]
            can_id = _u32(buf, p + 4)
            bits = 0 if buf[p + 2] & 1 else FLAG_RX
            if buf[p + 2] & 0x80:
                bits |= FLAG_REMOTE
            length = min(np.int64(raw_dlc), 8)
            data_at = p + 8
            chan = _u16(buf, p)
        elif obj_type == 73:
            if p + 32 > n:
                return start, count, 0
            raw_dlc = buf[p + 10]
            can_id = _u32(buf, p + 16)
            bits = FLAG_ERROR | FLAG_RX
            length = min(np.int64(raw_dlc), 8)
            data_at = p + 24
            chan = _u16(buf, p)
        elif obj_type == 100:
            if p + 84 > n:
                return start, count, 0
            raw_dlc = buf[p + 3]
            can_id = _u32(buf, p + 4)
            fd_flags = buf[p + 13]
            bits = 0 if buf[p + 2] & 1 else FLAG_RX
            if buf[p + 2] & 0x80:
                bits |= FLAG_REMOTE
            if fd_flags & 1:
                bits |= FLAG_FD
            if fd_flags & 2:
                bits |= FLAG_BRS
            if fd_flags & 4:
                bits |= FLAG_ESI
            length = min(np.int64(buf[p + 14]), 64)
            data_at = p + 20
            chan = _u16(buf, p)
        elif obj_type == 101:
            if p + 40 > n:
                return start, count, 0
            raw_dlc = buf[p + 1]
            valid = np.int64(buf[p + 2])
            can_id = _u32(buf, p + 4)
            fd_flags = _u32(buf, p + 12)
            ext_offset = np.int64(buf[p + 35])
            bits = FLAG_RX if buf[p + 34] == 0 else 0
            if fd_flags & 0x0010:
                bits |= FLAG_REMOTE
            if fd_flags & 0x1000:
                bits |= FLAG_FD
            if fd_flags & 0x2000:
                bits |= FLAG_BRS
            if fd_flags & 0x4000:
                bits |= FLAG_ESI
            limit = (ext_offset if ext_offset else obj_size) - header_size - 40
            available = min(valid, max(limit, 0))
            data_at = p + 40
            chan = np.int64(buf[p])
            # CANoe pads a short data field with zeros up to the valid length.
            if bits & FLAG_REMOTE:
                valid = 0
            for k in range(valid):
                payload[used + k] = buf[data_at + k] if k < available else 0
            time_ns[count] = ns
            ids[count] = can_id & 0x1FFFFFFF
            channel[count] = chan
            dlc[count] = raw_dlc
            flags[count] = bits | (FLAG_EXTENDED if can_id & 0x80000000 else 0)
            used += valid
            count += 1
            offsets[count] = used
            pos = next_pos
            continue
        else:
            skipped[min(obj_type, len(skipped) - 1)] += 1
            pos = next_pos
            continue

        if bits & FLAG_REMOTE:
            # python-can and CANoe show no payload for remote frames.
            length = 0
        for k in range(length):
            payload[used + k] = buf[data_at + k]
        time_ns[count] = ns
        ids[count] = can_id & 0x1FFFFFFF
        channel[count] = chan
        dlc[count] = raw_dlc
        flags[count] = bits | (FLAG_EXTENDED if can_id & 0x80000000 else 0)
        used += length
        count += 1
        offsets[count] = used
        pos = next_pos
