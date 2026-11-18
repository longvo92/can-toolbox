"""Colour tokens, the stylesheet built from them and the light/dark switch."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path
from string import Template

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from can_toolbox.app_paths import resource_path

MODES = ("system", "light", "dark")


@dataclass(frozen=True)
class Theme:
    """Every colour the app paints with; the stylesheet reads the string fields by name."""

    name: str
    window: str
    surface: str
    text: str
    heading: str
    muted: str
    muted_strong: str
    subtle: str
    border: str
    border_soft: str
    selection: str
    hover: str
    pressed: str
    chrome: str
    dock_title: str
    track: str
    grid_line: str
    scroll: str
    scroll_hover: str
    disabled_text: str
    disabled_soft: str
    disabled_bg: str
    field_disabled_bg: str
    field_disabled_border: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    accent_tint: str
    accent_strong: str
    accent_disabled: str
    accent_text: str
    error: str
    check_disabled: str
    chevron: str
    alternate: str
    # Group rows in the signal list: a band behind the whole row.
    group_row: str
    link: str
    code_bg: str
    # Graphics: pyqtgraph paints these itself, so they never reach the stylesheet.
    plot_bg: str
    plot_fg: str
    cursor_primary: str
    cursor_secondary: str
    grid_alpha: float
    curves: tuple[str, ...]

    def tokens(self) -> dict[str, str]:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.type == "str"}


LIGHT = Theme(
    name="light",
    # Instrument-tool greys: a flat window, toolbars one shade down, plots white.
    window="#f0f0f0",
    surface="#ffffff",
    text="#1b1b1b",
    heading="#141414",
    muted="#616161",
    muted_strong="#474747",
    subtle="#303030",
    border="#c8c8c8",
    border_soft="#dcdcdc",
    selection="#cde3fb",
    hover="#e6e6e6",
    pressed="#d8d8d8",
    chrome="#e4e4e4",
    dock_title="#dedede",
    track="#dcdcdc",
    grid_line="#e2e2e2",
    scroll="#c0c0c0",
    scroll_hover="#9a9a9a",
    disabled_text="#9b9b9b",
    disabled_soft="#6b6b6b",
    disabled_bg="#ebebeb",
    field_disabled_bg="#f2f2f2",
    field_disabled_border="#dcdcdc",
    accent="#0a66c2",
    accent_hover="#0b5cab",
    accent_pressed="#094e92",
    accent_soft="#dbeafe",
    accent_tint="#eff6ff",
    accent_strong="#0a66c2",
    accent_disabled="#9dc2e8",
    accent_text="#ffffff",
    error="#b3261e",
    check_disabled="#9b9b9b",
    chevron="#3c3c3c",
    alternate="#f7f7f7",
    group_row="#c6d4ec",
    link="#0a5ab0",
    code_bg="#f0f0f0",
    plot_bg="#ffffff",
    plot_fg="#1b1b1b",
    cursor_primary="#111111",
    cursor_secondary="#c25708",
    grid_alpha=0.18,
    curves=("#1d4ed8", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#be185d", "#4d7c0f",
            "#7c3aed", "#b45309", "#0f766e", "#e11d48", "#2563eb", "#65a30d", "#c026d3", "#475569"),
)

DARK = Theme(
    name="dark",
    # Editor greys: #1e1e1e for the work surface, panels and strips above it.
    window="#1e1e1e",
    surface="#252526",
    text="#e4e4e4",
    heading="#f5f5f5",
    muted="#9d9d9d",
    muted_strong="#bdbdbd",
    subtle="#d0d0d0",
    border="#3c3c3c",
    border_soft="#333333",
    selection="#264f78",
    hover="#2d2d2d",
    pressed="#37373d",
    chrome="#2d2d2d",
    dock_title="#333333",
    track="#3c3c3c",
    grid_line="#313131",
    scroll="#4a4a4a",
    scroll_hover="#5f5f5f",
    disabled_text="#6b6b6b",
    disabled_soft="#8c8c8c",
    disabled_bg="#2a2a2a",
    field_disabled_bg="#262626",
    field_disabled_border="#3c3c3c",
    accent="#3794ff",
    accent_hover="#5aa7ff",
    accent_pressed="#2b7fe0",
    accent_soft="#223a56",
    accent_tint="#1c3048",
    accent_strong="#3794ff",
    accent_disabled="#2f5a86",
    accent_text="#0b1118",
    error="#f47067",
    check_disabled="#4d4d4d",
    chevron="#c0c0c0",
    alternate="#232323",
    group_row="#374d6b",
    link="#6cb6ff",
    code_bg="#2a2a2a",
    plot_bg="#1e1e1e",
    plot_fg="#d4d4d4",
    cursor_primary="#f0f0f0",
    cursor_secondary="#e0a040",
    grid_alpha=0.28,
    curves=("#60a5fa", "#f87171", "#4ade80", "#c084fc", "#fb923c", "#22d3ee", "#f472b6", "#a3e635",
            "#a78bfa", "#fbbf24", "#2dd4bf", "#fb7185", "#38bdf8", "#bef264", "#e879f9", "#aab6cc"),
)

THEMES = {theme.name: theme for theme in (LIGHT, DARK)}

STYLESHEET = Template("""
QMainWindow, QDialog, QWidget#workspaceContent, QWidget#workspaceViewport {
    background-color: $window;
}
QWidget {
    font-family: 'Segoe UI', sans-serif;
    font-size: 10pt;
    color: $text;
}
QLabel#appTitle {
    font-size: 17pt;
    font-weight: 700;
    color: $heading;
}
QLabel#appSubtitle {
    color: $muted;
    font-size: 9pt;
}
QLabel#versionBadge {
    color: $accent;
    background: $accent_soft;
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 8pt;
    font-weight: 600;
}
QLineEdit {
    background: $surface;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: $selection;
}
QLineEdit:focus {
    border: 1px solid $accent;
}
QLineEdit:disabled {
    background: $field_disabled_bg;
    color: $disabled_soft;
    border-color: $field_disabled_border;
}
QPushButton {
    background: $surface;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 7px 16px;
}
QPushButton:hover { background: $hover; }
QPushButton:pressed { background: $pressed; }
QPushButton:disabled { color: $disabled_text; background: $disabled_bg; }
QToolButton {
    background: $surface;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 7px 24px 7px 16px;
}
QToolButton:hover { background: $hover; }
QToolButton:pressed, QToolButton:checked { background: $pressed; }
QToolButton:disabled { color: $disabled_text; background: $disabled_bg; }
QToolButton::menu-indicator {
    subcontrol-origin: padding;
    subcontrol-position: right center;
    right: 8px;
}
QPushButton#compactButton {
    padding: 6px 2px;
}
QPushButton#primaryButton {
    background: $accent;
    border: none;
    color: $surface;
    font-weight: 600;
    padding: 8px 22px;
}
QPushButton#primaryButton:hover { background: $accent_hover; }
QPushButton#primaryButton:pressed { background: $accent_pressed; }
QPushButton#primaryButton:disabled { background: $accent_disabled; color: $hover; }
QGroupBox#sectionCard {
    background: $surface;
    border: 1px solid $border_soft;
    border-radius: 8px;
}
QLabel#sectionTitle {
    color: $subtle;
    font-weight: 600;
}
QCheckBox {
    spacing: 6px;
    font-weight: 400;
}
QCheckBox:disabled { color: $disabled_soft; }
QLabel#runStatus {
    color: $subtle;
    font-weight: 600;
    font-size: 9pt;
}
QProgressBar {
    background: $track;
    border: none;
    border-radius: 4px;
    max-height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background: $accent;
    border-radius: 4px;
}
QTextEdit#logView {
    background: $surface;
    color: $subtle;
    border: 1px solid $border_soft;
    border-radius: 8px;
    font-family: 'Cascadia Mono', 'Consolas', monospace;
    font-size: 9pt;
    padding: 10px;
}
QTextBrowser {
    background: $surface;
    border: 1px solid $border_soft;
    border-radius: 8px;
    padding: 10px;
}
QMenuBar {
    background: $window;
}
QMenuBar::item {
    padding: 6px 10px;
    border-radius: 4px;
}
QMenuBar::item:selected { background: $accent_soft; }
QMenuBar::item:disabled { color: $disabled_soft; }
QMenu {
    background: $surface;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
}
QMenu::item:selected { background: $accent_soft; }
QStatusBar {
    background: $chrome;
    color: $muted_strong;
}
QTableWidget, QListWidget {
    background: $surface;
    border: 1px solid $border_soft;
    border-radius: 6px;
    gridline-color: $grid_line;
}
QHeaderView::section {
    background: $hover;
    border: none;
    border-bottom: 1px solid $border;
    padding: 6px 8px;
    font-weight: 600;
    color: $muted_strong;
}
QComboBox {
    background: $surface;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 5px 28px 5px 9px;
}
QComboBox:focus { border: 1px solid $accent; }
QComboBox:disabled { color: $disabled_soft; background: $field_disabled_bg; }
QComboBox QAbstractItemView {
    background: $surface;
    border: 1px solid $border;
    selection-background-color: $accent_soft;
    selection-color: $text;
}
QLabel#hintLabel {
    color: $muted;
    font-size: 9pt;
}
QLabel#errorLabel {
    color: $error;
}
QToolBar {
    background: $chrome;
    border: none;
    border-bottom: 1px solid $border_soft;
    padding: 3px 6px;
    spacing: 4px;
}
QToolBar::separator {
    background: $border;
    width: 1px;
    margin: 4px 6px;
}
QToolBar QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px;
}
QToolBar QToolButton:hover { background: $hover; border-color: $border_soft; }
QToolBar QToolButton:pressed, QToolBar QToolButton:checked {
    background: $pressed;
    border-color: $border;
}
QToolBar QToolButton:disabled { background: transparent; }
QToolBar QToolButton::menu-button {
    border: none;
    width: 12px;
}
QToolBar QToolButton::menu-indicator { right: 2px; }
QDockWidget {
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}
QDockWidget::title {
    background: $dock_title;
    color: $subtle;
    font-weight: 600;
    padding: 5px 8px;
    border-bottom: 1px solid $border;
}
QPlainTextEdit {
    background: $surface;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 6px 8px;
    font-family: 'Cascadia Mono', 'Consolas', monospace;
    font-size: 9pt;
}
QPlainTextEdit:focus { border: 1px solid $accent; }
QScrollArea#workspaceScroll {
    background: $window;
    border: none;
}
QScrollArea#workspaceScroll QScrollBar:vertical {
    background: $window;
    width: 10px;
}
QScrollArea#workspaceScroll QScrollBar::handle:vertical {
    background: $scroll;
    min-height: 28px;
    border-radius: 4px;
}
QScrollArea#workspaceScroll QScrollBar::handle:vertical:hover { background: $scroll_hover; }
QScrollArea#workspaceScroll QScrollBar::add-line:vertical,
QScrollArea#workspaceScroll QScrollBar::sub-line:vertical { height: 0; }
QScrollArea#workspaceScroll QScrollBar::add-page:vertical,
QScrollArea#workspaceScroll QScrollBar::sub-page:vertical { background: transparent; }
QTableView, QTreeView, QTreeWidget, QTableWidget {
    alternate-background-color: $alternate;
    selection-background-color: $accent_soft;
    selection-color: $text;
    outline: none;
}
QTableView::item:selected, QTreeView::item:selected, QTreeWidget::item:selected,
QTableWidget::item:selected, QListWidget::item:selected {
    background: $accent_soft;
    color: $text;
}
QHeaderView::section:hover { background: $hover; }
QScrollBar:vertical {
    background: transparent;
    width: 11px;
    margin: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 11px;
    margin: 0;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: $scroll;
    border-radius: 4px;
    min-height: 28px;
    min-width: 28px;
    margin: 2px;
}
QScrollBar::handle:hover { background: $scroll_hover; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSplitter::handle {
    background: $border_soft;
}
QSplitter::handle:hover { background: $accent; }
QToolTip {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    padding: 4px 6px;
}
QMenu::separator {
    height: 1px;
    background: $border_soft;
    margin: 4px 8px;
}
/* Radio buttons keep the Fusion indicator: it follows the palette in both themes,
   and a stylesheet one cannot draw the inner dot without an image. */
QRadioButton { spacing: 6px; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: $subtle; }
QDockWidget::close-button, QDockWidget::float-button {
    border: none;
    background: transparent;
    padding: 0;
}
""")


_ASSETS: dict[tuple[str, str], Path] = {}


def tinted_asset(name: str, color: str) -> Path | None:
    """A bundled SVG recoloured for a theme, written once per colour.

    Qt stylesheets can only point at files, so the copy lives in a temporary folder.
    """
    source = resource_path(name)
    if not source.is_file():
        return None
    key = (name, color)
    cached = _ASSETS.get(key)
    if cached is not None:
        return cached
    try:
        text = source.read_text(encoding="utf-8")
        target = Path(tempfile.gettempdir()) / "can_toolbox_assets" / f"{Path(name).stem}-{color.lstrip('#')}.svg"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(re.sub(r'stroke="#[0-9a-fA-F]{3,8}"', f'stroke="{color}"', text), encoding="utf-8")
    except OSError:
        return None
    _ASSETS[key] = target
    return target


def icon(name: str, theme: Theme | None = None) -> QIcon:
    """A toolbar icon from ``resources/icons``, stroked in the theme's text colour."""
    chosen = theme or current_theme()
    path = tinted_asset(f"icons/{name}.svg", chosen.text)
    return QIcon(str(path)) if path is not None else QIcon()


def _indicator_rules(theme: Theme) -> str:
    """Combo arrow and check mark: bundled SVGs, tinted so both themes stay readable."""
    rules = ""
    arrow = tinted_asset("chevron-down.svg", theme.chevron)
    if arrow is not None:
        rules += Template("""
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 25px;
    border: none;
}
QComboBox::down-arrow {
    image: url("$arrow");
    width: 10px;
    height: 6px;
}
""").substitute(arrow=arrow.as_posix())
    check = tinted_asset("checkbox-check.svg", theme.accent_text)
    if check is not None:
        rules += Template("""
QCheckBox::indicator, QListWidget::indicator, QTreeView::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid $disabled_soft;
    border-radius: 3px;
    background-color: $surface;
}
QCheckBox::indicator:unchecked:hover, QListWidget::indicator:unchecked:hover, QTreeView::indicator:unchecked:hover {
    border-color: $accent;
    background-color: $accent_tint;
}
QCheckBox::indicator:checked, QListWidget::indicator:checked, QTreeView::indicator:checked {
    border-color: $accent_strong;
    background-color: $accent_strong;
    image: url("$check");
}
QCheckBox::indicator:indeterminate, QListWidget::indicator:indeterminate,
QTreeView::indicator:indeterminate {
    border-color: $accent_strong;
    background-color: $accent_soft;
}
QCheckBox::indicator:disabled, QListWidget::indicator:disabled, QTreeView::indicator:disabled {
    border-color: $check_disabled;
    background-color: $field_disabled_bg;
}
QCheckBox::indicator:checked:disabled, QListWidget::indicator:checked:disabled, QTreeView::indicator:checked:disabled {
    border-color: $disabled_soft;
    background-color: $disabled_soft;
}
""").substitute(check=check.as_posix(), **theme.tokens())
    return rules


def stylesheet(theme: Theme) -> str:
    return STYLESHEET.substitute(theme.tokens()) + _indicator_rules(theme)


def palette(theme: Theme) -> QPalette:
    """Keep styled widgets and their native subcontrols on the same palette."""
    base = QApplication.style().standardPalette()
    for role, color in (
        (QPalette.ColorRole.Window, theme.window),
        (QPalette.ColorRole.Base, theme.surface),
        (QPalette.ColorRole.AlternateBase, theme.window),
        (QPalette.ColorRole.Button, theme.surface),
        (QPalette.ColorRole.WindowText, theme.text),
        (QPalette.ColorRole.Text, theme.text),
        (QPalette.ColorRole.ButtonText, theme.text),
        (QPalette.ColorRole.PlaceholderText, theme.disabled_soft),
        (QPalette.ColorRole.Highlight, theme.accent),
        (QPalette.ColorRole.HighlightedText, theme.accent_text),
        (QPalette.ColorRole.ToolTipBase, theme.surface),
        (QPalette.ColorRole.ToolTipText, theme.text),
    ):
        base.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        base.setColor(QPalette.ColorGroup.Disabled, role, QColor(theme.disabled_soft))
    return base


def system_theme(app: QApplication) -> Theme:
    """What the desktop asks for right now; light when Qt cannot tell."""
    hints = app.styleHints()
    scheme = hints.colorScheme() if hasattr(hints, "colorScheme") else Qt.ColorScheme.Unknown
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT


class ThemeManager(QObject):
    """Applies a theme to the application and tells the widgets that paint themselves."""

    changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._mode = "system"
        self._theme = LIGHT
        self._connected = False

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def theme(self) -> Theme:
        return self._theme

    def apply(self, app: QApplication, mode: str = "system") -> Theme:
        self._mode = mode if mode in MODES else "system"
        app.setStyle("Fusion")
        theme = THEMES.get(self._mode) or system_theme(app)
        self._theme = theme
        app.setPalette(palette(theme))
        app.setStyleSheet(stylesheet(theme))
        if not self._connected:
            hints = app.styleHints()
            if hasattr(hints, "colorSchemeChanged"):
                hints.colorSchemeChanged.connect(lambda _scheme: self._follow_system(app))
            self._connected = True
        self.changed.emit(theme)
        return theme

    def _follow_system(self, app: QApplication) -> None:
        if self._mode == "system":
            self.apply(app, "system")


manager = ThemeManager()


def configure_appearance(app: QApplication, mode: str = "system") -> Theme:
    """Entry point used by the app, the smoke script and the tests."""
    return manager.apply(app, mode)


def current_theme() -> Theme:
    return manager.theme
