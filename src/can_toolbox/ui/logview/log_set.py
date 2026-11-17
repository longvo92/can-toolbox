"""The logs the viewer has open, and which of them the window is showing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal


@dataclass(eq=False)
class LogEntry:
    """One open log: its frames, the signals decoded from it and what it costs."""

    path: str
    view: object  # LogView
    source: object | None = None  # SignalSource, created on first use
    series: dict = field(default_factory=dict)  # SignalRef -> SignalSeries | None

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def frames(self) -> int:
        return len(self.view.frames)

    @property
    def duration(self) -> float:
        view = self.view
        if not len(view.order):
            return 0.0
        return (int(view.frames.time_ns[view.order[-1]]) - view.origin_ns) / 1e9

    def channels(self) -> list[int]:
        import numpy as np

        return [int(channel) for channel in np.unique(self.view.frames.channel) if channel]

    def signal_source(self):
        """Decode signals of this log; one source per log, kept for its lifetime."""
        if self.source is None:
            from can_toolbox.canlog.signals import SignalSource

            self.source = SignalSource(self.view)
        return self.source

    def set_view(self, view) -> None:
        """Replace the frames, e.g. after a reload or a DBC change."""
        self.view = view
        self.source = None
        self.series.clear()

    def forget_signals(self) -> None:
        self.source = None
        self.series.clear()


class LogSet(QObject):
    """Every open log, in the order they were opened, and the active one.

    ``changed`` fires when the list changes, ``active_changed`` when the window
    should show a different log.
    """

    changed = Signal()
    active_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.entries: list[LogEntry] = []
        self._active: LogEntry | None = None

    # -- reading -------------------------------------------------------------------

    @property
    def active(self) -> LogEntry | None:
        return self._active

    def paths(self) -> list[str]:
        return [entry.path for entry in self.entries]

    def find(self, path: str) -> LogEntry | None:
        wanted = str(Path(path))
        return next((entry for entry in self.entries if str(Path(entry.path)) == wanted), None)

    def index_of(self, entry: LogEntry) -> int:
        return self.entries.index(entry)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    # -- editing -------------------------------------------------------------------

    def add(self, path: str, view) -> LogEntry:
        """Add a log, or replace the frames of one that is already open."""
        entry = self.find(path)
        if entry is not None:
            entry.set_view(view)
        else:
            entry = LogEntry(str(Path(path)), view)
            self.entries.append(entry)
        self.changed.emit()
        self.set_active(entry)
        return entry

    def close(self, entries) -> None:
        wanted = set(entries)
        if not wanted:
            return
        remaining = [entry for entry in self.entries if entry not in wanted]
        if len(remaining) == len(self.entries):
            return
        active = self._active
        self.entries = remaining
        self.changed.emit()
        if active in wanted:
            self.set_active(self.entries[-1] if self.entries else None)

    def clear(self) -> None:
        if not self.entries:
            return
        self.entries = []
        self.changed.emit()
        self.set_active(None)

    def set_active(self, entry: LogEntry | None) -> None:
        if entry is not None and entry not in self.entries:
            return
        if entry is self._active:
            return
        self._active = entry
        self.active_changed.emit()

    def set_database(self, database) -> None:
        """One database for every log; each view decodes its own frames with it."""
        for entry in self.entries:
            entry.view.set_database(database)
            entry.forget_signals()
        self.changed.emit()
