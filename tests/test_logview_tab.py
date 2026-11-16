"""Log Viewer tab driven through the real main window (offscreen Qt)."""

from __future__ import annotations

import json
import os
import time
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtCore")
import can  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from can_toolbox.ui.main_window import MainWindow  # noqa: E402

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
def tab(app, settings, log_files):
    settings.setValue("logview/dbc_assignments", json.dumps([[str(log_files[1]), 0]]))
    with patch("can_toolbox.ui.main_window.QSettings", return_value=settings):
        window = MainWindow()
    window.tabs.setCurrentWidget(window.log_tab)
    yield window.log_tab
    window.log_tab.wait_for_workers()
    window.close()
    window.deleteLater()
    app.processEvents()


def wait_until(condition, timeout=60):
    # QTest.qWait keeps the GIL while it waits, which starves the worker thread
    # importing and compiling the log engine; sleep releases it.
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert condition(), "Qt worker did not finish in time"


def _cell(tab, row, column):
    return tab.model.data(tab.model.index(row, column))


def _load(tab, path):
    tab.open_log(str(path))
    wait_until(lambda: tab.view is not None and not tab.is_busy())


def test_trace_lists_decoded_frames_in_time_order(tab, log_files):
    _load(tab, log_files[0])
    assert tab.model.rowCount() == 81
    assert [_cell(tab, 0, c) for c in range(8)] == [
        "0.000000", "1", "100", "Engine", "Rx", "CAN", "8", "40 1F 00 00 00 00 00 00",
    ]
    assert _cell(tab, 1, 2) == "18FF0001x" and _cell(tab, 1, 4) == "Tx" and _cell(tab, 1, 1) == "2"
    assert _cell(tab, 80, 3) == "Error Frame"
    assert "81 frames" in tab.status.text() and "81 shown" in tab.status.text()
    assert "drive.blf" in tab.file_label.text() and "1 DBC" in tab.file_label.text()


def test_selecting_a_frame_shows_signal_values(tab, log_files):
    _load(tab, log_files[0])
    tab.trace.setCurrentIndex(tab.model.index(2, 0))
    rows = {tab.signals.topLevelItem(i).text(0): tab.signals.topLevelItem(i) for i in range(tab.signals.topLevelItemCount())}
    assert rows["Rpm"].text(1) == "2000" and rows["Rpm"].text(3) == "rpm"
    assert rows["Gear"].text(1) == "Drive" and rows["Gear"].text(2) == "1 (0x1)"


def test_filters_modes_find_and_time_display(tab, log_files):
    _load(tab, log_files[0])
    tab.filter_input.setText("engine")
    tab.filter_input.returnPressed.emit()
    assert tab.model.rowCount() == 40
    tab.filter_input.clear()
    assert tab.model.rowCount() == 81
    tab.channel_input.setCurrentIndex(tab.channel_input.findData(2))
    assert tab.model.rowCount() == 40
    tab.channel_input.setCurrentIndex(0)
    tab.errors_input.setChecked(False)
    assert tab.model.rowCount() == 80
    tab.direction_input.setCurrentIndex(tab.direction_input.findData("tx"))
    assert tab.model.rowCount() == 40
    tab.direction_input.setCurrentIndex(0)

    tab.mode_input.setCurrentIndex(tab.mode_input.findData("fixed"))
    assert tab.model.rowCount() == 2
    assert _cell(tab, 0, 7).startswith("40 1F 01")  # newest Engine frame
    tab.mode_input.setCurrentIndex(0)

    tab.find_input.setText("18FF0001x")
    tab.find_next_button.click()
    assert tab.trace.currentIndex().row() == 1
    tab.find_next_button.click()
    assert tab.trace.currentIndex().row() == 3
    tab.find_prev_button.click()
    assert tab.trace.currentIndex().row() == 1

    tab.time_input.setCurrentIndex(tab.time_input.findData("absolute"))
    assert ":" in _cell(tab, 0, 0)


def test_statistics_and_log_info(tab, log_files):
    _load(tab, log_files[0])
    tab.details.setCurrentWidget(tab.stats_table)
    wait_until(lambda: tab.stats_table.rowCount() == 2)
    names = {tab.stats_table.item(r, 2).text(): r for r in range(2)}
    row = names["Engine"]
    assert tab.stats_table.item(row, 3).data(Qt.ItemDataRole.DisplayRole) == 40
    assert tab.stats_table.item(row, 6).data(Qt.ItemDataRole.DisplayRole) == pytest.approx(10.0)
    assert "Format: BLF" in tab.info.toPlainText()


def test_bad_file_reports_error_and_vietnamese_labels(tab, tmp_path):
    bogus = tmp_path / "broken.blf"
    bogus.write_bytes(b"not a log")
    tab.open_log(str(bogus))
    wait_until(lambda: "Could not open the log" in tab.status.text())
    assert tab.view is None
    tab.set_languages("vi", "gui")
    assert tab.open_button.text() == "Mở log…"
    assert "Không mở được log" in tab.status.text()
    assert tab.model.headerData(3, Qt.Orientation.Horizontal) == "Tên"


def test_graph_plots_signals_and_syncs_cursor_with_trace(tab, log_files):
    from can_toolbox.ui.graphics import ref_from_mime, ref_to_mime

    _load(tab, log_files[0])
    tree = tab.signal_tree
    assert tree.topLevelItemCount() == 1
    engine = tree.topLevelItem(0)
    assert engine.text(0).startswith("Engine  [100, CAN 1]")
    rpm_item, gear_item = engine.child(0), engine.child(1)
    tree.itemDoubleClicked.emit(rpm_item, 0)
    tree.setCurrentItem(gear_item)
    gear_item.setSelected(True)
    tab.add_signal_button.click()
    assert [series.ref.signal for series in tab.graph.series] == ["Rpm", "Gear"]
    tab.plot_signal(rpm_item.data(0, Qt.ItemDataRole.UserRole))
    assert len(tab.graph.series) == 2 and "already plotted" in tab.status.text()

    # Trace selection moves the cursor; readout shows sample-and-hold values.
    tab.trace.setCurrentIndex(tab.model.index(2, 0))
    assert tab.graph.cursor_time[0] == pytest.approx(0.01)
    assert tab.graph.readout.item(0, 1).text() == "2000 rpm"
    assert tab.graph.readout.item(1, 1).text() == "Drive (1)"

    # Dragging the graph cursor selects the last frame at or before it.
    tab.graph._cursors[0][0].setValue(0.0251)
    assert tab.trace.currentIndex().row() == 5
    assert tab.graph.readout.item(1, 1).text() == "Park (0)"

    tab.graph.measure_input.setChecked(True)
    tab.graph._cursors[1][0].setValue(0.1)
    assert "Δt = 0.074900 s" in tab.graph.delta_label.text()
    assert tab.graph.readout.item(0, 3).text() == "0"

    tree.apply_filter("gear")
    assert not engine.isHidden() and rpm_item.isHidden() and not gear_item.isHidden()
    assert ref_from_mime(ref_to_mime(gear_item.data(0, Qt.ItemDataRole.UserRole))).signal == "Gear"

    tab.graph.readout.selectRow(0)
    tab.graph.remove_selected()
    assert [series.ref.signal for series in tab.graph.series] == ["Gear"]
    tab.open_log(str(log_files[0]))  # reload keeps plots that still resolve
    wait_until(lambda: not tab.is_busy() and tab.graph.series and tab.graph.series[0].ref.signal == "Gear")
    tab.graph.clear()
    assert not tab.graph.series and tab.graph.placeholder.isVisibleTo(tab.graph)
