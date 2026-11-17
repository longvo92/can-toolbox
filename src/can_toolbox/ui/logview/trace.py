"""Virtual trace table: a :class:`LogView` painted one cell at a time."""

from __future__ import annotations

import datetime

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFontDatabase

from can_toolbox.ui import theme as app_theme

COLUMNS = ("Time", "Chn", "ID", "Name", "Dir", "Type", "DLC", "Data")


def number_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


class TraceModel(QAbstractItemModel):
    """Virtual tree over a :class:`LogView`.

    Top level is one row per frame, formatted only when painted. Expanding a
    frame decodes it and lists its signals; the decode is cached per frame.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.view = None
        self.rows = None
        self.absolute_time = False
        self.headers = list(COLUMNS)
        self._mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._decoded: dict[int, list] = {}

    def set_rows(self, view, rows) -> None:
        self.beginResetModel()
        self.view = view
        self.rows = rows
        self._decoded = {}
        self.endResetModel()

    # -- signals of one frame ------------------------------------------------------

    def signals_at(self, position: int) -> list:
        """Decoded signals of the frame at ``position``, decoded on first use."""
        row = self.frame_row(position)
        cached = self._decoded.get(row)
        if cached is None:
            cached = self._decode(row)
            self._decoded[row] = cached
        return cached

    def _decode(self, row: int) -> list:
        from can_toolbox.canlog.database import decode_frame
        from can_toolbox.canlog.decode import frame_keys

        frames = self.view.frames
        key = int(frame_keys(frames.take([row]))[0])
        codec = self.view.database.codec(key, int(frames.channel[row])) if key >= 0 else None
        return decode_frame(codec, frames.data(row)) if codec is not None else []

    def has_signals(self, position: int) -> bool:
        """Whether the frame is one a DBC describes; no decoding needed to tell."""
        if self.view is None:
            return False
        return bool(self.view.message_name(self.frame_row(position)))

    def set_absolute_time(self, absolute: bool) -> None:
        self.absolute_time = absolute
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 0))

    def frame_row(self, position: int) -> int:
        return int(self.rows[position])

    # -- tree structure ------------------------------------------------------------

    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        # Top-level rows carry id 0; a signal row carries its frame's position + 1.
        return self.createIndex(row, column, 0 if not parent.isValid() else parent.row() + 1)

    def parent(self, index: QModelIndex) -> QModelIndex:  # noqa: A003 - Qt's name
        if not index.isValid() or not index.internalId():
            return QModelIndex()
        return self.createIndex(int(index.internalId()) - 1, 0, 0)

    def rowCount(self, parent=QModelIndex()) -> int:
        if self.rows is None:
            return 0
        if not parent.isValid():
            return len(self.rows)
        if parent.internalId() or parent.column():
            return 0
        return len(self.signals_at(parent.row()))

    def hasChildren(self, parent=QModelIndex()) -> bool:
        if not parent.isValid():
            return self.rows is not None and bool(len(self.rows))
        if parent.internalId() or parent.column():
            return False
        return self.has_signals(parent.row())

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.rows is None:
            return None
        if index.internalId():
            return self._signal_data(index, role)
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
            theme = app_theme.current_theme()
            if flags & FLAG_ERROR:
                return QColor(theme.error)
            if flags & FLAG_REMOTE:
                return QColor(theme.disabled_soft)
        elif role == Qt.ItemDataRole.TextAlignmentRole and column in (0, 1, 6):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def _signal_data(self, index, role):
        """One decoded signal of the frame above it: the name and its value."""
        position = int(index.internalId()) - 1
        signals = self.signals_at(position)
        if index.row() >= len(signals):
            return None
        value = signals[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 3:
                return value.name
            if column == 7:
                if value.label is not None:
                    return f"{value.label} ({number_text(value.physical)})"
                return f"{number_text(value.physical)} {value.unit}".strip()
            return ""
        if role == Qt.ItemDataRole.FontRole and column == 7:
            return self._mono
        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor(app_theme.current_theme().muted_strong)
        if role == Qt.ItemDataRole.ToolTipRole and column in (3, 7):
            raw = value.raw
            raw_text = f"{raw} (0x{raw:X})" if isinstance(raw, int) and raw >= 0 else number_text(raw)
            return f"{value.name}: {number_text(value.physical)} {value.unit}".strip() + f"  ·  raw {raw_text}"
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
