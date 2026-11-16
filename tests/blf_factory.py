"""Hand-built BLF files covering object layouts python-can's writer never emits."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

_FILE_HEADER = struct.Struct("<4sLBBBBBBBBQQLL8H8H")


def obj(obj_type: int, body: bytes, timestamp: int, *, version: int = 1, ten_us: bool = False) -> bytes:
    flags = 1 if ten_us else 2
    if version == 1:
        header = struct.pack("<LHHQ", flags, 0, 0, timestamp)
    else:
        header = struct.pack("<LBxHQQ", flags, 0, 0, timestamp, 0)
    header_size = 16 + len(header)
    size = header_size + len(body)
    return struct.pack("<4sHHLL", b"LOBJ", header_size, version, size, obj_type) + header + body


def can_message(channel: int, can_id: int, data: bytes, *, extended=False, tx=False, remote=False, dlc=None) -> bytes:
    flags = (1 if tx else 0) | (0x80 if remote else 0)
    arb = can_id | (0x80000000 if extended else 0)
    return struct.pack("<HBBL8s", channel, flags, len(data) if dlc is None else dlc, arb, data.ljust(8, b"\0"))


def can_message2(channel: int, can_id: int, data: bytes, **kwargs) -> bytes:
    return can_message(channel, can_id, data, **kwargs) + struct.pack("<LBBH", 111, 64, 0, 0)


def can_fd64(
    channel: int, can_id: int, data: bytes, dlc: int, *, valid=None, extended=False, brs=True, esi=False, tx=False,
    stored=None,
) -> bytes:
    valid = len(data) if valid is None else valid
    fd_flags = 0x1000 | (0x2000 if brs else 0) | (0x4000 if esi else 0)
    arb = can_id | (0x80000000 if extended else 0)
    stored_data = data if stored is None else stored
    head = struct.pack(
        "<BBBBLLLLLLLHBBL", channel, dlc, valid, 0, arb, 0, fd_flags, 0, 0, 0, 0, 0, 1 if tx else 0, 0, 0
    )
    return head + stored_data


def can_fd(channel: int, can_id: int, data: bytes, dlc: int, *, edl=True, brs=False, esi=False, tx=False) -> bytes:
    fd_flags = (1 if edl else 0) | (2 if brs else 0) | (4 if esi else 0)
    return struct.pack(
        "<HBBLLBBB5x64s", channel, 1 if tx else 0, dlc, can_id, 0, 0, fd_flags, len(data), data.ljust(64, b"\0")
    )


def app_text(text: str) -> bytes:
    raw = text.encode()
    return struct.pack("<LLL4x", 0, len(raw), 0) + raw


def write_blf(path: Path, objects: list[bytes], *, container_size: int = 4096, compress: bool = True,
              top_level: list[bytes] = ()) -> Path:
    """Write ``objects`` into containers of ``container_size`` uncompressed bytes.

    Objects are padded to four bytes like CANoe does and may straddle containers.
    """
    stream = b"".join(item + b"\0" * (-len(item) % 4) for item in objects)
    containers = []
    for offset in range(0, len(stream), container_size):
        chunk = stream[offset : offset + container_size]
        body = zlib.compress(chunk) if compress else chunk
        payload = struct.pack("<H6xL4x", 2 if compress else 0, len(chunk)) + body
        size = 16 + len(payload)
        containers.append(struct.pack("<4sHHLL", b"LOBJ", 16, 1, size, 10) + payload + b"\0" * (size % 4))
    for item in top_level:
        containers.append(item + b"\0" * (len(item) % 4))
    start = (2024, 3, 5, 14, 9, 30, 15, 250)
    header = _FILE_HEADER.pack(b"LOGG", 144, 5, 1, 2, 3, 4, 7, 0, 0, 0, len(stream), len(objects), 0,
                               *start, *start)
    path.write_bytes(header.ljust(144, b"\0") + b"".join(containers))
    return path
