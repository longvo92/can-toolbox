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

from can_toolbox.ui.main_window import COMPARE_TOOL, MainWindow  # noqa: E402

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


def _value(panel, row, column):
    """One cell of the signal panel, by row among all entries in display order."""
    entry = panel.signals.entries()[row]
    index = panel.model.index_of(entry).siblingAtColumn(column)
    return panel.model.data(index)


def _select_entry(panel, row):
    entry = panel.signals.entries()[row]
    panel.view.setCurrentIndex(panel.model.index_of(entry))


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


def test_expanding_a_frame_lists_its_decoded_signals(window, log_files):
    """Signals are rows under the frame, decoded when the row is expanded."""
    _load(window, log_files[0])
    model = window.model
    frame = model.index(2, 0)
    assert model.hasChildren(frame)
    assert model.rowCount(frame) == 2
    rows = {model.data(model.index(row, 3, frame)): model.data(model.index(row, 7, frame))
            for row in range(model.rowCount(frame))}
    assert rows == {"Rpm": "2000 rpm", "Gear": "Drive (1)"}
    assert "raw 1 (0x1)" in model.data(model.index(1, 3, frame), Qt.ItemDataRole.ToolTipRole)

    error_frame = model.index(80, 0)  # an error frame has no DBC message
    assert not model.hasChildren(error_frame) and model.rowCount(error_frame) == 0

    # The cursor follows the frame a signal row belongs to.
    window.trace.setCurrentIndex(model.index(0, 0, frame))
    assert window.graph.cursor_time[0] == pytest.approx(0.01)

    window.expand_trace(True)
    assert window.trace.isExpanded(frame)
    window.expand_trace(False)
    assert not window.trace.isExpanded(frame)


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
    window.open_panel(window.statistics_dock)
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
    assert len(window.graph.series) == 2 and "already in the list" in window.status_label.text()

    # Trace selection moves the cursor; the panel shows sample-and-hold values.
    panel = window.signal_panel
    window.trace.setCurrentIndex(window.model.index(2, 0))
    assert window.graph.cursor_time[0] == pytest.approx(0.01)
    assert _value(panel, 0, 1) == "2000 rpm"
    assert _value(panel, 1, 1) == "Drive (1)"

    # Dragging the graph cursor selects the last frame at or before it.
    window.graph._cursors[0][0].setValue(0.0251)
    assert window.trace.currentIndex().row() == 5
    assert _value(panel, 1, 1) == "Park (0)"

    window.cursor2_action.setChecked(True)
    assert window.graph.measuring
    window.graph._cursors[1][0].setValue(0.1)
    assert "Δt = 0.074900 s" in window.graph.delta_label.text()
    assert _value(panel, 0, 5) == "0"
    assert not panel.view.isColumnHidden(2) and not panel.view.isColumnHidden(5)

    tree.apply_filter("gear")
    assert not engine.isHidden() and rpm_item.isHidden() and not gear_item.isHidden()
    assert ref_from_mime(ref_to_mime(gear_item.data(0, Qt.ItemDataRole.UserRole))).signal == "Gear"

    _select_entry(panel, 0)
    window.graph.remove_selected()
    assert [series.ref.signal for series in window.graph.series] == ["Gear"]
    window.open_log(str(log_files[0]))  # reload keeps the list that still resolves
    wait_until(lambda: not window.is_busy() and window.graph.series
               and window.graph.series[0].ref.signal == "Gear")
    window.signals.clear()
    assert not window.graph.series and window.graph.placeholder.isVisibleTo(window.graph)


def _dialog(window, tmp_path, **extra):
    from can_toolbox.ui.logview.export_dialog import ExportDialog

    options = dict(
        settings=window._settings, duration=0.4, cursors=(0.3, 0.1), filtered_count=40,
        total_count=81, folder=str(tmp_path), base_name="cut", dbc_paths=(),
    )
    options.update(extra)
    return ExportDialog(window, window._binder, **options)


