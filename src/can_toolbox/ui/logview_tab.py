"""Log Viewer tab: a CANoe-style trace of BLF, ASC and MF4 logs with DBC decoding."""

from __future__ import annotations

import datetime
import json
import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSettings, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from can_toolbox.ui.widgets import NoWheelComboBox, TextBinder, dialog_buttons

_SETTINGS_PREFIX = "logview/"
LOG_FILTER = "CAN logs (*.blf *.asc *.mf4);;BLF (*.blf);;ASC (*.asc);;MDF4 (*.mf4)"
LOG_SUFFIXES = (".blf", ".asc", ".mf4")
EXPORT_FILTER = "BLF (*.blf);;ASC (*.asc);;MDF4 (*.mf4);;CSV (*.csv);;MATLAB (*.mat)"
_MAX_CHANNEL_CHOICES = 16

COLUMNS = ("Time", "Chn", "ID", "Name", "Dir", "Type", "DLC", "Data")


class Task(QThread):
    """Run one callable off the GUI thread; ``progress`` receives a 0-1000 fraction."""

    progress = Signal(int)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, work: Callable[[Task], Any]) -> None:
        super().__init__()
        self._work = work
        self.cancelled = threading.Event()

    def report(self, done: int, total: int) -> None:
        self.progress.emit(int(1000 * done / total) if total else 0)

    def run(self) -> None:
        try:
            result = self._work(self)
        except Exception as exc:  # surfaced in the tab, never swallowed
            if not self.cancelled.is_set():
                self.failed.emit(str(exc) or type(exc).__name__)
            return
        if not self.cancelled.is_set():
            self.succeeded.emit(result)


def load_view(path: Path, assignments, task: Task | None = None):
    """Read a log, sort it and attach DBCs: everything the trace needs (Qt-free work)."""
    from can_toolbox.canlog import open_log
    from can_toolbox.canlog.database import LogDatabase
    from can_toolbox.canlog.view import LogView

    log = open_log(
        path,
        progress=task.report if task else None,
        cancel=task.cancelled.is_set if task else None,
    )
    return LogView(log, LogDatabase.load(assignments))


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


