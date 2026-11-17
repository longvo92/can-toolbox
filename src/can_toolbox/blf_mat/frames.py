"""Lossless CAN/CAN-FD frame export when no DBC is supplied."""

from __future__ import annotations

from pathlib import Path

from can_toolbox.canlog.blf import read_blf
from can_toolbox.canlog.export import frame_fields

from . import converter as core


def export_frames(blf: Path, target: Path) -> float:
    table, info = read_blf(blf)
    core.warn_skipped_objects(info)
    if not len(table):
        raise RuntimeError(f"BLF contains no CAN frames: {blf}")
    return export_frames_table(table, target)


def export_frames_table(table, target: Path) -> float:
    """Write frames already in memory, for example the cut the Log Viewer exports."""
    if not len(table):
        raise RuntimeError("No CAN frames to export.")
    fields = frame_fields(table)
    core.savemat(target, {"Frames": fields}, do_compression=True, long_field_names=True, oned_as="column")
    core.log(f"  Frames: {len(table)} CAN/CAN-FD frames -> {target}")
    timestamps = fields["Timestamp"]
    return max(core.MIN_FALLBACK_DURATION_S, float(timestamps.max() - timestamps.min()))
