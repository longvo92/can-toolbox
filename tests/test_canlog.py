"""The canlog engine against python-can and cantools as oracles."""

from __future__ import annotations

import random
from pathlib import Path

import can
import cantools
import numpy as np
import pytest

from can_toolbox.canlog import blf as blf_module
from can_toolbox.canlog import open_log
from can_toolbox.canlog.blf import BlfError, ReadCancelled, read_blf
from can_toolbox.canlog.decode import MessageCodec, rows_by_message
from can_toolbox.canlog.reader import frames_from_messages
from can_toolbox.canlog.table import FLAG_ERROR, FLAG_EXTENDED, FLAG_FD, FLAG_RX, FrameTable, dlc_to_length
from tests import blf_factory as bf


def _python_can(path: Path) -> list[can.Message]:
    with can.BLFReader(str(path)) as reader:
        return list(reader)


def assert_matches_python_can(table: FrameTable, messages: list[can.Message]) -> None:
    assert len(table) == len(messages)
    expected = frames_from_messages(messages, start_time=table.start_time)
    assert np.array_equal(table.timestamps(), np.asarray([m.timestamp for m in messages]))
    for column in ("arbitration_id", "flags", "offsets", "payload"):
        assert np.array_equal(getattr(table, column), getattr(expected, column)), column
    assert table.channel.tolist() == [m.channel + 1 for m in messages]
    # python-can reports a CAN FD object's DLC as a byte count.
    lengths = [len(m.data) if m.is_fd else m.dlc for m in messages]
    fd = table.has_flag(FLAG_FD)
    assert np.where(fd, dlc_to_length(table.dlc), table.dlc).tolist() == lengths


def _mixed_messages(count: int, seed: int = 7) -> list[can.Message]:
    rng = random.Random(seed)
    messages = []
    stamp = 1_700_000_000.0
    for index in range(count):
        stamp += rng.choice((0.0, 0.00001, 0.0013, 0.25))
        kind = rng.random()
        fd = kind < 0.3
        length = rng.choice((0, 1, 8, 12, 64)) if fd else rng.randint(0, 8)
        messages.append(
            can.Message(
                timestamp=stamp,
                arbitration_id=rng.randrange(0x20000000 if index % 3 == 0 else 0x800),
                is_extended_id=index % 3 == 0,
                is_fd=fd,
                bitrate_switch=fd and rng.random() < 0.5,
                error_state_indicator=fd and rng.random() < 0.2,
                is_remote_frame=not fd and kind > 0.97,
                is_error_frame=not fd and 0.94 < kind <= 0.97,
                is_rx=rng.random() < 0.7,
                channel=rng.randint(0, 3),
                data=bytes(rng.getrandbits(8) for _ in range(length)),
            )
        )
    return messages


def test_python_can_written_log_reads_identically(tmp_path, monkeypatch):
    path = tmp_path / "mixed.blf"
    with can.BLFWriter(path) as writer:
        for message in _mixed_messages(3000):
            writer.on_message_received(message)
    # Tiny kernel chunks force objects to straddle chunk and container boundaries.
    monkeypatch.setattr(blf_module, "_CHUNK_BYTES", 700)
    table, info = read_blf(path)
    assert_matches_python_can(table, _python_can(path))
    assert info.skipped_objects == {}
    assert info.trailing_bytes == 0


@pytest.mark.parametrize("compress", [True, False])
@pytest.mark.parametrize("container_size", [97, 4096])
def test_hand_built_object_layouts_match_python_can(tmp_path, compress, container_size):
    objects = [
        bf.obj(1, bf.can_message(1, 0x123, b"\x01\x02\x03"), 1500, ten_us=True),
        bf.obj(86, bf.can_message2(2, 0x1ABCDE, b"\xaa" * 8, extended=True, tx=True), 2_000_000, version=2),
        bf.obj(1, bf.can_message(1, 0x7FF, b"", remote=True, dlc=4), 2_100_000),
        bf.obj(65, bf.app_text("comment"), 2_200_000),
        bf.obj(101, bf.can_fd64(3, 0x55, bytes(range(12)), 9, esi=True), 3_000_000, version=2),
        # Valid length beyond the stored data: CANoe pads with zeros.
        bf.obj(101, bf.can_fd64(1, 0x56, bytes(range(16)), 10, valid=16, stored=bytes(range(5))), 3_100_000),
        bf.obj(100, bf.can_fd(2, 0x99, bytes(range(20)), 11, brs=True), 3_200_000),
        bf.obj(100, bf.can_fd(2, 0x9A, bytes(range(8)), 8, edl=False, tx=True), 3_300_000),
        bf.obj(96, b"\0" * 40, 3_400_000),
    ]
    path = bf.write_blf(tmp_path / "objects.blf", objects, container_size=container_size, compress=compress)
    table, info = read_blf(path)
    assert_matches_python_can(table, _python_can(path))
    assert info.skipped_objects == {65: 1, 96: 1}
    assert info.application_version == (1, 2, 3)
    assert table.data(2) == b""
    assert table.data(4) == bytes(range(5)) + b"\0" * 11
    assert table.channel.tolist() == [1, 2, 1, 3, 1, 2, 2]
    assert table.has_flag(FLAG_EXTENDED).tolist() == [False, True, False, False, False, False, False]
    assert table.has_flag(FLAG_RX).tolist() == [True, False, True, True, True, True, False]
    assert table.seconds()[:2].tolist() == [0.015, 0.002]


