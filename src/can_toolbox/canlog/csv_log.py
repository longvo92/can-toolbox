"""Read the CSV the Export window writes, and python-can's own CSV.

The two formats share a suffix and nothing else, so the header row decides which
reader runs. Our own columns match the trace, which makes a cut readable in a
spreadsheet and openable again here.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from can_toolbox.canlog.blf import CancelCallback, ProgressCallback, ReadCancelled
from can_toolbox.canlog.table import (
    FLAG_BRS,
    FLAG_ERROR,
    FLAG_EXTENDED,
    FLAG_FD,
    FLAG_REMOTE,
    FLAG_RX,
    FrameTable,
)

# What ``canlog.export`` writes. ESI is not among them, so it cannot be read back.
COLUMNS = ("Time", "Timestamp", "Channel", "ID", "Extended", "Dir", "Type", "DLC", "Length", "Data")
# python-can's own CSV, which ``can.CSVReader`` parses.
PYTHON_CAN_COLUMNS = ("timestamp", "arbitration_id", "extended", "remote", "error", "dlc", "data")

_TYPE_FLAGS = {
    "CAN": 0,
    "CAN FD": FLAG_FD,
    "CAN FD BRS": FLAG_FD | FLAG_BRS,
    "Remote": FLAG_REMOTE,
    "Error": FLAG_ERROR,
}


def is_python_can_csv(path: Path) -> bool:
    """Whether the file carries python-can's header instead of ours."""
    return _header(path) == list(PYTHON_CAN_COLUMNS)


def _header(path: Path) -> list[str]:
    with open(path, newline="", encoding="utf-8-sig") as stream:
        for row in csv.reader(stream):
            return [cell.strip() for cell in row]
    return []


def read_csv(
    path: Path,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> FrameTable:
    """Read a CSV written by Export into a :class:`FrameTable`."""
    header = _header(path)
    if header != list(COLUMNS):
        raise ValueError(f"Unsupported CSV columns {header}; expected {', '.join(COLUMNS)}")
    total = max(path.stat().st_size, 1)
    timestamps: list[float] = []
    ids: list[int] = []
    channels: list[int] = []
    dlcs: list[int] = []
    flags: list[int] = []
    lengths: list[int] = []
    chunks: list[bytes] = []
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        next(reader, None)
        for index, row in enumerate(reader):
            if index % 50_000 == 0:
                if cancel is not None and cancel():
                    raise ReadCancelled(f"Reading cancelled: {path}")
                if progress is not None:
                    # A text stream cannot be told its position while it is iterated;
                    # the buffer underneath can, and is close enough for a progress bar.
                    try:
                        progress(min(stream.buffer.tell(), total), total)
                    except (AttributeError, OSError, ValueError):
                        pass
            if not row:
                continue
            if len(row) != len(COLUMNS):
                raise ValueError(f"{path.name} line {index + 2}: expected {len(COLUMNS)} columns, got {len(row)}")
            frame_type = row[6].strip()
            if frame_type not in _TYPE_FLAGS:
                raise ValueError(f"{path.name} line {index + 2}: unknown frame type {frame_type!r}")
            identifier = row[3].strip()
            extended = identifier.lower().endswith("x") or row[4].strip() == "1"
            data = bytes.fromhex(row[9].replace(" ", ""))
            timestamps.append(float(row[1]))
            ids.append(int(identifier.rstrip("xX") or "0", 16))
            channels.append(int(row[2]))
            dlcs.append(int(row[7]))
            lengths.append(len(data))
            chunks.append(data)
            flags.append(
                _TYPE_FLAGS[frame_type]
                | (FLAG_EXTENDED if extended else 0)
                | (FLAG_RX if row[5].strip().lower() == "rx" else 0)
            )
    if progress is not None:
        progress(total, total)
    if not timestamps:
        return FrameTable.empty()
    seconds = np.asarray(timestamps, np.float64)
    origin = float(seconds.min())
    offsets = np.zeros(len(lengths) + 1, np.int64)
    np.cumsum(lengths, out=offsets[1:])
    return FrameTable(
        time_ns=np.rint((seconds - origin) * 1e9).astype(np.int64),
        arbitration_id=np.asarray(ids, np.uint32),
        channel=np.asarray(channels, np.uint16),
        dlc=np.asarray(dlcs, np.uint8),
        flags=np.asarray(flags, np.uint8),
        offsets=offsets,
        payload=np.frombuffer(b"".join(chunks), np.uint8).copy(),
        start_time=origin,
    )
