"""Qt-free log viewer engine: channel-scoped DBCs, filters, find, fixed mode and statistics."""

from __future__ import annotations

from pathlib import Path

import can
import numpy as np
import pytest

from can_toolbox.canlog import open_log
from can_toolbox.canlog.database import ALL_CHANNELS, DbcAssignment, LogDatabase, decode_frame
from can_toolbox.canlog.reader import LogFile, frames_from_messages
from can_toolbox.canlog.view import FrameFilter, FrameQuery, IdMatch, LogView, format_data, format_id, frame_type

_DBC_ALL = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 Engine: 8 ECU
 SG_ Rpm : 0|16@1+ (0.25,0) [0|16383] "rpm" ECU
 SG_ Gear : 16|3@1+ (1,0) [0|7] "" ECU
BO_ 2566848513 Diag: 8 ECU
 SG_ Code : 0|8@1+ (1,0) [0|255] "" ECU
VAL_ 256 Gear 0 "Park" 1 "Drive" ;
"""
_DBC_CH2 = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 BodyStatus: 2 ECU
 SG_ Door : 0|1@1+ (1,0) [0|1] "" ECU
"""


@pytest.fixture
def dbcs(tmp_path) -> tuple[Path, Path]:
    common = tmp_path / "powertrain.dbc"
    common.write_text(_DBC_ALL, encoding="ascii")
    body = tmp_path / "body.dbc"
    body.write_text(_DBC_CH2, encoding="ascii")
    return common, body


def _log(messages) -> LogFile:
    return LogFile(Path("synthetic.blf"), frames_from_messages(messages), "BLF")


def _messages():
    return [
        can.Message(is_extended_id=False, timestamp=10.000, arbitration_id=0x100, data=bytes([0x40, 0x1F, 1, 0, 0, 0, 0, 0]), channel=0),
        can.Message(is_extended_id=False, timestamp=10.010, arbitration_id=0x100, data=bytes([1, 0]), channel=1),
        can.Message(timestamp=10.005, arbitration_id=0x18FF0001, is_extended_id=True, data=b"\x07" * 8, channel=0,
                    is_rx=False),
        can.Message(is_extended_id=False, timestamp=10.020, arbitration_id=0x100, data=bytes([0x80, 0x1F, 0, 0, 0, 0, 0, 0]), channel=0),
        can.Message(is_extended_id=False, timestamp=10.030, is_error_frame=True, channel=0),
        can.Message(is_extended_id=False, timestamp=10.040, arbitration_id=0x200, is_remote_frame=True, dlc=2, channel=1),
    ]


def test_channel_specific_dbc_wins_over_all_channels(dbcs, tmp_path):
    common, body = dbcs
    broken = tmp_path / "broken.dbc"
    broken.write_text("BO_ nonsense", encoding="ascii")
    database = LogDatabase.load([DbcAssignment(common), DbcAssignment(body, channel=2), DbcAssignment(broken)])
    assert database.message_name(0x100, 1) == "Engine"
    assert database.message_name(0x100, 2) == "BodyStatus"
    assert database.message_name(0x18FF0001 | 0x80000000, 1) == "Diag"
    assert database.message_name(0x18FF0001, 1) == ""
    assert len(database.errors) == 1 and "broken.dbc" in database.errors[0]
    assert {scope for scope, _ in database.messages()} == {ALL_CHANNELS, 2}


def test_decode_frame_reports_physical_raw_unit_and_label(dbcs):
    database = LogDatabase.load([DbcAssignment(dbcs[0])])
    values = {value.name: value for value in decode_frame(database.codec(0x100, 1), bytes([0x40, 0x1F, 1, 0, 0, 0, 0, 0]))}
    assert values["Rpm"].physical == 2000.0 and values["Rpm"].raw == 0x1F40 and values["Rpm"].unit == "rpm"
    assert values["Gear"].label == "Drive" and values["Gear"].physical == 1
    assert decode_frame(database.codec(0x100, 1), b"\x01") == []


