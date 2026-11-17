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
    window="#f4f6fb",
    surface="#ffffff",
    text="#1f2430",
    heading="#16213a",
    muted="#6b7280",
    muted_strong="#4b5563",
    subtle="#334155",
    border="#d4d9e4",
    border_soft="#e1e5ee",
    selection="#bfd3f8",
    hover="#eef2fb",
    pressed="#e0e7f7",
    chrome="#eef1f8",
    dock_title="#e7ebf5",
    track="#e5e9f2",
    grid_line="#edf0f7",
    scroll="#c5cddd",
    scroll_hover="#9ba9c1",
    disabled_text="#9aa2b1",
    disabled_soft="#64748b",
    disabled_bg="#f0f1f5",
    field_disabled_bg="#f1f5f9",
    field_disabled_border="#e2e8f0",
    accent="#2563eb",
    accent_hover="#1d4fd7",
    accent_pressed="#1a46bd",
    accent_soft="#e3ecfd",
    accent_tint="#eff6ff",
    accent_strong="#1d4ed8",
    accent_disabled="#a5bdf2",
    accent_text="#ffffff",
    error="#b91c1c",
    check_disabled="#94a3b8",
    chevron="#475569",
    plot_bg="#ffffff",
    plot_fg="#1f2430",
    cursor_primary="#111827",
    cursor_secondary="#d97706",
    grid_alpha=0.15,
    curves=("#1d4ed8", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#be185d", "#4d7c0f",
            "#7c3aed", "#b45309", "#0f766e", "#e11d48", "#2563eb", "#65a30d", "#c026d3", "#475569"),
)

DARK = Theme(
    name="dark",
    window="#12151c",
    surface="#1a1f2a",
    text="#e6eaf2",
    heading="#f4f7ff",
    muted="#9aa6bd",
    muted_strong="#b2bdd1",
    subtle="#c3ccdd",
    border="#333c4d",
    border_soft="#2b3340",
    selection="#2b4a7d",
    hover="#232c3b",
    pressed="#2c3749",
    chrome="#161b24",
    dock_title="#1f2635",
    track="#273040",
    grid_line="#262e3c",
    scroll="#3d4759",
    scroll_hover="#4f5c73",
    disabled_text="#67738a",
    disabled_soft="#8793a8",
    disabled_bg="#222834",
    field_disabled_bg="#1d2430",
    field_disabled_border="#2b3340",
    accent="#4d8dff",
    accent_hover="#6a9dff",
    accent_pressed="#3f7ae6",
    accent_soft="#1e2b45",
    accent_tint="#1b2740",
    accent_strong="#4d8dff",
    accent_disabled="#35507d",
    accent_text="#0b1018",
    error="#ff7b72",
    check_disabled="#49546a",
    chevron="#9aa6bd",
    plot_bg="#0f1218",
    plot_fg="#d6dcea",
    cursor_primary="#e8edf7",
    cursor_secondary="#ffb454",
    grid_alpha=0.25,
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
QTabWidget#toolTabs::pane {
    border: none;
    border-top: 1px solid $border_soft;
    top: -1px;
}
QTabWidget#toolTabs > QTabBar::tab {
    background: transparent;
    color: $muted_strong;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 18px;
    margin-right: 4px;
    font-weight: 600;
}
QTabWidget#toolTabs > QTabBar::tab:hover { color: $text; background: $hover; }
QTabWidget#toolTabs > QTabBar::tab:selected {
    color: $accent;
    border-bottom: 2px solid $accent;
}
QTabWidget#toolTabs > QTabBar::tab:disabled { color: $disabled_text; }
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
QCheckBox::indicator, QListWidget::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid $disabled_soft;
    border-radius: 3px;
    background-color: $surface;
}
QCheckBox::indicator:unchecked:hover, QListWidget::indicator:unchecked:hover {
    border-color: $accent;
    background-color: $accent_tint;
}
QCheckBox::indicator:checked, QListWidget::indicator:checked {
    border-color: $accent_strong;
    background-color: $accent_strong;
    image: url("$check");
}
QCheckBox::indicator:disabled, QListWidget::indicator:disabled {
    border-color: $check_disabled;
    background-color: $field_disabled_bg;
}
QCheckBox::indicator:checked:disabled, QListWidget::indicator:checked:disabled {
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
