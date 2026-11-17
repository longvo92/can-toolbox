"""Workspace files: round trip, portable paths and rejection of foreign or newer files."""

from __future__ import annotations

import json

import pytest

from can_toolbox.canlog.refs import SignalRef
from can_toolbox.canlog.workspace import (
    PlottedSignal,
    SignalGroup,
    Workspace,
    WorkspaceError,
    load_workspace,
    save_workspace,
)


def test_round_trip_with_paths_relative_to_the_workspace(tmp_path):
    project = tmp_path / "project"
    (project / "logs").mkdir(parents=True)
    log = project / "logs" / "drive.blf"
    dbc = project / "pt.dbc"
    workspace = Workspace(
        log=str(log), dbcs=((str(dbc), 0), (str(project / "body.dbc"), 2)), filter="100-1FF engine",
        channel=2, direction="tx", errors=False, mode="fixed", time="absolute",
        signals=(PlottedSignal(SignalRef(2, 0x98FF0001, "Diag", "Code"), visible=False, color=3),),
        groups=(SignalGroup("Powertrain", (PlottedSignal(SignalRef(1, 0x100, "Engine", "Rpm"), color=0),),
                            expanded=False),),
        cursors=(1.25, 3.5), measure=True, plot_mode=True,
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
    assert loaded.signals == workspace.signals and loaded.groups == workspace.groups
    assert loaded.cursors == (1.25, 3.5) and loaded.measure and loaded.plot_mode


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


def test_version_1_signals_load_as_visible_root_entries(tmp_path):
    """A workspace saved before groups existed still opens, with everything shown."""
    path = tmp_path / "old.cantoolbox.json"
    path.write_text(json.dumps({
        "format": "can-toolbox-workspace",
        "version": 1,
        "log": "drive.blf",
        "dbcs": [{"path": "pt.dbc", "channel": 0}],
        "trace": {"filter": "engine"},
        "graph": {
            "signals": [{"channel": 1, "id": 256, "message": "Engine", "signal": "Rpm"}],
            "cursors": [0.5, 1.5],
            "measure": True,
        },
    }), encoding="utf-8")
    loaded = load_workspace(path)
    assert loaded.groups == ()
    assert loaded.signals == (PlottedSignal(SignalRef(1, 256, "Engine", "Rpm"), visible=True, color=None),)
    assert loaded.cursors == (0.5, 1.5) and loaded.measure and not loaded.plot_mode
