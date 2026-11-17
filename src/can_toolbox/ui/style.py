"""Shared light theme: palette, stylesheet and indicator icons for every tab."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

from can_toolbox.app_paths import resource_path

STYLESHEET = """
QMainWindow, QDialog, QWidget#workspaceContent, QWidget#workspaceViewport {
    background-color: #f4f6fb;
}
QWidget {
    font-family: 'Segoe UI', sans-serif;
    font-size: 10pt;
    color: #1f2430;
}
QLabel#appTitle {
    font-size: 17pt;
    font-weight: 700;
    color: #16213a;
}
QLabel#appSubtitle {
    color: #6b7280;
    font-size: 9pt;
}
QLabel#versionBadge {
    color: #2563eb;
    background: #e3ecfd;
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 8pt;
    font-weight: 600;
}
QLineEdit {
    background: #ffffff;
    border: 1px solid #d4d9e4;
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: #bfd3f8;
}
QLineEdit:focus {
    border: 1px solid #2563eb;
}
QLineEdit:disabled {
    background: #f1f5f9;
    color: #64748b;
    border-color: #e2e8f0;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d4d9e4;
    border-radius: 6px;
    padding: 7px 16px;
}
QPushButton:hover { background: #eef2fb; }
QPushButton:pressed { background: #e0e7f7; }
QPushButton:disabled { color: #9aa2b1; background: #f0f1f5; }
QToolButton {
    background: #ffffff;
    border: 1px solid #d4d9e4;
    border-radius: 6px;
    padding: 7px 24px 7px 16px;
}
QToolButton:hover { background: #eef2fb; }
QToolButton:pressed, QToolButton:checked { background: #e0e7f7; }
QToolButton:disabled { color: #9aa2b1; background: #f0f1f5; }
QToolButton::menu-indicator {
    subcontrol-origin: padding;
    subcontrol-position: right center;
    right: 8px;
}
QPushButton#primaryButton {
    background: #2563eb;
    border: none;
    color: #ffffff;
    font-weight: 600;
    padding: 8px 22px;
}
QPushButton#primaryButton:hover { background: #1d4fd7; }
QPushButton#primaryButton:pressed { background: #1a46bd; }
QPushButton#primaryButton:disabled { background: #a5bdf2; color: #eef2fb; }
QGroupBox#sectionCard {
    background: #ffffff;
    border: 1px solid #e1e5ee;
    border-radius: 8px;
}
QLabel#sectionTitle {
    color: #334155;
    font-weight: 600;
}
QCheckBox {
    spacing: 6px;
    font-weight: 400;
}
QCheckBox:disabled { color: #64748b; }
QLabel#runStatus {
    color: #334155;
    font-weight: 600;
    font-size: 9pt;
}
QProgressBar {
    background: #e5e9f2;
    border: none;
    border-radius: 4px;
    max-height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background: #2563eb;
    border-radius: 4px;
}
QTextEdit#logView {
    background: #ffffff;
    color: #334155;
    border: 1px solid #e1e5ee;
    border-radius: 8px;
    font-family: 'Cascadia Mono', 'Consolas', monospace;
    font-size: 9pt;
    padding: 10px;
}
QTextBrowser {
    background: #ffffff;
    border: 1px solid #e1e5ee;
    border-radius: 8px;
    padding: 10px;
}
QMenuBar {
    background: #f4f6fb;
}
QMenuBar::item {
    padding: 6px 10px;
    border-radius: 4px;
}
QMenuBar::item:selected { background: #e3ecfd; }
QMenuBar::item:disabled { color: #64748b; }
QMenu {
    background: #ffffff;
    border: 1px solid #d4d9e4;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
}
QMenu::item:selected { background: #e3ecfd; }
QStatusBar {
    background: #eef1f8;
    color: #4b5563;
}
QTableWidget, QListWidget {
    background: #ffffff;
    border: 1px solid #e1e5ee;
    border-radius: 6px;
    gridline-color: #edf0f7;
}
QHeaderView::section {
    background: #eef2fb;
    border: none;
    border-bottom: 1px solid #d4d9e4;
    padding: 6px 8px;
    font-weight: 600;
    color: #4b5563;
}
QComboBox {
    background: #ffffff;
    border: 1px solid #d4d9e4;
    border-radius: 6px;
    padding: 5px 28px 5px 9px;
}
QComboBox:focus { border: 1px solid #2563eb; }
QComboBox:disabled { color: #64748b; background: #f1f5f9; }
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d4d9e4;
    selection-background-color: #e3ecfd;
    selection-color: #1f2430;
}
QLabel#hintLabel {
    color: #6b7280;
    font-size: 9pt;
}
QLabel#errorLabel {
    color: #b91c1c;
}
QToolBar {
    background: #eef1f8;
    border: none;
    border-bottom: 1px solid #e1e5ee;
    padding: 3px 6px;
    spacing: 4px;
}
QToolBar::separator {
    background: #d4d9e4;
    width: 1px;
    margin: 4px 6px;
}
QDockWidget {
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}
QDockWidget::title {
    background: #e7ebf5;
    color: #334155;
    font-weight: 600;
    padding: 5px 8px;
    border-bottom: 1px solid #d4d9e4;
}
QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #d4d9e4;
    border-radius: 6px;
    padding: 6px 8px;
    font-family: 'Cascadia Mono', 'Consolas', monospace;
    font-size: 9pt;
}
QPlainTextEdit:focus { border: 1px solid #2563eb; }
QScrollArea#workspaceScroll {
    background: #f4f6fb;
    border: none;
}
QScrollArea#workspaceScroll QScrollBar:vertical {
    background: #f4f6fb;
    width: 10px;
}
QScrollArea#workspaceScroll QScrollBar::handle:vertical {
    background: #c5cddd;
    min-height: 28px;
    border-radius: 4px;
}
QScrollArea#workspaceScroll QScrollBar::handle:vertical:hover { background: #9ba9c1; }
QScrollArea#workspaceScroll QScrollBar::add-line:vertical,
QScrollArea#workspaceScroll QScrollBar::sub-line:vertical { height: 0; }
QScrollArea#workspaceScroll QScrollBar::add-page:vertical,
QScrollArea#workspaceScroll QScrollBar::sub-page:vertical { background: transparent; }
QTabWidget#toolTabs::pane {
    border: none;
    border-top: 1px solid #e1e5ee;
    top: -1px;
}
QTabWidget#toolTabs > QTabBar::tab {
    background: transparent;
    color: #4b5563;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 18px;
    margin-right: 4px;
    font-weight: 600;
}
QTabWidget#toolTabs > QTabBar::tab:hover { color: #1f2430; background: #eef2fb; }
QTabWidget#toolTabs > QTabBar::tab:selected {
    color: #2563eb;
    border-bottom: 2px solid #2563eb;
}
QTabWidget#toolTabs > QTabBar::tab:disabled { color: #9aa2b1; }
"""


def configure_appearance(app: QApplication) -> None:
    """Keep styled widgets and their native subcontrols on the same palette."""
    app.setStyle("Fusion")
    palette = app.style().standardPalette()
    for role, color in (
        (QPalette.ColorRole.Window, "#f4f6fb"),
        (QPalette.ColorRole.Base, "#ffffff"),
        (QPalette.ColorRole.AlternateBase, "#f4f6fb"),
        (QPalette.ColorRole.Button, "#ffffff"),
        (QPalette.ColorRole.WindowText, "#1f2430"),
        (QPalette.ColorRole.Text, "#1f2430"),
        (QPalette.ColorRole.ButtonText, "#1f2430"),
        (QPalette.ColorRole.PlaceholderText, "#64748b"),
        (QPalette.ColorRole.Highlight, "#2563eb"),
        (QPalette.ColorRole.HighlightedText, "#ffffff"),
        (QPalette.ColorRole.ToolTipBase, "#ffffff"),
        (QPalette.ColorRole.ToolTipText, "#1f2430"),
    ):
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#64748b"))
    app.setPalette(palette)
    arrow = resource_path("chevron-down.svg")
    stylesheet = STYLESHEET
    if arrow.is_file() and not QPixmap(str(arrow)).isNull():
        stylesheet += """
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 25px;
    border: none;
}
QComboBox::down-arrow {
    image: url("ARROW_PATH");
    width: 10px;
    height: 6px;
}
""".replace("ARROW_PATH", arrow.as_posix())
    check = resource_path("checkbox-check.svg")
    if check.is_file() and not QPixmap(str(check)).isNull():
        stylesheet += """
QCheckBox::indicator, QListWidget::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #64748b;
    border-radius: 3px;
    background-color: #ffffff;
}
QCheckBox::indicator:unchecked:hover, QListWidget::indicator:unchecked:hover {
    border-color: #2563eb;
    background-color: #eff6ff;
}
QCheckBox::indicator:checked, QListWidget::indicator:checked {
    border-color: #1d4ed8;
    background-color: #1d4ed8;
    image: url("CHECK_PATH");
}
QCheckBox::indicator:disabled, QListWidget::indicator:disabled {
    border-color: #94a3b8;
    background-color: #f1f5f9;
}
QCheckBox::indicator:checked:disabled, QListWidget::indicator:checked:disabled {
    border-color: #64748b;
    background-color: #64748b;
}
""".replace("CHECK_PATH", check.as_posix())
    app.setStyleSheet(stylesheet)
