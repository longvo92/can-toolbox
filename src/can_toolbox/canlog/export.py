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
# What one export run can write. "mat" holds raw frames; the signal formats need
# definitions (a DBC, an Excel template or a mapping config).
FRAME_FORMATS = ("blf", "asc", "mf4", "csv", "mat")
SIGNAL_FORMATS = ("signals", "dataset")
JOB_FORMATS = FRAME_FORMATS + SIGNAL_FORMATS
EXTENSIONS = {"blf": ".blf", "asc": ".asc", "mf4": ".mf4", "csv": ".csv", "mat": ".mat",
              "signals": ".mat", "dataset": ".mat"}
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


@dataclass(frozen=True)
class ExportJob:
    """One Export run: what to cut, which formats to write and where."""

    request: ExportRequest
    formats: tuple[str, ...]
    folder: Path
    base_name: str
    # (DBC file, channel); channel 0 means the database decodes every channel.
    dbc_paths: tuple[tuple[Path, int], ...] = ()
    excel: Path | None = None
    config_path: Path | None = None
    matlab: str = ""

    def target(self, fmt: str) -> Path:
        return self.folder / f"{self.base_name}{EXTENSIONS[fmt]}"

    @property
    def signal_formats(self) -> tuple[str, ...]:
        return tuple(fmt for fmt in self.formats if fmt in SIGNAL_FORMATS)

    @property
    def frame_formats(self) -> tuple[str, ...]:
        return tuple(fmt for fmt in self.formats if fmt in FRAME_FORMATS)


@dataclass(frozen=True)
class JobResult:
    """What one export run produced."""

    frames: int
    files: tuple[Path, ...]
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
    """Cut ``view`` and write it as one file."""
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    table = cut_table(view, request)
    warnings = [f"Not exported: {warning}" for warning in view.log.warnings if warning.startswith("Skipped")]
    return export_table(table, path, fmt, progress=progress, cancel=cancel, warnings=tuple(warnings))


def export_table(
    table: FrameTable,
    path: Path,
    fmt: str | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
    warnings: tuple[str, ...] = (),
) -> ExportResult:
    """Write frames already cut; the file type comes from ``fmt`` or the suffix."""
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt not in FORMATS:
        raise ValueError(f"Unsupported export format {fmt!r}; expected one of {', '.join(FORMATS)}")
    if not len(table):
        raise ValueError("No frames in the selected range and filter")
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


def run_export(
    view: LogView,
    job: ExportJob,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
    log_callback=None,
) -> JobResult:
    """Cut once, then write every selected format from the same frames.

    Frame formats are written here; MAT signals and Simulink Dataset go through
    the converter, which decodes the cut table instead of reading the log again.
    """
    unknown = [fmt for fmt in job.formats if fmt not in JOB_FORMATS]
    if unknown:
        raise ValueError(f"Unsupported export format(s): {', '.join(unknown)}")
    if not job.formats:
        raise ValueError("Choose at least one output format")
    if not job.base_name.strip():
        raise ValueError("Choose a name for the exported files")
    table = cut_table(view, job.request)
    if not len(table):
        raise ValueError("No frames in the selected range and filter")
    warnings = [f"Not exported: {warning}" for warning in view.log.warnings if warning.startswith("Skipped")]
    written: list[Path] = []
    steps = len(job.formats)
    for index, fmt in enumerate(job.frame_formats):
        if cancel is not None and cancel():
            raise ReadCancelled()
        result = export_table(table, job.target(fmt), fmt, cancel=cancel)
        written.append(result.path)
        if progress is not None:
            progress(index + 1, steps)
    if job.signal_formats:
        written.extend(_export_signals(table, job, log_callback))
        if progress is not None:
            progress(steps, steps)
    return JobResult(len(table), tuple(written), tuple(warnings))


def _export_signals(table: FrameTable, job: ExportJob, log_callback) -> list[Path]:
    """Decode the cut through the BLF → MAT engine, once per signal format."""
    from can_toolbox.blf_mat.config import load_config
    from can_toolbox.blf_mat.converter import SelectedPaths, convert
    from can_toolbox.blf_mat.options import default_config_path, find_matlab_executable

    # Without a config the file beside the app applies, as it does for a conversion.
    config = load_config(job.config_path or default_config_path())
    # The cut already carries the new channel numbers, so the scopes follow the map.
    remap = dict(job.request.channel_map)
    written: list[Path] = []
    for fmt in job.signal_formats:
        # The name the user typed is the name that is written. Two signal formats in one
        # run therefore target the same file and the later one wins.
        stem = job.base_name
        source = job.folder / f"{stem}.blf"  # a name for the logs, never read
        paths = SelectedPaths(
            blf_files=[source],
            output_folder=job.folder,
            dbc_sources=[path for path, _channel in job.dbc_paths],
            dbc_channels={
                str(path.resolve()): remap.get(channel, channel)
                for path, channel in job.dbc_paths if channel
            },
            excel=job.excel,
            config=config,
            matlab_exe=find_matlab_executable(job.matlab or None) if fmt == "dataset" else None,
            output_format="mat" if fmt == "signals" else "dataset",
            tables={source: table},
            base_name=stem,
            plain_names=True,
        )
        convert(paths, log_callback=log_callback)
        written.extend(sorted(job.folder.glob(f"{stem}*.mat")))
    return list(dict.fromkeys(written))


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