def test_export_dialog_validates_the_range_formats_and_name(window, log_files, tmp_path):
    _load(window, log_files[0])
    dialog = _dialog(window, tmp_path)
    try:
        assert dialog.between.isChecked() and dialog.filtered_input.isChecked()
        assert dialog.selected_formats() == ("blf",)
        job = dialog.build()
        assert (job.request.start_s, job.request.end_s, job.request.filtered) == (0.1, 0.3, True)
        assert job.target("blf") == tmp_path / "cut.blf"

        dialog.custom.setChecked(True)
        dialog.start_input.setText("0.2")
        dialog.end_input.setText("0.1")
        with pytest.raises(ValueError, match="before its start"):
            dialog.build()
        dialog.end_input.setText("0.25")
        dialog.name_input.setText("  ")
        with pytest.raises(ValueError, match="name for the exported files"):
            dialog.build()
        dialog.name_input.setText("cut")
        dialog.format_inputs["blf"].setChecked(False)
        with pytest.raises(ValueError, match="at least one output format"):
            dialog.build()
        dialog.format_inputs["signals"].setChecked(True)
        with pytest.raises(ValueError, match="need a DBC"):
            dialog.build()
        dialog.config_input.setText(str(tmp_path / "missing.yaml"))
        with pytest.raises(ValueError, match="does not exist"):
            dialog.build()
    finally:
        dialog.deleteLater()


def test_export_dialog_warns_until_definitions_are_given(window, log_files, tmp_path):
    _load(window, log_files[0])
    dialog = _dialog(window, tmp_path)
    try:
        assert dialog.export_button.isEnabled() and not dialog.error_label.text()
        dialog.format_inputs["dataset"].setChecked(True)
        assert "need a DBC" in dialog.error_label.text()
        dialog.config_input.setText(str(tmp_path / "mapping.yaml"))
        assert not dialog.error_label.text()
        assert dialog.upgrade_button.isEnabled()
        for box in dialog.format_inputs.values():
            box.setChecked(False)
        assert not dialog.export_button.isEnabled()
    finally:
        dialog.deleteLater()


def test_export_writes_every_selected_format_from_one_cut(window, log_files, tmp_path):
    from can_toolbox.canlog import open_log

    _load(window, log_files[0])
    window.filters.filter_input.setText("engine")
    window.filters.filter_input.returnPressed.emit()
    dialog = _dialog(window, tmp_path, dbc_paths=((log_files[1], 0),))
    dialog.custom.setChecked(True)
    dialog.start_input.setText("0.2")
    dialog.end_input.setText("0.25")
    dialog.channel_map_input.setText("1=5")
    dialog.time_input.setCurrentIndex(1)
    for key in ("blf", "csv", "signals"):
        dialog.format_inputs[key].setChecked(True)
    job = dialog.build()
    dialog.deleteLater()

    window.start_export(job)
    wait_until(lambda: "Exported" in window.status_label.text())
    assert window.last_export.frames == 6  # Engine frames at 0.20 ... 0.25 s
    frames = open_log(tmp_path / "cut.blf").frames
    assert set(frames.channel.tolist()) == {5}
    assert frames.arbitration_id.tolist() == [0x100] * 6
    assert frames.seconds()[0] == pytest.approx(0.0, abs=1e-6)
    assert (tmp_path / "cut.csv").is_file()
    signals = tmp_path / "cut_signals.mat"
    assert signals.is_file()
    from scipy.io import loadmat

    scenario = loadmat(signals, simplify_cells=True)["Scenario"]
    assert scenario["Engine"]["Rpm"]["Data"].tolist() == [2000] * 6


def test_export_can_be_cancelled(window, log_files, tmp_path):
    _load(window, log_files[0])
    dialog = _dialog(window, tmp_path, base_name="cancel")
    job = dialog.build()
    dialog.deleteLater()
    window.start_export(job)
    window._cancel_load()
    wait_until(lambda: not window.is_busy())
    assert not list(tmp_path.glob("cancel*.tmp"))