def test_top_level_objects_and_truncated_tail_are_reported(tmp_path):
    objects = [bf.obj(1, bf.can_message(1, 0x10, b"\x01"), 10)]
    path = bf.write_blf(tmp_path / "top.blf", objects, top_level=[bf.obj(65, bf.app_text("note"), 1)])
    _, info = read_blf(path)
    assert info.skipped_objects == {65: 1}
    truncated = tmp_path / "cut.blf"
    bf.write_blf(truncated, objects + [bf.obj(1, bf.can_message(1, 0x11, b"\x02"), 20)[:30]])
    table, info = read_blf(truncated)
    assert len(table) == 1
    assert info.trailing_bytes == 32  # the partial object plus its alignment padding
    warnings = open_log(truncated).warnings
    assert any("incomplete" in warning for warning in warnings)


def test_error_frames_and_header_start_time(tmp_path):
    path = tmp_path / "errors.blf"
    with can.BLFWriter(path) as writer:
        writer.on_message_received(can.Message(timestamp=1_700_000_000.5, arbitration_id=0x10, data=b"\x01"))
        writer.on_message_received(can.Message(timestamp=1_700_000_001.0, is_error_frame=True, channel=1))
    table, info = read_blf(path)
    assert_matches_python_can(table, _python_can(path))
    assert table.has_flag(FLAG_ERROR).tolist() == [False, True]
    assert info.start_time == pytest.approx(1_700_000_000.5)


def test_rejects_non_blf_and_honours_cancel(tmp_path):
    bogus = tmp_path / "bogus.blf"
    bogus.write_bytes(b"NOPE" + b"\0" * 200)
    with pytest.raises(BlfError, match="LOGG"):
        read_blf(bogus)
    path = bf.write_blf(tmp_path / "ok.blf", [bf.obj(1, bf.can_message(1, 1, b""), 1)])
    with pytest.raises(ReadCancelled):
        read_blf(path, cancel=lambda: True)
    seen = []
    read_blf(path, progress=lambda done, total: seen.append((done, total)))
    assert seen[-1][0] == seen[-1][1] == path.stat().st_size


def test_asc_reader_matches_python_can(tmp_path):
    path = tmp_path / "trace.asc"
    messages = [m for m in _mixed_messages(300, seed=3) if not m.is_error_frame]
    with can.ASCWriter(str(path)) as writer:
        for message in messages:
            writer.on_message_received(message)
    log = open_log(path)
    with can.ASCReader(str(path)) as reader:
        expected = list(reader)
    assert log.format == "ASC"
    assert len(log.frames) == len(expected)
    assert np.allclose(log.frames.timestamps(), [m.timestamp for m in expected], atol=1e-6, rtol=0)
    assert log.frames.arbitration_id.tolist() == [m.arbitration_id for m in expected]
    assert [log.frames.data(i) for i in range(len(expected))] == [bytes(m.data) for m in expected]


def test_table_take_concat_and_payload_matrix():
    table = frames_from_messages(
        [can.Message(timestamp=t, arbitration_id=i, data=bytes([i] * i)) for i, t in enumerate((1.0, 1.5, 2.0, 2.5))]
    )
    picked = table.take(np.array([3, 1]))
    assert [picked.data(0), picked.data(1)] == [b"\x03\x03\x03", b"\x01"]
    assert picked.seconds().tolist() == [1.5, 0.5]
    assert table.take(table.arbitration_id > 1).arbitration_id.tolist() == [2, 3]
    joined = FrameTable.concat([table.take(np.array([0, 1])), table.take(np.array([2, 3]))])
    assert np.array_equal(joined.payload, table.payload)
    assert np.array_equal(joined.time_ns, table.time_ns)
    assert table.payload_matrix(np.array([2, 0]), 2).tolist() == [[2, 2], [0, 0]]


_DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 Intel: 8 ECU
 SG_ A : 0|12@1+ (0.5,-10) [0|0] "" ECU
 SG_ B : 12|9@1- (1,0) [0|0] "" ECU
 SG_ C : 21|32@1+ (1,0) [0|0] "" ECU
 SG_ D : 53|11@1- (0.1,3) [0|0] "" ECU
BO_ 257 Moto: 8 ECU
 SG_ E : 7|12@0+ (2,1) [0|0] "" ECU
 SG_ F : 11|17@0- (0.01,0) [0|0] "" ECU
 SG_ G : 39|32@0+ (1,0) [0|0] "" ECU
BO_ 2147484160 Mux: 8 ECU
 SG_ M M : 0|4@1+ (1,0) [0|0] "" ECU
 SG_ X m0 : 8|16@1+ (1,0) [0|0] "" ECU
 SG_ Y m1 : 8|16@1- (1,0) [0|0] "" ECU
 SG_ Z m2 : 15|10@0+ (1,0) [0|0] "" ECU
 SG_ Common : 32|8@1+ (1,0) [0|0] "" ECU
BO_ 258 Flt: 12 ECU
 SG_ F32 : 0|32@1- (1,0) [0|0] "" ECU
 SG_ F64 : 32|64@1- (1,0) [0|0] "" ECU
BO_ 259 Wide: 8 ECU
 SG_ W : 0|64@1+ (1,0) [0|0] "" ECU
BO_ 260 Nested: 8 ECU
 SG_ Top M : 0|2@1+ (1,0) [0|0] "" ECU
 SG_ Sub m1M : 8|2@1+ (1,0) [0|0] "" ECU
 SG_ Leaf m0 : 16|8@1+ (1,0) [0|0] "" ECU
SIG_VALTYPE_ 258 F32 : 1;
SIG_VALTYPE_ 258 F64 : 2;
SG_MUL_VAL_ 260 Sub Top 1-1;
SG_MUL_VAL_ 260 Leaf Sub 0-0;
"""


def test_vectorized_decode_matches_cantools():
    db = cantools.database.load_string(_DBC, "dbc", strict=False)
    rng = random.Random(11)
    messages = []
    for index in range(20000):
        message = rng.choice(db.messages)
        length = message.length if rng.random() > 0.05 else rng.randint(0, message.length)
        data = bytearray(rng.getrandbits(8) for _ in range(length))
        if message.name in ("Mux", "Nested") and data and rng.random() < 0.9:
            data[0] = rng.randint(0, 2)
        if message.name == "Nested" and len(data) > 1 and rng.random() < 0.9:
            data[1] = rng.randint(0, 1)
        messages.append(
            can.Message(timestamp=index * 0.001, arbitration_id=message.frame_id,
                        is_extended_id=message.is_extended_frame, data=bytes(data), is_fd=length > 8)
        )
    # A remote frame of a known message must not be decoded.
    messages.append(can.Message(timestamp=99.0, arbitration_id=256, is_remote_frame=True, dlc=8))
    table = frames_from_messages(messages)
    groups = rows_by_message(table)

    expected: dict[tuple[str, str], list[tuple[int, float]]] = {}
    by_key = {(m.frame_id, m.is_extended_frame): m for m in db.messages}
    for row, frame in enumerate(messages):
        if frame.is_remote_frame:
            continue
        message = by_key[(frame.arbitration_id, frame.is_extended_id)]
        try:
            values = message.decode(bytes(frame.data), decode_choices=False, scaling=True, allow_truncated=False)
        except Exception:
            continue
        for name, value in values.items():
            expected.setdefault((message.name, name), []).append((row, float(value)))

    for message in db.messages:
        codec = MessageCodec(message)
        decoded = codec.decode(table, groups.get(codec.key, np.zeros(0, np.int64)))
        for signal in message.signals:
            pairs = expected.get((message.name, signal.name), [])
            rows, values = decoded.get(signal.name, (np.zeros(0), np.zeros(0)))
            assert rows.tolist() == [row for row, _ in pairs], (message.name, signal.name)
            assert np.array_equal(values, [value for _, value in pairs], equal_nan=True), (message.name, signal.name)
        subset = codec.decode(table, groups.get(codec.key, np.zeros(0, np.int64)), {message.signals[-1].name})
        assert set(subset) <= {message.signals[-1].name}
