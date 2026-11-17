"""Virtual trace table: a :class:`LogView` painted one cell at a time."""

from __future__ import annotations

import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFontDatabase

COLUMNS = ("Time", "Chn", "ID", "Name", "Dir", "Type", "DLC", "Data")


def number_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


class TraceModel(QAbstractTableModel):
    """Virtual table over a :class:`LogView`; cells are formatted only when painted."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.view = None
        self.rows = None
        self.absolute_time = False
        self.headers = list(COLUMNS)
        self._mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

    def set_rows(self, view, rows) -> None:
        self.beginResetModel()
        self.view = view
        self.rows = rows
        self.endResetModel()

    def set_absolute_time(self, absolute: bool) -> None:
        self.absolute_time = absolute
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 0))

    def frame_row(self, position: int) -> int:
        return int(self.rows[position])

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() or self.rows is None else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.rows is None:
            return None
        from can_toolbox.canlog.table import FLAG_ERROR, FLAG_EXTENDED, FLAG_REMOTE, FLAG_RX
        from can_toolbox.canlog.view import format_data, format_id, frame_type

        frames = self.view.frames
        row = int(self.rows[index.row()])
        flags = int(frames.flags[row])
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return self._time_text(int(frames.time_ns[row]))
            if column == 1:
                channel = int(frames.channel[row])
                return str(channel) if channel else "-"
            if column == 2:
                return "" if flags & FLAG_ERROR else format_id(int(frames.arbitration_id[row]), bool(flags & FLAG_EXTENDED))
            if column == 3:
                return "Error Frame" if flags & FLAG_ERROR else self.view.message_name(row)
            if column == 4:
                return "Rx" if flags & FLAG_RX else "Tx"
            if column == 5:
                return frame_type(flags)
            if column == 6:
                return str(int(frames.dlc[row]))
            if column == 7:
                return format_data(frames.data(row))
        elif role == Qt.ItemDataRole.FontRole and column in (0, 2, 7):
            return self._mono
        elif role == Qt.ItemDataRole.ForegroundRole:
            if flags & FLAG_ERROR:
                return QColor("#b91c1c")
            if flags & FLAG_REMOTE:
                return QColor("#64748b")
        elif role == Qt.ItemDataRole.TextAlignmentRole and column in (0, 1, 6):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def _time_text(self, time_ns: int) -> str:
        view = self.view
        if not self.absolute_time:
            return f"{(time_ns - view.origin_ns) / 1e9:.6f}"
        if view.frames.start_time > 0:
            moment = datetime.datetime.fromtimestamp(view.frames.start_time + time_ns / 1e9)
            return moment.strftime("%H:%M:%S.%f")
        # Without a wall-clock start, show the log's own time base.
        return f"{time_ns / 1e9:.6f}"
