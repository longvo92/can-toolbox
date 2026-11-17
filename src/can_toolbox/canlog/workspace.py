"""Log Viewer workspaces: the log, DBCs, trace settings and plotted signals in one JSON file (Qt-free)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from can_toolbox.canlog.refs import SignalRef

SUFFIX = ".cantoolbox.json"
FORMAT = "can-toolbox-workspace"
# 2: the graph keeps groups, per-signal visibility and colours.
VERSION = 2


class WorkspaceError(ValueError):
    """The file is not a readable workspace."""


@dataclass(frozen=True)
class PlottedSignal:
    """One signal in the graph list, with how it is shown."""

    ref: SignalRef
    visible: bool = True
    color: int | None = None


@dataclass(frozen=True)
class SignalGroup:
    name: str
    signals: tuple[PlottedSignal, ...] = ()
    expanded: bool = True


@dataclass(frozen=True)
class Workspace:
    log: str = ""
    dbcs: tuple[tuple[str, int], ...] = ()
    filter: str = ""
    channel: int = 0
    direction: str = "all"
    errors: bool = True
    mode: str = "chronological"
    time: str = "relative"
    signals: tuple[PlottedSignal, ...] = ()
    groups: tuple[SignalGroup, ...] = ()
    cursors: tuple[float, float] = (0.0, 0.0)
    measure: bool = False
    plot_mode: bool = False


def _signal_data(plotted: PlottedSignal) -> dict:
    data = {
        "channel": plotted.ref.channel,
        "id": plotted.ref.key,
        "message": plotted.ref.message,
        "signal": plotted.ref.signal,
        "visible": plotted.visible,
    }
    if plotted.color is not None:
        data["color"] = plotted.color
    return data


def _read_signal(item: dict) -> PlottedSignal:
    """Read one plotted signal; version 1 files have no visibility or colour."""
    ref = SignalRef(int(item["channel"]), int(item["id"]), str(item["message"]), str(item["signal"]))
    color = item.get("color")
    return PlottedSignal(ref, bool(item.get("visible", True)), None if color is None else int(color))


def _portable(path: str, base: Path) -> str:
    """Store paths relative to the workspace folder when they share a drive, so a project folder can move."""
    if not path:
        return ""
    try:
        return Path(os.path.relpath(Path(path).resolve(), base)).as_posix()
    except ValueError:  # different drive on Windows
        return str(Path(path))


def _resolve(path: str, base: Path) -> str:
    if not path:
        return ""
    candidate = Path(path)
    return str(candidate if candidate.is_absolute() else (base / candidate).resolve())


def save_workspace(path: Path, workspace: Workspace) -> Path:
    path = Path(path)
    base = path.resolve().parent
    data = {
        "format": FORMAT,
        "version": VERSION,
        "log": _portable(workspace.log, base),
        "dbcs": [{"path": _portable(dbc, base), "channel": channel} for dbc, channel in workspace.dbcs],
        "trace": {
            "filter": workspace.filter,
            "channel": workspace.channel,
            "direction": workspace.direction,
            "errors": workspace.errors,
            "mode": workspace.mode,
            "time": workspace.time,
        },
        "graph": {
            "groups": [
                {
                    "name": group.name,
                    "expanded": group.expanded,
                    "signals": [_signal_data(plotted) for plotted in group.signals],
                }
                for group in workspace.groups
            ],
            "signals": [_signal_data(plotted) for plotted in workspace.signals],
            "cursors": list(workspace.cursors),
            "measure": workspace.measure,
            "plot_mode": workspace.plot_mode,
        },
    }
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def load_workspace(path: Path) -> Workspace:
    path = Path(path)
    base = path.resolve().parent
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkspaceError(f"Cannot read workspace {path.name}: {exc}") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise WorkspaceError(f"{path.name} is not a CAN Toolbox workspace")
    if int(data.get("version", 0)) > VERSION:
        raise WorkspaceError(f"{path.name} was saved by a newer CAN Toolbox (version {data.get('version')})")
    try:
        trace = data.get("trace", {})
        graph = data.get("graph", {})
        cursors = [float(value) for value in graph.get("cursors", [0.0, 0.0])][:2]
        return Workspace(
            log=_resolve(str(data.get("log", "")), base),
            dbcs=tuple((_resolve(str(item["path"]), base), int(item.get("channel", 0))) for item in data.get("dbcs", [])),
            filter=str(trace.get("filter", "")),
            channel=int(trace.get("channel", 0)),
            direction=str(trace.get("direction", "all")),
            errors=bool(trace.get("errors", True)),
            mode=str(trace.get("mode", "chronological")),
            time=str(trace.get("time", "relative")),
            signals=tuple(_read_signal(item) for item in graph.get("signals", [])),
            groups=tuple(
                SignalGroup(
                    name=str(item.get("name", "")),
                    signals=tuple(_read_signal(entry) for entry in item.get("signals", [])),
                    expanded=bool(item.get("expanded", True)),
                )
                for item in graph.get("groups", [])
            ),
            cursors=tuple((cursors + [0.0, 0.0])[:2]),
            measure=bool(graph.get("measure", False)),
            plot_mode=bool(graph.get("plot_mode", False)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkspaceError(f"Workspace {path.name} has an invalid entry: {exc}") from exc
