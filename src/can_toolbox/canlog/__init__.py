"""Qt-free CAN log engine shared by the log viewer and the BLF to MAT converter.

A log is read once into a columnar :class:`~can_toolbox.canlog.table.FrameTable`;
signals are decoded from it with vectorized kernels instead of per-frame Python.
Submodules load lazily: importing the package does not start Numba.
"""

from __future__ import annotations

from typing import Any

__all__ = ["FrameTable", "LogFile", "open_log"]


def __getattr__(name: str) -> Any:
    if name in ("LogFile", "open_log"):
        from can_toolbox.canlog import reader

        return getattr(reader, name)
    if name == "FrameTable":
        from can_toolbox.canlog.table import FrameTable

        return FrameTable
    raise AttributeError(name)
