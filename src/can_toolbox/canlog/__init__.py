"""Qt-free CAN log engine shared by the log viewer and the BLF to MAT converter.

A log is read once into a columnar :class:`~can_toolbox.canlog.table.FrameTable`;
signals are decoded from it with vectorized kernels instead of per-frame Python.
"""

from can_toolbox.canlog.reader import LogFile, open_log
from can_toolbox.canlog.table import FrameTable

__all__ = ["FrameTable", "LogFile", "open_log"]
