"""Graphics window for the Log Viewer: stacked signal plots with measurement cursors."""

from __future__ import annotations

import json
from collections.abc import Sequence

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QAction, QFontMetrics, QImage, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from can_toolbox.canlog.refs import SignalRef
from can_toolbox.ui import theme as app_theme
from can_toolbox.ui.widgets import TextBinder

SIGNAL_MIME = "application/x-can-toolbox-signal"
MAX_PLOTS = 16
# One lane: tall enough to read the curve, short enough to stack a few on screen.
PLOT_HEIGHT = 80
AXIS_WIDTH = 72
LINE_WIDTHS = (1, 2, 3, 4)
DEFAULT_LINE_WIDTH = 2
# The cursor lines keep their own width: a curve and a measurement line are read differently.
CURSOR_WIDTHS = (1, 2, 3, 4)
DEFAULT_CURSOR_WIDTH = 2
# Sample markers show only while neighbours sit at least this far apart on screen:
# denser, they merge into a bar that hides the curve and costs a lot to draw.
MIN_SAMPLE_SPACING_PX = 4


def step_path(times: np.ndarray, values: np.ndarray, gaps: np.ndarray):
    """Sample-and-hold path through the samples, with the holds over ``gaps`` left out.

    Returns ``(x, y, connect)``: point ``2 i`` is sample ``i`` and point ``2 i + 1``
    the end of its hold, so the hold of sample ``i`` is the segment from point
    ``2 i`` to ``2 i + 1``. ``connect`` is ``"all"`` when nothing is cut out.
    """
    x = np.repeat(times, 2)[1:]
    y = np.repeat(values, 2)[:-1]
    if not len(gaps):
        return x, y, "all"
    connect = np.ones(len(x), dtype=bool)
    connect[2 * gaps] = False
    return x, y, connect


def gap_path(times: np.ndarray, values: np.ndarray, gaps: np.ndarray):
    """The holds over ``gaps`` as separate segments: ``(x, y, connect)`` in pairs."""
    x = np.empty(2 * len(gaps))
    y = np.empty(2 * len(gaps))
    x[0::2], x[1::2] = times[gaps], times[gaps + 1]
    y[0::2] = y[1::2] = values[gaps]
    connect = np.zeros(len(x), dtype=bool)
    connect[0::2] = True
    return x, y, connect

pg.setConfigOptions(antialias=False)


def _as_payload(ref: SignalRef) -> dict:
    return {"channel": ref.channel, "key": ref.key, "message": ref.message, "signal": ref.signal}


def _as_ref(payload: dict) -> SignalRef:
    return SignalRef(int(payload["channel"]), int(payload["key"]), str(payload["message"]), str(payload["signal"]))


def refs_to_mime(refs) -> QMimeData:
    """Carry one or many signals; the payload is a list."""
    data = QMimeData()
    data.setData(SIGNAL_MIME, json.dumps([_as_payload(ref) for ref in refs]).encode())
    return data


def refs_from_mime(data: QMimeData) -> list[SignalRef]:
    """Read a dropped payload, list or the single object older versions sent."""
    if not data.hasFormat(SIGNAL_MIME):
        return []
    try:
        payload = json.loads(bytes(data.data(SIGNAL_MIME)).decode())
    except ValueError:
        return []
    items = payload if isinstance(payload, list) else [payload]
    try:
        return [_as_ref(item) for item in items]
    except (KeyError, TypeError, ValueError):
        return []


def ref_to_mime(ref: SignalRef) -> QMimeData:
    return refs_to_mime([ref])


def ref_from_mime(data: QMimeData) -> SignalRef | None:
    refs = refs_from_mime(data)
    return refs[0] if refs else None