def test_excel_template_and_upgraded_config_are_written(window, log_files, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from can_toolbox.blf_mat.config import load_config

    _load(window, log_files[0])
    dialog = _dialog(window, tmp_path)
    try:
        template = tmp_path / "mapping_template.xlsx"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(template), ""))
        dialog.template_button.click()
        assert template.is_file() and dialog.excel_input.text() == str(template)

        legacy = tmp_path / "legacy.yaml"
        legacy.write_text(
            "input_forces:\n- {interface: Inputs, element: Enable, value: 1}\n", encoding="utf-8"
        )
        dialog.config_input.setText(str(legacy))
        upgraded = tmp_path / "legacy_v2.yaml"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(upgraded), ""))
        dialog.upgrade_button.click()
        assert load_config(upgraded).version == 2
        assert dialog.config_input.text() == str(upgraded)
    finally:
        dialog.deleteLater()


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
        assert [entry.ref.signal for entry in other.signals.entries()] == ["Gear"]
        assert other.graph.cursor_time == [0.05, 0.2] and other.graph.measuring
        assert other.cursor2_action.isChecked()

        missing = tmp_path / "missing.cantoolbox.json"
        missing.write_text(saved.read_text(encoding="utf-8").replace("drive.blf", "gone.blf"), encoding="utf-8")
        other.open_workspace(missing)
        assert "log was not found" in other.status_label.text()
    finally:
        other.wait_for_workers()
        other.close()
        other.deleteLater()
        app.processEvents()


def test_default_screen_is_graphics_and_trace(window):
    """Everything else starts hidden and comes back from the View menu."""
    window.show()
    # Graphics is the work surface; the signal list shares the splitter with it
    assert window.centralWidget() is window.graph_splitter
    assert window.graph_splitter.widget(0) is window.signal_panel
    assert window.graph_splitter.widget(1) is window.graph
    assert not window.browser_window.isVisible()
    assert not window.trace_dock.isHidden() and not window.graph.toolbar.isHidden()
    # The filter bar belongs to the trace dock, not to the window
    assert window.filters.isAncestorOf(window.filters.filter_input)
    assert window.trace_panel.isAncestorOf(window.filters)
    assert window.trace_dock.widget() is window.trace_panel
    hidden = {"Statistics": window.statistics_dock, "Log Info": window.info_dock}
    menu = {action.text(): action for action in window.view_menu.actions() if action.text()}
    assert {"Trace", *hidden} <= set(menu)
    for title, dock in hidden.items():
        assert dock.isHidden(), f"{title} should start hidden"
        menu[title].trigger()
        assert not dock.isHidden()
        menu[title].trigger()
        assert dock.isHidden()
    window.hide()


def test_panels_open_as_their_own_window_from_the_trace(window, log_files):
    _load(window, log_files[0])
    window.show()
    panel = window.open_panel(window.statistics_dock)
    assert panel is window.statistics_dock
    assert not panel.isHidden() and panel.isFloating()
    window.statistics_dock.setFloating(False)
    window.open_panel(window.statistics_dock)  # a docked panel the user kept stays docked
    assert not window.statistics_dock.isFloating()

    window.signal_search_action.trigger()
    assert window.browser_window.isVisible() and window.browser_window.widget is window.signal_browser
    window.browser_window.close()
    window.hide()


def test_fit_x_covers_the_log_and_fit_y_follows_the_visible_window(window, log_files):
    from can_toolbox.canlog.refs import SignalRef

    _load(window, log_files[0])
    window.plot_signal(SignalRef(1, 0x100, "Engine", "Rpm"))
    window.show()
    duration = window.duration()
    assert duration == pytest.approx(1.0, abs=0.01)

    window.fit_x_action.trigger()
    low, high = window.graph.x_range()
    assert low <= 0.0 and high >= duration

    # Rpm is 2000 for the whole log, so Y fits around a constant line.
    window.fit_y_action.trigger()
    bottom, top = window.graph._plots[0].viewRange()[1]
    assert bottom < 2000 < top and (top - bottom) < 1000

    window.zoom_in_action.trigger()
    zoomed_low, zoomed_high = window.graph.x_range()
    assert (zoomed_high - zoomed_low) < (high - low)
    window.zoom_out_action.trigger()
    assert (window.graph.x_range()[1] - window.graph.x_range()[0]) == pytest.approx(high - low, rel=0.01)

    window.cursor1_action.setChecked(False)
    assert not window.graph._cursors[0][0].isVisible()
    window.cursor1_action.setChecked(True)
    assert window.graph._cursors[0][0].isVisible()
    window.hide()


