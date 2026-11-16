"""BLF -> MAT tab driven through the real main window (offscreen Qt)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402
from scipy.io import loadmat  # noqa: E402

from can_toolbox.ui.blf_tab import ConvertWorker, SheetPickerDialog  # noqa: E402
from can_toolbox.ui.main_window import MainWindow  # noqa: E402

pytestmark = pytest.mark.gui

_SHELL = "can_toolbox.ui.main_window"
_TAB = "can_toolbox.ui.blf_tab"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def window(app, settings):
    with patch(f"{_SHELL}.QSettings", return_value=settings):
        window = MainWindow()
    window.tabs.setCurrentWidget(window.blf_tab)
    yield window
    window.blf_tab.wait_for_workers()
    window.close()
    window.deleteLater()
    app.processEvents()


def wait_until(condition, timeout=20):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert condition(), "Qt worker did not finish in time"


def test_window_has_both_tools_and_switches_subtitle(window):
    titles = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    assert titles == ["DBC Compare", "BLF → MAT"]
    assert window.subtitle.text().startswith("Convert CAN BLF logs")
    window.tabs.setCurrentWidget(window.compare_tab)
    assert window.subtitle.text().startswith("Compare DBC baselines")
    window._set_languages("vi", "gui")
    assert window.tabs.tabText(0) == "So sánh DBC"
    assert window.blf_tab.convert_button.text() == "Chuyển đổi"


def test_missing_blf_warns_without_starting_a_worker(window):
    tab = window.blf_tab
    with patch(f"{_TAB}.QMessageBox.warning") as warning:
        tab.convert_button.click()
    warning.assert_called_once()
    assert "Select a BLF" in warning.call_args.args[2]
    assert tab.worker is None
    assert tab.convert_button.isEnabled()


def test_blf_and_dbc_convert_through_the_worker_and_save_inputs(window, sample, settings):
    tab = window.blf_tab
    tab.blf_input.setText(str(sample["blf"]))
    tab.dbc_input.setText(str(sample["root"] / "dbc"))
    tab.output_input.setText(str(sample["output"]))
    busy = []
    tab.busy_changed.connect(busy.append)
    with patch(f"{_TAB}.QMessageBox.critical") as error:
        tab.convert_button.click()
        assert isinstance(tab.worker, ConvertWorker)
        assert not window.language_action.isEnabled()
        wait_until(lambda: tab.convert_button.isEnabled())
    error.assert_not_called()
    assert busy == [True, False]
    assert window.language_action.isEnabled()
    assert tab.run_status.text() == "Conversion complete · 1 BLF file(s)"
    assert tab.open_button.isEnabled()
    assert tab.last_output == sample["output"].resolve()
    log = tab.log_view.toPlainText()
    assert "[3/5]" in log and "Output folder:" in log
    scenario = loadmat(sample["output"] / "sample_signals.mat", simplify_cells=True)["Scenario"]
    assert scenario["Sample"]["SpeedCAN"]["Data"].tolist() == [10, 30]

    with patch(f"{_SHELL}.QSettings", return_value=settings):
        restored = MainWindow()
    try:
        assert restored.blf_tab.blf_input.text() == str(sample["blf"])
        assert restored.blf_tab.dbc_input.text() == str(sample["root"] / "dbc")
    finally:
        restored.close()
        restored.deleteLater()


def test_conversion_failure_restores_controls_and_reports(window, sample):
    tab = window.blf_tab
    tab.blf_input.setText(str(sample["blf"]))
    tab.output_input.setText(str(sample["output"]))

    def fail(paths, log_callback=None):
        log_callback("[1/5] Load optional DBC definitions")
        raise RuntimeError("disk full")

    with patch(f"{_TAB}.convert", side_effect=fail), patch(f"{_TAB}.QMessageBox.critical") as error:
        tab.convert_button.click()
        wait_until(lambda: tab.convert_button.isEnabled())
    error.assert_called_once()
    assert error.call_args.args[2] == "disk full"
    assert tab.run_status.text() == "Conversion failed — see log"
    assert "Failed: disk full" in tab.log_view.toPlainText()
    assert "[1/5]" in tab.log_view.toPlainText()
    assert tab.progress.isHidden()
    assert not tab.open_button.isEnabled()


def test_format_and_workbook_enable_their_options(window, sample):
    tab = window.blf_tab
    assert not tab.matlab_input.isEnabled()
    assert not tab.sheets_button.isEnabled()
    tab.format_input.setCurrentIndex(tab.format_input.findData("dataset"))
    assert tab.matlab_input.isEnabled() and tab.detect_matlab_button.isEnabled()
    tab.excel_input.setText(str(sample["root"] / "interfaces.xlsx"))
    assert tab.sheets_button.isEnabled() and tab.header_row_input.isEnabled()

    def choose(dialog):
        assert isinstance(dialog, SheetPickerDialog)
        assert [dialog.lists["input"].item(row).text() for row in range(2)] == ["SWC_INF", "SWC_OUTF"]
        dialog.lists["output"].item(1).setCheckState(Qt.CheckState.Checked)
        return QDialog.DialogCode.Accepted

    with patch.object(SheetPickerDialog, "exec", choose):
        tab.sheets_button.click()
    assert tab._sheets == {"input": (), "output": ("SWC_OUTF",)}
    assert tab.sheets_hint.text() == "Output sheets: SWC_OUTF"
    options = tab._options()
    assert options.output_sheets == ("SWC_OUTF",)
    tab.excel_input.setText("")
    assert tab._sheets == {"input": (), "output": ()}
    assert not tab.sheets_button.isEnabled()


def test_mat_format_never_passes_matlab(window, sample):
    tab = window.blf_tab
    tab.blf_input.setText(str(sample["blf"]))
    tab.matlab_input.setText(str(Path(__file__)))
    assert tab._options().matlab == ""
    tab.format_input.setCurrentIndex(tab.format_input.findData("dataset"))
    assert tab._options().matlab == str(Path(__file__))


def test_environment_check_logs_module_status(window):
    tab = window.blf_tab
    tab.check_button.click()
    wait_until(lambda: tab.check_button.isEnabled(), timeout=60)
    log = tab.log_view.toPlainText()
    assert "[OK] numpy" in log
    assert "MATLAB" in log
    assert tab.run_status.text() in {"Environment ready", "Environment problems found — see log"}


def test_dbc_compare_tool_settings_are_migrated_once(app, tmp_path):
    from can_toolbox.ui.main_window import migrate_legacy_settings

    legacy = QSettings(str(tmp_path / "legacy.ini"), QSettings.Format.IniFormat)
    for key, value in (("gui_language", "vi"), ("report_language", "en"), ("input_mode", "files"),
                       ("last_old_folder", r"C:\old"), ("last_new_folder", r"C:\new"),
                       ("last_report_path", r"C:\r.xlsx"), ("report_path_is_explicit", True)):
        legacy.setValue(key, value)
    settings = QSettings(str(tmp_path / "new.ini"), QSettings.Format.IniFormat)
    with patch(f"{_SHELL}.QSettings", return_value=settings), \
            patch(f"{_SHELL}._legacy_settings", return_value=legacy):
        window = MainWindow()
    try:
        assert window._gui_language == "vi" and window._report_language == "en"
        tab = window.compare_tab
        assert tab._files_mode()
        assert (tab.old_input.text(), tab.new_input.text()) == (r"C:\old", r"C:\new")
        assert tab.output_input.text() == r"C:\r.xlsx"
    finally:
        window.close()
        window.deleteLater()
    assert legacy.value("gui_language") == "vi"  # 0.8.0 keeps its own settings

    # Later changes are never overwritten by the legacy store.
    settings.setValue("gui_language", "en")
    migrate_legacy_settings(settings, legacy)
    assert settings.value("gui_language") == "en"