class DbcDialog(QDialog):
    """Assign DBC files to bus channels."""

    def __init__(self, parent, assignments: list[tuple[str, int]], binder: TextBinder, start_dir: str) -> None:
        super().__init__(parent)
        self._tr = binder.tr
        self._start_dir = start_dir
        self.setWindowTitle(self._tr("DBC Databases"))
        self.resize(640, 320)
        layout = QVBoxLayout(self)
        hint = QLabel(self._tr("A DBC assigned to a channel wins over one assigned to all channels."))
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([self._tr("DBC file"), self._tr("Channel")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.add_button = QPushButton(self._tr("Add…"))
        self.remove_button = QPushButton(self._tr("Remove"))
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        row.addStretch()
        layout.addLayout(row)
        buttons = dialog_buttons(binder.language, QDialogButtonBox.StandardButton.Save,
                                 QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.add_button.clicked.connect(self._add)
        self.remove_button.clicked.connect(self._remove)
        for path, channel in assignments:
            self.add_row(path, channel)

    def add_row(self, path: str, channel: int = 0) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(path)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setToolTip(path)
        self.table.setItem(row, 0, item)
        combo = NoWheelComboBox()
        combo.addItem(self._tr("All channels"), 0)
        for number in range(1, _MAX_CHANNEL_CHOICES + 1):
            combo.addItem(f"CAN {number}", number)
        combo.setCurrentIndex(max(combo.findData(channel), 0))
        self.table.setCellWidget(row, 1, combo)

    def _add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, self._tr("Add DBC files"), self._start_dir, "DBC (*.dbc)")
        for path in paths:
            self.add_row(path)

    def _remove(self) -> None:
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def assignments(self) -> list[tuple[str, int]]:
        return [
            (self.table.item(row, 0).text(), int(self.table.cellWidget(row, 1).currentData()))
            for row in range(self.table.rowCount())
        ]


class ExportDialog(QDialog):
    """Choose the time range, frames, channel mapping, time base and file for a cut."""

    def __init__(self, parent, binder: TextBinder, *, duration: float, cursors: tuple[float, float] | None,
                 filtered_count: int, total_count: int, default_path: str) -> None:
        super().__init__(parent)
        tr = binder.tr
        self.setWindowTitle(tr("Export Log"))
        self.resize(560, 0)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self.whole = QRadioButton(tr("Whole log ({duration} s)", duration=f"{duration:.3f}"))
        self.between = QRadioButton(tr("Between graph cursors"))
        self.custom = QRadioButton(tr("From / to (s)"))
        self.start_input = QLineEdit("0")
        self.end_input = QLineEdit(f"{duration:.6f}")
        if cursors is not None:
            low, high = sorted(cursors)
            self.between.setText(tr("Between graph cursors ({start} – {end} s)", start=f"{low:.6f}",
                                    end=f"{high:.6f}"))
            self.start_input.setText(f"{low:.6f}")
            self.end_input.setText(f"{high:.6f}")
        self.between.setEnabled(cursors is not None)
        self._cursors = cursors
        (self.between if cursors is not None else self.whole).setChecked(True)
        custom_row = QHBoxLayout()
        custom_row.addWidget(self.custom)
        custom_row.addWidget(self.start_input)
        custom_row.addWidget(QLabel("–"))
        custom_row.addWidget(self.end_input)
        range_box = QVBoxLayout()
        range_box.addWidget(self.whole)
        range_box.addWidget(self.between)
        range_box.addLayout(custom_row)
        form.addRow(tr("Range"), range_box)

        self.filtered_input = QCheckBox(tr("Only frames shown in the trace ({shown} of {total})",
                                           shown=f"{filtered_count:,}", total=f"{total_count:,}"))
        self.filtered_input.setChecked(filtered_count != total_count)
        form.addRow(tr("Frames"), self.filtered_input)
        self.channel_map_input = QLineEdit()
        self.channel_map_input.setPlaceholderText(tr("Optional, for example 1=2, 2=1"))
        form.addRow(tr("Channel mapping"), self.channel_map_input)
        self.time_input = NoWheelComboBox()
        self.time_input.addItem(tr("Keep original times"), False)
        self.time_input.addItem(tr("Start at 0"), True)
        form.addRow(tr("Time base"), self.time_input)
        path_row = QHBoxLayout()
        self.path_input = QLineEdit(default_path)
        self.browse_button = QPushButton(tr("Browse…"))
        path_row.addWidget(self.path_input, 1)
        path_row.addWidget(self.browse_button)
        form.addRow(tr("Output file"), path_row)
        hint = QLabel(tr("The file type follows the extension: .blf, .asc, .mf4, .csv or .mat."))
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addLayout(form)
        layout.addWidget(hint)
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #b91c1c;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox()
        self.export_button = buttons.addButton(tr("Export"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(tr("Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.browse_button.clicked.connect(lambda: self._browse(tr))
        self.request = None
        self.path = None
        self._tr = tr

    def _browse(self, tr) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("Export Log"), self.path_input.text(), EXPORT_FILTER)
        if path:
            self.path_input.setText(path)

    def build(self):
        """Validated (ExportRequest, path); raises ValueError with a message for the user."""
        from can_toolbox.canlog.export import FORMATS, ExportRequest, parse_channel_map

        start = end = None
        if self.between.isChecked() and self._cursors is not None:
            start, end = sorted(self._cursors)
        elif self.custom.isChecked():
            try:
                start, end = float(self.start_input.text()), float(self.end_input.text())
            except ValueError:
                raise ValueError(self._tr("Enter the range in seconds, for example 1.5 and 12.")) from None
            if end < start:
                raise ValueError(self._tr("The end of the range is before its start."))
        channel_map = parse_channel_map(self.channel_map_input.text())
        path = Path(self.path_input.text().strip())
        if not path.name or path.suffix.lower().lstrip(".") not in FORMATS:
            raise ValueError(self._tr("Choose an output file ending in .blf, .asc, .mf4, .csv or .mat."))
        request = ExportRequest(start_s=start, end_s=end, filtered=self.filtered_input.isChecked(),
                                channel_map=channel_map, rebase=bool(self.time_input.currentData()))
        return request, path

    def _accept(self) -> None:
        try:
            self.request, self.path = self.build()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()


class LogViewerTab(QWidget):
    title_key = "Log Viewer"
    subtitle_key = "Browse BLF, ASC and MF4 logs like a CANoe trace, decoded with DBC files."
    busy_changed = Signal(bool)

    def __init__(
        self,
        settings: QSettings,
        *,
        gui_language: str = "en",
        report_language: str = "gui",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        del report_language  # The viewer writes no report.
        self._settings = settings
        self._binder = TextBinder(gui_language)
        self.view = None
        self.worker: Task | None = None
        self.stats_worker: Task | None = None
        # Superseded statistics threads stay referenced until they finish; a
        # QThread destroyed while running aborts the process.
        self._retired: list[Task] = []
        self._stats_dirty = True
        self._loaded_summary: dict[str, str] = {}
        self._cursor_driving = False
        self.source = None
        self.last_export = None
        self._status: tuple[str, dict] = ("Open a BLF, ASC or MF4 log.", {})
        self.log_path = settings.value(_SETTINGS_PREFIX + "last_log", "", type=str)
        self.dbc_assignments: list[tuple[str, int]] = self._load_assignments()

        self._build_layout()
        self._wire_events()
        self._update_language()
        self.setAcceptDrops(True)

    # -- shell contract ------------------------------------------------------------

    def set_languages(self, gui_language: str, report_language: str) -> None:
        del report_language
        self._binder.language = gui_language
        self._update_language()

    def is_busy(self) -> bool:
        return bool(self.worker and self.worker.isRunning())

    def stop_workers(self) -> None:
        for worker in (self.worker, self.stats_worker, *self._retired):
            if worker and worker.isRunning():
                worker.cancelled.set()
                worker.wait(5000)

    def wait_for_workers(self, timeout_ms: int = 5000) -> None:
        for worker in (self.worker, self.stats_worker, *self._retired):
            if worker:
                worker.wait(timeout_ms)

    # -- layout --------------------------------------------------------------------

    def _tr(self, key: str, **parameters: object) -> str:
        return self._binder.tr(key, **parameters)

    def _label(self, key: str) -> QLabel:
        return self._binder.widget(QLabel, key)

    def _button(self, key: str) -> QPushButton:
        return self._binder.widget(QPushButton, key)

    def _build_layout(self) -> None:
        self.open_button = self._button("Open Log…")
        self.open_button.setObjectName("primaryButton")
        self.reload_button = self._button("Reload")
        self.dbc_button = self._button("DBC Files…")
        self.export_button = self._button("Export…")
        self.file_label = QLabel()
        self.file_label.setObjectName("hintLabel")
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.filter_input = QLineEdit()
        self.filter_input.setClearButtonEnabled(True)
        self.channel_input = NoWheelComboBox()
        self.direction_input = NoWheelComboBox()
        for key, value in (("All", "all"), ("Rx", "rx"), ("Tx", "tx")):
            self.direction_input.addItem(key, value)
        self.errors_input = QCheckBox()
        self.errors_input.setChecked(True)
        self.mode_input = NoWheelComboBox()
        self.mode_input.addItem("Chronological", "chronological")
        self.mode_input.addItem("Fixed position", "fixed")
        self.time_input = NoWheelComboBox()
        self.time_input.addItem("Relative", "relative")
        self.time_input.addItem("Absolute", "absolute")
        self.find_input = QLineEdit()
        self.find_input.setClearButtonEnabled(True)
        self.find_input.setMinimumWidth(140)
        self.filter_input.setMinimumWidth(220)
        self._binder.bind(self.filter_input.setPlaceholderText, "IDs, ranges or names: 100, 200-2FF, 18FF00x, Engine")
        self._binder.bind(self.find_input.setPlaceholderText, "ID or name")
        self.find_prev_button = QPushButton("◀")
        self.find_next_button = QPushButton("▶")
        self._binder.bind(self.find_prev_button.setToolTip, "Find previous")
        self._binder.bind(self.find_next_button.setToolTip, "Find next")

        self.model = TraceModel(self)
        self.trace = QTableView()
        self.trace.setObjectName("traceView")
        self.trace.setModel(self.model)
        self.trace.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.trace.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.trace.setAlternatingRowColors(True)
        self.trace.setWordWrap(False)
        self.trace.verticalHeader().hide()
        self.trace.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.trace.verticalHeader().setDefaultSectionSize(22)
        header = self.trace.horizontalHeader()
        header.setStretchLastSection(True)
        for column, width in enumerate((120, 44, 90, 180, 56, 90, 40)):
            header.resizeSection(column, width)

        self.signals = QTreeWidget()
        self.signals.setColumnCount(4)
        self.signals.setRootIsDecorated(False)
        self.signals.setAlternatingRowColors(True)
        self.stats_table = QTableWidget(0, 8)
        self.stats_table.verticalHeader().hide()
        self.stats_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stats_table.setSortingEnabled(True)
        self.stats_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.details = QTabWidget()
        self.details.addTab(self.signals, "")
        self.details.addTab(self.stats_table, "")
        self.details.addTab(self.info, "")

        from can_toolbox.ui.graphics import GraphPanel, SignalTree

        self.graph = GraphPanel(self._binder)
        self.signal_search = QLineEdit()
        self.signal_search.setClearButtonEnabled(True)
        self._binder.bind(self.signal_search.setPlaceholderText, "Search signals")
        self._binder.bind(self.signal_search.setAccessibleName, "Search signals")
        self.signal_tree = SignalTree()
        self.add_signal_button = self._button("Add to Graph")
        browser = QWidget()
        browser_layout = QVBoxLayout(browser)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.addWidget(self.signal_search)
        browser_layout.addWidget(self.signal_tree, 1)
        browser_layout.addWidget(self.add_signal_button)

        center = QSplitter(Qt.Orientation.Vertical)
        center.addWidget(self.graph)
        center.addWidget(self.trace)
        center.addWidget(self.details)
        center.setStretchFactor(0, 2)
        center.setStretchFactor(1, 3)
        center.setStretchFactor(2, 1)
        center.setSizes([400, 300, 150])
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(browser)
        splitter.addWidget(center)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 900])

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.cancel_button = self._button("Cancel")
        self.cancel_button.hide()
        self.status = QLabel()
        self.status.setObjectName("runStatus")

        top = QHBoxLayout()
        top.setSpacing(8)
        for widget in (self.open_button, self.reload_button, self.dbc_button, self.export_button):
            top.addWidget(widget)
        top.addWidget(self.file_label, 1)
        self._add_labeled(top, "Mode", self.mode_input)
        self._add_labeled(top, "Time", self.time_input)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        self._add_labeled(filters, "Filter", self.filter_input, 3)
        self._add_labeled(filters, "Channel", self.channel_input)
        self._add_labeled(filters, "Direction", self.direction_input)
        filters.addWidget(self.errors_input)
        filters.addSpacing(12)
        self._add_labeled(filters, "Find", self.find_input, 2)
        filters.addWidget(self.find_prev_button)
        filters.addWidget(self.find_next_button)

        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.progress, 1)
        bottom.addWidget(self.cancel_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addLayout(filters)
        layout.addWidget(splitter, 1)
        layout.addLayout(bottom)
        self._set_controls_enabled()

    def _add_labeled(self, layout: QHBoxLayout, key: str, widget: QWidget, stretch: int = 0) -> None:
        label = self._label(key)
        label.setBuddy(widget)
        self._binder.bind(widget.setAccessibleName, key)
        layout.addWidget(label)
        layout.addWidget(widget, stretch)

    def _wire_events(self) -> None:
        self.open_button.clicked.connect(self._choose_log)
        self.reload_button.clicked.connect(lambda: self.open_log(self.log_path))
        self.dbc_button.clicked.connect(self._edit_dbcs)
        self.export_button.clicked.connect(self._export)
        self.cancel_button.clicked.connect(self._cancel_load)
        self.filter_input.returnPressed.connect(self._apply_filter)
        self.filter_input.textChanged.connect(lambda text: self._apply_filter() if not text else None)
        for combo in (self.channel_input, self.direction_input, self.mode_input):
            combo.currentIndexChanged.connect(self._apply_filter)
        self.errors_input.toggled.connect(self._apply_filter)
        self.time_input.currentIndexChanged.connect(self._apply_time_mode)
        self.find_input.returnPressed.connect(partial(self._find, True))
        self.find_next_button.clicked.connect(partial(self._find, True))
        self.find_prev_button.clicked.connect(partial(self._find, False))
        self.trace.selectionModel().currentRowChanged.connect(self._show_signals)
        self.trace.selectionModel().currentRowChanged.connect(self._trace_moved)
        self.details.currentChanged.connect(lambda _: self._refresh_statistics())
        self.signal_search.textChanged.connect(self.signal_tree.apply_filter)
        self.signal_tree.signal_activated.connect(self.plot_signal)
        self.add_signal_button.clicked.connect(self._plot_selected)
        self.graph.signal_dropped.connect(self.plot_signal)
        self.graph.cursor_moved.connect(self._cursor_moved)

    def _update_language(self) -> None:
        self._binder.set_language(self._binder.language)
        tr = self._tr
        self.errors_input.setText(tr("Errors"))
        for index, key in enumerate(("All", "Rx", "Tx")):
            self.direction_input.setItemText(index, tr(key))
        self.mode_input.setItemText(0, tr("Chronological"))
        self.mode_input.setItemText(1, tr("Fixed position"))
        self.time_input.setItemText(0, tr("Relative"))
        self.time_input.setItemText(1, tr("Absolute"))
        if self.channel_input.count():
            self.channel_input.setItemText(0, tr("All"))
        self.model.headers = [tr(column) for column in COLUMNS]
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(COLUMNS) - 1)
        self.signals.setHeaderLabels([tr("Signal"), tr("Value"), tr("Raw"), tr("Unit")])
        self.stats_table.setHorizontalHeaderLabels([
            tr("Chn"), tr("ID"), tr("Name"), tr("Count"), tr("First (s)"), tr("Cycle min (ms)"),
            tr("Cycle avg (ms)"), tr("Cycle max (ms)"),
        ])
        for index, key in enumerate(("Signal Values", "Statistics", "Log Info")):
            self.details.setTabText(index, tr(key))
        self._update_file_label()
        self.graph.set_languages()
        key, parameters = self._status
        self._set_status(key, **parameters)

    def _set_status(self, key: str, **parameters: object) -> None:
        self._status = (key, parameters)
        self.status.setText(self._tr(key, **parameters))

    def _update_file_label(self) -> None:
        dbcs = len(self.dbc_assignments)
        name = Path(self.log_path).name if self.log_path else self._tr("No log loaded")
        self.file_label.setText(self._tr("{log}  ·  {count} DBC file(s)", log=name, count=dbcs))
        self.file_label.setToolTip(self.log_path)

    def _set_controls_enabled(self) -> None:
        loaded = self.view is not None
        busy = self.is_busy()
        self.open_button.setEnabled(not busy)
        self.reload_button.setEnabled(not busy and bool(self.log_path) and Path(self.log_path).is_file())
        self.dbc_button.setEnabled(not busy)
        self.export_button.setEnabled(loaded and not busy)
        for widget in (self.filter_input, self.channel_input, self.direction_input, self.errors_input,
                       self.mode_input, self.time_input, self.find_input, self.find_prev_button,
                       self.find_next_button, self.signal_search, self.add_signal_button):
            widget.setEnabled(loaded and not busy)

    # -- settings ------------------------------------------------------------------

    def _load_assignments(self) -> list[tuple[str, int]]:
        raw = self._settings.value(_SETTINGS_PREFIX + "dbc_assignments", "[]", type=str)
        try:
            items = json.loads(raw)
            return [(str(path), int(channel)) for path, channel in items]
        except (ValueError, TypeError):
            return []

    def _save_assignments(self) -> None:
        self._settings.setValue(_SETTINGS_PREFIX + "dbc_assignments", json.dumps(self.dbc_assignments))

    # -- loading -------------------------------------------------------------------

    def _choose_log(self) -> None:
        start = str(Path(self.log_path).parent) if self.log_path else ""
        path, _ = QFileDialog.getOpenFileName(self, self._tr("Open CAN log"), start, LOG_FILTER)
        if path:
            self.open_log(path)

    def _assignments(self):
        from can_toolbox.canlog.database import DbcAssignment

        return [DbcAssignment(Path(path), channel) for path, channel in self.dbc_assignments]

    def open_log(self, path: str) -> None:
        if self.is_busy() or not path:
            return
        self.log_path = str(Path(path))
        self._settings.setValue(_SETTINGS_PREFIX + "last_log", self.log_path)
        self._update_file_label()
        assignments = self._assignments()
        log_path = Path(self.log_path)
        self.worker = Task(lambda task: load_view(log_path, assignments, task))
        self.worker.progress.connect(self.progress.setValue)
        self.worker.succeeded.connect(self._on_loaded)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_worker_finished)
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        self._set_status("Reading {name}…", name=log_path.name)
        self.worker.start()
        self.busy_changed.emit(True)
        self._set_controls_enabled()

    def _export(self) -> None:
        if self.view is None or self.is_busy():
            return
        view = self.view
        duration = (int(view.frames.time_ns[view.order[-1]]) - view.origin_ns) / 1e9 if len(view.order) else 0.0
        cursors = tuple(self.graph.cursor_time) if self.graph.measure_input.isChecked() and self.graph.series else None
        log_path = Path(self.log_path)
        default = self._settings.value(_SETTINGS_PREFIX + "last_export", "", type=str)
        default = str(Path(default).parent / f"{log_path.stem}_cut{Path(default).suffix}") if default else \
            str(log_path.with_name(f"{log_path.stem}_cut.blf"))
        dialog = ExportDialog(self, self._binder, duration=duration, cursors=cursors,
                              filtered_count=len(view.rows), total_count=len(view.order), default_path=default)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            request, path = dialog.request, dialog.path
        finally:
            dialog.deleteLater()
        self.start_export(request, path)

    def start_export(self, request, path: Path) -> None:
        from can_toolbox.canlog.export import export_log

        view = self.view
        self._settings.setValue(_SETTINGS_PREFIX + "last_export", str(path))
        self.worker = Task(lambda task: export_log(view, request, path, progress=task.report,
                                                   cancel=task.cancelled.is_set))
        self.worker.progress.connect(self.progress.setValue)
        self.worker.succeeded.connect(self._on_exported)
        self.worker.failed.connect(lambda message: self._set_status("Export failed: {error}", error=message))
        self.worker.finished.connect(self._on_worker_finished)
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        self._set_status("Exporting {name}…", name=path.name)
        self.worker.start()
        self.busy_changed.emit(True)
        self._set_controls_enabled()

    def _on_exported(self, result) -> None:
        self.last_export = result
        self._set_status("Exported {count} frames to {name}.", count=f"{result.frames:,}", name=result.path.name)
        if result.warnings:
            self.info.appendPlainText("\n".join(f"[!] {warning}" for warning in result.warnings))

    def _cancel_load(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancelled.set()
            self._set_status("Cancelled.")

    def _on_worker_finished(self) -> None:
        self.progress.hide()
        self.cancel_button.hide()
        self.busy_changed.emit(False)
        self._set_controls_enabled()

    def _on_failed(self, message: str) -> None:
        self._set_status("Could not open the log: {error}", error=message)

    def _on_loaded(self, view) -> None:
        self.view = view
        frames = view.frames
        duration = (int(frames.time_ns[view.order[-1]]) - view.origin_ns) / 1e9 if len(frames) else 0.0
        self._loaded_summary = {"count": f"{len(frames):,}", "duration": f"{duration:.3f}"}
        self._populate_channels()
        self._stats_dirty = True
        self._apply_filter()
        self._show_info()
        self._reset_signals()
        if view.log.warnings or view.database.errors:
            self.details.setCurrentWidget(self.info)

    def _populate_channels(self) -> None:
        import numpy as np

        self.channel_input.blockSignals(True)
        self.channel_input.clear()
        self.channel_input.addItem(self._tr("All"), 0)
        for channel in np.unique(self.view.frames.channel):
            if channel:
                self.channel_input.addItem(f"CAN {int(channel)}", int(channel))
        self.channel_input.blockSignals(False)

    def _show_info(self) -> None:
        view = self.view
        frames = view.frames
        lines = [
            f"{self._tr('File')}: {view.log.path}",
            f"{self._tr('Format')}: {view.log.format}",
            f"{self._tr('Frames')}: {len(frames):,}",
            f"{self._tr('Memory')}: {frames.nbytes / 1e6:.1f} MB",
        ]
        if frames.start_time > 0:
            start = datetime.datetime.fromtimestamp(frames.start_time + view.origin_ns / 1e9)
            lines.append(f"{self._tr('Start')}: {start.isoformat(sep=' ', timespec='milliseconds')}")
        for assignment in view.database.assignments:
            scope = self._tr("All channels") if not assignment.channel else f"CAN {assignment.channel}"
            lines.append(f"DBC [{scope}]: {assignment.path}")
        lines += [f"[!] {warning}" for warning in view.log.warnings]
        lines += [f"[DBC] {error}" for error in view.database.errors]
        self.info.setPlainText("\n".join(lines))

    def _edit_dbcs(self) -> None:
        start = str(Path(self.dbc_assignments[-1][0]).parent) if self.dbc_assignments else ""
        dialog = DbcDialog(self, self.dbc_assignments, self._binder, start)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.dbc_assignments = dialog.assignments()
        finally:
            dialog.deleteLater()
        self._save_assignments()
        self._update_file_label()
        if self.view is not None:
            from can_toolbox.canlog.database import LogDatabase

            self.view.set_database(LogDatabase.load(self._assignments()))
            self._stats_dirty = True
            self._apply_filter()
            self._show_info()
            self._reset_signals()

    # -- trace ---------------------------------------------------------------------

    def current_filter(self):
        from can_toolbox.canlog.view import FrameFilter, FrameQuery

        channel = int(self.channel_input.currentData() or 0)
        return FrameFilter(
            query=FrameQuery.parse(self.filter_input.text()),
            channels=frozenset({channel}) if channel else frozenset(),
            direction=self.direction_input.currentData(),
            include_errors=self.errors_input.isChecked(),
        )

    def _apply_filter(self, *_args) -> None:
        if self.view is None:
            return
        self.view.apply(self.current_filter())
        fixed = self.mode_input.currentData() == "fixed"
        self.model.set_rows(self.view, self.view.latest_per_message() if fixed else self.view.rows)
        self._stats_dirty = True
        self._refresh_statistics()
        shown = self.model.rowCount()
        if self._loaded_summary:
            self._set_status("{count} frames, {duration} s  ·  {shown} shown", shown=f"{shown:,}",
                             **self._loaded_summary)

    def _apply_time_mode(self, *_args) -> None:
        self.model.set_absolute_time(self.time_input.currentData() == "absolute")

    def _find(self, forward: bool) -> None:
        from can_toolbox.canlog.view import FrameQuery

        if self.view is None or self.mode_input.currentData() == "fixed":
            return
        query = FrameQuery.parse(self.find_input.text())
        current = self.trace.currentIndex().row() if self.trace.currentIndex().isValid() else -1
        position = self.view.find(query, current, forward)
        if position < 0:
            self._set_status("No frame matches {query}.", query=self.find_input.text())
            return
        index = self.model.index(position, 0)
        self.trace.setCurrentIndex(index)
        self.trace.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _show_signals(self, current, _previous=None) -> None:
        from can_toolbox.canlog.database import decode_frame
        from can_toolbox.canlog.decode import frame_keys

        self.signals.clear()
        if self.view is None or not current.isValid():
            return
        row = self.model.frame_row(current.row())
        frames = self.view.frames
        key = int(frame_keys(frames.take([row]))[0])
        codec = self.view.database.codec(key, int(frames.channel[row])) if key >= 0 else None
        if codec is None:
            return
        for value in decode_frame(codec, frames.data(row)):
            physical = value.label if value.label is not None else _number(value.physical)
            raw = value.raw
            raw_text = f"{raw} (0x{raw:X})" if isinstance(raw, int) and raw >= 0 else _number(raw)
            item = QTreeWidgetItem([value.name, str(physical), raw_text, value.unit])
            self.signals.addTopLevelItem(item)
        for column in range(3):
            self.signals.resizeColumnToContents(column)

    # -- graphics ------------------------------------------------------------------

    def _reset_signals(self) -> None:
        """Rebuild the signal list for the current log and DBCs; keep plots that still resolve."""
        from can_toolbox.canlog.signals import SignalSource

        self.source = SignalSource(self.view)
        self.signal_tree.populate(self.source.catalog())
        self.signal_tree.apply_filter(self.signal_search.text())
        refs = self.graph.refs()
        self.graph.clear()
        for ref in refs:
            self.plot_signal(ref, quiet=True)

    def plot_signal(self, ref, quiet: bool = False) -> None:
        if self.view is None:
            return
        try:
            series = self.source.series(ref)
        except KeyError as exc:
            if not quiet:
                self._set_status("Cannot plot {signal}: {error}", signal=ref.signal, error=exc)
            return
        if not self.graph.add_series(series) and not quiet:
            self._set_status("{signal} is already plotted or the graph is full.", signal=ref.signal)

    def _plot_selected(self) -> None:
        for ref in self.signal_tree.selected_refs():
            self.plot_signal(ref)

    def _cursor_moved(self, seconds: float) -> None:
        """Graph cursor drives the trace: select the last frame at or before the cursor."""
        if self.view is None or self.mode_input.currentData() == "fixed" or not self.model.rowCount():
            return
        position = self.view.position_at_time(self.view.origin_ns + int(round(seconds * 1e9)))
        self._cursor_driving = True
        try:
            index = self.model.index(position, 0)
            self.trace.setCurrentIndex(index)
            self.trace.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        finally:
            self._cursor_driving = False

    def _trace_moved(self, current, _previous=None) -> None:
        if self.view is None or not current.isValid() or self._cursor_driving:
            return
        row = self.model.frame_row(current.row())
        self.graph.set_cursor((int(self.view.frames.time_ns[row]) - self.view.origin_ns) / 1e9)

    def _refresh_statistics(self) -> None:
        if self.view is None or not self._stats_dirty or self.details.currentWidget() is not self.stats_table:
            return
        if self.stats_worker and self.stats_worker.isRunning():
            old = self.stats_worker
            old.cancelled.set()
            self._retired.append(old)
            old.finished.connect(lambda: self._retired.remove(old) if old in self._retired else None)
        self._stats_dirty = False
        view = self.view
        self.stats_worker = Task(lambda _task: view.statistics())
        self.stats_worker.succeeded.connect(self._fill_statistics)
        self.stats_worker.start()

    def _fill_statistics(self, stats) -> None:
        from can_toolbox.canlog.view import format_key

        table = self.stats_table
        table.setSortingEnabled(False)
        table.setRowCount(len(stats))
        for row, item in enumerate(stats):
            values = (item.channel, format_key(item.key), item.name, item.count, item.first_s,
                      item.cycle_min_ms, item.cycle_avg_ms, item.cycle_max_ms)
            for column, value in enumerate(values):
                cell = QTableWidgetItem()
                if isinstance(value, (int, float)):
                    cell.setData(Qt.ItemDataRole.DisplayRole, round(value, 3) if isinstance(value, float) else value)
                else:
                    cell.setText("" if value is None else str(value))
                table.setItem(row, column, cell)
        table.setSortingEnabled(True)
        table.resizeColumnsToContents()

    # -- drag & drop ---------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if urls and Path(urls[0].toLocalFile()).suffix.lower() in LOG_SUFFIXES + (".dbc",):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        dbcs = [str(path) for path in paths if path.suffix.lower() == ".dbc"]
        logs = [str(path) for path in paths if path.suffix.lower() in LOG_SUFFIXES]
        if dbcs:
            known = {path for path, _ in self.dbc_assignments}
            self.dbc_assignments += [(path, 0) for path in dbcs if path not in known]
            self._save_assignments()
            self._update_file_label()
        if logs:
            self.open_log(logs[0])
        elif dbcs and self.log_path and not self.is_busy():
            self.open_log(self.log_path)
        event.acceptProposedAction()


def _number(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