def test_action_icons_follow_the_theme(window, app):
    from can_toolbox.ui import theme as app_theme

    assert not window.open_action.icon().isNull()
    light = window.fit_action.icon().pixmap(20, 20).toImage()
    try:
        app_theme.configure_appearance(app, "dark")
        dark = window.fit_action.icon().pixmap(20, 20).toImage()
        assert dark != light
    finally:
        app_theme.configure_appearance(app, "light")


def test_tools_open_in_their_own_windows_and_are_reused(window, app):
    compare = window.open_tool(COMPARE_TOOL)
    assert compare.isVisible() and compare.widget is window.compare_tab
    assert compare.windowTitle() == "DBC Compare"
    assert window.open_tool(COMPARE_TOOL) is compare
    assert set(window.open_tools()) == {compare.widget}
    compare.close()
    app.processEvents()


def test_dbc_compare_tool_settings_are_migrated_once(app, tmp_path):
    from PySide6.QtCore import QSettings

    from can_toolbox.ui.main_window import migrate_legacy_settings

    legacy = QSettings(str(tmp_path / "legacy.ini"), QSettings.Format.IniFormat)
    for key, value in (("gui_language", "vi"), ("report_language", "en"), ("input_mode", "files"),
                       ("last_old_folder", r"C:\old"), ("last_new_folder", r"C:\new"),
                       ("last_report_path", r"C:\r.xlsx"), ("report_path_is_explicit", True)):
        legacy.setValue(key, value)
    settings = QSettings(str(tmp_path / "new.ini"), QSettings.Format.IniFormat)
    viewer = MainWindow(settings, legacy=legacy)
    try:
        assert viewer.gui_language == "vi" and viewer._report_language == "en"
        tab = viewer.compare_tab
        assert tab._files_mode()
        assert (tab.old_input.text(), tab.new_input.text()) == (r"C:\old", r"C:\new")
        assert tab.output_input.text() == r"C:\r.xlsx"
    finally:
        viewer.close()
        viewer.deleteLater()
        app.processEvents()
    assert legacy.value("gui_language") == "vi"  # 0.8.0 keeps its own settings

    # Later changes are never overwritten by the legacy store.
    settings.setValue("gui_language", "en")
    migrate_legacy_settings(settings, legacy)
    assert settings.value("gui_language") == "en"


def test_window_layout_is_remembered(app, settings, legacy):
    first = MainWindow(settings, legacy=legacy)
    first.statistics_dock.show()
    first.close()
    first.deleteLater()
    app.processEvents()
    assert settings.value("window/state") is not None

    second = MainWindow(settings, legacy=legacy)
    try:
        assert not second.statistics_dock.isHidden()
    finally:
        second.close()
        second.deleteLater()
        app.processEvents()


def test_a_docked_panel_stays_docked_when_it_is_reopened(window):
    """Only a panel the user has never placed opens as its own window."""
    window.show()
    panel = window.open_panel(window.statistics_dock)
    assert panel.isFloating()
    panel.setFloating(False)
    panel.hide()
    window.open_panel(window.statistics_dock)
    assert not panel.isHidden() and not panel.isFloating()
    window.hide()


def test_a_workspace_cannot_be_saved_while_a_log_is_loading(window, log_files):
    _load(window, log_files[0])
    assert window.save_workspace_action.isEnabled()
    window.open_log(str(log_files[0]))
    assert window.is_busy() and not window.save_workspace_action.isEnabled()
    # The action comes back with the rest of the controls, once the load reports in.
    wait_until(lambda: not window.is_busy() and window.save_workspace_action.isEnabled())


