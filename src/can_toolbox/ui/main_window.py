"""Application shell: header, menus and one tab per tool."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from can_toolbox import __version__
from can_toolbox.app_paths import changelog_path, resource_path
from can_toolbox.i18n import LANGUAGES
from can_toolbox.release_notes import published_release_notes
from can_toolbox.ui.compare_tab import CompareTab
from can_toolbox.ui.widgets import NoWheelComboBox, TextBinder, dialog_buttons


def _read_resource_text(filename: str) -> str:
    return resource_path(filename).read_text(encoding="utf-8")


# Kept as a module attribute so tests can point Help → Release note at a fixture.
_changelog_path = changelog_path


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CAN Toolbox")
        self.resize(1000, 780)
        self.setMinimumSize(720, 520)
        self._settings = QSettings("CanToolbox", "CANToolbox")
        self._gui_language = self._language_preference("gui_language", LANGUAGES, "en")
        self._report_language = self._language_preference("report_language", ("gui", *LANGUAGES), "gui")
        self._binder = TextBinder(self._gui_language)
        self._busy_tabs: set[QWidget] = set()

        self.compare_tab = CompareTab(
            self._settings, gui_language=self._gui_language, report_language=self._report_language,
        )
        self.tool_tabs: tuple[QWidget, ...] = (self.compare_tab,)

        self._build_menu()
        self._build_layout()
        for tab in self.tool_tabs:
            tab.busy_changed.connect(partial(self._on_tab_busy, tab))
        self._update_language()

    # -- languages -----------------------------------------------------------------

    def _language_preference(self, key: str, choices: tuple[str, ...], default: str) -> str:
        value = self._settings.value(key, default, type=str)
        return value if value in choices else default

    def _tr(self, key: str, **parameters: object) -> str:
        return self._binder.tr(key, **parameters)

    def _update_language(self) -> None:
        self._binder.set_language(self._gui_language)
        for index, tab in enumerate(self.tool_tabs):
            self.tabs.setTabText(index, self._tr(tab.title_key))
        self._update_subtitle()

    def _set_languages(self, gui_language: str, report_language: str) -> None:
        self._gui_language = gui_language
        self._report_language = report_language
        self._settings.setValue("gui_language", gui_language)
        self._settings.setValue("report_language", report_language)
        for tab in self.tool_tabs:
            tab.set_languages(gui_language, report_language)
        self._update_language()

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
            ("GUI Language", self._gui_language, False),
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
            self._gui_language, QDialogButtonBox.StandardButton.Save, QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._set_languages(combos[0].currentData(), combos[1].currentData())
        finally:
            dialog.deleteLater()

    # -- layout --------------------------------------------------------------------

    def _build_menu(self) -> None:
        self.settings_menu = self.menuBar().addMenu("")
        self._binder.bind(self.settings_menu.setTitle, "Settings")
        self.language_action = self.settings_menu.addAction("")
        self._binder.bind(self.language_action.setText, "Language…")
        self.language_action.triggered.connect(self._show_language_settings)

        help_menu = self.menuBar().addMenu("Help")
        user_guide_action = help_menu.addAction("User Guide")
        release_note_action = help_menu.addAction("Release note")
        about_action = help_menu.addAction("About")
        self._binder.bind(help_menu.setTitle, "Help")
        for action, key in ((user_guide_action, "User Guide"), (release_note_action, "Release note"), (about_action, "About")):
            self._binder.bind(action.setText, key)
        user_guide_action.triggered.connect(
            lambda: self._show_help_document(
                "User Guide", "help/user_guide_vi.md" if self._gui_language == "vi" else "help/user_guide.md",
            )
        )
        release_note_action.triggered.connect(self._show_release_note)
        about_action.triggered.connect(lambda: self._show_help_document(
            "About", "help/about_vi.md" if self._gui_language == "vi" else "help/about.md",
        ))

    def _build_layout(self) -> None:
        title = self._binder.widget(QLabel, "CAN Toolbox")
        title.setObjectName("appTitle")
        version_label = QLabel(f"v{__version__}")
        version_label.setObjectName("versionBadge")

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.addWidget(title)
        title_row.addWidget(version_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch()

        self.subtitle = QLabel()
        self.subtitle.setObjectName("appSubtitle")
        self.subtitle.setWordWrap(True)

        header = QVBoxLayout()
        header.setSpacing(2)
        header.addLayout(title_row)
        header.addWidget(self.subtitle)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("toolTabs")
        self.tabs.setDocumentMode(True)
        for tab in self.tool_tabs:
            self.tabs.addTab(tab, "")
        self.tabs.currentChanged.connect(self._update_subtitle)

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(16, 12, 16, 12)
        central_layout.setSpacing(10)
        central_layout.addLayout(header)
        central_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

    def _update_subtitle(self) -> None:
        tab = self.tabs.currentWidget()
        self.subtitle.setText(self._tr(tab.subtitle_key) if tab is not None else "")

    # -- busy state ----------------------------------------------------------------

    def _on_tab_busy(self, tab: QWidget, busy: bool) -> None:
        """Lock language changes while any tool runs; tabs stay switchable."""
        if busy:
            self._busy_tabs.add(tab)
        else:
            self._busy_tabs.discard(tab)
        idle = not self._busy_tabs
        self.settings_menu.setEnabled(idle)
        self.language_action.setEnabled(idle)

    def closeEvent(self, event) -> None:
        running = [tab for tab in self.tool_tabs if tab.is_busy()]
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
            for tab in running:
                tab.stop_workers()
        event.accept()

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
        buttons = dialog_buttons(self._gui_language, QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(viewer)
        layout.addWidget(buttons)
        dialog.exec()
