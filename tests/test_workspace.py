"""Workspace files: round trip, portable paths and rejection of foreign or newer files."""

from __future__ import annotations

import json

import pytest

from can_toolbox.canlog.refs import SignalRef
from can_toolbox.canlog.workspace import Workspace, WorkspaceError, load_workspace, save_workspace


def test_round_trip_with_paths_relative_to_the_workspace(tmp_path):
    project = tmp_path / "project"
    (project / "logs").mkdir(parents=True)
    log = project / "logs" / "drive.blf"
    dbc = project / "pt.dbc"
    workspace = Workspace(
        log=str(log), dbcs=((str(dbc), 0), (str(project / "body.dbc"), 2)), filter="100-1FF engine",
        channel=2, direction="tx", errors=False, mode="fixed", time="absolute",
        signals=(SignalRef(1, 0x100, "Engine", "Rpm"), SignalRef(2, 0x98FF0001, "Diag", "Code")),
        cursors=(1.25, 3.5), measure=True,
    )
    path = save_workspace(project / "drive.cantoolbox.json", workspace)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["log"] == "logs/drive.blf" and raw["dbcs"][0] == {"path": "pt.dbc", "channel": 0}

    moved = tmp_path / "moved"
    project.rename(moved)
    loaded = load_workspace(moved / "drive.cantoolbox.json")
    assert loaded.log == str((moved / "logs" / "drive.blf").resolve())
    assert loaded.dbcs[1] == (str((moved / "body.dbc").resolve()), 2)
    assert (loaded.filter, loaded.channel, loaded.direction, loaded.errors, loaded.mode, loaded.time) == (
        "100-1FF engine", 2, "tx", False, "fixed", "absolute")
    assert loaded.signals == workspace.signals and loaded.cursors == (1.25, 3.5) and loaded.measure


@pytest.mark.parametrize(("content", "message"), [
    ("not json", "Cannot read"),
    ('{"format": "other"}', "not a CAN Toolbox workspace"),
    ('{"format": "can-toolbox-workspace", "version": 99}', "newer"),
    ('{"format": "can-toolbox-workspace", "version": 1, "graph": {"signals": [{"channel": 1}]}}', "invalid entry"),
])
def test_rejects_bad_files(tmp_path, content, message):
    path = tmp_path / "bad.cantoolbox.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(WorkspaceError, match=message):
        load_workspace(path)
