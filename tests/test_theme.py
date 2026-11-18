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


def _luminance(color: str) -> float:
    channels = []
    for index in (1, 3, 5):
        value = int(color[index:index + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    """WCAG contrast ratio, 1 (identical) to 21 (black on white)."""
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@pytest.mark.parametrize("theme", [app_theme.LIGHT, app_theme.DARK], ids=lambda t: t.name)
def test_text_stays_readable_in_both_themes(theme):
    """Body text needs 4.5:1, large or secondary text and lines 3:1 (WCAG AA)."""
    for token, background, minimum in (
        ("text", "window", 4.5), ("text", "surface", 4.5), ("heading", "window", 4.5),
        ("subtle", "chrome", 4.5), ("muted", "window", 3.0), ("muted_strong", "window", 4.5),
        ("accent", "window", 3.0), ("error", "surface", 4.0), ("text", "alternate", 4.5),
        ("text", "accent_soft", 4.5), ("accent_text", "accent", 4.5), ("link", "surface", 4.0),
        ("text", "dock_title", 4.5), ("plot_fg", "plot_bg", 4.5), ("chevron", "surface", 3.0),
        ("text", "group_row", 4.5),
    ):
        ratio = contrast(getattr(theme, token), getattr(theme, background))
        assert ratio >= minimum, f"{theme.name}: {token} on {background} is {ratio:.2f}:1"


@pytest.mark.parametrize("theme", [app_theme.LIGHT, app_theme.DARK], ids=lambda t: t.name)
def test_curves_and_cursors_stand_out_on_the_plot(theme):
    for index, color in enumerate(theme.curves):
        ratio = contrast(color, theme.plot_bg)
        assert ratio >= 3.0, f"{theme.name}: curve {index} ({color}) is {ratio:.2f}:1 on the plot"
    for token in ("cursor_primary", "cursor_secondary"):
        ratio = contrast(getattr(theme, token), theme.plot_bg)
        assert ratio >= 3.0, f"{theme.name}: {token} is {ratio:.2f}:1 on the plot"


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


def test_help_text_is_rendered_in_the_current_theme(app, tmp_path):
    """QTextBrowser paints markdown from its own document styles, not the stylesheet."""
    from can_toolbox.ui.main_window import MainWindow

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("theme", "dark")  # the window applies the stored preference
    legacy = QSettings(str(tmp_path / "legacy.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, legacy=legacy)
    assert app_theme.manager.theme is app_theme.DARK
    try:
        viewer = window.markdown_viewer("# Title\n\n[link](https://example.test)\n")
        styles = viewer.document().defaultStyleSheet()
        assert app_theme.DARK.link in styles and app_theme.DARK.code_bg in styles
        assert "link" in viewer.toPlainText()
        app_theme.configure_appearance(app, "light")
        viewer = window.markdown_viewer("# Title")
        assert app_theme.LIGHT.link in viewer.document().defaultStyleSheet()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


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


def test_a_configured_matlab_path_has_to_resolve(app, tmp_path):
    """With a path the user typed, Check Environment must fail when it is wrong."""
    from can_toolbox.ui.settings_dialog import SettingsDialog
    from can_toolbox.ui.widgets import TextBinder

    dialog = SettingsDialog(None, TextBinder("en"), gui_language="en", report_language="gui",
                            mode="light", matlab="")
    try:
        dialog._check_environment()
        assert dialog.worker.require_matlab is False
        dialog.wait_for_workers()
        dialog.matlab_input.setText(str(tmp_path / "nowhere" / "matlab.exe"))
        dialog._check_environment()
        assert dialog.worker.require_matlab is True
        dialog.wait_for_workers()
        app.processEvents()
        assert "problems" in dialog.status_label.text()
    finally:
        dialog.done(0)
        dialog.deleteLater()
        app.processEvents()


def test_closing_settings_leaves_a_running_check_alive(app, monkeypatch):
    """Deleting a running QThread aborts the process, so the worker outlives the dialog."""
    import time

    from can_toolbox.ui import settings_dialog as module
    from can_toolbox.ui.widgets import TextBinder

    def slow_check(matlab, emit, require_matlab=False):
        time.sleep(0.3)
        emit("[OK] slow")
        return 0

    monkeypatch.setattr("can_toolbox.blf_mat.checks.check_environment", slow_check)
    dialog = module.SettingsDialog(None, TextBinder("en"), gui_language="en", report_language="gui",
                                   mode="light", matlab="")
    dialog._check_environment()
    worker = dialog.worker
    assert worker in module._RUNNING
    dialog.done(0)
    dialog.deleteLater()
    app.processEvents()
    assert worker.isRunning() or worker.isFinished()
    worker.wait(5000)
    app.processEvents()
    assert worker not in module._RUNNING
