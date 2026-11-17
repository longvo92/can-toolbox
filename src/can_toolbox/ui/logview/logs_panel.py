"""The Logs panel: every open log, which one is active, and what to do with it."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from can_toolbox.ui import theme as app_theme
from can_toolbox.ui.logview.log_set import LogEntry, LogSet
from can_toolbox.ui.widgets import TextBinder

COLUMNS = ("Name", "Duration", "Frames", "Channels", "Path")


class LogsPanel(QWidget):
    """One row per open log. Double-click or Set Active switches the window to it."""

    activate_requested = Signal(object)
    export_requested = Signal(object)
    reload_requested = Signal(object)
    close_requested = Signal(list)

    def __init__(self, logs: LogSet, binder: TextBinder, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._binder = binder
        self.logs = logs
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

        self.table.itemDoubleClicked.connect(self._activate_item)
        self.table.customContextMenuRequested.connect(self._show_menu)
        logs.changed.connect(self.refresh)
        logs.active_changed.connect(self.refresh)
        app_theme.manager.changed.connect(lambda _theme: self.refresh())
        self.update_language()

    # -- contents ------------------------------------------------------------------

    def update_language(self) -> None:
        self.table.setHorizontalHeaderLabels([self._binder.tr(column) for column in COLUMNS])
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the rows; the active log is the bold one."""
        active = self.logs.active
        self.table.setRowCount(len(self.logs))
        for row, entry in enumerate(self.logs):
            channels = entry.channels()
            values = (
                entry.name,
                f"{entry.duration:.3f} s",
                f"{entry.frames:,}",
                ", ".join(str(channel) for channel in channels) or "-",
                entry.path,
            )
            for column, text in enumerate(values):
                item = self.table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(row, column, item)
                item.setText(text)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                font = item.font()
                font.setBold(entry is active)
                item.setFont(font)
                if column:
                    item.setToolTip(entry.path)
        self.table.resizeColumnsToContents()

    def selected_entries(self) -> list[LogEntry]:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        entries = []
        for row in rows:
            item = self.table.item(row, 0)
            entry = item.data(Qt.ItemDataRole.UserRole) if item else None
            if entry is not None:
                entries.append(entry)
        return entries

    # -- actions -------------------------------------------------------------------

    def _activate_item(self, item) -> None:
        entry = item.data(Qt.ItemDataRole.UserRole)
        if entry is not None:
            self.activate_requested.emit(entry)

    def _show_menu(self, point) -> None:
        entries = self.selected_entries()
        tr = self._binder.tr
        menu = QMenu(self)
        activate_action = menu.addAction(tr("Set Active"))
        activate_action.setEnabled(len(entries) == 1)
        export_action = menu.addAction(tr("Export…"))
        export_action.setEnabled(len(entries) == 1)
        menu.addSeparator()
        reload_action = menu.addAction(tr("Reload"))
        reload_action.setEnabled(len(entries) == 1)
        close_action = menu.addAction(tr("Close"))
        close_action.setEnabled(bool(entries))

        chosen = menu.exec(self.table.viewport().mapToGlobal(point))
        if chosen is None:
            return
        if chosen is activate_action:
            self.activate_requested.emit(entries[0])
        elif chosen is export_action:
            self.export_requested.emit(entries[0])
        elif chosen is reload_action:
            self.reload_requested.emit(entries[0])
        elif chosen is close_action:
            self.close_requested.emit(entries)
