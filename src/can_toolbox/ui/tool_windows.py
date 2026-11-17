"""Tools that are not the log viewer, each in its own window opened from the Tools menu."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLabel, QMainWindow, QWidget

from can_toolbox.ui.widgets import TextBinder


class ToolWindow(QMainWindow):
    """One tool widget in its own window; geometry survives close and reopen."""

    def __init__(self, parent: QWidget, widget, binder: TextBinder, *, settings: QSettings, key: str) -> None:
        super().__init__(parent)
        self.widget = widget
        self.key = key
        self._settings = settings
        self.setCentralWidget(widget)
        binder.bind(self.setWindowTitle, widget.title_key)
        subtitle = QLabel()
        subtitle.setObjectName("appSubtitle")
        binder.bind(subtitle.setText, widget.subtitle_key)
        self.statusBar().addWidget(subtitle, 1)
        self.resize(1060, 820)
        geometry = settings.value(self._geometry_key)
        if geometry:
            self.restoreGeometry(geometry)

    @property
    def _geometry_key(self) -> str:
        return f"tools/{self.key}/geometry"

    def closeEvent(self, event) -> None:
        """Keep the widget alive: a reopened tool shows the inputs the user left behind."""
        self._settings.setValue(self._geometry_key, self.saveGeometry())
        event.accept()