def test_a_mapping_file_beside_the_app_counts_as_definitions(window, log_files, tmp_path, monkeypatch):
    """The engine falls back to signal_mapping.* beside the app, so the dialog must too."""
    from can_toolbox.blf_mat import options as blf_options

    _load(window, log_files[0])
    beside = tmp_path / "app"
    beside.mkdir()
    (beside / "signal_mapping.yaml").write_text(
        "input_forces:\n- {interface: Inputs, element: Enable, value: 1}\n", encoding="utf-8"
    )
    monkeypatch.setattr(blf_options, "application_directory", lambda: beside)
    dialog = _dialog(window, tmp_path)
    try:
        dialog.format_inputs["signals"].setChecked(True)
        assert not dialog.error_label.text()
        job = dialog.build()
        assert "signals" in job.formats and job.config_path is None
        assert str(beside) in dialog.config_input.placeholderText()
    finally:
        dialog.deleteLater()


def test_file_menu_lists_recent_logs_and_drops_missing_ones(window, log_files, tmp_path):
    """Opening a log remembers it; the menu keeps the newest eight that still exist."""
    second = tmp_path / "second.blf"
    second.write_bytes(log_files[0].read_bytes())
    _load(window, log_files[0])
    _load(window, second)
    assert window.recent_logs() == [str(second), str(log_files[0])]
    assert [action.text() for action in window.recent_menu.actions()] == ["second.blf", "drive.blf"]

    # Opening a remembered log again moves it to the front instead of repeating it.
    _load(window, log_files[0])
    assert window.recent_logs() == [str(log_files[0]), str(second)]

    second.unlink()
    window._fill_recent_menu()
    assert window.recent_logs() == [str(log_files[0])]
    assert [action.text() for action in window.recent_menu.actions()] == ["drive.blf"]

    many = [tmp_path / f"log{index}.blf" for index in range(12)]
    for path in many:
        path.write_bytes(log_files[0].read_bytes())
        window._remember_log(str(path))
    assert len(window.recent_logs()) == 8
    assert window.recent_logs()[0] == str(many[-1])


def test_graph_toolbar_holds_the_window_actions_and_its_own(window, log_files):
    graph = window.graph
    names = [action.property("iconName") for action in graph.toolbar.actions() if action.property("iconName")]
    assert names == ["zoom-in", "zoom-out", "cursor-1", "cursor-2", "prev-change", "next-change",
                     "remove-plot", "clear-graph"]
    assert graph.fit_button.defaultAction() is window.fit_action
    assert [action.property("iconName") for action in graph.fit_button.menu().actions()] == ["fit", "fit-x", "fit-y"]
    assert [action.text() for action in graph.image_button.menu().actions()] == ["Save Image…", "Copy Image"]
    assert not graph.clear_action.isEnabled()  # nothing plotted yet

    _load(window, log_files[0])
    tree = window.signal_browser.tree
    window.plot_signal(tree.topLevelItem(0).child(0).data(0, Qt.ItemDataRole.UserRole))
    assert graph.clear_action.isEnabled() and graph.next_change_action.isEnabled()


def test_cursor_jumps_to_the_next_value_change(window, log_files):
    _load(window, log_files[0])
    tree = window.signal_browser.tree
    gear = tree.topLevelItem(0).child(1).data(0, Qt.ItemDataRole.UserRole)
    window.plot_signal(gear)
    graph = window.graph
    series = graph.series[0]

    graph.set_cursor(0.0)
    assert graph.jump_to_change(forward=True)
    first = graph.cursor_time[0]
    assert first == pytest.approx(float(series.change_times()[1]))
    assert graph.jump_to_change(forward=True) and graph.cursor_time[0] > first
    assert graph.jump_to_change(forward=False) and graph.cursor_time[0] == pytest.approx(first)

    graph.set_cursor(float(series.change_times()[0]))
    assert not graph.jump_to_change(forward=False)  # nothing before the first sample
    graph.clear()
    assert not graph.jump_to_change(forward=True)  # nothing plotted


