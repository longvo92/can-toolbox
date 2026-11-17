"""Colour tokens: both themes are complete, and nothing paints colours of its own."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from can_toolbox.ui import theme as app_theme  # noqa: E402
from can_toolbox.ui.settings_dialog import migrate_tool_settings, theme_mode  # noqa: E402

pytestmark = pytest.mark.gui

_UI = Path(__file__).resolve().parents[1] / "src" / "can_toolbox" / "ui"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def light_again(app):
    yield
    app_theme.configure_appearance(app, "light")


def test_both_themes_fill_every_token_in_the_stylesheet(app):
    placeholders = set(re.findall(r"\$([a-z_]+)", app_theme.STYLESHEET.template))
    assert placeholders, "the stylesheet lost its tokens"
    for theme in (app_theme.LIGHT, app_theme.DARK):
        tokens = theme.tokens()
        assert placeholders <= set(tokens), f"{theme.name} is missing {placeholders - set(tokens)}"
        sheet = app_theme.stylesheet(theme)
        assert "$" not in sheet
        assert theme.window in sheet and theme.accent in sheet


def test_themes_differ_and_name_their_graphics_colours():
    assert app_theme.LIGHT.plot_bg != app_theme.DARK.plot_bg
    assert len(app_theme.DARK.curves) == len(app_theme.LIGHT.curves) == 16
    for theme in (app_theme.LIGHT, app_theme.DARK):
        assert theme.cursor_primary != theme.cursor_secondary
        assert all(value.startswith("#") for value in theme.curves)


def test_only_the_theme_module_holds_colours():
    """A hard-coded hex in a widget would survive the theme switch unchanged."""
    offenders = []
    for path in _UI.rglob("*.py"):
        if path.name == "theme.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"#[0-9a-fA-F]{6}\b", line):
                offenders.append(f"{path.name}:{number}")
    assert not offenders, f"colours outside theme.py: {offenders}"


def test_applying_a_theme_repaints_the_application(app):
    light = app_theme.configure_appearance(app, "light")
    assert light is app_theme.LIGHT and app_theme.manager.mode == "light"
    assert app.palette().window().color().name() == app_theme.LIGHT.window

    seen = []
    app_theme.manager.changed.connect(seen.append)
    try:
        dark = app_theme.configure_appearance(app, "dark")
    finally:
        app_theme.manager.changed.disconnect(seen.append)
    assert dark is app_theme.DARK and seen == [app_theme.DARK]
    assert app.palette().window().color().name() == app_theme.DARK.window
    assert app_theme.DARK.surface in app.styleSheet()

    app_theme.configure_appearance(app, "nonsense")  # unknown modes follow the system
    assert app_theme.manager.mode == "system"
    assert app_theme.manager.theme in (app_theme.LIGHT, app_theme.DARK)


def test_tinted_assets_are_written_once_per_colour():
    first = app_theme.tinted_asset("chevron-down.svg", app_theme.DARK.chevron)
    assert first is not None and first.is_file()
    assert app_theme.DARK.chevron in first.read_text(encoding="utf-8")
    assert app_theme.tinted_asset("chevron-down.svg", app_theme.DARK.chevron) == first
    assert app_theme.tinted_asset("chevron-down.svg", app_theme.LIGHT.chevron) != first
    assert app_theme.tinted_asset("not-a-file.svg", "#000000") is None


def test_graph_panel_follows_the_theme(app):
    from can_toolbox.ui.graphics import GraphPanel
    from can_toolbox.ui.widgets import TextBinder

    app_theme.configure_appearance(app, "light")
    panel = GraphPanel(TextBinder("en"))
    try:
        assert panel._theme is app_theme.LIGHT
        app_theme.configure_appearance(app, "dark")
        assert panel._theme is app_theme.DARK
        assert panel.canvas.backgroundBrush().color().name() == app_theme.DARK.plot_bg
    finally:
        panel.deleteLater()


def test_matlab_setting_moves_out_of_the_blf_tool(tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("blf/matlab", r"C:\MATLAB\bin\matlab.exe")
    migrate_tool_settings(settings)
    assert settings.value("matlab/executable") == r"C:\MATLAB\bin\matlab.exe"
    assert not settings.contains("blf/matlab")

    # A second run keeps what the user has set since.
    settings.setValue("matlab/executable", r"D:\MATLAB\matlab.exe")
    migrate_tool_settings(settings)
    assert settings.value("matlab/executable") == r"D:\MATLAB\matlab.exe"
    assert theme_mode(settings) == "system"
    settings.setValue("theme", "dark")
    assert theme_mode(settings) == "dark"
    settings.setValue("theme", "neon")
    assert theme_mode(settings) == "system"
