"""One Export window for the open log: a cut, the formats to write and the definitions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from can_toolbox.ui.widgets import NoWheelComboBox, TextBinder, section

CONFIG_FILTER = "Mapping config (*.yaml *.yml *.json *.txt)"
EXCEL_FILTER = "Excel template (*.xlsx *.xlsm)"
SETTINGS_PREFIX = "logview/"
# Checkbox key, label key, needs signal definitions.
FORMAT_ROWS = (
    ("blf", "BLF (*.blf)", False),
    ("asc", "ASC (*.asc)", False),
    ("mf4", "MF4 (*.mf4)", False),
    ("csv", "CSV (*.csv)", False),
    ("mat", "MAT frames (*.mat)", False),
    ("signals", "MAT signals (*.mat)", True),
    ("dataset", "Simulink Dataset (*.mat)", True),
)


class ExportDialog(QDialog):
    """Range, formats, definitions and output of one export run."""

    def __init__(
        self,
        parent: QWidget,
        binder: TextBinder,
        *,
        settings: QSettings,
        duration: float,
        cursors: tuple[float, float] | None,
        filtered_count: int,
        total_count: int,
        folder: str,
        base_name: str,
        dbc_paths: tuple[tuple[Path, int], ...] = (),
    ) -> None:
        super().__init__(parent)
        self._binder = binder
        self._tr = binder.tr
        self._settings = settings
        self._cursors = cursors
        self._dbc_paths = dbc_paths
        self.job = None
        tr = self._tr
        self.setWindowTitle(tr("Export Log"))
        self.resize(720, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(self._range_card(duration, cursors, filtered_count, total_count))
        layout.addWidget(self._format_card())
        layout.addWidget(self._definitions_card())
        layout.addWidget(self._output_card(folder, base_name))

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
        self._restore()
        # Connected last: every widget the handler touches exists by now.
        for box in self.format_inputs.values():
            box.toggled.connect(self._update_enabled)
        for field in (self.config_input, self.excel_input):
            field.textChanged.connect(self._update_enabled)
        self._update_enabled()

    # -- cards ---------------------------------------------------------------------

    def _range_card(self, duration, cursors, filtered_count, total_count) -> QWidget:
        tr = self._tr
        card, grid = section(self._binder, "Range")
        self.whole = QRadioButton(tr("Whole log ({duration} s)", duration=f"{duration:.3f}"))
        self.between = QRadioButton(tr("Between graph cursors"))
        self.custom = QRadioButton(tr("From / to (s)"))
        self.start_input = QLineEdit("0")
        self.end_input = QLineEdit(f"{duration:.6f}")
        if cursors is not None:
            low, high = sorted(cursors)
            self.between.setText(tr("Between graph cursors ({start} – {end} s)",
                                    start=f"{low:.6f}", end=f"{high:.6f}"))
            self.start_input.setText(f"{low:.6f}")
            self.end_input.setText(f"{high:.6f}")
        self.between.setEnabled(cursors is not None)
        (self.between if cursors is not None else self.whole).setChecked(True)
        custom_row = QHBoxLayout()
        custom_row.addWidget(self.custom)
        custom_row.addWidget(self.start_input)
        custom_row.addWidget(QLabel("–"))
        custom_row.addWidget(self.end_input)
        grid.addWidget(self.whole, 0, 0, 1, 2)
        grid.addWidget(self.between, 1, 0, 1, 2)
        grid.addLayout(custom_row, 2, 0, 1, 2)
        self.filtered_input = QCheckBox(tr("Only frames shown in the trace ({shown} of {total})",
                                           shown=f"{filtered_count:,}", total=f"{total_count:,}"))
        self.filtered_input.setChecked(filtered_count != total_count)
        grid.addWidget(self.filtered_input, 3, 0, 1, 2)

        options = QFormLayout()
        self.channel_map_input = QLineEdit()
        self.channel_map_input.setPlaceholderText(tr("Optional, for example 1=2, 2=1"))
        self.time_input = NoWheelComboBox()
        self.time_input.addItem(tr("Keep original times"), False)
        self.time_input.addItem(tr("Start at 0"), True)
        options.addRow(tr("Channel mapping"), self.channel_map_input)
        options.addRow(tr("Time base"), self.time_input)
        grid.addLayout(options, 4, 0, 1, 2)
        return card

    def _format_card(self) -> QWidget:
        card, grid = section(self._binder, "Output formats")
        self.format_inputs: dict[str, QCheckBox] = {}
        for index, (key, label, needs_signals) in enumerate(FORMAT_ROWS):
            box = QCheckBox(self._tr(label))
            box.setProperty("needsSignals", needs_signals)
            grid.addWidget(box, index // 2, index % 2)
            self.format_inputs[key] = box
        self.format_inputs["blf"].setChecked(True)
        hint = self._binder.widget(
            QLabel, "MAT signals and Simulink Dataset decode the cut; they need a DBC, an Excel template or a config.",
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        grid.addWidget(hint, (len(FORMAT_ROWS) + 1) // 2, 0, 1, 2)
        return card

    def _definitions_card(self) -> QWidget:
        card, grid = section(self._binder, "Signal definitions")
        self.dbc_label = QLabel()
        self.dbc_label.setObjectName("hintLabel")
        self.dbc_label.setWordWrap(True)
        self.dbc_label.setText(self._tr(
            "DBC files: {count} assigned in the Log Viewer", count=len(self._dbc_paths),
        ))
        grid.addWidget(self.dbc_label, 0, 0, 1, 4)
        self.config_input = QLineEdit()
        self.config_input.setPlaceholderText(self._tr("Optional: YAML, JSON or TXT mapping"))
        self.excel_input = QLineEdit()
        self.excel_input.setPlaceholderText(self._tr("Optional: Excel template"))
        self._path_row(grid, 1, "Mapping config", self.config_input, CONFIG_FILTER)
        self._path_row(grid, 2, "Excel template", self.excel_input, EXCEL_FILTER)
        buttons = QHBoxLayout()
        self.template_button = self._binder.widget(QPushButton, "Save Excel template…")
        self.upgrade_button = self._binder.widget(QPushButton, "Save upgraded config…")
        buttons.addStretch()
        buttons.addWidget(self.template_button)
        buttons.addWidget(self.upgrade_button)
        grid.addLayout(buttons, 3, 0, 1, 4)
        self.template_button.clicked.connect(self._save_template)
        self.upgrade_button.clicked.connect(self._save_upgraded_config)
        return card

    def _output_card(self, folder: str, base_name: str) -> QWidget:
        card, grid = section(self._binder, "Output")
        self.folder_input = QLineEdit(folder)
        self.name_input = QLineEdit(base_name)
        self._path_row(grid, 0, "Output folder", self.folder_input, "")
        label = self._binder.widget(QLabel, "File name")
        label.setBuddy(self.name_input)
        grid.addWidget(label, 1, 0)
        grid.addWidget(self.name_input, 1, 1, 1, 3)
        hint = self._binder.widget(QLabel, "Each format is written as <name> with its own extension.")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        grid.addWidget(hint, 2, 0, 1, 4)
        return card

    def _path_row(self, grid: QGridLayout, row: int, key: str, field: QLineEdit, filters: str) -> None:
        label = self._binder.widget(QLabel, key)
        label.setBuddy(field)
        self._binder.bind(field.setAccessibleName, key)
        browse = self._binder.widget(QPushButton, "Browse…")
        browse.clicked.connect(lambda: self._browse(field, filters))
        grid.addWidget(label, row, 0)
        grid.addWidget(field, row, 1, 1, 2)
        grid.addWidget(browse, row, 3)

    # -- behaviour -----------------------------------------------------------------

    def _browse(self, field: QLineEdit, filters: str) -> None:
        if filters:
            path, _ = QFileDialog.getOpenFileName(self, self._tr("Select File"), field.text().strip(), filters)
        else:
            path = QFileDialog.getExistingDirectory(self, self._tr("Select Folder"), field.text().strip())
        if path:
            field.setText(str(Path(path)))

    def selected_formats(self) -> tuple[str, ...]:
        return tuple(key for key, box in self.format_inputs.items() if box.isChecked())

    def _update_enabled(self, *_args) -> None:
        """Keep the Export button and the warning in step with the chosen formats."""
        needs_signals = any(
            box.isChecked() for box in self.format_inputs.values() if box.property("needsSignals")
        )
        self.export_button.setEnabled(bool(self.selected_formats()))
        self.upgrade_button.setEnabled(bool(self.config_input.text().strip()))
        missing = needs_signals and not (
            self._dbc_paths or self.config_input.text().strip() or self.excel_input.text().strip()
        )
        if missing:
            self.error_label.setText(self._tr(
                "MAT signals and Simulink Dataset need a DBC, an Excel template or a mapping config."
            ))
        elif self.error_label.text():
            self.error_label.clear()

    def _save_template(self) -> None:
        from can_toolbox.blf_mat.excel_template import write_template

        start = self.excel_input.text().strip() or str(Path(self.folder_input.text().strip() or ".") / "mapping_template.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, self._tr("Save Excel template…"), start, EXCEL_FILTER)
        if not path:
            return
        try:
            written = write_template(Path(path))
        except OSError as exc:
            self.error_label.setText(str(exc))
            return
        self.excel_input.setText(str(written))
        self.error_label.setText(self._tr("Template written: {name}", name=written.name))

    def _save_upgraded_config(self) -> None:
        from can_toolbox.blf_mat.config import ConfigError, load_config, write_config

        source = self.config_input.text().strip()
        if not source:
            self.error_label.setText(self._tr("Choose a mapping config to upgrade first."))
            return
        start = str(Path(source).with_name(Path(source).stem + "_v2" + Path(source).suffix))
        path, _ = QFileDialog.getSaveFileName(self, self._tr("Save upgraded config…"), start, CONFIG_FILTER)
        if not path:
            return
        try:
            written = write_config(Path(path), load_config(Path(source)))
        except (ConfigError, OSError) as exc:
            self.error_label.setText(str(exc))
            return
        self.config_input.setText(str(written))
        self.error_label.setText(self._tr("Config written: {name}", name=written.name))

    # -- result --------------------------------------------------------------------

    def build(self):
        """The validated :class:`ExportJob`; raises ValueError with a message for the user."""
        from can_toolbox.canlog.export import ExportJob, ExportRequest, parse_channel_map

        formats = self.selected_formats()
        if not formats:
            raise ValueError(self._tr("Choose at least one output format."))
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
        folder = Path(self.folder_input.text().strip() or ".")
        name = self.name_input.text().strip()
        if not name:
            raise ValueError(self._tr("Choose a name for the exported files."))
        config_path = Path(self.config_input.text().strip()) if self.config_input.text().strip() else None
        excel = Path(self.excel_input.text().strip()) if self.excel_input.text().strip() else None
        for path, label in ((config_path, "Mapping config"), (excel, "Excel template")):
            if path is not None and not path.is_file():
                raise ValueError(self._tr("{label} does not exist: {path}", label=self._tr(label), path=path))
        needs_signals = any(key in formats for key in ("signals", "dataset"))
        if needs_signals and not (self._dbc_paths or config_path or excel):
            raise ValueError(self._tr(
                "MAT signals and Simulink Dataset need a DBC, an Excel template or a mapping config."
            ))
        request = ExportRequest(start_s=start, end_s=end, filtered=self.filtered_input.isChecked(),
                                channel_map=channel_map, rebase=bool(self.time_input.currentData()))
        return ExportJob(
            request=request,
            formats=formats,
            folder=folder,
            base_name=name,
            dbc_paths=self._dbc_paths,
            excel=excel,
            config_path=config_path,
            matlab=str(self._settings.value("matlab/executable", "", type=str)).strip(),
        )

    def _accept(self) -> None:
        try:
            self.job = self.build()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        self._save()
        self.accept()

    # -- settings ------------------------------------------------------------------

    def _restore(self) -> None:
        stored = self._settings.value(SETTINGS_PREFIX + "export_formats", [])
        names = [stored] if isinstance(stored, str) else list(stored or [])
        if names:
            for key, box in self.format_inputs.items():
                box.setChecked(key in names)
        for key, field in (("export_config", self.config_input), ("export_excel", self.excel_input)):
            value = str(self._settings.value(SETTINGS_PREFIX + key, "", type=str))
            if value:
                field.setText(value)

    def _save(self) -> None:
        self._settings.setValue(SETTINGS_PREFIX + "export_formats", list(self.selected_formats()))
        self._settings.setValue(SETTINGS_PREFIX + "export_config", self.config_input.text().strip())
        self._settings.setValue(SETTINGS_PREFIX + "export_excel", self.excel_input.text().strip())
        self._settings.setValue(SETTINGS_PREFIX + "export_folder", self.folder_input.text().strip())
