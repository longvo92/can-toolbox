"""One place for the preferences that are not part of a single job: language, theme, MATLAB."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from can_toolbox.ui import theme as app_theme
from can_toolbox.ui.widgets import NoWheelComboBox, TextBinder, dialog_buttons, section

MATLAB_KEY = "matlab/executable"
THEME_KEY = "theme"
LEGACY_MATLAB_KEY = "blf/matlab"


def migrate_tool_settings(settings: QSettings) -> None:
    """Move the MATLAB executable out of the BLF tool, where it used to live."""
    if settings.contains(LEGACY_MATLAB_KEY) and not settings.contains(MATLAB_KEY):
        value = str(settings.value(LEGACY_MATLAB_KEY, "", type=str)).strip()
        if value:
            settings.setValue(MATLAB_KEY, value)
    settings.remove(LEGACY_MATLAB_KEY)


def matlab_executable(settings: QSettings) -> str:
    return str(settings.value(MATLAB_KEY, "", type=str)).strip()


def theme_mode(settings: QSettings) -> str:
    mode = str(settings.value(THEME_KEY, "system", type=str))
    return mode if mode in app_theme.MODES else "system"


class EnvironmentWorker(QThread):
    """Report the runtime the converter needs; never starts MATLAB."""

    log = Signal(list)
    finished_check = Signal(int)

    def __init__(self, matlab: str, *, require_matlab: bool) -> None:
        super().__init__()
        self.matlab = matlab
        self.require_matlab = require_matlab

    def run(self) -> None:
        from can_toolbox.blf_mat.checks import check_environment

        lines: list[str] = []
        try:
            status = check_environment(self.matlab or None, lines.append,
                                       require_matlab=self.require_matlab)
        except Exception as exc:
            lines.append(f"[FAIL] Environment check: {exc}")
            status = 1
        self.log.emit(lines)
        self.finished_check.emit(status)


class SettingsDialog(QDialog):
    """Language, theme and MATLAB. Job inputs stay on the window that runs the job."""

    def __init__(
        self,
        parent: QWidget,
        binder: TextBinder,
        *,
        gui_language: str,
        report_language: str,
        mode: str,
        matlab: str,
    ) -> None:
        super().__init__(parent)
        self._binder = binder
        self._tr = binder.tr
        self.worker: EnvironmentWorker | None = None
        self.setWindowTitle(self._tr("Settings"))
        self.resize(640, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        language_card, language_form = section(binder, "Language")
        self.gui_input = self._combo(("English", "en"), ("Tiếng Việt", "vi"), current=gui_language)
        self.report_input = self._combo((self._tr("Follow GUI"), "gui"), ("English", "en"), ("Tiếng Việt", "vi"),
                                        current=report_language)
        self._row(language_form, 0, "GUI Language", self.gui_input)
        self._row(language_form, 1, "Report Language", self.report_input)
        layout.addWidget(language_card)

        appearance_card, appearance_form = section(binder, "Appearance")
        self.theme_input = self._combo(
            (self._tr("Follow Windows"), "system"), (self._tr("Light"), "light"), (self._tr("Dark"), "dark"),
            current=mode,
        )
        self._row(appearance_form, 0, "Theme", self.theme_input)
        layout.addWidget(appearance_card)

        matlab_card, matlab_form = section(binder, "MATLAB")
        self.matlab_input = QLineEdit(matlab)
        self.matlab_input.setMinimumWidth(240)
        binder.bind(self.matlab_input.setPlaceholderText, "Detected automatically when blank")
        self.browse_button = binder.widget(QPushButton, "Browse…")
        self.detect_button = binder.widget(QPushButton, "Detect")
        self.check_button = binder.widget(QPushButton, "Check Environment")
        label = self._row(matlab_form, 0, "MATLAB executable", self.matlab_input)
        matlab_form.addWidget(self.browse_button, 0, 2)
        matlab_form.addWidget(self.detect_button, 0, 3)
        del label
        hint = binder.widget(QLabel, "MAT files need no MATLAB. Simulink Dataset export runs it once.")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        matlab_form.addWidget(hint, 1, 0, 1, 4)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(110)
        binder.bind(self.log_view.setPlaceholderText, "Check Environment reports the runtime here.")
        matlab_form.addWidget(self.log_view, 2, 0, 1, 4)
        check_row = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setObjectName("hintLabel")
        check_row.addWidget(self.status_label, 1)
        check_row.addWidget(self.check_button)
        matlab_form.addLayout(check_row, 3, 0, 1, 4)
        layout.addWidget(matlab_card)

        buttons = dialog_buttons(binder.language, QDialogButtonBox.StandardButton.Save,
                                 QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.browse_button.clicked.connect(self._browse)
        self.detect_button.clicked.connect(self._detect)
        self.check_button.clicked.connect(self._check_environment)

    # -- construction --------------------------------------------------------------

    def _combo(self, *choices: tuple[str, str], current: str) -> NoWheelComboBox:
        combo = NoWheelComboBox(self)
        for text, value in choices:
            combo.addItem(text, value)
        combo.setCurrentIndex(max(combo.findData(current), 0))
        return combo

    def _row(self, form, row: int, key: str, widget: QWidget) -> QLabel:
        label = self._binder.widget(QLabel, key)
        label.setBuddy(widget)
        self._binder.bind(widget.setAccessibleName, key)
        form.addWidget(label, row, 0)
        form.addWidget(widget, row, 1)
        return label

    # -- values --------------------------------------------------------------------

    def values(self) -> dict[str, str]:
        return {
            "gui_language": str(self.gui_input.currentData()),
            "report_language": str(self.report_input.currentData()),
            "theme": str(self.theme_input.currentData()),
            "matlab": self.matlab_input.text().strip(),
        }

    # -- MATLAB --------------------------------------------------------------------

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self._tr("MATLAB executable"), self.matlab_input.text().strip(),
                                              "MATLAB (matlab.exe);;All files (*)")
        if path:
            self.matlab_input.setText(str(Path(path)))

    def _detect(self) -> None:
        from can_toolbox.blf_mat.options import OptionError, find_matlab_executable

        try:
            self.matlab_input.setText(str(find_matlab_executable()))
        except OptionError as exc:
            QMessageBox.warning(self, self._tr("MATLAB Not Found"), str(exc))

    def _check_environment(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.log_view.clear()
        self.status_label.setText(self._tr("Checking environment…"))
        self.check_button.setEnabled(False)
        self.worker = EnvironmentWorker(self.matlab_input.text().strip(), require_matlab=False)
        self.worker.log.connect(self._log_lines)
        self.worker.finished_check.connect(self._checked)
        self.worker.start()

    def _log_lines(self, lines: list) -> None:
        self.log_view.appendPlainText("\n".join(lines))

    def _checked(self, status: int) -> None:
        self.check_button.setEnabled(True)
        self.status_label.setText(
            self._tr("Environment ready" if status == 0 else "Environment problems found — see log")
        )

    def wait_for_workers(self, timeout_ms: int = 5000) -> None:
        if self.worker:
            self.worker.wait(timeout_ms)

    def done(self, result: int) -> None:
        self.wait_for_workers()
        super().done(result)


def open_settings(
    parent: QWidget,
    binder: TextBinder,
    settings: QSettings,
    *,
    gui_language: str,
    report_language: str,
    apply: Callable[[str, str], None],
) -> bool:
    """Show the dialog and store what the user saved; ``apply`` takes the languages."""
    dialog = SettingsDialog(
        parent, binder, gui_language=gui_language, report_language=report_language,
        mode=theme_mode(settings), matlab=matlab_executable(settings),
    )
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        values = dialog.values()
    finally:
        dialog.deleteLater()
    settings.setValue(MATLAB_KEY, values["matlab"])
    settings.setValue(THEME_KEY, values["theme"])
    application = QApplication.instance()
    if application is not None:
        app_theme.configure_appearance(application, values["theme"])
    apply(values["gui_language"], values["report_language"])
    return True
