"""BLF to MAT on the canlog engine must reproduce the former per-frame python-can/cantools results."""

from __future__ import annotations

import math
import random
from pathlib import Path

import can
import numpy as np
import pytest
from scipy.io import loadmat

from can_toolbox.blf_mat import converter as core
from can_toolbox.blf_mat.frames import export_frames

pytestmark = pytest.mark.usefixtures("blf_runtime")

_DBC_A = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 Speed: 8 ECU
 SG_ VehSpd : 0|16@1+ (0.01,0) [0|0] "" ECU
 SG_ Gear : 16|4@1+ (1,0) [0|0] "" ECU
 SG_ Torque : 31|12@0- (0.5,-100) [0|0] "" ECU
BO_ 2148532224 Ext: 8 ECU
 SG_ Mode M : 0|2@1+ (1,0) [0|0] "" ECU
 SG_ Temp m0 : 8|8@1- (1,-40) [0|0] "" ECU
 SG_ Volt m1 : 8|12@1+ (0.1,0) [0|0] "" ECU
"""
_DBC_B = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 SpeedAlt: 8 ECU
 SG_ VehSpd : 8|16@1+ (0.1,0) [0|0] "" ECU
BO_ 300 Rare: 2 ECU
 SG_ Gear : 0|8@1+ (1,0) [0|0] "" ECU
"""


def _messages(count: int, seed: int) -> list[can.Message]:
    rng = random.Random(seed)
    out = []
    stamp = 5000.0
    for index in range(count):
        stamp += rng.choice((0.0, 0.0001, 0.01))
        roll = rng.random()
        if roll < 0.45:
            arb, ext, size = 256, False, rng.choice((8, 8, 8, 3))
        elif roll < 0.85:
            arb, ext, size = 0x10000, True, 8
        elif roll < 0.9:
            arb, ext, size = 300, False, 2
        else:
            arb, ext, size = rng.randrange(0x800), False, rng.randint(0, 8)
        data = bytearray(rng.getrandbits(8) for _ in range(size))
        if arb == 0x10000:
            data[0] = rng.choice((0, 1, 2))
        out.append(can.Message(timestamp=stamp, arbitration_id=arb, is_extended_id=ext, data=bytes(data),
                               is_error_frame=roll > 0.995, channel=index % 2))
    return out


def _reference_decode(blf_path: Path, requests):
    """The pre-canlog decode loop, kept verbatim in behaviour as the oracle."""
    stores = {}
    tasks: dict = {}
    for request_key, candidates in requests.items():
        for c in candidates:
            stores[(request_key, c.key)] = ([], [])
            msg_key = (c.dbc_file, c.message_name, c.frame_id, c.is_extended)
            tasks.setdefault((c.frame_id, c.is_extended), {}).setdefault(
                msg_key, {"message": c.message_obj, "requests": []})["requests"].append((request_key, c))
    first = last = None
    with can.BLFReader(str(blf_path)) as reader:
        for frame in reader:
            ts = float(frame.timestamp)
            first = ts if first is None else min(first, ts)
            last = ts if last is None else max(last, ts)
            if frame.is_error_frame or frame.is_remote_frame:
                continue
            for task in tasks.get((frame.arbitration_id, frame.is_extended_id), {}).values():
                try:
                    values = task["message"].decode(bytes(frame.data), decode_choices=False, scaling=True,
                                                    allow_truncated=False)
                except Exception:
                    continue
                for request_key, cand in task["requests"]:
                    if cand.signal_name in values:
                        times, data = stores[(request_key, cand.key)]
                        times.append(ts)
                        data.append(float(values[cand.signal_name]))
    result = {}
    for request_key, candidates in requests.items():
        ranked = sorted(((len(stores[(request_key, c.key)][0]), c) for c in candidates),
                        key=lambda item: item[0], reverse=True)
        if not ranked or ranked[0][0] == 0:
            result[request_key] = (None, [], [])
            continue
        times, data = stores[(request_key, ranked[0][1].key)]
        t, y = core.collapse_duplicate_times(np.asarray(times) - first, np.asarray(data))
        result[request_key] = (ranked[0][1].key, t.tolist(), y.tolist())
    return result, max(core.MIN_FALLBACK_DURATION_S, last - first)


