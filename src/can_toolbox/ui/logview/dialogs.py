"""Dialogs of the log viewer: DBC assignment and the export cut."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
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
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from can_toolbox.ui.widgets import NoWheelComboBox, TextBinder, dialog_buttons

LOG_FILTER = "CAN logs (*.blf *.asc *.mf4);;BLF (*.blf);;ASC (*.asc);;MDF4 (*.mf4)"
LOG_SUFFIXES = (".blf", ".asc", ".mf4")
WORKSPACE_FILTER = "CAN Toolbox workspace (*.cantoolbox.json)"
EXPORT_FILTER = "BLF (*.blf);;ASC (*.asc);;MDF4 (*.mf4);;CSV (*.csv);;MATLAB (*.mat)"
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
        self.error_label.setObjectName("errorLabel")
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
