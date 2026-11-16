"""Cut a log by time, filter and channel and write it as BLF, ASC, MF4, CSV or MAT (Qt-free)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

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
    dlc_to_length,
)
from can_toolbox.canlog.view import LogView, format_data, format_id, frame_type

FORMATS = ("blf", "asc", "mf4", "csv", "mat")
_FLAG_FIELDS = (
    ("Extended", FLAG_EXTENDED),
    ("FD", FLAG_FD),
    ("Remote", FLAG_REMOTE),
    ("Error", FLAG_ERROR),
    ("BRS", FLAG_BRS),
    ("ESI", FLAG_ESI),
    ("Rx", FLAG_RX),
)


@dataclass(frozen=True)
class ExportRequest:
    """What to cut. Times are seconds from the view origin (the trace's relative time), both inclusive."""

    start_s: float | None = None
    end_s: float | None = None
    # True: only frames the trace filter shows; False: every frame in the range.
    filtered: bool = False
    # Old channel -> new channel; unlisted channels keep their number.
    channel_map: tuple[tuple[int, int], ...] = ()
    # True: exported times start at 0 at the first exported frame (absolute times kept in the BLF header).
    rebase: bool = False


@dataclass(frozen=True)
class ExportResult:
    path: Path
    frames: int
    warnings: tuple[str, ...]


def parse_channel_map(text: str) -> tuple[tuple[int, int], ...]:
    """``"1=2, 2=1"`` or ``"1>2"`` -> ((1, 2), (2, 1)); raises ValueError on bad input."""
    pairs = []
    for term in text.replace(";", ",").split(","):
        term = term.strip()
        if not term:
            continue
        for separator in ("->", "→", "=", ">"):
            if separator in term:
                old, new = (part.strip() for part in term.split(separator, 1))
                break
        else:
            raise ValueError(f"Channel mapping {term!r} needs the form old=new")
        if not old.isdigit() or not new.isdigit() or not 1 <= int(old) <= 255 or not 1 <= int(new) <= 255:
            raise ValueError(f"Channel mapping {term!r} must use channel numbers 1-255")
        pairs.append((int(old), int(new)))
    olds = [old for old, _ in pairs]
    if len(set(olds)) != len(olds):
        raise ValueError("A channel is mapped twice")
    return tuple(pairs)


def select_rows(view: LogView, request: ExportRequest) -> np.ndarray:
    """Time-ordered rows to export."""
    rows = view.rows if request.filtered else view.order
    times = view.frames.time_ns[rows] - view.origin_ns
    keep = np.ones(len(rows), np.bool_)
    if request.start_s is not None:
        keep &= times >= round(request.start_s * 1e9)
    if request.end_s is not None:
        keep &= times <= round(request.end_s * 1e9)
    return rows[keep]


def cut_table(view: LogView, request: ExportRequest) -> FrameTable:
    """The exported frames as their own table, channels remapped and time base applied."""
    table = view.frames.take(select_rows(view, request))
    if request.channel_map:
        mapping = dict(request.channel_map)
        channel = table.channel.copy()
        for old, new in mapping.items():
            channel[table.channel == old] = new
        table = FrameTable(table.time_ns, table.arbitration_id, channel, table.dlc, table.flags, table.offsets,
                           table.payload, table.start_time)
    if request.rebase and len(table):
        first = int(table.time_ns[0])
        table = FrameTable(table.time_ns - first, table.arbitration_id, table.channel, table.dlc, table.flags,
                           table.offsets, table.payload, table.start_time + first / 1e9 if table.start_time else 0.0)
    return table


def export_log(
    view: LogView,
    request: ExportRequest,
    path: Path,
    fmt: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> ExportResult:
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt not in FORMATS:
        raise ValueError(f"Unsupported export format {fmt!r}; expected one of {', '.join(FORMATS)}")
    table = cut_table(view, request)
    if not len(table):
        raise ValueError("No frames in the selected range and filter")
    warnings = [f"Not exported: {warning}" for warning in view.log.warnings if warning.startswith("Skipped")]
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "blf":
        from can_toolbox.canlog.blf_writer import write_blf

        write_blf(path, table, progress=progress, cancel=cancel)
    elif fmt in ("asc", "mf4"):
        _write_python_can(path, table, fmt, progress, cancel)
    elif fmt == "csv":
        _write_csv(path, table, progress, cancel)
    else:
        from scipy.io import savemat

        savemat(path, {"Frames": frame_fields(table)}, do_compression=True, long_field_names=True, oned_as="column")
    return ExportResult(path, len(table), tuple(warnings))


def frame_fields(table: FrameTable) -> dict[str, np.ndarray]:
    """The ``Frames`` MAT struct shared with BLF → MAT.

    Layout contract: ``Time`` from the first frame, ``Timestamp`` absolute,
    0-based ``Channel`` (-1 unknown), ``DLC`` as a byte count for CAN FD and a
    64-column zero-padded ``Data`` matrix.
    """
    timestamps = table.timestamps()
    fd = table.has_flag(FLAG_FD)
    fields: dict[str, np.ndarray] = {
        "Time": timestamps - float(timestamps.min()) if len(table) else timestamps,
        "Timestamp": timestamps,
        "ID": table.arbitration_id.astype(np.uint32),
        "Channel": table.channel.astype(np.int32) - 1,
        "DLC": np.where(fd, dlc_to_length(table.dlc), table.dlc).astype(np.uint8),
        "Length": table.lengths().astype(np.uint8),
        "Data": table.payload_matrix(np.arange(len(table)), 64),
    }
    for label, flag in _FLAG_FIELDS:
        fields[label] = table.has_flag(flag)
    return fields


def _check(index: int, count: int, path: Path, progress, cancel) -> None:
    if index % 50_000:
        return
    if cancel is not None and cancel():
        raise ReadCancelled(f"Export cancelled: {path}")
    if progress is not None:
        progress(index, count)


def _write_python_can(path: Path, table: FrameTable, fmt: str, progress, cancel) -> None:
    import can

    writer_type = can.ASCWriter if fmt == "asc" else can.MF4Writer
    timestamps = table.timestamps()
    temporary = path.with_name(path.name + ".tmp" + path.suffix)
    try:
        with writer_type(str(temporary)) as writer:
            for index in range(len(table)):
                _check(index, len(table), path, progress, cancel)
                flags = int(table.flags[index])
                data = table.data(index)
                channel = int(table.channel[index])
                fd = bool(flags & FLAG_FD)
                writer.on_message_received(can.Message(
                    timestamp=float(timestamps[index]),
                    arbitration_id=int(table.arbitration_id[index]),
                    is_extended_id=bool(flags & FLAG_EXTENDED),
                    is_remote_frame=bool(flags & FLAG_REMOTE),
                    is_error_frame=bool(flags & FLAG_ERROR),
                    is_fd=fd,
                    bitrate_switch=bool(flags & FLAG_BRS),
                    error_state_indicator=bool(flags & FLAG_ESI),
                    is_rx=bool(flags & FLAG_RX),
                    # python-can numbers channels from 0 and stores a byte count as FD "dlc".
                    channel=channel - 1 if channel else None,
                    dlc=len(data) if fd else int(table.dlc[index]),
                    data=data,
                ))
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    if progress is not None:
        progress(len(table), len(table))


def _write_csv(path: Path, table: FrameTable, progress, cancel) -> None:
    timestamps = table.timestamps()
    origin = float(timestamps[0])
    temporary = path.with_name(path.name + ".tmp")
    try:
        with open(temporary, "w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Time", "Timestamp", "Channel", "ID", "Extended", "Dir", "Type", "DLC", "Length", "Data"])
            for index in range(len(table)):
                _check(index, len(table), path, progress, cancel)
                flags = int(table.flags[index])
                data = table.data(index)
                writer.writerow([
                    f"{timestamps[index] - origin:.9f}",
                    f"{timestamps[index]:.9f}",
                    int(table.channel[index]),
                    format_id(int(table.arbitration_id[index]), bool(flags & FLAG_EXTENDED)),
                    int(bool(flags & FLAG_EXTENDED)),
                    "Rx" if flags & FLAG_RX else "Tx",
                    frame_type(flags),
                    int(table.dlc[index]),
                    len(data),
                    format_data(data),
                ])
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    if progress is not None:
        progress(len(table), len(table))