def test_decode_blf_matches_former_per_frame_decoder(tmp_path):
    dbc = tmp_path / "dbc"
    dbc.mkdir()
    (dbc / "a.dbc").write_text(_DBC_A, encoding="ascii")
    (dbc / "b.dbc").write_text(_DBC_B, encoding="ascii")
    blf = tmp_path / "drive.blf"
    with can.BLFWriter(blf) as writer:
        for message in _messages(5000, seed=5):
            writer.on_message_received(message)
    candidates, _ = core.load_dbc_folder(dbc)
    requests = core.build_decode_requests(["VehSpd", "Gear", "Torque", "Temp", "Volt", "Missing"], candidates)

    decoded, duration = core.decode_blf(blf, requests)
    expected, expected_duration = _reference_decode(blf, requests)

    assert duration == expected_duration
    for key, (candidate_key, times, values) in expected.items():
        info = decoded[key]
        assert (info["candidate"].key if info["candidate"] else None) == candidate_key, key
        assert info["time"].tolist() == times, key
        assert info["data"].tolist() == values, key
    assert decoded["vehspd"]["status"] == "DECODED_AMBIGUOUS_DBC"
    assert decoded["missing"]["status"] == "NOT_IN_DBC"


def _reference_frames(blf: Path) -> dict[str, np.ndarray]:
    with can.BLFReader(str(blf)) as reader:
        frames = list(reader)
    origin = min(frame.timestamp for frame in frames)
    payload = np.zeros((len(frames), 64), np.uint8)
    for index, frame in enumerate(frames):
        payload[index, : len(frame.data)] = list(frame.data)
    fields = {
        "Time": [frame.timestamp - origin for frame in frames],
        "Timestamp": [frame.timestamp for frame in frames],
        "ID": [frame.arbitration_id for frame in frames],
        "Channel": [frame.channel if frame.channel is not None else -1 for frame in frames],
        "DLC": [frame.dlc for frame in frames],
        "Length": [len(frame.data) for frame in frames],
        "Data": payload,
    }
    for label, attribute in (("Extended", "is_extended_id"), ("FD", "is_fd"), ("Remote", "is_remote_frame"),
                             ("Error", "is_error_frame"), ("BRS", "bitrate_switch"),
                             ("ESI", "error_state_indicator"), ("Rx", "is_rx")):
        fields[label] = [getattr(frame, attribute) for frame in frames]
    return fields


def test_frame_export_matches_former_layout(tmp_path):
    blf = tmp_path / "frames.blf"
    rng = random.Random(9)
    with can.BLFWriter(blf) as writer:
        for index, message in enumerate(_messages(800, seed=2)):
            if index % 4 == 0:
                size = rng.choice((12, 20, 64))
                message = can.Message(timestamp=message.timestamp, arbitration_id=0x321, is_fd=True,
                                      bitrate_switch=index % 8 == 0, data=bytes(rng.getrandbits(8) for _ in range(size)),
                                      channel=2, is_rx=False)
            writer.on_message_received(message)
    target = tmp_path / "frames.mat"
    duration = export_frames(blf, target)
    frames = loadmat(target, simplify_cells=True)["Frames"]
    expected = _reference_frames(blf)
    for name, values in expected.items():
        assert np.array_equal(np.asarray(frames[name]).reshape(np.shape(values)), np.asarray(values)), name
    span = max(expected["Timestamp"]) - min(expected["Timestamp"])
    assert math.isclose(duration, max(core.MIN_FALLBACK_DURATION_S, span))


def test_conversion_names_blf_objects_it_cannot_export(tmp_path, capsys):
    from tests import blf_factory as bf

    blf = bf.write_blf(tmp_path / "marked.blf", [
        bf.obj(1, bf.can_message(1, 0x10, b"\x01"), 1000),
        bf.obj(65, bf.app_text("driver note"), 2000),
        bf.obj(96, b"\0" * 40, 3000),
    ])
    export_frames(blf, tmp_path / "marked.mat")
    assert "Not exported (non-CAN BLF objects): 1 app text, 1 global marker" in capsys.readouterr().out
