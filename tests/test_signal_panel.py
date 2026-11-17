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
    assert panel.model.data(index.siblingAtColumn(1)) == "20 rpm"
    assert panel.model.data(index.siblingAtColumn(2)) == ""  # cursor 2 is off
    assert (panel.model.data(index.siblingAtColumn(3)), panel.model.data(index.siblingAtColumn(4))) == ("5", "30")
    assert panel.view.isColumnHidden(2) and panel.view.isColumnHidden(5)

    panel.set_cursors(1.0, 2.5, True)
    assert panel.model.data(index.siblingAtColumn(2)) == "5 rpm"
    assert panel.model.data(index.siblingAtColumn(5)) == "-15"
    # Measuring narrows min/max to the span between the cursors.
    assert (panel.model.data(index.siblingAtColumn(3)), panel.model.data(index.siblingAtColumn(4))) == ("5", "20")
    assert not panel.view.isColumnHidden(2) and not panel.view.isColumnHidden(5)


def test_a_signal_the_log_cannot_decode_is_greyed_out(panel, signals):
    entry = signals.add(CODE)
    panel.set_series_lookup(lambda _ref: None)
    index = panel.model.index_of(entry)
    assert panel.model.data(index, Qt.ItemDataRole.ToolTipRole).endswith("not in this log")
    assert panel.model.data(index.siblingAtColumn(1)) == ""


def test_plot_mode_makes_the_selection_the_visible_set(panel, signals):
    first = signals.add(RPM)
    second = signals.add(GEAR)
    panel.set_plot_mode(True)
    panel.view.setCurrentIndex(panel.model.index_of(second))
    assert [entry.ref for entry in signals.visible_entries()] == [GEAR]
    panel.set_plot_mode(False)
    panel.view.setCurrentIndex(panel.model.index_of(first))
    assert [entry.ref for entry in signals.visible_entries()] == [GEAR]  # selection no longer decides


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


def test_plot_mode_restored_from_a_workspace_keeps_saved_visibility(panel, signals):
    """Nothing is selected yet, so the saved visibility must survive."""
    first = signals.add(RPM)
    second = signals.add(GEAR)
    signals.set_visible(second, False)
    panel.set_plot_mode(True, apply=False)
    assert panel.plot_mode
    assert [entry.ref for entry in signals.visible_entries()] == [RPM]
    panel.view.setCurrentIndex(panel.model.index_of(second))
    assert [entry.ref for entry in signals.visible_entries()] == [GEAR]
    del first


def test_dropping_at_a_top_level_row_lands_in_the_root_list(panel, signals):
    """Top-level rows count the groups; the root list does not."""
    signals.new_group("Powertrain")
    signals.add(RPM)
    signals.add(GEAR)
    data = refs_to_mime([GEAR])
    from PySide6.QtCore import QModelIndex as _QModelIndex

    assert panel.model.dropMimeData(data, Qt.DropAction.MoveAction, 1, 0, _QModelIndex())
    assert [entry.ref for entry in signals.root] == [GEAR, RPM]
