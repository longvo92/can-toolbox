"""The application window: a CANoe-style log viewer with dockable Trace and Graphics."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDockWidget,
    QLabel,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeWidgetItem,
    QWidget,
)

from can_toolbox.ui.logview.dialogs import (
    LOG_FILTER,
    LOG_SUFFIXES,
    WORKSPACE_FILTER,
    DbcDialog,
    ExportDialog,
)
from can_toolbox.ui.logview.panels import (
    SIGNAL_VALUE_COLUMNS,
    STATISTICS_COLUMNS,
    FilterBar,
    SignalBrowser,
    build_info_view,
    build_signal_values,
    build_statistics_table,
    build_trace_view,
    fill_statistics,
)
from can_toolbox.ui.logview.tasks import Task, load_view
from can_toolbox.ui.logview.trace import COLUMNS, TraceModel, number_text
from can_toolbox.ui.widgets import TextBinder

SETTINGS_PREFIX = "logview/"
STATE_VERSION = 1
BROWSER_WIDTH = 260
DETAIL_TABS = ("Signal Values", "Statistics", "Log Info")


class LogViewerWindow(QMainWindow):
    """Trace, graphics and signal browser around one open log.

    Tools that are not the viewer (DBC Compare, BLF → MAT) live in their own
    windows; see :class:`can_toolbox.ui.main_window.MainWindow`.
    """

    busy_changed = Signal(bool)

    def __init__(
        self,
        settings: QSettings,
        *,
        gui_language: str = "en",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._binder = TextBinder(gui_language)
        self.view = None
        self.worker: Task | None = None
        self.stats_worker: Task | None = None
        # Superseded statistics threads stay referenced until they finish; a
        # QThread destroyed while running aborts the process.
        self._retired: list[Task] = []
        self._stats_dirty = True
        self._loaded_summary: dict[str, str] = {}
        self._cursor_driving = False
        self.source = None
        self.last_export = None
        self._pending_workspace = None
        self._status: tuple[str, dict] = ("Open a BLF, ASC or MF4 log.", {})
        self._restored_layout = False
        self._laid_out = False
        self.log_path = settings.value(SETTINGS_PREFIX + "last_log", "", type=str)
        self.dbc_assignments: list[tuple[str, int]] = self._load_assignments()

        self.setWindowTitle("CAN Toolbox")
        self.resize(1280, 860)
        self.setMinimumSize(880, 600)
        self.setAcceptDrops(True)
        self._build_widgets()
        self._build_actions()
        self._build_docks()
        self._build_toolbars()
        self._build_status_bar()
        self._build_menus()
        self._build_extra_menus()
        self._wire_events()
        self._update_language()
        self._set_controls_enabled()
        self._restore_window_state()

    # -- construction --------------------------------------------------------------

    def _build_widgets(self) -> None:
        from can_toolbox.ui.graphics import GraphPanel

        self.model = TraceModel(self)
        self.trace = build_trace_view(self.model)
        self.signal_values = build_signal_values()
        self.statistics = build_statistics_table()
        self.info = build_info_view()
        self.details = QTabWidget()
        for widget in (self.signal_values, self.statistics, self.info):
            self.details.addTab(widget, "")
        self.graph = GraphPanel(self._binder)
        self.signal_browser = SignalBrowser(self._binder)
        self.filters = FilterBar(self._binder)
        # Graphics is the work surface every dock arranges itself around. Without a
        # real central widget Qt hands the leftover width to the dock areas, which
        # leaves dead space beside the panels.
        self.setCentralWidget(self.graph)

    def _build_actions(self) -> None:
        self.open_action = self._action("Open Log…", "Ctrl+O")
        self.reload_action = self._action("Reload", "F5")
        self.dbc_action = self._action("DBC Files…")
        self.export_action = self._action("Export…", "Ctrl+E")
        self.open_workspace_action = self._action("Open Workspace…")
        self.save_workspace_action = self._action("Save Workspace…", "Ctrl+S")
        self.quit_action = self._action("Quit", "Ctrl+Q")

    def _action(self, key: str, shortcut: str = "") -> QAction:
        action = QAction(self)
        self._binder.bind(action.setText, key)
        if shortcut:
            action.setShortcut(shortcut)
        return action

    def _dock(self, key: str, widget: QWidget, area, object_name: str) -> QDockWidget:
        dock = QDockWidget(self)
        dock.setObjectName(object_name)
        self._binder.bind(dock.setWindowTitle, key)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _build_docks(self) -> None:
        # The side columns own their corners, so the browser keeps the full height
        # while Graphics and Trace stack beside it.
        for corner in (Qt.Corner.TopLeftCorner, Qt.Corner.BottomLeftCorner):
            self.setCorner(corner, Qt.DockWidgetArea.LeftDockWidgetArea)
        for corner in (Qt.Corner.TopRightCorner, Qt.Corner.BottomRightCorner):
            self.setCorner(corner, Qt.DockWidgetArea.RightDockWidgetArea)
        self.browser_dock = self._dock("Signal Browser", self.signal_browser,
                                       Qt.DockWidgetArea.LeftDockWidgetArea, "signalBrowserDock")
        self.trace_dock = self._dock("Trace", self.trace, Qt.DockWidgetArea.BottomDockWidgetArea, "traceDock")
        self.details_dock = self._dock("Details", self.details, Qt.DockWidgetArea.BottomDockWidgetArea,
                                       "detailsDock")
        self.splitDockWidget(self.trace_dock, self.details_dock, Qt.Orientation.Horizontal)
        self._apply_default_dock_sizes()

    def _apply_default_dock_sizes(self) -> None:
        """Graphics keeps the centre; the browser is a narrow column, the trace wide.

        Dock sizes only stick once the window has a size of its own, so this runs
        again from :meth:`showEvent` unless a saved layout was restored.
        """
        # resizeDocks accepts docks of one area at a time.
        self.resizeDocks([self.browser_dock], [BROWSER_WIDTH], Qt.Orientation.Horizontal)
        self.resizeDocks([self.trace_dock, self.details_dock], [660, 340], Qt.Orientation.Horizontal)
        self.resizeDocks([self.trace_dock, self.details_dock], [320, 320], Qt.Orientation.Vertical)

    def _build_toolbars(self) -> None:
        self.toolbar = QToolBar(self)
        self.toolbar.setObjectName("mainToolBar")
        self._binder.bind(self.toolbar.setWindowTitle, "Main toolbar")
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for action in (self.open_action, self.reload_action, self.dbc_action, self.export_action):
            self.toolbar.addAction(action)
        self.toolbar.addSeparator()
        self.workspace_button = QToolButton(self.toolbar)
        self.workspace_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._binder.bind(self.workspace_button.setText, "Workspace")
        workspace_menu = QMenu(self.workspace_button)
        workspace_menu.addAction(self.open_workspace_action)
        workspace_menu.addAction(self.save_workspace_action)
        self.workspace_button.setMenu(workspace_menu)
        self.toolbar.addWidget(self.workspace_button)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)

        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.filter_toolbar = QToolBar(self)
        self.filter_toolbar.setObjectName("filterToolBar")
        self._binder.bind(self.filter_toolbar.setWindowTitle, "Filter bar")
        self.filter_toolbar.addWidget(self.filters)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.filter_toolbar)

    def _build_status_bar(self) -> None:
        self.status_label = QLabel()
        self.status_label.setObjectName("runStatus")
        self.file_label = QLabel()
        self.file_label.setObjectName("hintLabel")
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setMaximumWidth(220)
        self.progress.hide()
        self.cancel_button = self._binder.widget(QPushButton, "Cancel")
        self.cancel_button.hide()
        bar = self.statusBar()
        bar.addWidget(self.status_label, 1)
        bar.addPermanentWidget(self.file_label)
        bar.addPermanentWidget(self.progress)
        bar.addPermanentWidget(self.cancel_button)

    def _build_menus(self) -> None:
        self.file_menu = self.menuBar().addMenu("")
        self._binder.bind(self.file_menu.setTitle, "File")
        for action in (self.open_action, self.reload_action):
            self.file_menu.addAction(action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.dbc_action)
        self.file_menu.addSeparator()
        for action in (self.open_workspace_action, self.save_workspace_action):
            self.file_menu.addAction(action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.export_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.quit_action)

        self.view_menu = self.menuBar().addMenu("")
        self._binder.bind(self.view_menu.setTitle, "View")
        for dock, key in ((self.trace_dock, "Trace"), (self.browser_dock, "Signal Browser"),
                          (self.details_dock, "Details")):
            action = dock.toggleViewAction()
            self._binder.bind(action.setText, key)
            self.view_menu.addAction(action)
        self.view_menu.addSeparator()
        for bar, key in ((self.toolbar, "Main toolbar"), (self.filter_toolbar, "Filter bar")):
            action = bar.toggleViewAction()
            self._binder.bind(action.setText, key)
            self.view_menu.addAction(action)

    def _build_extra_menus(self) -> None:
        """Hook: menus the application shell appends after File and View."""

    def _update_extra_language(self) -> None:
        """Hook: retranslate what the application shell owns."""

    def _wire_events(self) -> None:
        self.open_action.triggered.connect(self._choose_log)
        self.reload_action.triggered.connect(lambda: self.open_log(self.log_path))
        self.dbc_action.triggered.connect(self._edit_dbcs)
        self.export_action.triggered.connect(self._export)
        self.open_workspace_action.triggered.connect(self._choose_workspace)
        self.save_workspace_action.triggered.connect(self._save_workspace_as)
        self.quit_action.triggered.connect(self.close)
        self.cancel_button.clicked.connect(self._cancel_load)
        self.filters.filter_changed.connect(self._apply_filter)
        self.filters.time_mode_changed.connect(self._apply_time_mode)
        self.filters.find_requested.connect(self._find)
        self.trace.selectionModel().currentRowChanged.connect(self._show_signals)
        self.trace.selectionModel().currentRowChanged.connect(self._trace_moved)
        self.details.currentChanged.connect(lambda _: self._refresh_statistics())
        self.signal_browser.plot_requested.connect(self.plot_signal)
        self.signal_browser.add_selected.connect(self._plot_selected)
        self.graph.signal_dropped.connect(self.plot_signal)
        self.graph.cursor_moved.connect(self._cursor_moved)

    # -- language ------------------------------------------------------------------

    def _tr(self, key: str, **parameters: object) -> str:
        return self._binder.tr(key, **parameters)

    @property
    def gui_language(self) -> str:
        return self._binder.language

    def set_gui_language(self, gui_language: str) -> None:
        self._binder.language = gui_language
        self._update_language()

    def _update_language(self) -> None:
        self._binder.set_language(self._binder.language)
        tr = self._tr
        self.filters.update_language()
        self.model.headers = [tr(column) for column in COLUMNS]
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(COLUMNS) - 1)
        self.signal_values.setHeaderLabels([tr(column) for column in SIGNAL_VALUE_COLUMNS])
        self.statistics.setHorizontalHeaderLabels([tr(column) for column in STATISTICS_COLUMNS])
        for index, key in enumerate(DETAIL_TABS):
            self.details.setTabText(index, tr(key))
        self._update_file_label()
        self.graph.set_languages()
        key, parameters = self._status
        self._set_status(key, **parameters)
        self._update_extra_language()

    # -- state ---------------------------------------------------------------------

    def is_busy(self) -> bool:
        return bool(self.worker and self.worker.isRunning())

    def stop_workers(self) -> None:
        for worker in (self.worker, self.stats_worker, *self._retired):
            if worker and worker.isRunning():
                worker.cancelled.set()
                worker.wait(5000)

    def wait_for_workers(self, timeout_ms: int = 5000) -> None:
        for worker in (self.worker, self.stats_worker, *self._retired):
            if worker:
                worker.wait(timeout_ms)

    def _set_status(self, key: str, **parameters: object) -> None:
        self._status = (key, parameters)
        self.status_label.setText(self._tr(key, **parameters))

    def _update_file_label(self) -> None:
        dbcs = len(self.dbc_assignments)
        name = Path(self.log_path).name if self.log_path else self._tr("No log loaded")
        self.file_label.setText(self._tr("{log}  ·  {count} DBC file(s)", log=name, count=dbcs))
        self.file_label.setToolTip(self.log_path)

    def _set_controls_enabled(self) -> None:
        loaded = self.view is not None
        busy = self.is_busy()
        self.open_action.setEnabled(not busy)
        self.reload_action.setEnabled(not busy and bool(self.log_path) and Path(self.log_path).is_file())
        self.dbc_action.setEnabled(not busy)
        self.export_action.setEnabled(loaded and not busy)
        self.open_workspace_action.setEnabled(not busy)
        self.save_workspace_action.setEnabled(loaded)
        self.workspace_button.setEnabled(not busy)
        self.filters.set_controls_enabled(loaded and not busy)
        self.signal_browser.set_controls_enabled(loaded and not busy)

    def _load_assignments(self) -> list[tuple[str, int]]:
        raw = self._settings.value(SETTINGS_PREFIX + "dbc_assignments", "[]", type=str)
        try:
            items = json.loads(raw)
            return [(str(path), int(channel)) for path, channel in items]
        except (ValueError, TypeError):
            return []

    def _save_assignments(self) -> None:
        self._settings.setValue(SETTINGS_PREFIX + "dbc_assignments", json.dumps(self.dbc_assignments))

    def _restore_window_state(self) -> None:
        geometry = self._settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self._settings.value("window/state")
        self._restored_layout = bool(state) and self.restoreState(state, STATE_VERSION)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._laid_out:
            self._laid_out = True
            if not self._restored_layout:
                self._apply_default_dock_sizes()

    def _save_window_state(self) -> None:
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState(STATE_VERSION))

    # -- loading -------------------------------------------------------------------

    def _choose_log(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        start = str(Path(self.log_path).parent) if self.log_path else ""
        path, _ = QFileDialog.getOpenFileName(self, self._tr("Open CAN log"), start, LOG_FILTER)
        if path:
            self.open_log(path)

    def _assignments(self):
        from can_toolbox.canlog.database import DbcAssignment

        return [DbcAssignment(Path(path), channel) for path, channel in self.dbc_assignments]

    def open_log(self, path: str) -> None:
        if self.is_busy() or not path:
            return
        self.log_path = str(Path(path))
        self._settings.setValue(SETTINGS_PREFIX + "last_log", self.log_path)
        self._update_file_label()
        assignments = self._assignments()
        log_path = Path(self.log_path)
        self.worker = Task(lambda task: load_view(log_path, assignments, task))
        self.worker.progress.connect(self.progress.setValue)
        self.worker.succeeded.connect(self._on_loaded)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_worker_finished)
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        self._set_status("Reading {name}…", name=log_path.name)
        self.worker.start()
        self.busy_changed.emit(True)
        self._set_controls_enabled()

    def _on_loaded(self, view) -> None:
        self.view = view
        frames = view.frames
        duration = (int(frames.time_ns[view.order[-1]]) - view.origin_ns) / 1e9 if len(frames) else 0.0
        self._loaded_summary = {"count": f"{len(frames):,}", "duration": f"{duration:.3f}"}
        self._populate_channels()
        self._stats_dirty = True
        self._apply_filter()
        self._show_info()
        self._reset_signals()
        if self._pending_workspace is not None:
            workspace, self._pending_workspace = self._pending_workspace, None
            self._apply_workspace(workspace)
        if view.log.warnings or view.database.errors:
            self.details.setCurrentWidget(self.info)

    def _on_failed(self, message: str) -> None:
        self._pending_workspace = None
        self._set_status("Could not open the log: {error}", error=message)

    def _on_worker_finished(self) -> None:
        self.progress.hide()
        self.cancel_button.hide()
        self.busy_changed.emit(False)
        self._set_controls_enabled()

    def _cancel_load(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancelled.set()
            self._set_status("Cancelled.")

    def _populate_channels(self) -> None:
        import numpy as np

        self.filters.populate_channels([channel for channel in np.unique(self.view.frames.channel) if channel])

    def _show_info(self) -> None:
        view = self.view
        frames = view.frames
        lines = [
            f"{self._tr('File')}: {view.log.path}",
            f"{self._tr('Format')}: {view.log.format}",
            f"{self._tr('Frames')}: {len(frames):,}",
            f"{self._tr('Memory')}: {frames.nbytes / 1e6:.1f} MB",
        ]
        if frames.start_time > 0:
            start = datetime.datetime.fromtimestamp(frames.start_time + view.origin_ns / 1e9)
            lines.append(f"{self._tr('Start')}: {start.isoformat(sep=' ', timespec='milliseconds')}")
        for assignment in view.database.assignments:
            scope = self._tr("All channels") if not assignment.channel else f"CAN {assignment.channel}"
            lines.append(f"DBC [{scope}]: {assignment.path}")
        lines += [f"[!] {warning}" for warning in view.log.warnings]
        lines += [f"[DBC] {error}" for error in view.database.errors]
        self.info.setPlainText("\n".join(lines))

    def _edit_dbcs(self) -> None:
        start = str(Path(self.dbc_assignments[-1][0]).parent) if self.dbc_assignments else ""
        dialog = DbcDialog(self, self.dbc_assignments, self._binder, start)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.dbc_assignments = dialog.assignments()
        finally:
            dialog.deleteLater()
        self._save_assignments()
        self._update_file_label()
        if self.view is not None:
            from can_toolbox.canlog.database import LogDatabase

            self.view.set_database(LogDatabase.load(self._assignments()))
            self._stats_dirty = True
            self._apply_filter()
            self._show_info()
            self._reset_signals()

    # -- export --------------------------------------------------------------------

    def _export(self) -> None:
        if self.view is None or self.is_busy():
            return
        view = self.view
        duration = (int(view.frames.time_ns[view.order[-1]]) - view.origin_ns) / 1e9 if len(view.order) else 0.0
        cursors = tuple(self.graph.cursor_time) if self.graph.measure_input.isChecked() and self.graph.series else None
        log_path = Path(self.log_path)
        default = self._settings.value(SETTINGS_PREFIX + "last_export", "", type=str)
        default = str(Path(default).parent / f"{log_path.stem}_cut{Path(default).suffix}") if default else \
            str(log_path.with_name(f"{log_path.stem}_cut.blf"))
        dialog = ExportDialog(self, self._binder, duration=duration, cursors=cursors,
                              filtered_count=len(view.rows), total_count=len(view.order), default_path=default)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            request, path = dialog.request, dialog.path
        finally:
            dialog.deleteLater()
        self.start_export(request, path)

    def start_export(self, request, path: Path) -> None:
        from can_toolbox.canlog.export import export_log

        view = self.view
        self._settings.setValue(SETTINGS_PREFIX + "last_export", str(path))
        self.worker = Task(lambda task: export_log(view, request, path, progress=task.report,
                                                   cancel=task.cancelled.is_set))
        self.worker.progress.connect(self.progress.setValue)
        self.worker.succeeded.connect(self._on_exported)
        self.worker.failed.connect(lambda message: self._set_status("Export failed: {error}", error=message))
        self.worker.finished.connect(self._on_worker_finished)
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        self._set_status("Exporting {name}…", name=path.name)
        self.worker.start()
        self.busy_changed.emit(True)
        self._set_controls_enabled()

    def _on_exported(self, result) -> None:
        self.last_export = result
        self._set_status("Exported {count} frames to {name}.", count=f"{result.frames:,}", name=result.path.name)
        if result.warnings:
            self.info.appendPlainText("\n".join(f"[!] {warning}" for warning in result.warnings))

    # -- workspace -----------------------------------------------------------------

    def current_workspace(self):
        from can_toolbox.canlog.workspace import Workspace

        return Workspace(
            log=self.log_path,
            dbcs=tuple(self.dbc_assignments),
            filter=self.filters.filter_input.text(),
            channel=int(self.filters.channel_input.currentData() or 0),
            direction=self.filters.direction_input.currentData(),
            errors=self.filters.errors_input.isChecked(),
            mode=self.filters.mode(),
            time=self.filters.time_mode(),
            signals=tuple(self.graph.refs()),
            cursors=tuple(self.graph.cursor_time),
            measure=self.graph.measure_input.isChecked(),
        )

    def _save_workspace_as(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from can_toolbox.canlog.workspace import SUFFIX

        start = self._settings.value(SETTINGS_PREFIX + "last_workspace", "", type=str)
        if not start and self.log_path:
            start = str(Path(self.log_path).with_name(Path(self.log_path).stem + SUFFIX))
        path, _ = QFileDialog.getSaveFileName(self, self._tr("Save Workspace…"), start, WORKSPACE_FILTER)
        if path:
            self.save_workspace(Path(path))

    def save_workspace(self, path: Path) -> None:
        from can_toolbox.canlog.workspace import SUFFIX, save_workspace

        if not path.name.endswith(SUFFIX):
            path = path.with_name(path.name.removesuffix(".json") + SUFFIX)
        try:
            save_workspace(path, self.current_workspace())
        except OSError as exc:
            self._set_status("Cannot save the workspace: {error}", error=exc)
            return
        self._settings.setValue(SETTINGS_PREFIX + "last_workspace", str(path))
        self._set_status("Workspace saved: {name}", name=path.name)

    def _choose_workspace(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        start = self._settings.value(SETTINGS_PREFIX + "last_workspace", "", type=str)
        path, _ = QFileDialog.getOpenFileName(self, self._tr("Open Workspace…"), start, WORKSPACE_FILTER)
        if path:
            self.open_workspace(Path(path))

    def open_workspace(self, path: Path) -> None:
        from can_toolbox.canlog.workspace import WorkspaceError, load_workspace

        if self.is_busy():
            return
        try:
            workspace = load_workspace(path)
        except WorkspaceError as exc:
            self._set_status("Cannot open the workspace: {error}", error=exc)
            return
        self._settings.setValue(SETTINGS_PREFIX + "last_workspace", str(path))
        self.dbc_assignments = list(workspace.dbcs)
        self._save_assignments()
        self.filters.restore_display_modes(workspace.mode, workspace.time)
        if not workspace.log or not Path(workspace.log).is_file():
            self._update_file_label()
            self._set_status("The workspace log was not found: {path}", path=workspace.log)
            return
        self._pending_workspace = workspace
        self.open_log(workspace.log)

    def _apply_workspace(self, workspace) -> None:
        """Restore trace settings and plots once the workspace log is loaded."""
        self.filters.restore_filters(workspace.filter, workspace.channel, workspace.direction, workspace.errors)
        self._apply_filter()
        self.graph.clear()
        missing = []
        for ref in workspace.signals:
            before = len(self.graph.series)
            self.plot_signal(ref, quiet=True)
            if len(self.graph.series) == before:
                missing.append(ref.signal)
        self.graph.restore_cursors(*workspace.cursors, workspace.measure)
        if missing:
            self._set_status("Workspace opened; not found in this log: {signals}", signals=", ".join(missing))

    # -- trace ---------------------------------------------------------------------

    def current_filter(self):
        return self.filters.current_filter()

    def _apply_filter(self, *_args) -> None:
        if self.view is None:
            return
        self.view.apply(self.filters.current_filter())
        fixed = self.filters.mode() == "fixed"
        self.model.set_rows(self.view, self.view.latest_per_message() if fixed else self.view.rows)
        self._stats_dirty = True
        self._refresh_statistics()
        shown = self.model.rowCount()
        if self._loaded_summary:
            self._set_status("{count} frames, {duration} s  ·  {shown} shown", shown=f"{shown:,}",
                             **self._loaded_summary)

    def _apply_time_mode(self, *_args) -> None:
        self.model.set_absolute_time(self.filters.time_mode() == "absolute")

    def _find(self, forward: bool) -> None:
        from can_toolbox.canlog.view import FrameQuery

        if self.view is None or self.filters.mode() == "fixed":
            return
        query = FrameQuery.parse(self.filters.find_input.text())
        current = self.trace.currentIndex().row() if self.trace.currentIndex().isValid() else -1
        position = self.view.find(query, current, forward)
        if position < 0:
            self._set_status("No frame matches {query}.", query=self.filters.find_input.text())
            return
        index = self.model.index(position, 0)
        self.trace.setCurrentIndex(index)
        self.trace.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _show_signals(self, current, _previous=None) -> None:
        from can_toolbox.canlog.database import decode_frame
        from can_toolbox.canlog.decode import frame_keys

        self.signal_values.clear()
        if self.view is None or not current.isValid():
            return
        row = self.model.frame_row(current.row())
        frames = self.view.frames
        key = int(frame_keys(frames.take([row]))[0])
        codec = self.view.database.codec(key, int(frames.channel[row])) if key >= 0 else None
        if codec is None:
            return
        for value in decode_frame(codec, frames.data(row)):
            physical = value.label if value.label is not None else number_text(value.physical)
            raw = value.raw
            raw_text = f"{raw} (0x{raw:X})" if isinstance(raw, int) and raw >= 0 else number_text(raw)
            item = QTreeWidgetItem([value.name, str(physical), raw_text, value.unit])
            self.signal_values.addTopLevelItem(item)
        for column in range(3):
            self.signal_values.resizeColumnToContents(column)

    def _refresh_statistics(self) -> None:
        if self.view is None or not self._stats_dirty or self.details.currentWidget() is not self.statistics:
            return
        if self.stats_worker and self.stats_worker.isRunning():
            old = self.stats_worker
            old.cancelled.set()
            self._retired.append(old)
            old.finished.connect(lambda: self._retired.remove(old) if old in self._retired else None)
        self._stats_dirty = False
        view = self.view
        self.stats_worker = Task(lambda _task: view.statistics())
        self.stats_worker.succeeded.connect(lambda stats: fill_statistics(self.statistics, stats))
        self.stats_worker.start()

    # -- graphics ------------------------------------------------------------------

    def _reset_signals(self) -> None:
        """Rebuild the signal list for the current log and DBCs; keep plots that still resolve."""
        from can_toolbox.canlog.signals import SignalSource

        self.source = SignalSource(self.view)
        self.signal_browser.populate(self.source.catalog())
        refs = self.graph.refs()
        self.graph.clear()
        for ref in refs:
            self.plot_signal(ref, quiet=True)

    def plot_signal(self, ref, quiet: bool = False) -> None:
        if self.view is None:
            return
        try:
            series = self.source.series(ref)
        except KeyError as exc:
            if not quiet:
                self._set_status("Cannot plot {signal}: {error}", signal=ref.signal, error=exc)
            return
        if not self.graph.add_series(series) and not quiet:
            self._set_status("{signal} is already plotted or the graph is full.", signal=ref.signal)

    def _plot_selected(self) -> None:
        for ref in self.signal_browser.selected_refs():
            self.plot_signal(ref)

    def _cursor_moved(self, seconds: float) -> None:
        """Graph cursor drives the trace: select the last frame at or before the cursor."""
        if self.view is None or self.filters.mode() == "fixed" or not self.model.rowCount():
            return
        position = self.view.position_at_time(self.view.origin_ns + int(round(seconds * 1e9)))
        self._cursor_driving = True
        try:
            index = self.model.index(position, 0)
            self.trace.setCurrentIndex(index)
            self.trace.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        finally:
            self._cursor_driving = False

    def _trace_moved(self, current, _previous=None) -> None:
        if self.view is None or not current.isValid() or self._cursor_driving:
            return
        row = self.model.frame_row(current.row())
        self.graph.set_cursor((int(self.view.frames.time_ns[row]) - self.view.origin_ns) / 1e9)

    # -- drag & drop ---------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        first = Path(urls[0].toLocalFile()) if urls else None
        if first and (first.suffix.lower() in LOG_SUFFIXES + (".dbc",) or first.name.endswith(".cantoolbox.json")):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        workspaces = [path for path in paths if path.name.endswith(".cantoolbox.json")]
        if workspaces:
            self.open_workspace(workspaces[0])
            event.acceptProposedAction()
            return
        dbcs = [str(path) for path in paths if path.suffix.lower() == ".dbc"]
        logs = [str(path) for path in paths if path.suffix.lower() in LOG_SUFFIXES]
        if dbcs:
            known = {path for path, _ in self.dbc_assignments}
            self.dbc_assignments += [(path, 0) for path in dbcs if path not in known]
            self._save_assignments()
            self._update_file_label()
        if logs:
            self.open_log(logs[0])
        elif dbcs and self.log_path and not self.is_busy():
            self.open_log(self.log_path)
        event.acceptProposedAction()

    # -- shutdown ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._save_window_state()
        if self.is_busy():
            self.stop_workers()
        event.accept()
