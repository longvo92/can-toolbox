"""Cutting and exporting logs: every format reads back with the frames that were selected."""

from __future__ import annotations

import csv

import can
import numpy as np
import pytest
from scipy.io import loadmat

from can_toolbox.canlog import open_log
from can_toolbox.canlog.blf import ReadCancelled, read_blf
from can_toolbox.canlog.blf_writer import write_blf
from can_toolbox.canlog.export import (
    ExportRequest,
    cut_table,
    export_log,
    frame_fields,
    parse_channel_map,
    select_rows,
)
from can_toolbox.canlog.table import FLAG_ERROR, FLAG_FD, FLAG_RX, FrameTable
from can_toolbox.canlog.view import FrameFilter, FrameQuery, LogView
from tests import blf_factory as bf
from tests.test_canlog import _mixed_messages, assert_matches_python_can


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.blf"
    with can.BLFWriter(path) as writer:
        for message in _mixed_messages(2500, seed=21):
            writer.on_message_received(message)
    return path


def _same_frames(left: FrameTable, right: FrameTable) -> None:
    assert len(left) == len(right)
    for column in ("arbitration_id", "channel", "dlc", "flags", "offsets", "payload"):
        assert np.array_equal(getattr(left, column), getattr(right, column)), column


def test_blf_writer_round_trip_is_exact(source, tmp_path):
    table, _ = read_blf(source)
    target = tmp_path / "copy.blf"
    assert write_blf(target, table) == len(table)
    copy, info = read_blf(target)
    _same_frames(copy, table)
    # Relative times are exact to the nanosecond; absolute times keep the header start.
    assert np.array_equal(copy.time_ns - copy.time_ns[0], table.time_ns - table.time_ns[0])
    assert np.allclose(copy.timestamps(), table.timestamps(), atol=1e-6, rtol=0)
    assert info.skipped_objects == {}
    with can.BLFReader(str(target)) as reader:
        assert_matches_python_can(copy, list(reader))


def test_blf_writer_keeps_sub_millisecond_start_and_unknown_wall_clock(tmp_path):
    messages = [can.Message(timestamp=1_700_000_000.0004567 + i * 0.001, arbitration_id=i, is_extended_id=False,
                            data=bytes([i])) for i in range(5)]
    from can_toolbox.canlog.reader import frames_from_messages

    table = frames_from_messages(messages)
    copy, _ = read_blf(write_blf(tmp_path / "start.blf", table) and tmp_path / "start.blf")
    assert np.allclose(copy.timestamps(), table.timestamps(), atol=1e-6, rtol=0)
    no_clock = FrameTable(table.time_ns, table.arbitration_id, table.channel, table.dlc, table.flags, table.offsets,
                          table.payload, 0.0)
    write_blf(tmp_path / "plain.blf", no_clock)
    plain, info = read_blf(tmp_path / "plain.blf")
    assert info.start_time == 0.0 and np.array_equal(plain.time_ns, no_clock.time_ns)


def test_cut_by_time_filter_channel_map_and_rebase(source):
    view = LogView(open_log(source))
    view.apply(FrameFilter(FrameQuery.parse("0-7FF")))
    total = (int(view.frames.time_ns.max()) - view.origin_ns) / 1e9
    request = ExportRequest(start_s=total * 0.25, end_s=total * 0.75)
    rows = select_rows(view, request)
    seconds = (view.frames.time_ns[rows] - view.origin_ns) / 1e9
    assert len(rows) and seconds.min() >= total * 0.25 and seconds.max() <= total * 0.75
    assert np.all(np.diff(view.frames.time_ns[rows]) >= 0)
    filtered = select_rows(view, ExportRequest(start_s=total * 0.25, end_s=total * 0.75, filtered=True))
    assert 0 < len(filtered) < len(rows)
    assert set(filtered.tolist()) <= set(rows.tolist())

    cut = cut_table(view, ExportRequest(channel_map=((1, 3), (3, 1)), rebase=True))
    original = view.frames.take(view.order)
    assert np.array_equal(cut.channel == 3, original.channel == 1)
    assert np.array_equal(cut.channel == 1, original.channel == 3)
    assert cut.time_ns[0] == 0
    assert np.allclose(cut.timestamps(), original.timestamps(), atol=1e-6, rtol=0)


@pytest.mark.parametrize("fmt", ["blf", "asc", "mf4"])
def test_log_formats_read_back(source, tmp_path, fmt):
    view = LogView(open_log(source))
    request = ExportRequest(start_s=0.5, end_s=None, channel_map=((2, 4),))
    expected = cut_table(view, request)
    result = export_log(view, request, tmp_path / f"cut.{fmt}")
    assert result.frames == len(expected) and result.path.is_file()
    back = open_log(result.path).frames
    if fmt == "blf":
        _same_frames(back, expected)
        assert np.allclose(back.timestamps(), expected.timestamps(), atol=1e-6, rtol=0)
        return

    # ASC and MF4 store no ID (ASC no data) for error frames, MF4 groups frame types (frames
    # sharing a timestamp may come back in another order) and ASC keeps its start
    # time to the millisecond: compare times relative to the first frame.
    def frames(table):
        times = table.timestamps() - table.timestamps().min()
        return sorted(
            (int(table.channel[i]), 0 if table.flags[i] & FLAG_ERROR else int(table.arbitration_id[i]),
             b"" if table.flags[i] & FLAG_ERROR else table.data(i),
             bool(table.flags[i] & FLAG_FD), bool(table.flags[i] & FLAG_RX), float(times[i]))
            for i in range(len(table))
        )

    got, want = frames(back), frames(expected)
    assert [item[:-1] for item in got] == [item[:-1] for item in want]
    # ASC stores microseconds.
    assert np.allclose([item[-1] for item in got], [item[-1] for item in want], atol=2e-6, rtol=0)