def test_view_sorts_by_time_and_names_frames_per_channel(dbcs):
    view = LogView(_log(_messages()), LogDatabase.load([DbcAssignment(dbcs[0]), DbcAssignment(dbcs[1], 2)]))
    assert view.order.tolist() == [0, 2, 1, 3, 4, 5]
    assert [view.message_name(row) for row in view.rows] == ["Engine", "Diag", "BodyStatus", "Engine", "", ""]
    assert view.origin_ns == view.frames.time_ns[0]


def test_query_parsing_and_filters(dbcs):
    view = LogView(_log(_messages()), LogDatabase.load([DbcAssignment(dbcs[0])]))
    query = FrameQuery.parse("100, 18ff0000x-18FF00FFx diag 0x7FF")
    assert query.ids == (IdMatch(0x100, 0x100), IdMatch(0x18FF0000, 0x18FF00FF, True), IdMatch(0x7FF, 0x7FF))
    assert query.names == ("diag",)
    assert view.apply(FrameFilter(FrameQuery.parse("engine"))).tolist() == [0, 1, 3]
    assert view.apply(FrameFilter(FrameQuery.parse("18FF0001x"))).tolist() == [2]
    assert view.apply(FrameFilter(FrameQuery.parse("18FF0001"))).tolist() == [2]
    assert view.apply(FrameFilter(channels=frozenset({2}))).tolist() == [1, 5]
    assert view.apply(FrameFilter(direction="tx")).tolist() == [2]
    assert view.apply(FrameFilter(include_errors=False, include_remote=False)).tolist() == [0, 2, 1, 3]
    assert view.apply(FrameFilter(FrameQuery.parse("nothing-here"))).tolist() == []


def test_find_wraps_in_both_directions_and_time_lookup():
    view = LogView(_log(_messages()))
    query = FrameQuery.parse("100")
    assert view.find(query, -1) == 0
    assert view.find(query, 0) == 2
    assert view.find(query, 3) == 0
    assert view.find(query, 0, forward=False) == 3
    assert view.find(FrameQuery.parse("5AA"), 0) == -1
    origin = view.origin_ns
    assert view.position_at_time(origin + 12_000_000) == 2
    assert view.position_at_time(origin - 1) == 0


def test_fixed_mode_keeps_newest_frame_per_channel_and_id():
    view = LogView(_log(_messages()))
    latest = view.latest_per_message()
    # Channel 1: error frame (ID 0), 0x100, 18FF0001x; channel 2: 0x100, 0x200.
    assert latest.tolist() == [4, 3, 2, 1, 5]
    early = view.latest_per_message(view.origin_ns + 6_000_000)
    assert sorted(early.tolist()) == [0, 2]


def test_statistics_cycle_times(dbcs):
    messages = [can.Message(is_extended_id=False, timestamp=1 + 0.01 * i + (0.005 if i == 3 else 0), arbitration_id=0x100,
                            data=bytes(8), channel=0) for i in range(5)]
    messages.append(can.Message(timestamp=1.5, arbitration_id=0x18FF0001, is_extended_id=True, data=bytes(8)))
    view = LogView(_log(messages), LogDatabase.load([DbcAssignment(dbcs[0])]))
    stats = {item.name: item for item in view.statistics()}
    engine = stats["Engine"]
    assert engine.count == 5 and engine.channel == 1
    assert engine.cycle_min_ms == pytest.approx(5.0)
    assert engine.cycle_max_ms == pytest.approx(15.0)
    assert engine.cycle_avg_ms == pytest.approx(10.0)
    assert stats["Diag"].cycle_avg_ms is None
    assert stats["Diag"].first_s == pytest.approx(0.5)


def test_formatting_helpers():
    assert format_id(0x1AB, False) == "1AB"
    assert format_id(0x18FF0001, True) == "18FF0001x"
    assert format_data(b"\x01\xab") == "01 AB"
    assert [frame_type(flags) for flags in (0, 0x02, 0x06, 0x10, 0x20)] == ["CAN", "CAN FD", "CAN FD BRS", "Remote",
                                                                            "Error"]