def test_line_width_setting_is_applied_to_the_curves(window, log_files, settings):
    from can_toolbox.ui.settings_dialog import DEFAULT_LINE_WIDTH, line_width

    assert line_width(settings) == DEFAULT_LINE_WIDTH
    assert window.graph.line_width() == DEFAULT_LINE_WIDTH
    _load(window, log_files[0])
    tree = window.signal_browser.tree
    window.plot_signal(tree.topLevelItem(0).child(0).data(0, Qt.ItemDataRole.UserRole))

    def pens():
        return [item.opts["pen"].width() for plot in window.graph._plots
                for item in plot.listDataItems()]

    assert pens() == [DEFAULT_LINE_WIDTH]
    window.graph.set_line_width(4)
    assert pens() == [4]
    window.graph.set_line_width(9)  # clamped to the offered range
    assert window.graph.line_width() == 4
    settings.setValue("graph/line_width", 7)
    assert line_width(settings) == DEFAULT_LINE_WIDTH  # an unknown value falls back


def test_lane_is_labelled_on_its_axis_with_the_full_name_as_tooltip(window, log_files):
    _load(window, log_files[0])
    tree = window.signal_browser.tree
    window.plot_signal(tree.topLevelItem(0).child(0).data(0, Qt.ItemDataRole.UserRole))
    plot = window.graph._plots[0]
    assert plot.titleLabel.text == ""  # no title row: the lane is short
    axis = plot.getAxis("left")
    assert "Rpm" in axis.labelText
    assert axis.label.toolTip() == "Rpm (Engine, CAN 1) [rpm]"


