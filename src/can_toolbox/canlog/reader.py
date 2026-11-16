"""Open a CAN log of any supported format as a :class:`LogFile`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from can_toolbox.canlog.blf import CancelCallback, ProgressCallback, ReadCancelled, read_blf
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

SUPPORTED_SUFFIXES = (".blf", ".asc")


@dataclass(frozen=True)
class LogFile:
    path: Path
    frames: FrameTable
    format: str
    # Human-readable notes about content the reader could not represent.
    warnings: tuple[str, ...] = field(default_factory=tuple)


def open_log(
    path: Path | str,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> LogFile:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".blf":
        frames, info = read_blf(path, progress=progress, cancel=cancel)
        warnings = []
        if info.skipped_objects:
            warnings.append(f"Skipped non-CAN objects: {info.skipped_summary()}")
        if info.trailing_bytes:
            warnings.append(f"Ignored {info.trailing_bytes} bytes of an incomplete last object")
        return LogFile(path, frames, "BLF", tuple(warnings))
    if suffix == ".asc":
        return LogFile(path, read_with_python_can(path, progress=progress, cancel=cancel), "ASC")
    raise ValueError(f"Unsupported log format {path.suffix!r}; expected one of {', '.join(SUPPORTED_SUFFIXES)}")


def frames_from_messages(messages, start_time: float | None = None) -> FrameTable:
    """Build a table from python-can ``Message`` objects (any iterable)."""
    time_s: list[float] = []
    ids: list[int] = []
    channels: list[int] = []
    dlcs: list[int] = []
    flags: list[int] = []
    lengths: list[int] = []
    chunks: list[bytes] = []
    for message in messages:
        time_s.append(float(message.timestamp))
        ids.append(int(message.arbitration_id))
        channel = message.channel
        channels.append(int(channel) + 1 if isinstance(channel, (int, np.integer)) and channel >= 0 else 0)
        data = bytes(message.data)
        chunks.append(data)
        lengths.append(len(data))
        dlcs.append(_dlc_code(message, len(data)))
        flags.append(
            (FLAG_EXTENDED if message.is_extended_id else 0)
            | (FLAG_FD if message.is_fd else 0)
            | (FLAG_BRS if message.bitrate_switch else 0)
            | (FLAG_ESI if message.error_state_indicator else 0)
            | (FLAG_REMOTE if message.is_remote_frame else 0)
            | (FLAG_ERROR if message.is_error_frame else 0)
            | (FLAG_RX if message.is_rx else 0)
        )
    seconds = np.asarray(time_s, np.float64)
    origin = float(seconds.min()) if start_time is None and len(seconds) else (start_time or 0.0)
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


def _dlc_code(message, length: int) -> int:
    from can.util import len2dlc

    # python-can reports CAN FD "dlc" as a byte count; tables keep the DLC code.
    if message.is_fd:
        return len2dlc(length)
    return int(message.dlc)


def read_with_python_can(
    path: Path,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> FrameTable:
    import can

    total = max(path.stat().st_size, 1)

    def messages():
        with can.LogReader(str(path)) as reader:
            for index, message in enumerate(reader):
                if index % 50000 == 0:
                    if cancel is not None and cancel():
                        raise ReadCancelled(f"Reading cancelled: {path}")
                    if progress is not None and hasattr(reader, "file"):
                        try:
                            progress(min(reader.file.tell(), total), total)
                        except (OSError, ValueError):
                            pass
                yield message

    table = frames_from_messages(messages())
    if progress is not None:
        progress(total, total)
    return table
