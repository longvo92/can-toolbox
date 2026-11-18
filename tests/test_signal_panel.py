"""The signal list beside the graph: groups, visibility, values and drag payloads."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np  # noqa: E402
from PySide6.QtCore import QModelIndex, QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from can_toolbox.canlog.refs import SignalRef  # noqa: E402
from can_toolbox.canlog.signals import SignalSeries  # noqa: E402
from can_toolbox.ui.graphics import refs_from_mime, refs_to_mime  # noqa: E402
from can_toolbox.ui.logview.signal_panel import SignalPanel  # noqa: E402
from can_toolbox.ui.logview.signal_set import SignalSet  # noqa: E402
from can_toolbox.ui.widgets import TextBinder  # noqa: E402

pytestmark = pytest.mark.gui

RPM = SignalRef(1, 0x100, "Engine", "Rpm")
GEAR = SignalRef(1, 0x100, "Engine", "Gear")
CODE = SignalRef(2, 0x200, "Diag", "Code")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def signals():
    return SignalSet()


@pytest.fixture
def panel(app, signals, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    widget = SignalPanel(signals, TextBinder("en"), settings)
    yield widget
    widget.deleteLater()
    app.processEvents()


def _series(ref, times, values, unit=""):
    return SignalSeries(ref=ref, time=np.array(times, dtype=float), values=np.array(values, dtype=float), unit=unit)


# -- the model ----------------------------------------------------------------------


def test_colours_are_fixed_when_a_signal_is_added(signals):
    first = signals.add(RPM)
    second = signals.add(GEAR)
    assert (first.color_index, second.color_index) == (0, 1)
    signals.set_visible(first, False)
    assert second.color_index == 1  # hiding one never recolours the others
    signals.remove([first])
    third = signals.add(CODE)
    assert third.color_index == 0  # the freed colour comes back
    assert signals.add(CODE) is None  # already in the list


def test_groups_hold_signals_and_each_signal_sits_in_one(signals):
    powertrain = signals.new_group("Powertrain")
    signals.add(RPM, powertrain)
    gear = signals.add(GEAR)
    assert [entry.ref for entry in signals.entries()] == [RPM, GEAR]  # groups first, then loose
    signals.move([gear], powertrain)
    assert [entry.ref for entry in powertrain.entries] == [RPM, GEAR] and signals.root == []
    assert signals.group_of(gear) is powertrain

    signals.set_group_visible(powertrain, False)
    assert signals.visible_entries() == []
    signals.set_visible(gear, True)
    assert [entry.ref for entry in signals.visible_entries()] == [GEAR]

    assert signals.new_group("Powertrain").name == "Powertrain 2"
    signals.delete_group(powertrain)
    assert signals.entries() == []


def test_tree_shows_groups_with_their_signals_and_check_states(panel, signals):
    group = signals.new_group("Powertrain")
    entry = signals.add(RPM, group)
    signals.add(GEAR)
    model = panel.model

    assert model.rowCount(QModelIndex()) == 2  # one group, one loose signal
    group_index = model.index(0, 0)
    assert model.data(group_index) == "Powertrain  (1)"
    assert model.rowCount(group_index) == 1
    child = model.index(0, 0, group_index)
    assert model.data(child) == "Rpm"
    assert model.parent(child) == group_index
    assert model.data(child, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked

    model.setData(child, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert not entry.visible
    assert model.data(group_index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    model.setData(group_index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert entry.visible

    loose = model.index(1, 0)
    assert model.data(loose) == "Gear" and model.parent(loose) == QModelIndex()


def test_values_follow_the_cursors_and_the_visible_range(panel, signals):
    entry = signals.add(RPM)
    series = _series(RPM, [0.0, 1.0, 2.0, 3.0], [10.0, 20.0, 5.0, 30.0], unit="rpm")
    panel.set_series_lookup(lambda ref: series if ref == RPM else None)

    panel.set_range(0.0, 3.0)
    panel.set_cursors(1.0, 2.5, False)
    index = panel.model.index_of(entry)
    assert panel.model.data(index.siblingAtColumn(1)) == "20 rpm"  # Value
    assert panel.model.data(index.siblingAtColumn(2)) == "20"  # y, the bare number
    assert panel.model.data(index.siblingAtColumn(3)) == ""  # Value2: cursor 2 is off
    assert (panel.model.data(index.siblingAtColumn(4)), panel.model.data(index.siblingAtColumn(5))) == ("5", "30")
    assert panel.view.isColumnHidden(3) and panel.view.isColumnHidden(6)

    panel.set_cursors(1.0, 2.5, True)
    assert panel.model.data(index.siblingAtColumn(3)) == "5 rpm"
    assert panel.model.data(index.siblingAtColumn(6)) == "-15"
    # Measuring narrows min/max to the span between the cursors.
    assert (panel.model.data(index.siblingAtColumn(4)), panel.model.data(index.siblingAtColumn(5))) == ("5", "20")
    assert not panel.view.isColumnHidden(3) and not panel.view.isColumnHidden(6)


def test_a_named_value_reads_as_its_name_and_y_carries_the_number(panel, signals):
    entry = signals.add(GEAR)
    series = SignalSeries(ref=GEAR, time=np.array([0.0]), values=np.array([1.0]), choices={1: "Drive"})
    panel.set_series_lookup(lambda ref: series if ref == GEAR else None)
    panel.set_cursors(0.5, 0.0, False)
    index = panel.model.index_of(entry)
    assert panel.model.data(index.siblingAtColumn(1)) == "Drive"
    assert panel.model.data(index.siblingAtColumn(2)) == "1"


def test_ctrl_clicking_a_second_signal_adds_it_to_the_plot(panel, signals):
    """Resetting the model clears the view's selection silently; it must come back."""
    from PySide6.QtCore import QItemSelectionModel

    first = signals.add(RPM)
    second = signals.add(GEAR)
    panel.set_plot_mode(True)

    def ctrl_click(entry):
        index = panel.model.index_of(entry)
        panel.view.selectionModel().select(
            index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    ctrl_click(first)
    assert signals.visible_entries() == [first]
    ctrl_click(second)
    assert signals.visible_entries() == [first, second]
    assert panel.selected_entries() == [first, second]


def test_a_rebuild_keeps_the_plot_mode_selection(panel, signals):
    first = signals.add(RPM)
    second = signals.add(GEAR)
    panel.set_plot_mode(True, [first, second])
    signals.add(CODE)  # a structural change resets the model
    assert signals.visible_entries() == [first, second]
    assert panel.selected_entries() == [first, second]


def test_a_signal_the_log_cannot_decode_is_greyed_out(panel, signals):
    entry = signals.add(CODE)
    panel.set_series_lookup(lambda _ref: None)
    index = panel.model.index_of(entry)
    assert panel.model.data(index, Qt.ItemDataRole.ToolTipRole).endswith("not in this log")
    assert panel.model.data(index.siblingAtColumn(1)) == ""


def test_plot_mode_makes_the_selection_the_visible_set(panel, signals):
    first = signals.add(RPM)
    second = signals.add(GEAR)
    signals.set_visible(second, False)  # unticked before the mode is switched on

    panel.set_plot_mode(True)
    assert [entry.visible for entry in signals.entries()] == [True, True]  # every box is ticked
    assert signals.visible_entries() == []  # nothing selected yet, so nothing is drawn
    panel.view.setCurrentIndex(panel.model.index_of(second))
    assert [entry.ref for entry in signals.visible_entries()] == [GEAR]

    panel.set_plot_mode(False)
    assert [entry.ref for entry in signals.visible_entries()] == [RPM, GEAR]  # back to the boxes
    panel.view.setCurrentIndex(panel.model.index_of(first))
    assert [entry.ref for entry in signals.visible_entries()] == [RPM, GEAR]  # selection no longer decides


def test_checkboxes_are_ignored_while_plot_mode_runs(panel, signals):
    """The two ways of choosing lanes must not fight over the same rows."""
    entry = signals.add(RPM)
    signals.add(GEAR)
    panel.set_plot_mode(True)
    index = panel.model.index_of(entry)

    assert panel.model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert not (panel.model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable)
    assert not panel.model.setData(index, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert entry.visible
    signals.set_visible(entry, False)  # even the model API leaves it alone
    assert entry.visible

    panel.set_plot_mode(False)
    assert panel.model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable
    assert panel.model.setData(index, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert not entry.visible


def test_group_rows_are_painted_across_every_column(panel, signals):
    from can_toolbox.ui import theme as app_theme

    group = signals.new_group("Powertrain")
    signals.add(RPM, group)
    group_index = panel.model.index(0, 0)
    for column in range(panel.model.columnCount()):
        brush = panel.model.data(group_index.siblingAtColumn(column), Qt.ItemDataRole.BackgroundRole)
        assert brush is not None and brush.color().name() == app_theme.current_theme().group_row
    assert panel.model.data(group_index, Qt.ItemDataRole.FontRole).bold()
    child = panel.model.index(0, 0, group_index)
    assert panel.model.data(child, Qt.ItemDataRole.BackgroundRole) is None


def test_dropping_signals_adds_or_moves_them(panel, signals):
    group = signals.new_group("Powertrain")
    signals.add(RPM)
    data = refs_to_mime([RPM, GEAR])
    group_index = panel.model.index(0, 0)
    assert panel.model.dropMimeData(data, Qt.DropAction.MoveAction, -1, 0, group_index)
    assert [entry.ref for entry in group.entries] == [RPM, GEAR]
    assert signals.root == []


def test_the_drag_payload_is_a_list_and_still_reads_the_old_one():
    data = refs_to_mime([RPM, GEAR])
    assert refs_from_mime(data) == [RPM, GEAR]
    legacy = refs_to_mime([CODE])
    legacy.setData("application/x-can-toolbox-signal",
                   b'{"channel": 2, "key": 512, "message": "Diag", "signal": "Code"}')
    assert refs_from_mime(legacy) == [CODE]
    from PySide6.QtCore import QMimeData

    assert refs_from_mime(QMimeData()) == []


def test_header_layout_is_remembered(app, signals, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    first = SignalPanel(signals, TextBinder("en"), settings)
    first.view.header().resizeSection(0, 140)
    first._save_header()
    first.deleteLater()
    app.processEvents()

    second = SignalPanel(signals, TextBinder("en"), settings)
    try:
        assert second.view.header().sectionSize(0) == 140
    finally:
        second.deleteLater()
        app.processEvents()


def test_extrema_hold_the_sample_before_the_window():
    series = _series(RPM, [0.0, 1.0, 2.0], [10.0, 20.0, 5.0])
    assert series.extrema(1.5, 2.5) == (5.0, 20.0)  # 20 is still held at 1.5
    assert series.extrema(-2.0, -1.0) is None
    assert series.extrema(0.0, 3.0) == (5.0, 20.0)
    empty = _series(RPM, [], [])
    assert empty.extrema(0.0, 1.0) is None


def test_selecting_rows_restores_what_plot_mode_was_drawing(panel, signals):
    """A workspace stores what was drawn; the panel selects it back."""
    signals.add(RPM)
    second = signals.add(GEAR)
    panel.select_entries([second])
    panel.set_plot_mode(True)
    assert panel.plot_mode
    assert [entry.ref for entry in signals.visible_entries()] == [GEAR]
    assert all(entry.visible for entry in signals.entries())


def test_dropping_at_a_top_level_row_lands_in_the_root_list(panel, signals):
    """Top-level rows count the groups; the root list does not."""
    signals.new_group("Powertrain")
    signals.add(RPM)
    signals.add(GEAR)
    data = refs_to_mime([GEAR])
    from PySide6.QtCore import QModelIndex as _QModelIndex

    assert panel.model.dropMimeData(data, Qt.DropAction.MoveAction, 1, 0, _QModelIndex())
    assert [entry.ref for entry in signals.root] == [GEAR, RPM]