class SignalTree(QTreeWidget):
    """Messages and signals that the log and DBCs provide; drag a signal onto the graph."""

    signal_activated = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.itemDoubleClicked.connect(self._activate)

    def populate(self, entries) -> None:
        from can_toolbox.canlog.view import format_key

        self.clear()
        for entry in entries:
            parent = QTreeWidgetItem([f"{entry.message}  [{format_key(entry.key)}, CAN {entry.channel}]"])
            parent.setToolTip(0, f"{entry.frames:,} frames")
            parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            parent.setData(0, Qt.ItemDataRole.UserRole + 1, (entry.channel, entry.message))
            for name in entry.signals:
                child = QTreeWidgetItem([name])
                child.setData(0, Qt.ItemDataRole.UserRole, SignalRef(entry.channel, entry.key, entry.message, name))
                parent.addChild(child)
            self.addTopLevelItem(parent)

    def apply_filter(self, text: str, *, channel=None, message=None) -> None:
        """Show the signals matching the search text, channel and message."""
        needle = text.strip().casefold()
        for index in range(self.topLevelItemCount()):
            parent = self.topLevelItem(index)
            owner = parent.data(0, Qt.ItemDataRole.UserRole + 1) or (None, None)
            if (channel is not None and owner[0] != channel) or (message is not None and owner[1] != message):
                parent.setHidden(True)
                continue
            parent_hit = needle in parent.text(0).casefold()
            visible = 0
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                hit = not needle or parent_hit or needle in child.text(0).casefold()
                child.setHidden(not hit)
                visible += hit
            parent.setHidden(visible == 0)
            parent.setExpanded((bool(needle) or message is not None) and visible > 0)

    def selected_refs(self) -> list[SignalRef]:
        return [ref for item in self.selectedItems() if (ref := item.data(0, Qt.ItemDataRole.UserRole))]

    def mimeData(self, items):
        refs = [item.data(0, Qt.ItemDataRole.UserRole) for item in items]
        refs = [ref for ref in refs if ref]
        return refs_to_mime(refs) if refs else QMimeData()

    def _activate(self, item, _column) -> None:
        ref = item.data(0, Qt.ItemDataRole.UserRole)
        if ref:
            self.signal_activated.emit(ref)


