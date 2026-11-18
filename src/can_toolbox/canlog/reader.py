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

SUPPORTED_SUFFIXES = (".blf", ".asc", ".mf4", ".trc", ".log", ".csv")
# What ``LogFile.format`` reports per suffix; BLF and CSV are named by their readers.
_FORMAT_NAMES = {".asc": "ASC", ".mf4": "MF4", ".trc": "TRC", ".log": "candump"}


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
    if suffix == ".csv":
        from can_toolbox.canlog.csv_log import is_python_can_csv, read_csv

        if is_python_can_csv(path):
            return LogFile(path, read_with_python_can(path, progress=progress, cancel=cancel), "CSV")
        return LogFile(path, read_csv(path, progress=progress, cancel=cancel), "CSV")
    if suffix in _FORMAT_NAMES:
        # python-can parses ASC text, ASAM MDF4 bus logging (through asammdf),
        # PEAK TRC traces and candump logs.
        frames = read_with_python_can(path, progress=progress, cancel=cancel)
        return LogFile(path, frames, _FORMAT_NAMES[suffix])
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
    # candump and TRC name their bus instead of numbering it; give each name a number
    # of its own so a multi-bus log does not collapse onto one channel.
    named_channels: dict[str, int] = {}
    for message in messages:
        time_s.append(float(message.timestamp))
        ids.append(int(message.arbitration_id))
        channels.append(_channel_number(message.channel, named_channels))
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


def _channel_number(channel, named: dict[str, int]) -> int:
    """Vector-style 1-based channel; 0 when the log does not say which bus."""
    if isinstance(channel, (int, np.integer)) and not isinstance(channel, bool):
        return int(channel) + 1 if channel >= 0 else 0
    if channel is None:
        return 0
    name = str(channel).strip()
    if not name:
        return 0
    if name.isdigit():
        return int(name) + 1
    return named.setdefault(name, len(named) + 1)


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
        # ASC: absolute times from the file's "date" line, like CANoe shows them.
        options = {"relative_timestamp": False} if path.suffix.lower() == ".asc" else {}
        with can.LogReader(str(path), **options) as reader:
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
