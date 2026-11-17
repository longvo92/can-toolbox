"""Background work for the log viewer: one thread per load, export or statistics run."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal


class Task(QThread):
    """Run one callable off the GUI thread; ``progress`` receives a 0-1000 fraction."""

    progress = Signal(int)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, work: Callable[[Task], Any]) -> None:
        super().__init__()
        self._work = work
        self.cancelled = threading.Event()

    def report(self, done: int, total: int) -> None:
        self.progress.emit(int(1000 * done / total) if total else 0)

    def run(self) -> None:
        try:
            result = self._work(self)
        except Exception as exc:  # surfaced in the window, never swallowed
            if not self.cancelled.is_set():
                self.failed.emit(str(exc) or type(exc).__name__)
            return
        if not self.cancelled.is_set():
            self.succeeded.emit(result)


def load_view(path: Path, assignments, task: Task | None = None):
    """Read a log, sort it and attach DBCs: everything the trace needs (Qt-free work)."""
    from can_toolbox.canlog import open_log
    from can_toolbox.canlog.database import LogDatabase
    from can_toolbox.canlog.view import LogView

    log = open_log(
        path,
        progress=task.report if task else None,
        cancel=task.cancelled.is_set if task else None,
    )
    return LogView(log, LogDatabase.load(assignments))