class _DropArea(pg.GraphicsLayoutWidget):
    dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(SIGNAL_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        refs = refs_from_mime(event.mimeData())
        if refs:
            self.dropped.emit(refs)
            event.acceptProposedAction()


class GraphPanel(QWidget):
    """Stacked plots, one per signal, sharing the time axis of the trace (seconds from the first frame)."""

    cursor_moved = Signal(float)
    signal_dropped = Signal(list)
    measuring_changed = Signal(bool)
    remove_requested = Signal()
    clear_requested = Signal()
    range_changed = Signal(float, float)
    cursors_changed = Signal()
    samples_toggled = Signal(bool)

    def __init__(self, binder: TextBinder, parent=None, *, actions: Sequence[QAction] = ()) -> None:
        super().__init__(parent)
        self._binder = binder
        self.series: list = []  # SignalSeries
        self._plots: list[pg.PlotItem] = []
        self._cursors: list[list[pg.InfiniteLine]] = [[], []]
        self.cursor_time = [0.0, 0.0]
        self._syncing = False
        self._measuring = False
        self._visible_cursors = [True, False]
        self._line_width = DEFAULT_LINE_WIDTH
        self._cursor_width = DEFAULT_CURSOR_WIDTH
        self.plotted: list = []  # (Entry, SignalSeries) pairs in display order
        self._focus = None
        # The lane the user last dragged a cursor in: the sample keys step through it
        # when the signal list has no single signal selected.
        self._dragged_ref = None
        self._show_samples = True
        self._markers: list = []  # one marker item (or None) per lane
        self._theme = app_theme.current_theme()
        app_theme.manager.changed.connect(self.apply_theme)

        self.canvas = _DropArea()
        self.canvas.setBackground(self._theme.plot_bg)
        self.canvas.dropped.connect(self.signal_dropped)
        self.canvas.ci.setSpacing(0)
        self.placeholder = QLabel()
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setObjectName("hintLabel")
        binder.bind(self.placeholder.setText,
                    "Double-click or drag signals from the list to plot them.")

        self.delta_label = QLabel()
        self.delta_label.setObjectName("hintLabel")
        self.toolbar = self._build_toolbar(actions)

        # Each plot keeps a readable height; many signals scroll instead of shrinking.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setWidget(self.canvas)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.placeholder)
        layout.addWidget(self.scroll, 1)

        self._update_language()
        self._show_canvas()

    # -- toolbar -------------------------------------------------------------------

    def _action(self, key: str, icon: str, slot) -> QAction:
        action = QAction(self)
        self._binder.bind(action.setText, key)
        self._binder.bind(action.setToolTip, key)
        action.setProperty("iconName", icon)
        action.setIcon(app_theme.icon(icon))
        action.triggered.connect(slot)
        return action

    def _build_toolbar(self, actions: Sequence[QAction]) -> QToolBar:
        """The graph's own strip: the window's fit/zoom/cursor actions plus ours."""
        window_actions = {action.property("iconName"): action for action in actions}
        toolbar = QToolBar(self)
        toolbar.setObjectName("graphToolBar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar.setIconSize(QSize(16, 16))

        fit = window_actions.get("fit")
        if fit is not None:
            self.fit_button = QToolButton(toolbar)
            self.fit_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            self.fit_button.setDefaultAction(fit)
            menu = QMenu(self.fit_button)
            for name in ("fit", "fit-x", "fit-y"):
                action = window_actions.get(name)
                if action is not None:
                    menu.addAction(action)
            self.fit_button.setMenu(menu)
            toolbar.addWidget(self.fit_button)
        for name in ("zoom-in", "zoom-out"):
            if (action := window_actions.get(name)) is not None:
                toolbar.addAction(action)
        toolbar.addSeparator()
        for name in ("cursor-1", "cursor-2"):
            if (action := window_actions.get(name)) is not None:
                toolbar.addAction(action)
        self.prev_change_action = self._action("Previous change", "prev-change",
                                               lambda: self.jump_to_change(forward=False))
        self.next_change_action = self._action("Next change", "next-change",
                                               lambda: self.jump_to_change(forward=True))
        toolbar.addAction(self.prev_change_action)
        toolbar.addAction(self.next_change_action)
        # Arrow keys walk cursor 1 sample by sample; no button, the keys are the point.
        self.prev_sample_action = self._action("Previous sample", "prev-change",
                                               lambda: self.step_sample(forward=False))
        self.next_sample_action = self._action("Next sample", "next-change",
                                               lambda: self.step_sample(forward=True))
        for action, key in ((self.prev_sample_action, Qt.Key.Key_Left),
                            (self.next_sample_action, Qt.Key.Key_Right)):
            action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.addAction(action)
        self.samples_action = self._action("Show samples", "samples", self.set_show_samples)
        self.samples_action.setCheckable(True)
        self.samples_action.setChecked(self._show_samples)
        toolbar.addAction(self.samples_action)
        toolbar.addSeparator()
        self.remove_action = self._action("Remove Plot", "remove-plot", self.remove_selected)
        self.clear_action = self._action("Clear Graph", "clear-graph", self.clear)
        toolbar.addAction(self.remove_action)
        toolbar.addAction(self.clear_action)
        toolbar.addSeparator()

        self.save_image_action = self._action("Save Image…", "image", self.save_image)
        self.copy_image_action = self._action("Copy Image", "image", self.copy_image)
        self.image_button = QToolButton(toolbar)
        self.image_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.image_button.setDefaultAction(self.save_image_action)
        image_menu = QMenu(self.image_button)
        image_menu.addAction(self.save_image_action)
        image_menu.addAction(self.copy_image_action)
        self.image_button.setMenu(image_menu)
        toolbar.addWidget(self.image_button)

        spacer = QWidget(toolbar)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addWidget(self.delta_label)
        return toolbar

    def _update_icons(self) -> None:
        for action in self.findChildren(QAction):
            name = action.property("iconName")
            if name:
                action.setIcon(app_theme.icon(str(name)))

    # -- public API ----------------------------------------------------------------

    def refs(self) -> list[SignalRef]:
        return [series.ref for series in self.series]

    def show_entries(self, plots) -> None:
        """Draw ``plots``: ``(entry, series)`` pairs, already in display order.

        At most :data:`MAX_PLOTS` lanes are drawn; the rest of the list stays in
        the signal panel, waiting to be made visible.
        """
        self.plotted = list(plots)[:MAX_PLOTS]
        self.series = [series for _entry, series in self.plotted]
        self._rebuild()

    def remove_selected(self) -> None:
        """The signal panel owns the list; it decides what 'remove' means."""
        self.remove_requested.emit()

    def clear(self) -> None:
        self.clear_requested.emit()

    @property
    def measuring(self) -> bool:
        """Whether the second cursor is shown, which is what measuring means here."""
        return self._measuring

    def set_measuring(self, enabled: bool) -> None:
        if enabled == self._measuring:
            return
        self._measuring = enabled
        self._visible_cursors[1] = enabled
        if enabled:
            # Switching a cursor on brings it to where the user is looking, not to t = 0.
            # Cursor 2 lands beside the middle so the two lines never hide each other.
            centre = self._view_centre()
            if centre is not None:
                low, high = self.x_range()
                self.cursor_time[1] = self._snap(centre + (high - low) / 10)
        for line in self._cursors[1]:
            line.setValue(self.cursor_time[1])
            line.setVisible(enabled)
        self._update_delta()
        self.measuring_changed.emit(enabled)

    def set_cursor_visible(self, cursor: int, visible: bool) -> None:
        """Show or hide a cursor line; showing it brings it to the middle of the view."""
        if cursor == 1:
            self.set_measuring(visible)
            return
        self._visible_cursors[cursor] = visible
        if visible:
            centre = self._view_centre()
            if centre is not None:
                centre = self._snap(centre)
                self.set_cursor(centre)
                self.cursor_moved.emit(centre)
        for line in self._cursors[cursor]:
            line.setVisible(visible)

    def _view_centre(self) -> float | None:
        """Middle of the time axis on screen, or ``None`` when nothing is plotted."""
        if not self._plots:
            return None
        low, high = self.x_range()
        return (low + high) / 2 if high > low else None

    def x_range(self) -> tuple[float, float]:
        if not self._plots:
            return (0.0, 0.0)
        low, high = self._plots[0].viewRange()[0]
        return (float(low), float(high))

    def fit_x(self, duration: float) -> None:
        """Show the whole log on the time axis, whatever the plotted signals cover."""
        if not self._plots or duration <= 0:
            return
        self._plots[0].setXRange(0.0, duration, padding=0.02)

    def fit_y(self) -> None:
        """Autoscale every plot over the time range on screen, sample-and-hold included."""
        low, high = self.x_range()
        if low == high:
            return
        for plot, series in zip(self._plots, self.series):
            times, values = series.time, series.values
            if not len(times):
                continue
            # The sample before the window is still on screen: it is held until the next one.
            start = max(int(np.searchsorted(times, low, side="right")) - 1, 0)
            stop = max(int(np.searchsorted(times, high, side="right")), start + 1)
            window = values[start:stop]
            if not len(window):
                continue
            bottom, top = float(np.min(window)), float(np.max(window))
            if bottom == top:
                margin = abs(bottom) * 0.1 or 0.5
                bottom, top = bottom - margin, top + margin
            plot.setYRange(bottom, top, padding=0.05)

    def fit(self, duration: float = 0.0) -> None:
        """Fit X then Y; without a duration the plotted signals decide the time axis."""
        if duration > 0:
            self.fit_x(duration)
        else:
            for plot in self._plots:
                plot.enableAutoRange(axis="x")
                plot.autoRange()
        self.fit_y()

    def zoom(self, factor: float) -> None:
        """Zoom the time axis around the main cursor, which stays where it is."""
        if not self._plots or factor <= 0:
            return
        low, high = self.x_range()
        span = (high - low) / factor
        centre = self.cursor_time[0]
        if not low <= centre <= high:
            centre = (low + high) / 2
        self._plots[0].setXRange(centre - span / 2, centre + span / 2, padding=0)

    def set_cursor(self, seconds: float) -> None:
        """Move the main cursor without echoing :attr:`cursor_moved`."""
        self._syncing = True
        try:
            self.cursor_time[0] = seconds
            for line in self._cursors[0]:
                line.setValue(seconds)
            self._update_delta()
        finally:
            self._syncing = False

    def restore_cursors(self, first: float, second: float, measure: bool) -> None:
        """Put both cursors and the measure mode back, e.g. from a workspace."""
        self._measuring = measure
        self._visible_cursors[1] = measure
        self.cursor_time[1] = second
        for line in self._cursors[1]:
            line.setValue(second)
            line.setVisible(measure)
        self.set_cursor(first)
        self.measuring_changed.emit(measure)

    def selected_series(self):
        """The series the change-jump buttons act on, set by the signal panel."""
        if self._focus is not None:
            return next((series for series in self.series if series.ref == self._focus), None)
        return self.series[0] if len(self.series) == 1 else None

    def set_focus_ref(self, ref) -> None:
        """The signal the panel has selected; the change-jump buttons follow it."""
        self._focus = ref

    def jump_to_change(self, *, forward: bool) -> bool:
        """Move cursor 1 to the next or previous value change of the chosen signal."""
        series = self.selected_series()
        if series is None:
            return False
        target = series.next_change(self.cursor_time[0], forward=forward)
        if target is None:
            return False
        self.set_cursor(target)
        self.cursor_moved.emit(target)
        return True

    def step_sample(self, *, forward: bool) -> bool:
        """Move cursor 1 to the next or previous sample of the signal being looked at."""
        series = self._stepping_series()
        if series is None:
            return False
        target = series.step_sample(self.cursor_time[0], forward=forward)
        if target is None:
            return False
        low, high = self.x_range()
        if high > low and not low <= target <= high:
            # Stepping off screen pans the view, so the cursor never walks out of sight.
            shift = target - (high if forward else low)
            self._plots[0].setXRange(low + shift, high + shift, padding=0)
        self.set_cursor(target)
        self.cursor_moved.emit(target)
        return True

    def show_samples(self) -> bool:
        return self._show_samples

    def set_show_samples(self, shown: bool) -> None:
        """Draw a marker on every sample, as long as the zoom leaves room for them."""
        shown = bool(shown)
        if self.samples_action.isChecked() != shown:
            self.samples_action.setChecked(shown)
        if shown == self._show_samples:
            return
        self._show_samples = shown
        self._update_markers()
        self.samples_toggled.emit(shown)

    def image(self) -> QImage:
        """The plots as they are on screen, at the canvas' own size."""
        return self.canvas.grab().toImage()

    def copy_image(self) -> None:
        if self.series:
            QApplication.clipboard().setImage(self.image())

    def save_image(self) -> None:
        if not self.series:
            return
        path, _ = QFileDialog.getSaveFileName(self, self._binder.tr("Save Image…"), "graph.png",
                                              self._binder.tr("PNG image (*.png)"))
        if path:
            self.image().save(path if path.lower().endswith(".png") else f"{path}.png", "PNG")

    def line_width(self) -> int:
        return self._line_width

    def set_line_width(self, width: int) -> None:
        """Curve thickness in pixels; applied to the plots right away."""
        width = min(max(int(width), LINE_WIDTHS[0]), LINE_WIDTHS[-1])
        if width == self._line_width:
            return
        self._line_width = width
        self._rebuild()

    def cursor_width(self) -> int:
        return self._cursor_width

    def set_cursor_width(self, width: int) -> None:
        """Cursor line thickness in pixels; a thicker line is also easier to grab."""
        width = min(max(int(width), CURSOR_WIDTHS[0]), CURSOR_WIDTHS[-1])
        if width == self._cursor_width:
            return
        self._cursor_width = width
        self._rebuild()

    def apply_theme(self, theme) -> None:
        """Repaint the plots in ``theme``: background, axes, curves and cursors."""
        self._theme = theme
        self.canvas.setBackground(theme.plot_bg)
        self._update_icons()
        self._rebuild()

    def set_languages(self) -> None:
        self._update_language()

    # -- internals -----------------------------------------------------------------

    def _update_language(self) -> None:
        self._update_delta()

    def _show_canvas(self) -> None:
        empty = not self.series
        self.placeholder.setVisible(empty)
        self.scroll.setVisible(not empty)
        self.canvas.setMinimumHeight(PLOT_HEIGHT * len(self.series) + 30)
        for action in (self.clear_action, self.remove_action, self.prev_change_action,
                       self.next_change_action, self.prev_sample_action, self.next_sample_action,
                       self.save_image_action, self.copy_image_action):
            action.setEnabled(not empty)

    def _rebuild(self) -> None:
        self.canvas.clear()
        self._plots = []
        self._cursors = [[], []]
        self._markers = []
        first = None
        theme = self._theme
        for index, (entry, series) in enumerate(self.plotted):
            # The colour belongs to the entry, so hiding a lane never recolours the rest.
            color = theme.curves[entry.color_index % len(theme.curves)]
            plot = self.canvas.addPlot(row=index, col=0)
            plot.showGrid(x=True, y=True, alpha=theme.grid_alpha)
            plot.setMenuEnabled(False)
            plot.hideButtons()
            # No title row: the lane is short, so the signal names the left axis.
            plot.setContentsMargins(0, 0, 0, 0)
            plot.layout.setContentsMargins(0, 0, 0, 0)
            left = plot.getAxis("left")
            left.setWidth(AXIS_WIDTH)
            for edge in ("left", "bottom"):
                axis = plot.getAxis(edge)
                axis.setTextPen(theme.plot_fg)
                axis.setPen(theme.plot_fg)
            self._label_lane(plot, series, color)
            if index:
                # A rule between lanes: stacked plots otherwise read as one grid.
                top = plot.getAxis("top")
                top.setPen(pg.mkPen(theme.grid_line, width=1))
                top.setStyle(showValues=False, tickLength=0)
                plot.showAxis("top")
            self._markers.append(self._add_curves(plot, series, color) if len(series.time) else None)
            if first is None:
                first = plot
                plot.sigXRangeChanged.connect(
                    lambda _item, bounds: self.range_changed.emit(float(bounds[0]), float(bounds[1]))
                )
                plot.sigXRangeChanged.connect(self._update_markers)
                plot.vb.sigResized.connect(self._update_markers)
            else:
                plot.setXLink(first)
            if index < len(self.plotted) - 1:
                plot.getAxis("bottom").setStyle(showValues=False)
            else:
                plot.setLabel("bottom", self._binder.tr("Time (s)"))
            for cursor, color_line in ((0, theme.cursor_primary), (1, theme.cursor_secondary)):
                line = pg.InfiniteLine(
                    pos=self.cursor_time[cursor], angle=90, movable=True,
                    pen=pg.mkPen(color_line, width=self._cursor_width),
                )
                line.setVisible(self._visible_cursors[cursor])
                line.sigPositionChanged.connect(lambda moved, c=cursor: self._cursor_dragged(c, moved))
                plot.addItem(line, ignoreBounds=True)
                self._cursors[cursor].append(line)
            self._plots.append(plot)
        self._update_delta()
        self._show_canvas()
        self._update_markers()

    def _add_curves(self, plot, series, color: str):
        """Sample-and-hold curve of ``series``; holds over missed samples are dashed.

        Returns the item that carries the sample markers, filled by
        :meth:`_update_markers` with what is on screen.
        """
        times, values = series.time, series.values
        gaps = series.gaps()
        x, y, connect = step_path(times, values, gaps)
        curve = pg.PlotDataItem(x, y, connect=connect, pen=pg.mkPen(color, width=self._line_width))
        # Clip and downsample only once the curve sits in its view box.
        plot.addItem(curve)
        curve.setClipToView(True)
        curve.setDownsampling(auto=True, method="peak")
        if len(gaps):
            x, y, connect = gap_path(times, values, gaps)
            dashed = pg.PlotDataItem(x, y, connect=connect, pen=pg.mkPen(
                color, width=self._line_width, style=Qt.PenStyle.DashLine))
            plot.addItem(dashed)
            dashed.setClipToView(True)
        markers = pg.PlotDataItem(pen=None, symbol="s", symbolSize=3 + 2 * self._line_width,
                                  symbolPen=None, symbolBrush=color)
        plot.addItem(markers)
        return markers

    def _update_markers(self, *_args) -> None:
        """Put the markers of the samples on screen, or none when they would crowd.

        Markers are filled from the visible slice only: a scatter of a whole
        long log is slow to build and unreadable anyway.
        """
        if not self._plots:
            return
        low, high = self.x_range()
        for plot, series, markers in zip(self._plots, self.series, self._markers):
            if markers is None:
                continue
            start = int(np.searchsorted(series.time, low, side="left"))
            stop = int(np.searchsorted(series.time, high, side="right"))
            width = float(plot.vb.width())
            if self._show_samples and stop > start and (stop - start) * MIN_SAMPLE_SPACING_PX <= width:
                markers.setData(series.time[start:stop], series.values[start:stop])
            else:
                markers.setData([], [])

    def _label_lane(self, plot, series, color: str) -> None:
        """Name the lane on its left axis, elided to the height it has.

        pyqtgraph rotates the left label by -90°, so the room for it is the
        lane height, not its width.
        """
        axis = plot.getAxis("left")
        metrics = QFontMetrics(axis.label.font())
        name = series.ref.signal
        text = metrics.elidedText(name, Qt.TextElideMode.ElideRight, PLOT_HEIGHT - 12)
        axis.setLabel(text, color=color)
        tooltip = f"{series.ref.label} [{series.unit}]" if series.unit else series.ref.label
        axis.setToolTip(tooltip)
        axis.label.setToolTip(tooltip)

    def _cursor_dragged(self, cursor: int, line) -> None:
        if self._syncing:
            return
        seconds = float(line.value())
        snap = getattr(line, "moving", False) and not (
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        if snap:
            # A drag lands on the nearest sample of the lane it happens in; Shift drags freely.
            lane = self._cursors[cursor].index(line)
            if lane < len(self.series):
                series = self.series[lane]
                self._dragged_ref = series.ref
                nearest = series.nearest_sample(seconds)
                if nearest is not None:
                    seconds = nearest
        self._syncing = True
        try:
            self.cursor_time[cursor] = seconds
            for other in self._cursors[cursor]:
                if other is not line or other.value() != seconds:
                    other.setValue(seconds)
        finally:
            self._syncing = False
        self._update_delta()
        if cursor == 0:
            self.cursor_moved.emit(seconds)

    def _stepping_series(self):
        """The signal the sample keys walk: the selected one, else the last dragged lane."""
        series = self.selected_series()
        if series is None and self._dragged_ref is not None:
            series = next((item for item in self.series if item.ref == self._dragged_ref), None)
        return series

    def _snap(self, seconds: float) -> float:
        """``seconds`` moved onto the nearest sample of the signal being looked at.

        A sample off screen is no snap target: the cursor stays where the user looks.
        """
        series = self._stepping_series() or next((item for item in self.series if len(item.time)), None)
        nearest = series.nearest_sample(seconds) if series is not None else None
        low, high = self.x_range()
        return nearest if nearest is not None and low <= nearest <= high else seconds

    def _update_delta(self) -> None:
        """Both cursors moved or changed state: repaint Δt and tell the panel."""
        first, second = self.cursor_time
        self.delta_label.setText(
            self._binder.tr("Δt = {delta} s", delta=f"{second - first:.6f}") if self._measuring else ""
        )
        self.cursors_changed.emit()
