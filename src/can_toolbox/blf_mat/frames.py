"""Lossless CAN/CAN-FD frame export when no DBC is supplied."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from can_toolbox.canlog.blf import read_blf
from can_toolbox.canlog.table import (
    FLAG_BRS,
    FLAG_ERROR,
    FLAG_ESI,
    FLAG_EXTENDED,
    FLAG_FD,
    FLAG_REMOTE,
    FLAG_RX,
    dlc_to_length,
)

from . import converter as core

_FLAG_FIELDS = (
    ("Extended", FLAG_EXTENDED),
    ("FD", FLAG_FD),
    ("Remote", FLAG_REMOTE),
    ("Error", FLAG_ERROR),
    ("BRS", FLAG_BRS),
    ("ESI", FLAG_ESI),
    ("Rx", FLAG_RX),
)


def export_frames(blf: Path, target: Path) -> float:
    table, info = read_blf(blf)
    core.warn_skipped_objects(info)
    if not len(table):
        raise RuntimeError(f"BLF contains no CAN frames: {blf}")
    timestamps = table.timestamps()
    origin = float(timestamps.min())
    lengths = table.lengths()
    fd = table.has_flag(FLAG_FD)
    fields = {
        "Time": timestamps - origin,
        "Timestamp": timestamps,
        "ID": table.arbitration_id.astype(np.uint32),
        # MAT layout contract: 0-based channel (-1 unknown) and DLC as a byte count for CAN FD.
        "Channel": table.channel.astype(np.int32) - 1,
        "DLC": np.where(fd, dlc_to_length(table.dlc), table.dlc).astype(np.uint8),
        "Length": lengths.astype(np.uint8),
        "Data": table.payload_matrix(np.arange(len(table)), 64),
    }
    for label, flag in _FLAG_FIELDS:
        fields[label] = table.has_flag(flag)
    core.savemat(target, {"Frames": fields}, do_compression=True, long_field_names=True, oned_as="column")
    core.log(f"  Frames: {len(table)} CAN/CAN-FD frames -> {target}")
    return max(core.MIN_FALLBACK_DURATION_S, float(timestamps.max()) - origin)
