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
    assert gear.text_at(0.0) == "Park (1)"
    assert gear.value_at(0.0124) == 1.0
    assert gear.text_at(gear.time[1]) == "Park (1)"
    rpm = source.series(SignalRef(1, 0x100, "Engine", "Rpm"))
    assert rpm.text_at(rpm.time[2]).endswith(" rpm")
    assert gear.choices == {0: "Park", 1: "Drive"}


def test_unknown_signal_or_message_raises(source):
    with pytest.raises(KeyError):
        source.series(SignalRef(1, 0x100, "Engine", "Missing"))
    with pytest.raises(KeyError):
        source.series(SignalRef(1, 0x7FF, "Ghost", "X"))
