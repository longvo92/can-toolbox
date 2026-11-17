"""BLF -> MAT tab: convert CAN logs to MATLAB MAT files or Simulink Datasets."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from can_toolbox.blf_mat.converter import SelectedPaths, convert
from can_toolbox.blf_mat.options import (
    ConversionOptions,
    OptionError,
    build_selected_paths,
    default_config_path,
    default_output_folder,
)
from can_toolbox.i18n import translate
from can_toolbox.ui.settings_dialog import matlab_executable
from can_toolbox.ui.widgets import DropLineEdit, NoWheelComboBox, TextBinder, dialog_buttons, scrollable, section

_SETTINGS_PREFIX = "blf/"
_LOG_BATCH_LINES = 200
_LOG_BATCH_SECONDS = 0.1
_LOG_MAX_BLOCKS = 20000
_COLUMNS = (
    ("element_column", "Element column"),
    ("can_column", "CAN column"),
    ("interface_column", "Interface column"),
    ("dtype_column", "Datatype column"),
)


class _LineBatcher:
    """Collect log lines on a worker thread and hand them over in batches.

    A conversion can log thousands of lines; one queued signal per line would
    flood the GUI event loop.
    """

    def __init__(self, emit: Callable[[list], None]) -> None:
        self._emit = emit
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._last = time.monotonic()

    def __call__(self, line: str) -> None:
        with self._lock:
            self._lines.append(str(line))
            due = len(self._lines) >= _LOG_BATCH_LINES or time.monotonic() - self._last >= _LOG_BATCH_SECONDS
        if due:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            lines, self._lines = self._lines, []
            self._last = time.monotonic()
        if lines:
            self._emit(lines)


class ConvertWorker(QThread):
    log = Signal(list)
    converted = Signal(object)
    failed = Signal(str)

    def __init__(self, paths: SelectedPaths) -> None:
        super().__init__()
        self.paths = paths

    def run(self) -> None:
        batcher = _LineBatcher(self.log.emit)
        try:
            convert(self.paths, log_callback=batcher)
        except Exception as exc:
            batcher.flush()
            self.failed.emit(str(exc))
            return
        batcher.flush()
        self.converted.emit(self.paths)


class SheetPickerDialog(QDialog):
    """Choose input and output sheets; nothing checked means automatic detection."""

    def __init__(
        self,
        parent,
        sheet_names: list[str],
        selected: dict[str, tuple[str, ...]],
        *,
        language: str = "en",
    ) -> None:
        super().__init__(parent)
        tr = partial(translate, language)
        self.setWindowTitle(tr("Select Excel Sheets"))
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        hint = QLabel(tr("Check the sheets that hold input and output mappings. Leave a side empty to detect it."))
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        lists = QHBoxLayout()
        self.lists: dict[str, QListWidget] = {}
        for side, title in (("input", "Input sheets"), ("output", "Output sheets")):
            column = QVBoxLayout()
            label = QLabel(tr(title))
            label.setObjectName("sectionTitle")
            column.addWidget(label)
            sheets = QListWidget()
            sheets.setAccessibleName(tr(title))
            for name in sheet_names:
                item = QListWidgetItem(name, sheets)
                item.setCheckState(
                    Qt.CheckState.Checked if name in selected.get(side, ()) else Qt.CheckState.Unchecked
                )
            label.setBuddy(sheets)
            column.addWidget(sheets)
            lists.addLayout(column)
            self.lists[side] = sheets
        layout.addLayout(lists)
        buttons = dialog_buttons(language, QDialogButtonBox.StandardButton.Save, QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_sheets(self) -> dict[str, tuple[str, ...]]:
        return {
            side: tuple(
                sheets.item(row).text()
                for row in range(sheets.count())
                if sheets.item(row).checkState() == Qt.CheckState.Checked
            )
            for side, sheets in self.lists.items()
        }


class BlfTab(QWidget):
    """Convert BLF logs with optional DBC, Excel, TXT and YAML definitions."""

    title_key = "BLF → MAT"
    subtitle_key = "Convert CAN BLF logs to MATLAB MAT files or Simulink Datasets."
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
        del report_language  # The converter writes no localized report.
        self._settings = settings
        self._binder = TextBinder(gui_language)
        self._status = ("Ready to convert", {})
        self._sheets: dict[str, tuple[str, ...]] = {"input": (), "output": ()}
        self.worker: ConvertWorker | None = None
        self.last_output: Path | None = None

        self.blf_input = DropLineEdit()
        self.dbc_input = DropLineEdit()
        self.excel_input = DropLineEdit()
        self.input_schema_input = DropLineEdit()
        self.output_schema_input = DropLineEdit()
        self.config_input = DropLineEdit()
        self.output_input = DropLineEdit()
        self.column_inputs = {name: QLineEdit() for name, _ in _COLUMNS}
        self.header_row_input = QLineEdit()
        self.header_row_input.setValidator(QIntValidator(1, 1_048_576, self))
        self.format_input = NoWheelComboBox()
        self.format_input.addItem("MAT file", "mat")
        self.format_input.addItem("Simulink Dataset (MATLAB)", "dataset")
        self.sheets_button = self._text_widget(QPushButton, "Select Sheets…")
        self.sheets_hint = QLabel()
        self.sheets_hint.setObjectName("hintLabel")
        self.sheets_hint.setWordWrap(True)
        self.convert_button = self._text_widget(QPushButton, "Convert")
        self.open_button = self._text_widget(QPushButton, "Open Output Folder")
        self.progress = QProgressBar()
        self.log_view = QTextEdit()
        self.run_status = QLabel()
        self.run_status.setObjectName("runStatus")
        self.run_status.setWordWrap(True)
        self._accepts = (
            (self.blf_input, True, (".blf",), "Browse or drag & drop a BLF file or folder here"),
            (self.dbc_input, True, (".dbc",), "Optional: a DBC file or a folder of DBCs"),
            (self.excel_input, False, (".xlsx", ".xlsm"), "Optional: interface mapping workbook"),
            (self.input_schema_input, False, (".txt",), "Optional: Interface.Element : datatype"),
            (self.output_schema_input, False, (".txt",), "Optional: Interface.Element : datatype"),
            (self.config_input, False, (".yaml", ".yml"), ""),
            (self.output_input, True, (), ""),
        )

        self._build_layout()
        self._wire_events()
        self._restore_settings()
        self._update_language()

    # -- shell contract ------------------------------------------------------------

    @property
    def _gui_language(self) -> str:
        return self._binder.language

    def set_languages(self, gui_language: str, report_language: str) -> None:
        self._binder.language = gui_language
        self._update_language()

    def is_busy(self) -> bool:
        return any(worker and worker.isRunning() for worker in self._workers())

    def stop_workers(self) -> None:
        for worker in self._workers():
            if worker and worker.isRunning():
                worker.disconnect()
                worker.terminate()
                worker.wait(3000)

    def wait_for_workers(self, timeout_ms: int = 5000) -> None:
        for worker in self._workers():
            if worker:
                worker.wait(timeout_ms)

    def _workers(self) -> tuple[QThread | None, ...]:
        return (self.worker,)

    # -- i18n ----------------------------------------------------------------------

    def _tr(self, key: str, **parameters: object) -> str:
        return self._binder.tr(key, **parameters)

    def _text_widget(self, widget_type, key: str):
        return self._binder.widget(widget_type, key)

    def _update_language(self) -> None:
        self._binder.set_language(self._binder.language)
        for field, _, _, _ in self._accepts:
            field.set_language(self._gui_language)
        self.format_input.setItemText(0, self._tr("MAT file"))
        self.format_input.setItemText(1, self._tr("Simulink Dataset (MATLAB)"))
        self._update_sheet_hint()
        self._update_automatic_hints()
        # Align the field column across cards, as the compare tab does.
        for label in self._row_labels:
            label.setMinimumWidth(0)
            label.setMaximumWidth(16777215)
        width = max(label.sizeHint().width() for label in self._row_labels)
        for label in self._row_labels:
            label.setFixedWidth(width)
        status, parameters = self._status
        self._set_status(status, **parameters)

    def _set_status(self, key: str, **parameters: object) -> None:
        self._status = (key, parameters)
        self.run_status.setText(self._tr(key, **parameters))

    # -- layout --------------------------------------------------------------------

    def _path_row(self, form: QGridLayout, row: int, key: str, field: QLineEdit, *buttons: QPushButton) -> QLabel:
        label = self._text_widget(QLabel, key)
        label.setBuddy(field)
        self._binder.bind(field.setAccessibleName, key)
        self._row_labels.append(label)
        form.addWidget(label, row, 0)
        form.addWidget(field, row, 1)
        for column, button in enumerate(buttons, start=2):
            form.addWidget(button, row, column)
        return label

    def _browse_button(self, key: str, accessible_key: str, handler) -> QPushButton:
        button = self._text_widget(QPushButton, key)
        self._binder.bind(button.setAccessibleName, accessible_key)
        button.clicked.connect(handler)
        self._browse_buttons.append(button)
        return button

    def _build_layout(self) -> None:
        for field, directories, suffixes, placeholder in self._accepts:
            field.set_accepts(directories=directories, suffixes=suffixes, placeholder_key=placeholder,
                              language=self._gui_language)
        self._browse_buttons: list[QPushButton] = []
        self._row_labels: list[QLabel] = []
        browse = self._browse_button

        log_group, log_form = section(self._binder, "CAN Log")
        self._path_row(
            log_form, 0, "BLF file / folder", self.blf_input,
            browse("File…", "Browse BLF file", partial(self._choose_file, self.blf_input, "BLF logs (*.blf)")),
            browse("Folder…", "Browse BLF folder", partial(self._choose_folder, self.blf_input)),
        )

        definitions, form = section(self._binder, "Signal Definitions (optional)")
        self._path_row(
            form, 0, "DBC file / folder", self.dbc_input,
            browse("File…", "Browse DBC file", partial(self._choose_file, self.dbc_input, "DBC files (*.dbc)")),
            browse("Folder…", "Browse DBC folder", partial(self._choose_folder, self.dbc_input)),
        )
        self._path_row(
            form, 1, "Excel workbook", self.excel_input,
            browse("Browse", "Browse Excel workbook",
                   partial(self._choose_file, self.excel_input, "Excel workbooks (*.xlsx *.xlsm)")),
        )
        self._path_row(
            form, 2, "Input TXT schema", self.input_schema_input,
            browse("Browse", "Browse input TXT schema",
                   partial(self._choose_file, self.input_schema_input, "TXT schemas (*.txt)")),
            browse("Clear", "Clear input TXT schema", self.input_schema_input.clear),
        )
        self._path_row(
            form, 3, "Output TXT schema", self.output_schema_input,
            browse("Browse", "Browse output TXT schema",
                   partial(self._choose_file, self.output_schema_input, "TXT schemas (*.txt)")),
            browse("Clear", "Clear output TXT schema", self.output_schema_input.clear),
        )
        self._path_row(
            form, 4, "YAML config", self.config_input,
            browse("Browse", "Browse YAML config",
                   partial(self._choose_file, self.config_input, "YAML mapping (*.yaml *.yml)")),
        )

        excel_box = QGridLayout()
        excel_box.setHorizontalSpacing(8)
        excel_box.setVerticalSpacing(8)
        sheets_row = QHBoxLayout()
        sheets_row.setSpacing(8)
        sheets_row.addWidget(self.sheets_button)
        sheets_row.addWidget(self.sheets_hint, 1)
        excel_box.addLayout(sheets_row, 0, 0, 1, 4)
        self._excel_labels: list[QLabel] = []
        for index, (name, key) in enumerate((*_COLUMNS, ("header_row", "Header row"))):
            field = self.header_row_input if name == "header_row" else self.column_inputs[name]
            label = self._text_widget(QLabel, key)
            label.setBuddy(field)
            self._binder.bind(field.setAccessibleName, key)
            self._binder.bind(field.setPlaceholderText, "Auto")
            row, column = 1 + index // 2, 2 * (index % 2)
            excel_box.addWidget(label, row, column)
            excel_box.addWidget(field, row, column + 1)
            self._excel_labels.append(label)
        excel_box.setColumnStretch(1, 1)
        excel_box.setColumnStretch(3, 1)
        form.addLayout(excel_box, 5, 0, 1, 4)
        excel_hint = self._text_widget(
            QLabel, "Excel options apply only with a workbook. Columns take a header name or a 1-based number."
        )
        excel_hint.setObjectName("hintLabel")
        excel_hint.setWordWrap(True)
        form.addWidget(excel_hint, 6, 0, 1, 4)

        output_group, output_form = section(self._binder, "Output")
        format_label = self._text_widget(QLabel, "Output format")
        format_label.setBuddy(self.format_input)
        self._row_labels.append(format_label)
        self._binder.bind(self.format_input.setAccessibleName, "Output format")
        self.format_input.setMinimumWidth(220)
        output_form.addWidget(format_label, 0, 0)
        output_form.addWidget(self.format_input, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        self._path_row(
            output_form, 1, "Output folder (optional)", self.output_input,
            browse("Browse", "Browse output folder", partial(self._choose_folder, self.output_input)),
        )
        format_hint = self._text_widget(
            QLabel, "MAT needs no MATLAB. Simulink Dataset runs the MATLAB from Settings once per run."
        )
        format_hint.setObjectName("hintLabel")
        format_hint.setWordWrap(True)
        output_form.addWidget(format_hint, 2, 0, 1, 4)

        self.convert_button.setObjectName("primaryButton")
        self._binder.bind(
            self.convert_button.setToolTip,
            "Convert every selected BLF log. Without definitions, raw CAN frames are exported.",
        )
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.run_status, 1)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.convert_button)

        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.open_button.setEnabled(False)
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(_LOG_MAX_BLOCKS)
        self._binder.bind(self.log_view.setPlaceholderText, "Conversion progress and results will appear here.")
        self.log_view.setMinimumHeight(120)
        self.log_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        log_label = self._text_widget(QLabel, "Execution Log")
        log_label.setObjectName("hintLabel")

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        for card in (log_group, definitions, output_group):
            content_layout.addWidget(card)
        content_layout.addWidget(log_label)
        content_layout.addWidget(self.log_view, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(scrollable(content))
        layout.addWidget(self.progress)
        layout.addLayout(buttons)

    def _wire_events(self) -> None:
        self.convert_button.clicked.connect(self._start_conversion)
        self.open_button.clicked.connect(self._open_output)
        self.sheets_button.clicked.connect(self._select_sheets)
        self.format_input.currentIndexChanged.connect(self._update_enabled_controls)
        self.excel_input.textChanged.connect(self._on_excel_changed)
        self.blf_input.textChanged.connect(self._update_automatic_hints)

    # -- field state ---------------------------------------------------------------

    def _dataset(self) -> bool:
        return self.format_input.currentData() == "dataset"

    def _on_excel_changed(self) -> None:
        self._sheets = {"input": (), "output": ()}
        self._update_sheet_hint()
        self._update_enabled_controls()

    def _update_enabled_controls(self) -> None:
        idle = self.convert_button.isEnabled()
        excel = idle and bool(self.excel_input.text().strip())
        for widget in (self.sheets_button, *self.column_inputs.values(), self.header_row_input, *self._excel_labels):
            widget.setEnabled(excel)


    def _update_sheet_hint(self) -> None:
        parts = [
            self._tr("{side}: {sheets}", side=self._tr(title), sheets=", ".join(names))
            for side, title in (("input", "Input sheets"), ("output", "Output sheets"))
            if (names := self._sheets.get(side))
        ]
        self.sheets_hint.setText(" · ".join(parts) or self._tr("Sheets are detected automatically."))

    def _update_automatic_hints(self) -> None:
        blf = self.blf_input.text().strip()
        if blf:
            source = Path(blf)
            hint = self._tr("Automatic: {path}", path=default_output_folder(source))
        else:
            hint = self._tr("Automatic: mat_output beside the BLF file or inside the BLF folder")
        self.output_input.setPlaceholderText(hint)
        self.output_input.setToolTip(hint)
        config = default_config_path()
        config_hint = (
            self._tr("Automatic: {path}", path=config) if config
            else self._tr("Optional: signal_mapping.yaml beside the app is used when present")
        )
        self.config_input.setPlaceholderText(config_hint)
        self.config_input.setToolTip(config_hint)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for widget in (
            self.convert_button, self.format_input, self.blf_input, self.dbc_input,
            self.excel_input, self.input_schema_input, self.output_schema_input, self.config_input,
            self.output_input, *self._browse_buttons,
        ):
            widget.setEnabled(enabled)
        self._update_enabled_controls()
        self.busy_changed.emit(not enabled)

    # -- pickers -------------------------------------------------------------------

    def _choose_file(self, target: QLineEdit, filters: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self._tr("Select File"), target.text().strip(), self._tr(filters))
        if path:
            target.setText(str(Path(path)))

    def _choose_folder(self, target: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, self._tr("Select Folder"), target.text().strip())
        if path:
            target.setText(str(Path(path)))

    def _select_sheets(self) -> None:
        excel = self.excel_input.text().strip()
        try:
            from openpyxl import load_workbook

            book = load_workbook(excel, read_only=True)
            try:
                names = list(book.sheetnames)
            finally:
                book.close()
        except Exception as exc:
            QMessageBox.warning(
                self, self._tr("Excel Workbook"),
                self._tr("Choose a readable Excel workbook first.\n{error}", error=exc),
            )
            return
        dialog = SheetPickerDialog(self, names, self._sheets, language=self._gui_language)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._sheets = dialog.selected_sheets()
            self._update_sheet_hint()

    # -- conversion ----------------------------------------------------------------

    def _options(self) -> ConversionOptions:
        header = self.header_row_input.text().strip()
        return ConversionOptions(
            blf=self.blf_input.text().strip(),
            dbc=self.dbc_input.text().strip(),
            excel=self.excel_input.text().strip(),
            input_schema=self.input_schema_input.text().strip(),
            output_schema=self.output_schema_input.text().strip(),
            output_folder=self.output_input.text().strip(),
            config=self.config_input.text().strip(),
            matlab=matlab_executable(self._settings) if self._dataset() else "",
            output_format=self.format_input.currentData(),
            input_sheets=self._sheets["input"],
            output_sheets=self._sheets["output"],
            header_row=int(header) if header else None,
            **{name: field.text().strip() for name, field in self.column_inputs.items()},
        )

    def _start_conversion(self) -> None:
        try:
            paths = build_selected_paths(self._options())
        except OptionError as exc:
            QMessageBox.warning(self, self._tr("Invalid Input"), str(exc))
            return
        self.log_view.clear()
        self._log(f"Converting {len(paths.blf_files)} BLF file(s) to {paths.output_format.upper()}...")
        self.progress.setRange(0, 0)
        self.progress.show()
        self._set_status("Converting BLF logs…")
        self._set_actions_enabled(False)
        self.open_button.setEnabled(False)
        self.worker = ConvertWorker(paths)
        self.worker.log.connect(self._log_lines)
        self.worker.converted.connect(self._converted)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _finish(self) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.hide()
        self._set_actions_enabled(True)

    def _converted(self, paths: SelectedPaths) -> None:
        self._finish()
        self.last_output = paths.output_folder
        self.open_button.setEnabled(True)
        count = len(paths.blf_files)
        self._set_status("Conversion complete · {count} BLF file(s)", count=count)
        self._log(f"Output folder: {paths.output_folder}")
        self._save_settings()

    def _failed(self, message: str) -> None:
        self._finish()
        self.open_button.setEnabled(self.last_output is not None)
        self._set_status("Conversion failed — see log")
        self._log(f"Failed: {message}")
        QMessageBox.critical(self, self._tr("Conversion Failed"), message)

    def _open_output(self) -> None:
        if self.last_output and self.last_output.is_dir():
            os.startfile(self.last_output)
        else:
            QMessageBox.information(
                self, self._tr("Folder Not Found"),
                self._tr("The output folder no longer exists. Run the conversion again."),
            )

    def _log(self, message: str) -> None:
        self.log_view.append(message)

    def _log_lines(self, lines: list) -> None:
        self.log_view.append("\n".join(lines))

    # -- settings ------------------------------------------------------------------

    def _text_fields(self) -> dict[str, QLineEdit]:
        return {
            "blf": self.blf_input, "dbc": self.dbc_input, "excel": self.excel_input,
            "input_schema": self.input_schema_input, "output_schema": self.output_schema_input,
            "config": self.config_input, "output_folder": self.output_input,
            "header_row": self.header_row_input, **self.column_inputs,
        }

    def _restore_settings(self) -> None:
        for name, field in self._text_fields().items():
            value = self._settings.value(_SETTINGS_PREFIX + name, "")
            if value:
                field.setText(str(value))
        index = self.format_input.findData(self._settings.value(_SETTINGS_PREFIX + "output_format", "mat"))
        self.format_input.setCurrentIndex(max(0, index))
        # Restore sheets after the workbook path, whose change clears them.
        for side in ("input", "output"):
            value = self._settings.value(f"{_SETTINGS_PREFIX}{side}_sheets", [])
            names = [value] if isinstance(value, str) else list(value or [])
            self._sheets[side] = tuple(name for name in names if name)
        self._update_enabled_controls()

    def _save_settings(self) -> None:
        for name, field in self._text_fields().items():
            self._settings.setValue(_SETTINGS_PREFIX + name, field.text().strip())
        self._settings.setValue(_SETTINGS_PREFIX + "output_format", self.format_input.currentData())
        for side in ("input", "output"):
            self._settings.setValue(f"{_SETTINGS_PREFIX}{side}_sheets", list(self._sheets[side]))
