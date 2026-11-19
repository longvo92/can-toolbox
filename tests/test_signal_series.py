"""Signal time series and the signal catalog against per-frame cantools decoding."""

from __future__ import annotations

from pathlib import Path

import can
import cantools
import numpy as np
import pytest

from can_toolbox.canlog.database import DbcAssignment, LogDatabase
from can_toolbox.canlog.reader import LogFile, frames_from_messages
from can_toolbox.canlog.signals import SignalRef, SignalSource
from can_toolbox.canlog.view import LogView

_DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 Engine: 8 ECU
 SG_ Rpm : 0|16@1+ (0.25,0) [0|16383] "rpm" ECU
 SG_ Gear : 16|3@1+ (2,1) [0|15] "" ECU
BO_ 512 Brake: 2 ECU
 SG_ Pressure : 0|12@1- (0.1,0) [-200|200] "bar" ECU
VAL_ 256 Gear 0 "Park" 1 "Drive" ;
"""


@pytest.fixture
def source(tmp_path) -> SignalSource:
    dbc = tmp_path / "car.dbc"
    dbc.write_text(_DBC, encoding="ascii")
    messages = []
    for index in range(200):
        stamp = 50.0 + index * 0.005
        messages.append(can.Message(timestamp=stamp, arbitration_id=0x100, is_extended_id=False,
                                    data=bytes([index, index >> 1, index % 2, 0, 0, 0, 0, 0]), channel=index % 2))
        if index % 3 == 0:
            messages.append(can.Message(timestamp=stamp + 0.001, arbitration_id=0x200, is_extended_id=False,
                                        data=bytes([index, 0x0F]), channel=0))
    # A short Engine frame must be skipped like cantools does.
    messages.append(can.Message(timestamp=51.5, arbitration_id=0x100, is_extended_id=False, data=b"\x01", channel=0))
    view = LogView(LogFile(Path("x.blf"), frames_from_messages(messages), "BLF"),
                   LogDatabase.load([DbcAssignment(dbc)]))
    source = SignalSource(view)
    source.messages = messages
    source.database = cantools.database.load_file(str(dbc))
    return source


def test_catalog_lists_messages_present_per_channel(source):
    entries = [(entry.channel, entry.message, entry.frames, entry.signals) for entry in source.catalog()]
    assert entries == [
        (1, "Brake", 67, ("Pressure",)),
        (1, "Engine", 101, ("Rpm", "Gear")),
        (2, "Engine", 100, ("Rpm", "Gear")),
    ]


@pytest.mark.parametrize(("channel", "message", "signal"), [(1, "Engine", "Rpm"), (2, "Engine", "Gear"),
                                                            (1, "Brake", "Pressure")])
def test_series_matches_cantools_frame_by_frame(source, channel, message, signal):
    definition = source.database.get_message_by_name(message)
    expected_t, expected_y = [], []
    origin = source.messages[0].timestamp
    for frame in source.messages:
        if frame.arbitration_id != definition.frame_id or frame.channel + 1 != channel:
            continue
        try:
            values = definition.decode(bytes(frame.data), decode_choices=False, allow_truncated=False)
        except Exception:
            continue
        expected_t.append(frame.timestamp - origin)
        expected_y.append(float(values[signal]))
    series = source.series(SignalRef(channel, definition.frame_id, message, signal))
    assert np.allclose(series.time, expected_t, atol=1e-9)
    assert series.values.tolist() == expected_y
    assert series.unit == (definition.get_signal_by_name(signal).unit or "")


def test_value_lookup_holds_and_labels_choices(source):
    gear = source.series(SignalRef(1, 0x100, "Engine", "Gear"))
    assert gear.value_at(-1.0) is None and gear.text_at(-1.0) == ""
    assert gear.value_at(0.0) == 1.0
    # Physical 1 is raw 0 (scale 2, offset 1): the label comes from the raw value.
    assert gear.text_at(0.0) == "Park"
    assert gear.value_at(0.0124) == 1.0
    assert gear.text_at(gear.time[1]) == "Park"
    rpm = source.series(SignalRef(1, 0x100, "Engine", "Rpm"))
    assert rpm.text_at(rpm.time[2]).endswith(" rpm")
    assert gear.choices == {0: "Park", 1: "Drive"}


def test_unknown_signal_or_message_raises(source):
    with pytest.raises(KeyError):
        source.series(SignalRef(1, 0x100, "Engine", "Missing"))
    with pytest.raises(KeyError):
        source.series(SignalRef(1, 0x7FF, "Ghost", "X"))


def test_change_times_and_cursor_jumps(source):
    import numpy as np

    from can_toolbox.canlog.signals import SignalSeries

    rpm = source.series(SignalRef(1, 0x100, "Engine", "Rpm"))
    changes = rpm.change_times()
    assert changes[0] == rpm.time[0]
    assert len(changes) > 1
    # Every change is a sample where the held value differs from the one before.
    for moment in changes[1:]:
        index = int(np.searchsorted(rpm.time, moment))
        assert rpm.values[index] != rpm.values[index - 1]

    first, second = float(changes[0]), float(changes[1])
    assert rpm.next_change(first - 1.0) == first
    assert rpm.next_change(first) == second
    assert rpm.next_change(second, forward=False) == first
    assert rpm.next_change(first, forward=False) is None
    assert rpm.next_change(float(changes[-1])) is None

    steady = SignalSeries(ref=rpm.ref, time=np.array([0.0, 1.0, 2.0]), values=np.array([5.0, 5.0, 5.0]))
    assert steady.change_times().tolist() == [0.0]
    assert steady.next_change(0.0) is None
    empty = SignalSeries(ref=rpm.ref, time=np.zeros(0), values=np.zeros(0))
    assert not len(empty.change_times()) and empty.next_change(0.0) is None


def _series(times, period=None):
    from can_toolbox.canlog.signals import SignalSeries

    times = np.asarray(times, dtype=float)
    return SignalSeries(SignalRef(1, 0x100, "Engine", "Rpm"), times, np.arange(len(times), dtype=float),
                        period=period)


def test_period_is_measured_for_periodic_signals_only(source):
    from can_toolbox.canlog.signals import estimate_period

    rpm = source.series(SignalRef(1, 0x100, "Engine", "Rpm"))
    assert rpm.period == pytest.approx(0.01)
    pressure = source.series(SignalRef(1, 0x200, "Brake", "Pressure"))
    assert pressure.period == pytest.approx(0.015)
    # A few missed samples do not move the period; event-driven traffic has none.
    assert estimate_period(np.array([0.0, 0.1, 0.2, 0.5, 0.6, 0.7, 0.8])) == pytest.approx(0.1)
    assert estimate_period(np.array([0.0, 0.01, 0.4, 0.45, 1.3, 1.31, 2.9])) is None
    assert estimate_period(np.array([0.0, 0.1, 0.2])) is None
    assert estimate_period(np.zeros(6)) is None


def test_dbc_cycle_time_wins_unless_the_signal_is_multiplexed():
    from types import SimpleNamespace

    from can_toolbox.canlog.signals import _signal_period

    times = np.arange(10) * 0.02
    message = SimpleNamespace(cycle_time=20)
    # A cycle time the log agrees with wins even where the measured period is off.
    jittery = times + np.array([0, 0.004, -0.004, 0.004, -0.004, 0.004, -0.004, 0.004, -0.004, 0])
    assert _signal_period(message, SimpleNamespace(multiplexer_ids=None), jittery) == pytest.approx(0.02)
    # A multiplexed signal comes every other frame: its own period counts.
    assert _signal_period(SimpleNamespace(cycle_time=10), SimpleNamespace(multiplexer_ids=[1]),
                          times) == pytest.approx(0.02)
    assert _signal_period(SimpleNamespace(cycle_time=None), SimpleNamespace(multiplexer_ids=None),
                          times) == pytest.approx(0.02)
    assert _signal_period(SimpleNamespace(cycle_time=0), SimpleNamespace(multiplexer_ids=None),
                          np.array([0.0, 0.01, 0.4, 0.45, 1.3])) is None


def test_gaps_are_holds_longer_than_one_and_a_half_periods():
    series = _series([0.0, 0.1, 0.2, 0.32, 0.5, 0.66, 1.0], period=0.1)
    assert series.gaps().tolist() == [3, 4, 5]
    assert _series([0.0, 0.5, 2.0]).gaps().tolist() == []  # no period, no gaps
    assert _series([0.0], period=0.1).gaps().tolist() == []


def test_nearest_and_stepped_samples():
    series = _series([0.0, 0.1, 0.2, 0.4], period=0.1)
    assert series.nearest_sample(-1.0) == 0.0
    assert series.nearest_sample(0.14) == pytest.approx(0.1)
    assert series.nearest_sample(0.15) == pytest.approx(0.1)  # a tie goes to the earlier sample
    assert series.nearest_sample(0.31) == pytest.approx(0.4)
    assert series.nearest_sample(9.0) == pytest.approx(0.4)
    assert series.step_sample(0.1, forward=True) == pytest.approx(0.2)
    assert series.step_sample(0.15, forward=True) == pytest.approx(0.2)
    assert series.step_sample(0.1, forward=False) == pytest.approx(0.0)
    assert series.step_sample(0.15, forward=False) == pytest.approx(0.1)
    assert series.step_sample(0.4, forward=True) is None
    assert series.step_sample(0.0, forward=False) is None
    assert _series([]).nearest_sample(0.0) is None and _series([]).step_sample(0.0) is None


def test_a_late_frame_is_jitter_not_a_gap():
    # 2 ms period, one frame 1.1 ms late: 3.1 ms then 0.9 ms; no frame was lost.
    late = _series([0.0, 0.002, 0.004, 0.0071, 0.008, 0.010], period=0.002)
    assert late.gaps().tolist() == []
    # A lost frame leaves two periods of hold whatever follows.
    lost = _series([0.0, 0.002, 0.004, 0.008, 0.010, 0.012], period=0.002)
    assert lost.gaps().tolist() == [2]


def test_a_default_cycle_time_does_not_dash_event_messages():
    from types import SimpleNamespace

    from can_toolbox.canlog.signals import _signal_period

    # cantools reports the database default GenMsgCycleTime for an event message too.
    events = np.array([0.0, 0.05, 0.9, 1.0, 2.7, 2.75, 4.0])
    plain = SimpleNamespace(multiplexer_ids=None)
    assert _signal_period(SimpleNamespace(cycle_time=10), plain, events) is None
    # A periodic message keeps its DBC cycle time, losses included.
    periodic = np.delete(np.arange(50) * 0.01, [10, 11, 12, 30])
    assert _signal_period(SimpleNamespace(cycle_time=10), plain, periodic) == pytest.approx(0.01)
