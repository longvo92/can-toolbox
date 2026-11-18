"""Dialogs of the log viewer: DBC assignment; Export has its own module."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from can_toolbox.ui.widgets import NoWheelComboBox, TextBinder, dialog_buttons

LOG_FILTER = (
    "CAN logs (*.blf *.asc *.mf4 *.trc *.log *.csv);;BLF (*.blf);;ASC (*.asc);;MDF4 (*.mf4);;"
    "PEAK trace (*.trc);;candump log (*.log);;CSV (*.csv)"
)
LOG_SUFFIXES = (".blf", ".asc", ".mf4", ".trc", ".log", ".csv")
WORKSPACE_FILTER = "CAN Toolbox workspace (*.cantoolbox.json)"
MAX_CHANNEL_CHOICES = 16


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
        for number in range(1, MAX_CHANNEL_CHOICES + 1):
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