def test_csv_and_mat_exports(source, tmp_path):
    view = LogView(open_log(source))
    request = ExportRequest(end_s=0.2)
    expected = cut_table(view, request)
    csv_path = export_log(view, request, tmp_path / "cut.csv").path
    with open(csv_path, newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == ["Time", "Timestamp", "Channel", "ID", "Extended", "Dir", "Type", "DLC", "Length", "Data"]
    assert len(rows) == len(expected) + 1 and rows[1][0] == "0.000000000"
    assert rows[1][9] == expected.data(0).hex(" ").upper()
    mat = loadmat(export_log(view, request, tmp_path / "cut.mat").path, simplify_cells=True)["Frames"]
    for name, values in frame_fields(expected).items():
        assert np.array_equal(np.asarray(mat[name]).reshape(np.shape(values)), values), name


def test_errors_cancel_and_skipped_object_warning(tmp_path, source):
    view = LogView(open_log(source))
    with pytest.raises(ValueError, match="No frames"):
        export_log(view, ExportRequest(start_s=1e9), tmp_path / "none.blf")
    with pytest.raises(ValueError, match="Unsupported"):
        export_log(view, ExportRequest(), tmp_path / "out.txt")
    target = tmp_path / "cancelled.blf"
    with pytest.raises(ReadCancelled):
        export_log(view, ExportRequest(), target, cancel=lambda: True)
    assert not target.exists() and not list(tmp_path.glob("cancelled*"))

    marked = bf.write_blf(tmp_path / "marked.blf", [
        bf.obj(1, bf.can_message(1, 0x10, b"\x01"), 1000),
        bf.obj(96, b"\0" * 40, 2000),
    ])
    result = export_log(LogView(open_log(marked)), ExportRequest(), tmp_path / "marked_cut.blf")
    assert result.warnings == ("Not exported: Skipped non-CAN objects: 1 global marker",)


@pytest.mark.parametrize(("text", "expected"), [
    ("", ()), ("1=2", ((1, 2),)), ("1->2; 2 > 1", ((1, 2), (2, 1))), ("3→4", ((3, 4),)),
])
def test_channel_map_parsing(text, expected):
    assert parse_channel_map(text) == expected


@pytest.mark.parametrize("text", ["1", "a=2", "0=1", "1=2,1=3", "1=300"])
def test_channel_map_rejects(text):
    with pytest.raises(ValueError):
        parse_channel_map(text)


_CHANNEL_DBC = '''VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 Shared: 2 ECU
 SG_ Value : 0|16@1+ ({scale},0) [0|65535] "" ECU
'''


def test_a_channel_scoped_dbc_only_decodes_its_own_channel(tmp_path, blf_runtime):
    """A DBC assigned to CAN 1 must not decode the same ID seen on CAN 2."""
    from can_toolbox.blf_mat.converter import build_decode_requests, decode_table, load_dbc_sources

    first = tmp_path / "bus1.dbc"
    second = tmp_path / "bus2.dbc"
    first.write_text(_CHANNEL_DBC.format(scale=1), encoding="ascii")
    second.write_text(_CHANNEL_DBC.format(scale=10), encoding="ascii")
    path = tmp_path / "two_buses.blf"
    with can.BLFWriter(path) as writer:
        for index, channel in enumerate((0, 1)):  # python-can channels are 0-based
            writer.on_message_received(can.Message(
                timestamp=100.0 + index, arbitration_id=0x100, is_extended_id=False,
                data=[7, 0], channel=channel,
            ))
    table, _info = read_blf(path)

    candidates, _names = load_dbc_sources([first, second])
    requests = build_decode_requests(["Value"], candidates)

    # Without scopes a database decodes every bus that carries the ID.
    unscoped, _duration = decode_table(table, requests)
    assert unscoped["value"]["samples"] == 2

    scopes = {str(first.resolve()): 1, str(second.resolve()): 2}
    decoded, _duration = decode_table(table, requests, scopes)
    chosen = decoded["value"]["candidate"]
    assert chosen is not None
    # Both databases describe ID 0x100; each may only use the frames of its own bus.
    assert decoded["value"]["samples"] == 1
    scale = 1 if chosen.dbc_file == str(first.resolve()) else 10
    assert decoded["value"]["data"].tolist() == [7 * scale]


def test_dataset_and_mat_signals_get_their_own_stem():
    from can_toolbox.canlog.export import signal_stem

    assert signal_stem("drive_cut", "signals") == "drive_cut"
    assert signal_stem("drive_cut", "dataset") == "drive_cut_dataset"
