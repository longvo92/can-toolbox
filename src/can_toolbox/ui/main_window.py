"""Application shell: the log viewer window plus the Tools, Settings and Help menus."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from can_toolbox import __version__
from can_toolbox.app_paths import changelog_path, resource_path
from can_toolbox.i18n import LANGUAGES
from can_toolbox.release_notes import published_release_notes
from can_toolbox.ui.logview.window import LogViewerWindow
from can_toolbox.ui.tool_windows import ToolWindow
from can_toolbox.ui.widgets import NoWheelComboBox, dialog_buttons


def _read_resource_text(filename: str) -> str:
    return resource_path(filename).read_text(encoding="utf-8")


# Kept as a module attribute so tests can point Help → Release note at a fixture.
_changelog_path = changelog_path

# DBC Compare Tool <= 0.8.0 stored these keys unprefixed in its own namespace.
_LEGACY_KEYS = {
    "gui_language": "gui_language",
    "report_language": "report_language",
    "input_mode": "compare/input_mode",
    "last_old_folder": "compare/last_old_folder",
    "last_new_folder": "compare/last_new_folder",
    "last_report_path": "compare/last_report_path",
    "report_path_is_explicit": "compare/report_path_is_explicit",
}
_MIGRATED_KEY = "migrated_from_dbc_compare_tool"

COMPARE_TOOL = "compare"
BLF_TOOL = "blf"


def _legacy_settings() -> QSettings:
    return QSettings("DbcCompareTool", "DBCCompareTool")


def migrate_legacy_settings(settings: QSettings, legacy: QSettings) -> None:
    """Copy DBC Compare Tool preferences once; values already in ``settings`` win.

    The legacy store is left untouched so 0.8.0 keeps working side by side.
    """
    if settings.value(_MIGRATED_KEY, False, type=bool):
        return
    for old_key, new_key in _LEGACY_KEYS.items():
        if legacy.contains(old_key) and not settings.contains(new_key):
            settings.setValue(new_key, legacy.value(old_key))
    settings.setValue(_MIGRATED_KEY, True)
    settings.sync()


def _language_preference(settings: QSettings, key: str, choices: tuple[str, ...], default: str) -> str:
    value = settings.value(key, default, type=str)
    return value if value in choices else default


class MainWindow(LogViewerWindow):
    """The log viewer window, with DBC Compare and BLF → MAT in their own windows."""

    def __init__(self, settings: QSettings | None = None, legacy: QSettings | None = None) -> None:
        """``settings`` and ``legacy`` default to the stores of the installed app.

        Tests pass their own so a run never reads or writes the user's preferences.
        """
        store = settings if settings is not None else QSettings("CanToolbox", "CANToolbox")
        migrate_legacy_settings(store, legacy if legacy is not None else _legacy_settings())
        super().__init__(store, gui_language=_language_preference(store, "gui_language", LANGUAGES, "en"))

    # -- shell menus ---------------------------------------------------------------

    def _build_extra_menus(self) -> None:
        self._tool_windows: dict[str, ToolWindow] = {}
        self._busy_tools: set[QWidget] = set()
        self._report_language = _language_preference(
            self._settings, "report_language", ("gui", *LANGUAGES), "gui",
        )

        self.tools_menu = self.menuBar().addMenu("")
        self._binder.bind(self.tools_menu.setTitle, "Tools")
        self.compare_action = self.tools_menu.addAction("")
        self._binder.bind(self.compare_action.setText, "DBC Compare…")
        self.compare_action.triggered.connect(partial(self.open_tool, COMPARE_TOOL))
        self.blf_action = self.tools_menu.addAction("")
        self._binder.bind(self.blf_action.setText, "BLF → MAT…")
        self.blf_action.triggered.connect(partial(self.open_tool, BLF_TOOL))

        self.settings_menu = self.menuBar().addMenu("")
        self._binder.bind(self.settings_menu.setTitle, "Settings")
        self.language_action = self.settings_menu.addAction("")
        self._binder.bind(self.language_action.setText, "Language…")
        self.language_action.triggered.connect(self._show_language_settings)

        help_menu = self.menuBar().addMenu("")
        self._binder.bind(help_menu.setTitle, "Help")
        user_guide_action = help_menu.addAction("")
        release_note_action = help_menu.addAction("")
        about_action = help_menu.addAction("")
        for action, key in ((user_guide_action, "User Guide"), (release_note_action, "Release note"),
                            (about_action, "About")):
            self._binder.bind(action.setText, key)
        user_guide_action.triggered.connect(
            lambda: self._show_help_document(
                "User Guide", "help/user_guide_vi.md" if self.gui_language == "vi" else "help/user_guide.md",
            )
        )
        release_note_action.triggered.connect(self._show_release_note)
        about_action.triggered.connect(lambda: self._show_help_document(
            "About", "help/about_vi.md" if self.gui_language == "vi" else "help/about.md",
        ))
        self.busy_changed.connect(self._on_viewer_busy)

    def _update_extra_language(self) -> None:
        for window in getattr(self, "_tool_windows", {}).values():
            window.widget.set_languages(self.gui_language, self._report_language)

    # -- tool windows --------------------------------------------------------------

    def _create_tool(self, key: str) -> QWidget:
        if key == COMPARE_TOOL:
            from can_toolbox.ui.compare_tab import CompareTab

            return CompareTab(self._settings, gui_language=self.gui_language,
                              report_language=self._report_language)
        from can_toolbox.ui.blf_tab import BlfTab

        return BlfTab(self._settings, gui_language=self.gui_language, report_language=self._report_language)

    def tool_window(self, key: str) -> ToolWindow:
        """The window for ``key``, created (hidden) on first use."""
        window = self._tool_windows.get(key)
        if window is None:
            widget = self._create_tool(key)
            window = ToolWindow(self, widget, self._binder, settings=self._settings, key=key)
            widget.busy_changed.connect(partial(self._on_tool_busy, widget))
            self._tool_windows[key] = window
        return window

    def open_tool(self, key: str) -> ToolWindow:
        window = self.tool_window(key)
        window.show()
        window.raise_()
        window.activateWindow()
        return window

    @property
    def compare_tab(self):
        return self.tool_window(COMPARE_TOOL).widget

    @property
    def blf_tab(self):
        return self.tool_window(BLF_TOOL).widget

    def open_tools(self) -> tuple[QWidget, ...]:
        return tuple(window.widget for window in self._tool_windows.values())

    # -- busy state ----------------------------------------------------------------

    def _on_viewer_busy(self, busy: bool) -> None:
        self._on_tool_busy(self, busy)

    def _on_tool_busy(self, owner: QWidget, busy: bool) -> None:
        """Lock language changes while any tool runs; every window stays usable."""
        if busy:
            self._busy_tools.add(owner)
        else:
            self._busy_tools.discard(owner)
        idle = not self._busy_tools
        self.settings_menu.setEnabled(idle)
        self.language_action.setEnabled(idle)

    def busy_widgets(self) -> list[QWidget]:
        running: list[QWidget] = [self] if self.is_busy() else []
        running += [widget for widget in self.open_tools() if widget.is_busy()]
        return running

    # -- languages -----------------------------------------------------------------

    def _set_languages(self, gui_language: str, report_language: str) -> None:
        self._report_language = report_language
        self._settings.setValue("gui_language", gui_language)
        self._settings.setValue("report_language", report_language)
        self.set_gui_language(gui_language)

    def _show_language_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(self._tr("Language"))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        combos = []
        for key, current, follow_gui in (
            ("GUI Language", self.gui_language, False),
            ("Report Language", self._report_language, True),
        ):
            combo = NoWheelComboBox(dialog)
            if follow_gui:
                combo.addItem(self._tr("Follow GUI"), "gui")
            combo.addItem("English", "en")
            combo.addItem("Tiếng Việt", "vi")
            combo.setCurrentIndex(combo.findData(current))
            label = QLabel(self._tr(key))
            label.setBuddy(combo)
            combo.setAccessibleName(label.text())
            form.addRow(label, combo)
            combos.append(combo)
        layout.addLayout(form)

        buttons = dialog_buttons(
            self.gui_language, QDialogButtonBox.StandardButton.Save, QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._set_languages(combos[0].currentData(), combos[1].currentData())
        finally:
            dialog.deleteLater()

    # -- shutdown ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        running = self.busy_widgets()
        if running:
            reply = QMessageBox.question(
                self,
                self._tr("Task Running"),
                self._tr("A task is still running. Quit anyway?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for widget in running:
                widget.stop_workers()
        for window in self._tool_windows.values():
            window.close()
        super().closeEvent(event)

    # -- help ----------------------------------------------------------------------

    def _show_help_document(self, title: str, filename: str) -> None:
        title = self._tr(title)
        try:
            content = _read_resource_text(filename)
        except OSError as exc:
            QMessageBox.critical(self, title, self._tr("Unable to open help file: {error}", error=exc))
            return
        self._show_markdown(title, content)

    def _show_release_note(self) -> None:
        title = self._tr("Release note")
        try:
            content = published_release_notes(_changelog_path().read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            QMessageBox.critical(self, title, self._tr("Unable to open the release notes: {error}", error=exc))
            return
        self._show_markdown(title, content or self._tr("No release notes available."))

    def _show_markdown(self, title: str, content: str) -> None:
        content = content.replace("{version}", __version__)

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(720, 560)
        layout = QVBoxLayout(dialog)
        viewer = QTextBrowser()
        viewer.setOpenExternalLinks(True)
        viewer.setMarkdown(content)
        buttons = dialog_buttons(self.gui_language, QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(viewer)
        layout.addWidget(buttons)
        dialog.exec()
