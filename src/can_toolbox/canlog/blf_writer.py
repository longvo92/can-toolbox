"""Write a :class:`FrameTable` as a Vector BLF log.

Objects use the layouts :mod:`can_toolbox.canlog.blf` reads (CAN_MESSAGE,
CAN_FD_MESSAGE_64, CAN_ERROR_EXT) inside zlib containers, the arrangement
python-can's writer produces and CANoe opens. Timestamps stay exact: the
header start is the table start floored to a millisecond (SYSTEMTIME
resolution) and the remainder is carried in each object's nanosecond offset.
"""

from __future__ import annotations

import datetime
import math
import struct
import zlib
from pathlib import Path

from can_toolbox.canlog.blf import CancelCallback, ProgressCallback, ReadCancelled
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
_FILE_HEADER_SIZE = 144
_OBJ_BASE = struct.Struct("<4sHHLL")
_OBJ_V1 = struct.Struct("<LHHQ")
_CONTAINER = struct.Struct("<H6xL4x")
_CAN_MSG = struct.Struct("<HBBL8s")
_CAN_FD64 = struct.Struct("<BBBBLLLLLLLHBBL")
_CAN_ERROR_EXT = struct.Struct("<HHLBBBxLLH2x8s")
_HEADER_SIZE = _OBJ_BASE.size + _OBJ_V1.size
_TIME_ONE_NANS = 2
_CONTAINER_BYTES = 128 * 1024
_APPLICATION_ID = 5
_PROGRESS_EVERY = 50_000


def _systemtime(epoch_ms: int) -> tuple[int, ...]:
    if epoch_ms <= 0:
        return (0,) * 8
    moment = datetime.datetime.fromtimestamp(epoch_ms / 1000, tz=datetime.timezone.utc)
    return (moment.year, moment.month, moment.isoweekday() % 7, moment.day, moment.hour, moment.minute,
            moment.second, moment.microsecond // 1000)


def _frame_object(table: FrameTable, row: int) -> tuple[int, bytes]:
    flags = int(table.flags[row])
    channel = int(table.channel[row]) or 1
    arbitration = int(table.arbitration_id[row]) | (0x80000000 if flags & FLAG_EXTENDED else 0)
    data = table.data(row)
    dlc = int(table.dlc[row])
    if flags & FLAG_ERROR:
        return 73, _CAN_ERROR_EXT.pack(channel, 0, 0, 0, 0, dlc, 0, arbitration, 0, data[:8].ljust(8, b"\0"))
    if flags & FLAG_FD:
        fd_flags = 0x1000 | (0x2000 if flags & FLAG_BRS else 0) | (0x4000 if flags & FLAG_ESI else 0)
        direction = 0 if flags & FLAG_RX else 1
        head = _CAN_FD64.pack(min(channel, 255), dlc, len(data), 0, arbitration, 0, fd_flags, 0, 0, 0, 0, 0,
                              direction, 0, 0)
        return 101, head + data
    msg_flags = (0 if flags & FLAG_RX else 0x01) | (0x80 if flags & FLAG_REMOTE else 0)
    return 1, _CAN_MSG.pack(channel, msg_flags, dlc, arbitration, data[:8].ljust(8, b"\0"))


def write_blf(
    path: Path,
    table: FrameTable,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> int:
    """Write every frame of ``table`` in order; return the number of objects."""
    path = Path(path)
    start_ns = round(table.start_time * 1e9) if table.start_time > 0 else 0
    header_ms = math.floor(start_ns / 1e6) if start_ns else 0
    carry_ns = start_ns - header_ms * 1_000_000
    count = len(table)
    pending: list[bytes] = []
    pending_size = 0
    uncompressed = _FILE_HEADER_SIZE
    last_ns = 0
    temporary = path.with_name(path.name + ".tmp")
    stream = open(temporary, "wb")
    stream.write(b"\0" * _FILE_HEADER_SIZE)

    def flush(final: bool) -> None:
        nonlocal pending, pending_size, uncompressed
        buffer = b"".join(pending)
        while len(buffer) >= _CONTAINER_BYTES or (final and buffer):
            chunk, buffer = buffer[:_CONTAINER_BYTES], buffer[_CONTAINER_BYTES:]
            body = zlib.compress(chunk, 6)
            size = _OBJ_BASE.size + _CONTAINER.size + len(body)
            stream.write(_OBJ_BASE.pack(b"LOBJ", _OBJ_BASE.size, 1, size, 10) + _CONTAINER.pack(2, len(chunk)))
            stream.write(body + b"\0" * (size % 4))
            uncompressed += _OBJ_BASE.size + _CONTAINER.size + len(chunk)
        pending = [buffer] if buffer else []
        pending_size = len(buffer)

    try:
        for row in range(count):
            if row % _PROGRESS_EVERY == 0:
                if cancel is not None and cancel():
                    raise ReadCancelled(f"Export cancelled: {path}")
                if progress is not None:
                    progress(row, count)
            offset_ns = int(table.time_ns[row]) + carry_ns
            last_ns = max(last_ns, offset_ns)
            kind, body = _frame_object(table, row)
            size = _HEADER_SIZE + len(body)
            pending.append(_OBJ_BASE.pack(b"LOBJ", _HEADER_SIZE, 1, size, kind))
            pending.append(_OBJ_V1.pack(_TIME_ONE_NANS, 0, 0, max(offset_ns, 0)))
            pending.append(body)
            pending.append(b"\0" * (len(body) % 4))
            pending_size += size + len(body) % 4
            if pending_size >= _CONTAINER_BYTES:
                flush(final=False)
        flush(final=True)
        file_size = stream.tell()
        stop_ms = header_ms + last_ns // 1_000_000 if header_ms else 0
        header = _FILE_HEADER.pack(
            b"LOGG", _FILE_HEADER_SIZE, _APPLICATION_ID, 0, 0, 0, 2, 6, 8, 1,
            file_size, uncompressed, count, 0, *_systemtime(header_ms), *_systemtime(stop_ms),
        )
        stream.seek(0)
        stream.write(header.ljust(_FILE_HEADER_SIZE, b"\0"))
        stream.close()
        temporary.replace(path)
    except BaseException:
        stream.close()
        temporary.unlink(missing_ok=True)
        raise
    if progress is not None:
        progress(count, count)
    return count