def test_mf4_bus_logging_opens(tmp_path):
    path = tmp_path / "drive.mf4"
    messages = [can.Message(is_extended_id=False, timestamp=200 + i * 0.5, arbitration_id=0x100 + i, data=bytes([i] * 8), channel=i % 2)
                for i in range(6)]
    with can.MF4Writer(str(path)) as writer:
        for message in messages:
            writer.on_message_received(message)
    log = open_log(path)
    assert log.format == "MF4"
    assert log.frames.arbitration_id.tolist() == [0x100 + i for i in range(6)]
    assert log.frames.channel.tolist() == [1, 2, 1, 2, 1, 2]
    assert np.allclose(log.frames.seconds(), [0.5 * i for i in range(6)], atol=1e-6)


def test_peak_trace_opens(tmp_path):
    path = tmp_path / "drive.trc"
    messages = [can.Message(is_extended_id=False, timestamp=10 + i * 0.5, arbitration_id=0x100 + i,
                            data=bytes([i] * 8), channel=1) for i in range(4)]
    with can.TRCWriter(str(path)) as writer:
        for message in messages:
            writer.on_message_received(message)
    log = open_log(path)
    assert log.format == "TRC"
    assert log.frames.arbitration_id.tolist() == [0x100 + i for i in range(4)]
    assert np.allclose(log.frames.seconds(), [0.5 * i for i in range(4)], atol=1e-3)


def test_candump_log_opens_and_names_its_buses(tmp_path):
    """candump writes a bus name, not a number; each name gets a channel of its own."""
    path = tmp_path / "drive.log"
    with can.CanutilsLogWriter(str(path)) as writer:
        for index in range(4):
            writer.on_message_received(can.Message(
                is_extended_id=False, timestamp=5 + index * 0.25, arbitration_id=0x200 + index,
                data=bytes([index] * 4), channel="vcan0" if index % 2 == 0 else "vcan1"))
    log = open_log(path)
    assert log.format == "candump"
    assert log.frames.arbitration_id.tolist() == [0x200 + i for i in range(4)]
    assert log.frames.channel.tolist() == [1, 2, 1, 2]
    assert np.allclose(log.frames.seconds(), [0.25 * i for i in range(4)], atol=1e-6)


def _csv_source(tmp_path):
    messages = [
        can.Message(is_extended_id=False, timestamp=100.0, arbitration_id=0x100, data=b"\x01\x02", channel=0),
        can.Message(is_extended_id=True, timestamp=100.5, arbitration_id=0x18FF0001, data=bytes(range(8)),
                    channel=1, is_fd=True, bitrate_switch=True),
        can.Message(is_extended_id=False, timestamp=101.0, arbitration_id=0x200, data=b"", channel=0,
                    is_remote_frame=True, dlc=4),
    ]
    return frames_from_messages(messages)


def test_an_exported_csv_opens_again(tmp_path):
    from can_toolbox.canlog.export import export_table

    table = _csv_source(tmp_path)
    path = tmp_path / "cut.csv"
    export_table(table, path, "csv")
    log = open_log(path)
    assert log.format == "CSV"
    frames = log.frames
    assert frames.arbitration_id.tolist() == table.arbitration_id.tolist()
    assert frames.channel.tolist() == table.channel.tolist()
    assert frames.dlc.tolist() == table.dlc.tolist()
    assert frames.flags.tolist() == table.flags.tolist()
    assert [frames.data(i) for i in range(len(frames))] == [table.data(i) for i in range(len(table))]
    assert np.allclose(frames.seconds(), table.seconds(), atol=1e-6)


def test_a_python_can_csv_opens_and_a_foreign_one_is_rejected(tmp_path):
    path = tmp_path / "theirs.csv"
    with can.CSVWriter(str(path)) as writer:
        writer.on_message_received(can.Message(is_extended_id=False, timestamp=1.0,
                                               arbitration_id=0x123, data=b"\xaa\xbb"))
    log = open_log(path)
    assert log.format == "CSV"
    assert log.frames.arbitration_id.tolist() == [0x123]
    assert log.frames.data(0) == b"\xaa\xbb"

    stranger = tmp_path / "stranger.csv"
    stranger.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported CSV columns"):
        open_log(stranger)


def test_an_unknown_suffix_names_the_formats_that_open(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("not a log", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported log format"):
        open_log(path)