def test_expand_all_asks_before_decoding_a_huge_trace(window, log_files, monkeypatch):
    """Every expanded row is decoded, so a big trace needs a yes first."""
    from PySide6.QtWidgets import QMessageBox

    from can_toolbox.ui.logview import window as window_module

    _load(window, log_files[0])
    monkeypatch.setattr(window_module, "EXPAND_CONFIRM_ROWS", 10)
    asked = []

    def answer(_parent, title, text, *_args, **_kwargs):
        asked.append((title, text))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(window_module.QMessageBox, "question", answer)
    window.expand_trace(True)
    assert asked and "81" in asked[0][1]
    assert not window.trace.isExpanded(window.model.index(2, 0))

    monkeypatch.setattr(window_module.QMessageBox, "question",
                        lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window.expand_trace(True)
    assert window.trace.isExpanded(window.model.index(2, 0))


def test_the_filter_bar_can_expand_and_collapse_the_trace(window, log_files):
    _load(window, log_files[0])
    window.filters.expand_button.click()
    assert window.trace.isExpanded(window.model.index(2, 0))
    window.filters.collapse_button.click()
    assert not window.trace.isExpanded(window.model.index(2, 0))


def test_several_logs_stay_open_and_the_active_one_drives_the_window(window, log_files, tmp_path, app):
    """Opening a log adds it; the active one is what the trace and graph show."""
    from can_toolbox.canlog.refs import SignalRef

    second = tmp_path / "second.blf"
    with can.BLFWriter(second) as writer:
        for index in range(10):
            writer.on_message_received(can.Message(
                timestamp=1_700_000_100 + index * 0.01, arbitration_id=0x100, is_extended_id=False,
                data=bytes([0x20, 0x4E, index % 2, 0, 0, 0, 0, 0]), channel=0,
            ))
    _load(window, log_files[0])
    window.plot_signal(SignalRef(1, 0x100, "Engine", "Rpm"))
    first_entry = window.logs.active
    assert window.model.rowCount() == 81

    window.open_log(str(second))
    wait_until(lambda: not window.is_busy() and len(window.logs) == 2)
    assert [entry.name for entry in window.logs] == ["drive.blf", "second.blf"]
    assert window.logs.active.name == "second.blf"
    assert window.model.rowCount() == 10  # the trace follows the active log
    assert window.view is window.logs.active.view
    # The signal list is untouched; the series come from the log on screen.
    assert [entry.ref.signal for entry in window.signals.entries()] == ["Rpm"]
    assert window.series_for(SignalRef(1, 0x100, "Engine", "Rpm")).values[0] == 5000.0

    window.logs.set_active(first_entry)
    app.processEvents()
    assert window.model.rowCount() == 81
    assert window.series_for(SignalRef(1, 0x100, "Engine", "Rpm")).values[0] == 2000.0

    # The Logs panel lists them, and double-clicking one makes it active.
    panel = window.logs_panel
    assert panel.table.rowCount() == 2
    assert panel.table.item(1, 0).text() == "second.blf"
    assert panel.table.item(1, 2).text() == "10"
    panel.activate_requested.emit(window.logs.entries[1])
    app.processEvents()
    assert window.logs.active.name == "second.blf"

    window.close_logs([window.logs.active])
    assert [entry.name for entry in window.logs] == ["drive.blf"]
    assert window.logs.active is first_entry and window.model.rowCount() == 81
    window.close_logs(list(window.logs))
    assert window.logs.active is None and window.model.rowCount() == 0


def test_a_signal_missing_from_the_active_log_is_greyed_out(window, log_files, tmp_path, app):
    from can_toolbox.canlog.refs import SignalRef

    other = tmp_path / "other.blf"
    with can.BLFWriter(other) as writer:
        writer.on_message_received(can.Message(
            timestamp=1_700_000_200, arbitration_id=0x200, is_extended_id=False, data=b"\x01\x02", channel=0,
        ))
    _load(window, log_files[0])
    window.plot_signal(SignalRef(1, 0x100, "Engine", "Rpm"))
    window.open_log(str(other))
    wait_until(lambda: not window.is_busy() and len(window.logs) == 2)

    entry = window.signals.entries()[0]
    assert not len(window.series_for(entry.ref).time)  # the log carries no such frame
    assert not window.graph.series  # nothing to draw from this log
    index = window.signal_panel.model.index_of(entry)
    assert "not in this log" in window.signal_panel.model.data(index, Qt.ItemDataRole.ToolTipRole)


def test_one_dbc_set_applies_to_every_open_log(window, log_files, tmp_path, app):
    second = tmp_path / "second.blf"
    second.write_bytes(log_files[0].read_bytes())
    _load(window, log_files[0])
    window.open_log(str(second))
    wait_until(lambda: not window.is_busy() and len(window.logs) == 2)
    databases = {id(entry.view.database) for entry in window.logs}

    window.dbc_assignments = []
    window._save_assignments()
    from can_toolbox.canlog.database import LogDatabase

    window.logs.set_database(LogDatabase.load([]))
    assert all(not entry.view.database for entry in window.logs)
    assert len(databases) >= 1


def test_workspace_version_3_restores_every_log(window, log_files, tmp_path, legacy, app):
    second = tmp_path / "second.blf"
    second.write_bytes(log_files[0].read_bytes())
    _load(window, log_files[0])
    window.open_log(str(second))
    wait_until(lambda: not window.is_busy() and len(window.logs) == 2)
    window.logs.set_active(window.logs.entries[0])
    window.save_workspace(tmp_path / "multi.json")
    saved = tmp_path / "multi.cantoolbox.json"

    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["version"] == 3 and len(data["logs"]) == 2 and data["active"] == 0

    other = MainWindow(QSettings(str(tmp_path / "other.ini"), QSettings.Format.IniFormat), legacy=legacy)
    try:
        other.open_workspace(saved)
        wait_until(lambda: not other.is_busy() and len(other.logs) == 2)
        assert [entry.name for entry in other.logs] == ["drive.blf", "second.blf"]
        assert other.logs.active.name == "drive.blf"
    finally:
        other.wait_for_workers()
        other.close()
        other.deleteLater()
        app.processEvents()


def test_find_continues_from_the_frame_of_a_selected_signal_row(window, log_files):
    """A signal row answers for its frame, so Find does not jump somewhere else."""
    _load(window, log_files[0])
    frame = window.model.index(2, 0)
    window.trace.setCurrentIndex(window.model.index(0, 0, frame))
    window.filters.find_input.setText("18FF0001")
    window._find(True)
    assert window.trace.currentIndex().row() == 3  # the next matching frame, not row 0 again


def test_dropped_dbcs_reach_every_open_log(window, log_files, tmp_path, app):
    second = tmp_path / "second.blf"
    second.write_bytes(log_files[0].read_bytes())
    _load(window, log_files[0])
    window.open_log(str(second))
    wait_until(lambda: not window.is_busy() and len(window.logs) == 2)

    window.dbc_assignments = []
    window.apply_databases()
    assert all(not entry.view.database for entry in window.logs)
    window.dbc_assignments = [(str(log_files[1]), 0)]
    window.apply_databases()
    assert all(entry.view.database for entry in window.logs)


def test_a_batch_dropped_while_loading_keeps_its_order(window, log_files, tmp_path):
    names = []
    for index in range(2):
        path = tmp_path / f"queued{index}.blf"
        path.write_bytes(log_files[0].read_bytes())
        names.append(str(path))
    window.open_log(str(log_files[0]))  # busy from here
    window.open_logs(names)
    assert window._queue == names
    wait_until(lambda: not window.is_busy() and len(window.logs) == 3)
    assert [entry.name for entry in window.logs] == ["drive.blf", "queued0.blf", "queued1.blf"]


def test_a_workspace_in_plot_mode_comes_back_drawing_the_same_signals(window, log_files, tmp_path, legacy, app):
    from can_toolbox.canlog.refs import SignalRef

    _load(window, log_files[0])
    window.plot_signal(SignalRef(1, 0x100, "Engine", "Rpm"))
    window.plot_signal(SignalRef(1, 0x100, "Engine", "Gear"))
    gear = window.signals.entries()[1]
    window.signal_panel.select_entries([gear])
    window.signal_panel.set_plot_mode(True)
    assert [series.ref.signal for series in window.graph.series] == ["Gear"]
    window.save_workspace(tmp_path / "plotmode.json")
    saved = tmp_path / "plotmode.cantoolbox.json"

    other = MainWindow(QSettings(str(tmp_path / "other.ini"), QSettings.Format.IniFormat), legacy=legacy)
    try:
        other.open_workspace(saved)
        wait_until(lambda: not other.is_busy() and len(other.signals.entries()) == 2)
        assert other.signal_panel.plot_mode
        assert [entry.ref.signal for entry in other.signals.visible_entries()] == ["Gear"]
        assert all(entry.visible for entry in other.signals.entries())  # every box ticked
        assert [series.ref.signal for series in other.graph.series] == ["Gear"]
    finally:
        other.wait_for_workers()
        other.close()
        other.deleteLater()
        app.processEvents()


def test_a_plot_mode_workspace_opens_in_a_window_already_in_plot_mode(window, log_files, tmp_path, legacy, app):
    """The rebuild clears the view selection, so the rows must come from the workspace."""
    from can_toolbox.canlog.refs import SignalRef

    _load(window, log_files[0])
    window.plot_signal(SignalRef(1, 0x100, "Engine", "Rpm"))
    window.plot_signal(SignalRef(1, 0x100, "Engine", "Gear"))
    window.signal_panel.set_plot_mode(True, [window.signals.entries()[1]])
    window.save_workspace(tmp_path / "plotmode2.json")
    saved = tmp_path / "plotmode2.cantoolbox.json"

    other = MainWindow(QSettings(str(tmp_path / "other2.ini"), QSettings.Format.IniFormat), legacy=legacy)
    try:
        other.plot_signal(SignalRef(1, 0x100, "Engine", "Rpm"))
        other.signal_panel.set_plot_mode(True)  # already in plot mode before the workspace opens
        other.open_workspace(saved)
        wait_until(lambda: not other.is_busy() and len(other.signals.entries()) == 2)
        assert other.signal_panel.plot_mode
        assert [entry.ref.signal for entry in other.signals.visible_entries()] == ["Gear"]
        assert [series.ref.signal for series in other.graph.series] == ["Gear"]
        assert [entry.ref.signal for entry in other.signal_panel.selected_entries()] == ["Gear"]
    finally:
        other.wait_for_workers()
        other.close()
        other.deleteLater()
        app.processEvents()
