"""Dockable pieces of the log viewer: filter bar, trace view, signal browser, details."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from can_toolbox.ui.widgets import NoWheelComboBox, TextBinder

STATISTICS_COLUMNS = (
    "Chn", "ID", "Name", "Count", "First (s)", "Cycle min (ms)", "Cycle avg (ms)", "Cycle max (ms)",
)
SIGNAL_VALUE_COLUMNS = ("Signal", "Value", "Raw", "Unit")


def build_trace_view(model) -> QTableView:
    """CANoe-style trace table: fixed row height, monospace columns, single row selection."""
    trace = QTableView()
    trace.setObjectName("traceView")
    trace.setModel(model)
    trace.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    trace.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    trace.setAlternatingRowColors(True)
    trace.setWordWrap(False)
    trace.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    trace.verticalHeader().hide()
    trace.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    trace.verticalHeader().setDefaultSectionSize(22)
    header = trace.horizontalHeader()
    header.setStretchLastSection(True)
    for column, width in enumerate((120, 44, 90, 180, 56, 90, 40)):
        header.resizeSection(column, width)
    return trace


def build_signal_values() -> QTreeWidget:
    tree = QTreeWidget()
    tree.setColumnCount(len(SIGNAL_VALUE_COLUMNS))
    tree.setRootIsDecorated(False)
    tree.setAlternatingRowColors(True)
    return tree


def build_statistics_table() -> QTableWidget:
    table = QTableWidget(0, len(STATISTICS_COLUMNS))
    table.verticalHeader().hide()
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSortingEnabled(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    return table


def build_info_view() -> QPlainTextEdit:
    info = QPlainTextEdit()
    info.setReadOnly(True)
    return info


def fill_statistics(table: QTableWidget, stats) -> None:
    from can_toolbox.canlog.view import format_key

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


class FilterBar(QWidget):
    """Trace filter, display mode and find controls; owns no log state."""

    filter_changed = Signal()
    time_mode_changed = Signal()
    find_requested = Signal(bool)

    def __init__(self, binder: TextBinder, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._binder = binder
        self.filter_input = QLineEdit()
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.setMinimumWidth(220)
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
        binder.bind(self.filter_input.setPlaceholderText, "IDs, ranges or names: 100, 200-2FF, 18FF00x, Engine")
        binder.bind(self.find_input.setPlaceholderText, "ID or name")
        self.find_prev_button = QPushButton("◀")
        self.find_next_button = QPushButton("▶")
        binder.bind(self.find_prev_button.setToolTip, "Find previous")
        binder.bind(self.find_next_button.setToolTip, "Find next")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        self._add_labeled(layout, "Filter", self.filter_input, 3)
        self._add_labeled(layout, "Channel", self.channel_input)
        self._add_labeled(layout, "Direction", self.direction_input)
        layout.addWidget(self.errors_input)
        layout.addSpacing(12)
        self._add_labeled(layout, "Mode", self.mode_input)
        self._add_labeled(layout, "Time", self.time_input)
        layout.addSpacing(12)
        self._add_labeled(layout, "Find", self.find_input, 2)
        layout.addWidget(self.find_prev_button)
        layout.addWidget(self.find_next_button)

        self.filter_input.returnPressed.connect(self.filter_changed)
        self.filter_input.textChanged.connect(lambda text: self.filter_changed.emit() if not text else None)
        for combo in (self.channel_input, self.direction_input, self.mode_input):
            combo.currentIndexChanged.connect(self.filter_changed)
        self.errors_input.toggled.connect(self.filter_changed)
        self.time_input.currentIndexChanged.connect(self.time_mode_changed)
        self.find_input.returnPressed.connect(partial(self.find_requested.emit, True))
        self.find_next_button.clicked.connect(partial(self.find_requested.emit, True))
        self.find_prev_button.clicked.connect(partial(self.find_requested.emit, False))
        self.update_language()

    def _add_labeled(self, layout: QHBoxLayout, key: str, widget: QWidget, stretch: int = 0) -> None:
        label = self._binder.widget(QLabel, key)
        label.setBuddy(widget)
        self._binder.bind(widget.setAccessibleName, key)
        layout.addWidget(label)
        layout.addWidget(widget, stretch)

    # -- state ---------------------------------------------------------------------

    def current_filter(self):
        from can_toolbox.canlog.view import FrameFilter, FrameQuery

        channel = int(self.channel_input.currentData() or 0)
        return FrameFilter(
            query=FrameQuery.parse(self.filter_input.text()),
            channels=frozenset({channel}) if channel else frozenset(),
            direction=self.direction_input.currentData(),
            include_errors=self.errors_input.isChecked(),
        )

    def mode(self) -> str:
        return str(self.mode_input.currentData())

    def time_mode(self) -> str:
        return str(self.time_input.currentData())

    def populate_channels(self, channels) -> None:
        self.channel_input.blockSignals(True)
        self.channel_input.clear()
        self.channel_input.addItem(self._binder.tr("All"), 0)
        for channel in channels:
            self.channel_input.addItem(f"CAN {int(channel)}", int(channel))
        self.channel_input.blockSignals(False)

    def set_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.filter_input, self.channel_input, self.direction_input, self.errors_input,
                       self.mode_input, self.time_input, self.find_input, self.find_prev_button,
                       self.find_next_button):
            widget.setEnabled(enabled)

    def restore_display_modes(self, mode: str, time_mode: str) -> None:
        """Workspace display modes, applied before the log is read."""
        for combo, value in ((self.mode_input, mode), (self.time_input, time_mode)):
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)

    def restore_filters(self, text: str, channel: int, direction: str, errors: bool) -> None:
        widgets = (self.channel_input, self.direction_input, self.errors_input, self.filter_input)
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self.filter_input.setText(text)
            self.channel_input.setCurrentIndex(max(self.channel_input.findData(channel), 0))
            self.direction_input.setCurrentIndex(max(self.direction_input.findData(direction), 0))
            self.errors_input.setChecked(errors)
        finally:
            for widget in widgets:
                widget.blockSignals(False)

    def update_language(self) -> None:
        tr = self._binder.tr
        self.errors_input.setText(tr("Errors"))
        for index, key in enumerate(("All", "Rx", "Tx")):
            self.direction_input.setItemText(index, tr(key))
        self.mode_input.setItemText(0, tr("Chronological"))
        self.mode_input.setItemText(1, tr("Fixed position"))
        self.time_input.setItemText(0, tr("Relative"))
        self.time_input.setItemText(1, tr("Absolute"))
        if self.channel_input.count():
            self.channel_input.setItemText(0, tr("All"))


class SignalBrowser(QWidget):
    """Searchable catalog of decodable signals; double-click or Add plots them."""

    plot_requested = Signal(object)
    add_selected = Signal()

    def __init__(self, binder: TextBinder, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from can_toolbox.ui.graphics import SignalTree

        self.search_input = QLineEdit()
        self.search_input.setClearButtonEnabled(True)
        binder.bind(self.search_input.setPlaceholderText, "Search signals")
        binder.bind(self.search_input.setAccessibleName, "Search signals")
        self.tree = SignalTree()
        self.add_button = binder.widget(QPushButton, "Add to Graph")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        layout.addWidget(self.search_input)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.add_button)

        self.search_input.textChanged.connect(self.tree.apply_filter)
        self.tree.signal_activated.connect(self.plot_requested)
        self.add_button.clicked.connect(self.add_selected)

    def sizeHint(self):
        """A narrow column: the tree's own hint would claim a third of the window."""
        return QSize(260, 480)

    def populate(self, catalog) -> None:
        self.tree.populate(catalog)
        self.tree.apply_filter(self.search_input.text())

    def selected_refs(self):
        return self.tree.selected_refs()

    def set_controls_enabled(self, enabled: bool) -> None:
        self.search_input.setEnabled(enabled)
        self.add_button.setEnabled(enabled)
