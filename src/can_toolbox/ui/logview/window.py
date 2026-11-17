"""The application window: a CANoe-style log viewer with dockable Trace and Graphics."""

from __future__ import annotations

import datetime
import json
from functools import partial
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
    QToolBar,
    QTreeWidgetItem,
    QWidget,
)

from can_toolbox.ui.logview.dialogs import LOG_FILTER, LOG_SUFFIXES, WORKSPACE_FILTER, DbcDialog
from can_toolbox.ui.logview.export_dialog import ExportDialog
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
from can_toolbox.ui.theme import icon as themed_icon
from can_toolbox.ui.theme import manager as theme_manager
from can_toolbox.ui.widgets import TextBinder

SETTINGS_PREFIX = "logview/"
# 3: the main toolbar was removed, so a layout saved with it must not be restored.
STATE_VERSION = 3
BROWSER_WIDTH = 260
ZOOM_STEP = 1.6
RECENT_LOGS = 8


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
        self._engine_log: list[str] = []
        self._status: tuple[str, dict] = ("Open a BLF, ASC or MF4 log.", {})
        self._restored_layout = False
        self._laid_out = False
        self.log_path = settings.value(SETTINGS_PREFIX + "last_log", "", type=str)
        self.dbc_assignments: list[tuple[str, int]] = self._load_assignments()

        self.setWindowTitle("CAN Toolbox")
        self.resize(1280, 860)
        self.setMinimumSize(880, 600)
        self.setAcceptDrops(True)
        self._build_actions()
        self._build_widgets()
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
        from can_toolbox.ui.settings_dialog import line_width

        self.graph = GraphPanel(self._binder, actions=self.graph_actions)
        self.graph.set_line_width(line_width(self._settings))
        self.signal_browser = SignalBrowser(self._binder)
        self.filters = FilterBar(self._binder)
        # Graphics is the work surface every dock arranges itself around. Without a
        # real central widget Qt hands the leftover width to the dock areas, which
        # leaves dead space beside the panels.
        self.setCentralWidget(self.graph)

    def _build_actions(self) -> None:
        self.open_action = self._action("Open Log…", "Ctrl+O", icon="open")
        self.reload_action = self._action("Reload", "F5", icon="reload")
        self.dbc_action = self._action("DBC Files…", icon="dbc")
        self.export_action = self._action("Export…", "Ctrl+E", icon="export")
        self.open_workspace_action = self._action("Open Workspace…")
        self.save_workspace_action = self._action("Save Workspace…", "Ctrl+S")
        self.quit_action = self._action("Quit", "Ctrl+Q")
        self.fit_action = self._action("Fit", "Ctrl+0", icon="fit")
        self.fit_x_action = self._action("Fit X", "Ctrl+Shift+X", icon="fit-x")
        self.fit_y_action = self._action("Fit Y", "Ctrl+Shift+Y", icon="fit-y")
        self.zoom_in_action = self._action("Zoom In", "Ctrl++", icon="zoom-in")
        self.zoom_out_action = self._action("Zoom Out", "Ctrl+-", icon="zoom-out")
        self.cursor1_action = self._action("Cursor 1", icon="cursor-1", checkable=True)
        self.cursor1_action.setChecked(True)
        self.cursor2_action = self._action("Cursor 2", icon="cursor-2", checkable=True)
        self.statistics_action = self._action("Statistics", icon="statistics")
        self.info_action = self._action("Log Info", icon="info")
        self.signal_search_action = self._action("Signal search…", icon="search")
        self.signal_values_action = self._action("Signal Values")
        self.graph_actions = (self.fit_action, self.fit_x_action, self.fit_y_action,
                              self.zoom_in_action, self.zoom_out_action,
                              self.cursor1_action, self.cursor2_action)

    def _action(self, key: str, shortcut: str = "", *, icon: str = "", checkable: bool = False) -> QAction:
        action = QAction(self)
        self._binder.bind(action.setText, key)
        self._binder.bind(action.setToolTip, key)
        if shortcut:
            action.setShortcut(shortcut)
        if icon:
            action.setProperty("iconName", icon)
            action.setIcon(themed_icon(icon))
        action.setCheckable(checkable)
        return action

    def _update_icons(self) -> None:
        """Re-tint every toolbar icon after a theme change."""
        for action in self.findChildren(QAction):
            name = action.property("iconName")
            if name:
                action.setIcon(themed_icon(str(name)))

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
        self.values_dock = self._dock("Signal Values", self.signal_values,
                                      Qt.DockWidgetArea.BottomDockWidgetArea, "signalValuesDock")
        self.statistics_dock = self._dock("Statistics", self.statistics,
                                          Qt.DockWidgetArea.BottomDockWidgetArea, "statisticsDock")
        self.info_dock = self._dock("Log Info", self.info, Qt.DockWidgetArea.BottomDockWidgetArea, "logInfoDock")
        for dock in (self.values_dock, self.statistics_dock, self.info_dock):
            self.splitDockWidget(self.trace_dock, dock, Qt.Orientation.Horizontal)
        # A minimal first screen: toolbar, Graphics and Trace. Everything else is
        # one click away in View, or from the trace's own context menu.
        self.panel_docks = (self.values_dock, self.statistics_dock, self.info_dock)
        for dock in (*self.panel_docks, self.browser_dock):
            dock.hide()
        self._apply_default_dock_sizes()

    def _apply_default_dock_sizes(self) -> None:
        """Graphics keeps the centre; the browser is a narrow column, the trace wide.

        Dock sizes only stick once the window has a size of its own, so this runs
        again from :meth:`showEvent` unless a saved layout was restored.
        """
        # resizeDocks accepts docks of one area at a time.
        self.resizeDocks([self.browser_dock], [BROWSER_WIDTH], Qt.Orientation.Horizontal)
        self.resizeDocks([self.trace_dock, *self.panel_docks], [660, 340, 340, 340],
                         Qt.Orientation.Horizontal)
        self.resizeDocks([self.trace_dock], [320], Qt.Orientation.Vertical)

    def _build_toolbars(self) -> None:
        """Only the filter bar; the log actions live in File, the graph ones on its toolbar."""
        self.filter_toolbar = QToolBar(self)
        self.filter_toolbar.setObjectName("filterToolBar")
        self._binder.bind(self.filter_toolbar.setWindowTitle, "Filter bar")
        self.filter_toolbar.addWidget(self.filters)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.filter_toolbar)
        self.filter_toolbar.hide()

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
        self.recent_menu = QMenu(self.file_menu)
        self._binder.bind(self.recent_menu.setTitle, "Recent Logs")
        self.file_menu.addMenu(self.recent_menu)
        self._fill_recent_menu()
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
                          (self.values_dock, "Signal Values"), (self.statistics_dock, "Statistics"),
                          (self.info_dock, "Log Info")):
            action = dock.toggleViewAction()
            self._binder.bind(action.setText, key)
            self.view_menu.addAction(action)
        self.view_menu.addSeparator()
        for action in self.graph_actions:
            self.view_menu.addAction(action)
        self.view_menu.addSeparator()
        filter_action = self.filter_toolbar.toggleViewAction()
        self._binder.bind(filter_action.setText, "Filter bar")
        self.view_menu.addAction(filter_action)

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
        self.trace.customContextMenuRequested.connect(self._show_trace_menu)
        self.statistics_dock.visibilityChanged.connect(lambda _visible: self._refresh_statistics())
        self.signal_browser.plot_requested.connect(self.plot_signal)
        self.signal_browser.add_selected.connect(self._plot_selected)
        self.graph.signal_dropped.connect(self.plot_signal)
        self.graph.cursor_moved.connect(self._cursor_moved)
        self.graph.measuring_changed.connect(self._measuring_changed)
        self.fit_action.triggered.connect(lambda: self.graph.fit(self.duration()))
        self.fit_x_action.triggered.connect(lambda: self.graph.fit_x(self.duration()))
        self.fit_y_action.triggered.connect(self.graph.fit_y)
        self.zoom_in_action.triggered.connect(lambda: self.graph.zoom(ZOOM_STEP))
        self.zoom_out_action.triggered.connect(lambda: self.graph.zoom(1 / ZOOM_STEP))
        self.cursor1_action.toggled.connect(lambda shown: self.graph.set_cursor_visible(0, shown))
        self.cursor2_action.toggled.connect(self.graph.set_measuring)
        self.statistics_action.triggered.connect(lambda: self.open_panel(self.statistics_dock))
        self.info_action.triggered.connect(lambda: self.open_panel(self.info_dock))
        self.signal_values_action.triggered.connect(lambda: self.open_panel(self.values_dock))
        self.signal_search_action.triggered.connect(self._open_signal_search)
        theme_manager.changed.connect(lambda _theme: self._update_icons())

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
        self.save_workspace_action.setEnabled(loaded and not busy)
        self.filters.set_controls_enabled(loaded and not busy)
        self.signal_browser.set_controls_enabled(loaded and not busy)
        for action in self.graph_actions:
            action.setEnabled(loaded and not busy)
        for action in (self.statistics_action, self.info_action, self.signal_values_action,
                       self.signal_search_action):
            action.setEnabled(loaded and not busy)

    # -- recent logs ---------------------------------------------------------------

    def recent_logs(self) -> list[str]:
        """The last logs that were opened, newest first; missing files are dropped."""
        raw = self._settings.value(SETTINGS_PREFIX + "recent", "[]", type=str)
        try:
            paths = [str(path) for path in json.loads(raw)]
        except (ValueError, TypeError):
            return []
        return [path for path in paths if Path(path).is_file()][:RECENT_LOGS]

    def _remember_log(self, path: str) -> None:
        recent = [path] + [other for other in self.recent_logs() if other != path]
        self._settings.setValue(SETTINGS_PREFIX + "recent", json.dumps(recent[:RECENT_LOGS]))
        self._fill_recent_menu()

    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        recent = self.recent_logs()
        self.recent_menu.setEnabled(bool(recent))
        for path in recent:
            action = self.recent_menu.addAction(Path(path).name)
            action.setToolTip(path)
            action.triggered.connect(partial(self.open_log, path))

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

    def open_panel(self, dock: QDockWidget) -> QDockWidget:
        """Statistics, Log Info and Signal Values open as their own window.

        A panel the user has docked stays docked; only a hidden one floats.
        """
        if dock.isHidden():
            if not dock.property("openedBefore"):
                # First time: a panel the user has never placed opens as a window.
                dock.setFloating(True)
                dock.resize(640, 360)
                dock.move(self.geometry().center() - dock.rect().center())
            dock.setProperty("openedBefore", True)
            dock.show()
        dock.raise_()
        dock.activateWindow()
        return dock

    def _open_signal_search(self) -> None:
        self.open_panel(self.browser_dock)
        self.signal_browser.search_input.setFocus()

    def _show_trace_menu(self, point) -> None:
        index = self.trace.indexAt(point)
        menu = QMenu(self)
        tr = self._tr
        plot_action = menu.addAction(tr("Plot signals of this message"))
        cursor_action = menu.addAction(tr("Set cursor here"))
        plot_action.setEnabled(index.isValid() and self.source is not None)
        cursor_action.setEnabled(index.isValid())
        menu.addSeparator()
        for action in (self.signal_values_action, self.statistics_action, self.info_action,
                       self.signal_search_action):
            menu.addAction(action)
        chosen = menu.exec(self.trace.viewport().mapToGlobal(point))
        if chosen is plot_action:
            self._plot_message(index)
        elif chosen is cursor_action:
            self.trace.setCurrentIndex(index)

    def _plot_message(self, index) -> None:
        """Plot every signal of the message under the cursor, as CANoe's trace does."""
        from can_toolbox.canlog.decode import frame_keys
        from can_toolbox.canlog.refs import SignalRef

        if self.source is None or not index.isValid():
            return
        row = self.model.frame_row(index.row())
        frames = self.view.frames
        key = int(frame_keys(frames.take([row]))[0])
        channel = int(frames.channel[row])
        for entry in self.source.catalog():
            if entry.key == key and entry.channel == channel:
                for name in entry.signals:
                    self.plot_signal(SignalRef(channel, key, entry.message, name), quiet=True)
                return
        self._set_status("No DBC message for this frame.")

    def duration(self) -> float:
        """Seconds from the first frame to the last, 0 without a log."""
        view = self.view
        if view is None or not len(view.order):
            return 0.0
        return (int(view.frames.time_ns[view.order[-1]]) - view.origin_ns) / 1e9

    def _measuring_changed(self, enabled: bool) -> None:
        self.cursor2_action.blockSignals(True)
        self.cursor2_action.setChecked(enabled)
        self.cursor2_action.blockSignals(False)

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
        self._remember_log(self.log_path)
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
        self._loaded_summary = {"count": f"{len(frames):,}", "duration": f"{self.duration():.3f}"}
        self._populate_channels()
        self._stats_dirty = True
        self._apply_filter()
        self._show_info()
        self._reset_signals()
        if self._pending_workspace is not None:
            workspace, self._pending_workspace = self._pending_workspace, None
            self._apply_workspace(workspace)
        if view.log.warnings or view.database.errors:
            self.open_panel(self.info_dock)

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
        log_path = Path(self.log_path)
        folder = self._settings.value(SETTINGS_PREFIX + "export_folder", "", type=str)
        dialog = ExportDialog(
            self, self._binder, settings=self._settings, duration=self.duration(),
            cursors=tuple(self.graph.cursor_time) if self.graph.measuring and self.graph.series else None,
            filtered_count=len(view.rows), total_count=len(view.order),
            folder=folder or str(log_path.parent), base_name=f"{log_path.stem}_cut",
            dbc_paths=tuple((Path(path), int(channel)) for path, channel in self.dbc_assignments),
        )
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            job = dialog.job
        finally:
            dialog.deleteLater()
        self.start_export(job)

    def start_export(self, job) -> None:
        """Run one export job off the GUI thread; the engine log goes to Log Info."""
        from can_toolbox.canlog.export import run_export

        view = self.view
        self.worker = Task(lambda task: run_export(
            view, job, progress=task.report, cancel=task.cancelled.is_set,
            log_callback=self._engine_log.append,
        ))
        self._engine_log = []
        self.worker.progress.connect(self.progress.setValue)
        self.worker.succeeded.connect(self._on_exported)
        self.worker.failed.connect(lambda message: self._set_status("Export failed: {error}", error=message))
        self.worker.finished.connect(self._on_worker_finished)
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        self._set_status("Exporting {name}…", name=job.base_name)
        self.worker.start()
        self.busy_changed.emit(True)
        self._set_controls_enabled()

    def _on_exported(self, result) -> None:
        self.last_export = result
        self._set_status("Exported {count} frames to {count_files} file(s).",
                         count=f"{result.frames:,}", count_files=len(result.files))
        lines = [*self._engine_log, *(f"[!] {warning}" for warning in result.warnings)]
        if lines:
            self.info.appendPlainText("\n".join(str(line) for line in lines))

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
            measure=self.graph.measuring,
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
        if self.view is None or not self._stats_dirty or not self.statistics_dock.isVisible():
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
