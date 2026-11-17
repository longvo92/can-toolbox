"""Log viewer driven through the real application window (offscreen Qt)."""

from __future__ import annotations

import json
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtCore")
import can  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from can_toolbox.ui.main_window import BLF_TOOL, COMPARE_TOOL, MainWindow  # noqa: E402

pytestmark = pytest.mark.gui

_DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 Engine: 8 ECU
 SG_ Rpm : 0|16@1+ (0.25,0) [0|16383] "rpm" ECU
 SG_ Gear : 16|3@1+ (1,0) [0|7] "" ECU
VAL_ 256 Gear 0 "Park" 1 "Drive" ;
"""


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def legacy(tmp_path):
    """An empty 0.8.0 store: a test never reads the preferences of the installed app."""
    return QSettings(str(tmp_path / "legacy.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def log_files(tmp_path):
    dbc = tmp_path / "engine.dbc"
    dbc.write_text(_DBC, encoding="ascii")
    blf = tmp_path / "drive.blf"
    with can.BLFWriter(blf) as writer:
        for index in range(40):
            writer.on_message_received(can.Message(
                timestamp=1_700_000_000 + index * 0.01, arbitration_id=0x100, is_extended_id=False,
                data=bytes([0x40, 0x1F, index % 2, 0, 0, 0, 0, 0]), channel=0,
            ))
            writer.on_message_received(can.Message(
                timestamp=1_700_000_000.005 + index * 0.01, arbitration_id=0x18FF0001, is_extended_id=True,
                data=bytes([index]), channel=1, is_rx=False,
            ))
        writer.on_message_received(can.Message(timestamp=1_700_000_001, is_error_frame=True, channel=0))
    return blf, dbc


@pytest.fixture
def window(app, settings, legacy, log_files):
    settings.setValue("logview/dbc_assignments", json.dumps([[str(log_files[1]), 0]]))
    viewer = MainWindow(settings, legacy=legacy)
    yield viewer
    viewer.wait_for_workers()
    viewer.close()
    viewer.deleteLater()
    app.processEvents()


def wait_until(condition, timeout=60):
    # QTest.qWait keeps the GIL while it waits, which starves the worker thread
    # importing and compiling the log engine; sleep releases it.
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert condition(), "Qt worker did not finish in time"


def _cell(window, row, column):
    return window.model.data(window.model.index(row, column))


def _load(window, path):
    window.open_log(str(path))
    wait_until(lambda: window.view is not None and not window.is_busy())


def test_trace_lists_decoded_frames_in_time_order(window, log_files):
    _load(window, log_files[0])
    assert window.model.rowCount() == 81
    assert [_cell(window, 0, c) for c in range(8)] == [
        "0.000000", "1", "100", "Engine", "Rx", "CAN", "8", "40 1F 00 00 00 00 00 00",
    ]
    assert _cell(window, 1, 2) == "18FF0001x" and _cell(window, 1, 4) == "Tx" and _cell(window, 1, 1) == "2"
    assert _cell(window, 80, 3) == "Error Frame"
    assert "81 frames" in window.status_label.text() and "81 shown" in window.status_label.text()
    assert "drive.blf" in window.file_label.text() and "1 DBC" in window.file_label.text()


def test_selecting_a_frame_shows_signal_values(window, log_files):
    _load(window, log_files[0])
    window.trace.setCurrentIndex(window.model.index(2, 0))
    values = window.signal_values
    rows = {values.topLevelItem(i).text(0): values.topLevelItem(i) for i in range(values.topLevelItemCount())}
    assert rows["Rpm"].text(1) == "2000" and rows["Rpm"].text(3) == "rpm"
    assert rows["Gear"].text(1) == "Drive" and rows["Gear"].text(2) == "1 (0x1)"


def test_filters_modes_find_and_time_display(window, log_files):
    _load(window, log_files[0])
    filters = window.filters
    filters.filter_input.setText("engine")
    filters.filter_input.returnPressed.emit()
    assert window.model.rowCount() == 40
    filters.filter_input.clear()
    assert window.model.rowCount() == 81
    filters.channel_input.setCurrentIndex(filters.channel_input.findData(2))
    assert window.model.rowCount() == 40
    filters.channel_input.setCurrentIndex(0)
    filters.errors_input.setChecked(False)
    assert window.model.rowCount() == 80
    filters.direction_input.setCurrentIndex(filters.direction_input.findData("tx"))
    assert window.model.rowCount() == 40
    filters.direction_input.setCurrentIndex(0)

    filters.mode_input.setCurrentIndex(filters.mode_input.findData("fixed"))
    assert window.model.rowCount() == 2
    assert _cell(window, 0, 7).startswith("40 1F 01")  # newest Engine frame
    filters.mode_input.setCurrentIndex(0)

    filters.find_input.setText("18FF0001x")
    filters.find_next_button.click()
    assert window.trace.currentIndex().row() == 1
    filters.find_next_button.click()
    assert window.trace.currentIndex().row() == 3
    filters.find_prev_button.click()
    assert window.trace.currentIndex().row() == 1

    filters.time_input.setCurrentIndex(filters.time_input.findData("absolute"))
    assert ":" in _cell(window, 0, 0)


def test_statistics_and_log_info(window, log_files):
    _load(window, log_files[0])
    window.details.setCurrentWidget(window.statistics)
    wait_until(lambda: window.statistics.rowCount() == 2)
    names = {window.statistics.item(r, 2).text(): r for r in range(2)}
    row = names["Engine"]
    assert window.statistics.item(row, 3).data(Qt.ItemDataRole.DisplayRole) == 40
    assert window.statistics.item(row, 6).data(Qt.ItemDataRole.DisplayRole) == pytest.approx(10.0)
    assert "Format: BLF" in window.info.toPlainText()


def test_bad_file_reports_error_and_vietnamese_labels(window, tmp_path):
    bogus = tmp_path / "broken.blf"
    bogus.write_bytes(b"not a log")
    window.open_log(str(bogus))
    wait_until(lambda: "Could not open the log" in window.status_label.text())
    assert window.view is None
    window._set_languages("vi", "gui")
    assert window.open_action.text() == "Mở log…"
    assert window.file_menu.title() == "File" and window.view_menu.title() == "Hiển thị"
    assert window.trace_dock.windowTitle() == "Trace"
    assert "Không mở được log" in window.status_label.text()
    assert window.model.headerData(3, Qt.Orientation.Horizontal) == "Tên"


def test_graph_plots_signals_and_syncs_cursor_with_trace(window, log_files):
    from can_toolbox.ui.graphics import ref_from_mime, ref_to_mime

    _load(window, log_files[0])
    tree = window.signal_browser.tree
    assert tree.topLevelItemCount() == 1
    engine = tree.topLevelItem(0)
    assert engine.text(0).startswith("Engine  [100, CAN 1]")
    rpm_item, gear_item = engine.child(0), engine.child(1)
    tree.itemDoubleClicked.emit(rpm_item, 0)
    tree.setCurrentItem(gear_item)
    gear_item.setSelected(True)
    window.signal_browser.add_button.click()
    assert [series.ref.signal for series in window.graph.series] == ["Rpm", "Gear"]
    window.plot_signal(rpm_item.data(0, Qt.ItemDataRole.UserRole))
    assert len(window.graph.series) == 2 and "already plotted" in window.status_label.text()

    # Trace selection moves the cursor; readout shows sample-and-hold values.
    window.trace.setCurrentIndex(window.model.index(2, 0))
    assert window.graph.cursor_time[0] == pytest.approx(0.01)
    assert window.graph.readout.item(0, 1).text() == "2000 rpm"
    assert window.graph.readout.item(1, 1).text() == "Drive (1)"

    # Dragging the graph cursor selects the last frame at or before it.
    window.graph._cursors[0][0].setValue(0.0251)
    assert window.trace.currentIndex().row() == 5
    assert window.graph.readout.item(1, 1).text() == "Park (0)"

    window.graph.measure_input.setChecked(True)
    window.graph._cursors[1][0].setValue(0.1)
    assert "Δt = 0.074900 s" in window.graph.delta_label.text()
    assert window.graph.readout.item(0, 3).text() == "0"

    tree.apply_filter("gear")
    assert not engine.isHidden() and rpm_item.isHidden() and not gear_item.isHidden()
    assert ref_from_mime(ref_to_mime(gear_item.data(0, Qt.ItemDataRole.UserRole))).signal == "Gear"

    window.graph.readout.selectRow(0)
    window.graph.remove_selected()
    assert [series.ref.signal for series in window.graph.series] == ["Gear"]
    window.open_log(str(log_files[0]))  # reload keeps plots that still resolve
    wait_until(lambda: not window.is_busy() and window.graph.series
               and window.graph.series[0].ref.signal == "Gear")
    window.graph.clear()
    assert not window.graph.series and window.graph.placeholder.isVisibleTo(window.graph)


def test_export_dialog_validates_and_cut_runs_in_background(window, log_files, tmp_path):
    from can_toolbox.canlog import open_log
    from can_toolbox.ui.logview.dialogs import ExportDialog

    _load(window, log_files[0])
    window.filters.filter_input.setText("engine")
    window.filters.filter_input.returnPressed.emit()
    dialog = ExportDialog(window, window._binder, duration=0.4, cursors=(0.3, 0.1), filtered_count=40,
                          total_count=81, default_path=str(tmp_path / "cut.blf"))
    assert dialog.between.isChecked() and dialog.filtered_input.isChecked()
    request, path = dialog.build()
    assert (request.start_s, request.end_s, request.filtered) == (0.1, 0.3, True)

    dialog.custom.setChecked(True)
    dialog.start_input.setText("0.2")
    dialog.end_input.setText("0.1")
    with pytest.raises(ValueError, match="before its start"):
        dialog.build()
    dialog.end_input.setText("0.25")
    dialog.channel_map_input.setText("1=5")
    dialog.time_input.setCurrentIndex(1)
    dialog.path_input.setText(str(tmp_path / "cut.txt"))
    with pytest.raises(ValueError, match="ending in"):
        dialog.build()
    dialog.path_input.setText(str(tmp_path / "cut.asc"))
    request, path = dialog.build()
    dialog.deleteLater()

    window.start_export(request, path)
    wait_until(lambda: "Exported" in window.status_label.text())
    assert window.last_export.frames == 6  # Engine frames at 0.20 ... 0.25 s
    frames = open_log(path).frames
    assert set(frames.channel.tolist()) == {5}
    assert frames.arbitration_id.tolist() == [0x100] * 6
    assert frames.seconds()[0] == pytest.approx(0.0, abs=1e-6)

    window.start_export(request, tmp_path / "cancel.blf")
    window._cancel_load()
    wait_until(lambda: not window.is_busy())
    assert not list(tmp_path.glob("cancel*.tmp"))


def test_workspace_restores_log_dbcs_trace_settings_and_plots(app, window, legacy, log_files, tmp_path):
    from can_toolbox.canlog.refs import SignalRef

    _load(window, log_files[0])
    window.filters.filter_input.setText("engine")
    window.filters.filter_input.returnPressed.emit()
    window.filters.direction_input.setCurrentIndex(window.filters.direction_input.findData("rx"))
    window.filters.time_input.setCurrentIndex(window.filters.time_input.findData("absolute"))
    window.plot_signal(SignalRef(1, 0x100, "Engine", "Gear"))
    window.graph.restore_cursors(0.05, 0.2, True)
    window.save_workspace(tmp_path / "session.json")
    saved = tmp_path / "session.cantoolbox.json"
    assert saved.is_file() and "Workspace saved" in window.status_label.text()

    other = MainWindow(QSettings(str(tmp_path / "other.ini"), QSettings.Format.IniFormat), legacy=legacy)
    try:
        other.open_workspace(saved)
        wait_until(lambda: other.view is not None and not other.is_busy() and other.graph.series)
        assert other.dbc_assignments == [(str(log_files[1]), 0)]
        assert other.model.rowCount() == 40 and other.filters.filter_input.text() == "engine"
        assert other.filters.direction_input.currentData() == "rx"
        assert other.filters.time_mode() == "absolute"
        assert [series.ref.signal for series in other.graph.series] == ["Gear"]
        assert other.graph.cursor_time == [0.05, 0.2] and other.graph.measure_input.isChecked()

        missing = tmp_path / "missing.cantoolbox.json"
        missing.write_text(saved.read_text(encoding="utf-8").replace("drive.blf", "gone.blf"), encoding="utf-8")
        other.open_workspace(missing)
        assert "log was not found" in other.status_label.text()
    finally:
        other.wait_for_workers()
        other.close()
        other.deleteLater()
        app.processEvents()


def test_docks_are_toggled_from_the_view_menu(window):
    docks = {
        "Trace": window.trace_dock, "Signal Browser": window.browser_dock,
        "Details": window.details_dock,
    }
    window.show()
    assert window.centralWidget() is window.graph  # Graphics is the work surface
    app_actions = {action.text(): action for action in window.view_menu.actions() if action.text()}
    assert set(docks) <= set(app_actions)
    for title, dock in docks.items():
        assert not dock.isHidden(), f"{title} should be visible by default"
        app_actions[title].trigger()
        assert dock.isHidden()
        app_actions[title].trigger()
        assert not dock.isHidden()
    assert not window.toolbar.isHidden() and not window.filter_toolbar.isHidden()
    window.hide()


def test_tools_open_in_their_own_windows_and_are_reused(window, app):
    compare = window.open_tool(COMPARE_TOOL)
    assert compare.isVisible() and compare.widget is window.compare_tab
    assert compare.windowTitle() == "DBC Compare"
    assert window.open_tool(COMPARE_TOOL) is compare
    blf = window.open_tool(BLF_TOOL)
    assert blf.widget is window.blf_tab and blf is not compare
    assert set(window.open_tools()) == {compare.widget, blf.widget}
    compare.close()
    blf.close()
    app.processEvents()


def test_window_layout_is_remembered(app, settings, legacy):
    first = MainWindow(settings, legacy=legacy)
    first.browser_dock.hide()
    first.close()
    first.deleteLater()
    app.processEvents()
    assert settings.value("window/state") is not None

    second = MainWindow(settings, legacy=legacy)
    try:
        assert second.browser_dock.isHidden()
    finally:
        second.close()
        second.deleteLater()
        app.processEvents()
