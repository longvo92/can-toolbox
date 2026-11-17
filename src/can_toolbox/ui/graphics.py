"""Graphics window for the Log Viewer: stacked signal plots with measurement cursors."""

from __future__ import annotations

import json

import pyqtgraph as pg
from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
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
PLOT_HEIGHT = 110

pg.setConfigOptions(antialias=False)


def ref_to_mime(ref: SignalRef) -> QMimeData:
    data = QMimeData()
    payload = {"channel": ref.channel, "key": ref.key, "message": ref.message, "signal": ref.signal}
    data.setData(SIGNAL_MIME, json.dumps(payload).encode())
    return data


def ref_from_mime(data: QMimeData) -> SignalRef | None:
    if not data.hasFormat(SIGNAL_MIME):
        return None
    payload = json.loads(bytes(data.data(SIGNAL_MIME)).decode())
    return SignalRef(int(payload["channel"]), int(payload["key"]), payload["message"], payload["signal"])


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
            for name in entry.signals:
                child = QTreeWidgetItem([name])
                child.setData(0, Qt.ItemDataRole.UserRole, SignalRef(entry.channel, entry.key, entry.message, name))
                parent.addChild(child)
            self.addTopLevelItem(parent)

    def apply_filter(self, text: str) -> None:
        needle = text.strip().casefold()
        for index in range(self.topLevelItemCount()):
            parent = self.topLevelItem(index)
            parent_hit = needle in parent.text(0).casefold()
            visible = 0
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                hit = not needle or parent_hit or needle in child.text(0).casefold()
                child.setHidden(not hit)
                visible += hit
            parent.setHidden(visible == 0)
            parent.setExpanded(bool(needle) and visible > 0)

    def selected_refs(self) -> list[SignalRef]:
        return [ref for item in self.selectedItems() if (ref := item.data(0, Qt.ItemDataRole.UserRole))]

    def mimeData(self, items):
        refs = [item.data(0, Qt.ItemDataRole.UserRole) for item in items]
        refs = [ref for ref in refs if ref]
        return ref_to_mime(refs[0]) if refs else QMimeData()

    def _activate(self, item, _column) -> None:
        ref = item.data(0, Qt.ItemDataRole.UserRole)
        if ref:
            self.signal_activated.emit(ref)


class _DropArea(pg.GraphicsLayoutWidget):
    dropped = Signal(object)

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
        ref = ref_from_mime(event.mimeData())
        if ref is not None:
            self.dropped.emit(ref)
            event.acceptProposedAction()


class GraphPanel(QWidget):
    """Stacked plots, one per signal, sharing the time axis of the trace (seconds from the first frame)."""

    cursor_moved = Signal(float)
    signal_dropped = Signal(object)
    measuring_changed = Signal(bool)

    def __init__(self, binder: TextBinder, parent=None) -> None:
        super().__init__(parent)
        self._binder = binder
        self.series: list = []  # SignalSeries
        self._plots: list[pg.PlotItem] = []
        self._cursors: list[list[pg.InfiniteLine]] = [[], []]
        self.cursor_time = [0.0, 0.0]
        self._syncing = False
        self._measuring = False
        self._visible_cursors = [True, False]
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

        self.clear_button = binder.widget(QPushButton, "Clear Graph")
        self.readout = QTableWidget(0, 4)
        self.readout.verticalHeader().hide()
        self.readout.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.readout.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.readout.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.remove_button = binder.widget(QPushButton, "Remove Plot")
        self.delta_label = QLabel()
        self.delta_label.setObjectName("hintLabel")

        tools = QHBoxLayout()
        tools.addWidget(self.delta_label, 1)
        tools.addWidget(self.remove_button)
        tools.addWidget(self.clear_button)

        # Each plot keeps a readable height; many signals scroll instead of shrinking.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setWidget(self.canvas)
        plots = QWidget()
        plots_layout = QVBoxLayout(plots)
        plots_layout.setContentsMargins(0, 0, 0, 0)
        plots_layout.addWidget(self.placeholder)
        plots_layout.addWidget(self.scroll, 1)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(self.readout, 1)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(plots)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([700, 300])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(tools)
        layout.addWidget(splitter, 1)

        self.clear_button.clicked.connect(self.clear)
        self.remove_button.clicked.connect(self.remove_selected)
        QShortcut(QKeySequence.StandardKey.Delete, self.readout, activated=self.remove_selected)
        self._update_language()
        self._show_canvas()

    # -- public API ----------------------------------------------------------------

    def refs(self) -> list[SignalRef]:
        return [series.ref for series in self.series]

    def add_series(self, series) -> bool:
        if series.ref in self.refs() or len(self.series) >= MAX_PLOTS:
            return False
        self.series.append(series)
        self._rebuild()
        return True

    def remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.readout.selectedIndexes()}, reverse=True)
        for row in rows:
            if row < len(self.series):
                del self.series[row]
        if rows:
            self._rebuild()

    def clear(self) -> None:
        self.series = []
        self._rebuild()

    @property
    def measuring(self) -> bool:
        """Whether the second cursor is shown, which is what measuring means here."""
        return self._measuring

    def set_measuring(self, enabled: bool) -> None:
        if enabled == self._measuring:
            return
        self._measuring = enabled
        self._visible_cursors[1] = enabled
        if enabled and self._plots:
            low, high = self._plots[0].viewRange()[0]
            if not low <= self.cursor_time[1] <= high:
                self.cursor_time[1] = self.cursor_time[0] + (high - low) / 10
        for line in self._cursors[1]:
            line.setValue(self.cursor_time[1])
            line.setVisible(enabled)
        self._update_readout()
        self.measuring_changed.emit(enabled)

    def set_cursor_visible(self, cursor: int, visible: bool) -> None:
        """Hide a cursor line without forgetting where it is."""
        if cursor == 1:
            self.set_measuring(visible)
            return
        self._visible_cursors[cursor] = visible
        for line in self._cursors[cursor]:
            line.setVisible(visible)

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
        import numpy as np

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
            self._update_readout()
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

    def apply_theme(self, theme) -> None:
        """Repaint the plots in ``theme``: background, axes, curves and cursors."""
        self._theme = theme
        self.canvas.setBackground(theme.plot_bg)
        self._rebuild()

    def set_languages(self) -> None:
        self._update_language()

    # -- internals -----------------------------------------------------------------

    def _update_language(self) -> None:
        tr = self._binder.tr
        self.readout.setHorizontalHeaderLabels([tr("Signal"), tr("Cursor 1"), tr("Cursor 2"), tr("Delta")])
        self._update_readout()

    def _show_canvas(self) -> None:
        empty = not self.series
        self.placeholder.setVisible(empty)
        self.scroll.setVisible(not empty)
        self.canvas.setMinimumHeight(PLOT_HEIGHT * len(self.series) + 30)
        for widget in (self.clear_button, self.remove_button):
            widget.setEnabled(not empty)

    def _rebuild(self) -> None:
        self.canvas.clear()
        self._plots = []
        self._cursors = [[], []]
        first = None
        theme = self._theme
        for index, series in enumerate(self.series):
            color = theme.curves[index % len(theme.curves)]
            plot = self.canvas.addPlot(row=index, col=0)
            plot.showGrid(x=True, y=True, alpha=theme.grid_alpha)
            plot.setMenuEnabled(False)
            plot.getAxis("left").setWidth(64)
            plot.hideButtons()
            for edge in ("left", "bottom"):
                axis = plot.getAxis(edge)
                axis.setTextPen(theme.plot_fg)
                axis.setPen(theme.plot_fg)
            if series.unit:
                plot.setTitle(f"<span style='color:{color}'>{series.ref.signal} [{series.unit}]</span>", size="8pt")
            else:
                plot.setTitle(f"<span style='color:{color}'>{series.ref.signal}</span>", size="8pt")
            if len(series.time):
                # Sample-and-hold: each value lasts until the next sample.
                curve = pg.PlotDataItem(series.time, series.values, stepMode="right",
                                        pen=pg.mkPen(color, width=1.2))
                # Clip and downsample only once the curve sits in its view box.
                plot.addItem(curve)
                curve.setClipToView(True)
                curve.setDownsampling(auto=True, method="peak")
            if first is None:
                first = plot
            else:
                plot.setXLink(first)
            if index < len(self.series) - 1:
                plot.getAxis("bottom").setStyle(showValues=False)
            else:
                plot.setLabel("bottom", self._binder.tr("Time (s)"))
            for cursor, color_line in ((0, theme.cursor_primary), (1, theme.cursor_secondary)):
                line = pg.InfiniteLine(
                    pos=self.cursor_time[cursor], angle=90, movable=True, pen=pg.mkPen(color_line, width=1),
                )
                line.setVisible(self._visible_cursors[cursor])
                line.sigPositionChanged.connect(lambda moved, c=cursor: self._cursor_dragged(c, moved))
                plot.addItem(line, ignoreBounds=True)
                self._cursors[cursor].append(line)
            self._plots.append(plot)
        self._fill_readout()
        self._show_canvas()

    def _cursor_dragged(self, cursor: int, line) -> None:
        if self._syncing:
            return
        seconds = float(line.value())
        self._syncing = True
        try:
            self.cursor_time[cursor] = seconds
            for other in self._cursors[cursor]:
                if other is not line:
                    other.setValue(seconds)
        finally:
            self._syncing = False
        self._update_readout()
        if cursor == 0:
            self.cursor_moved.emit(seconds)

    def _fill_readout(self) -> None:
        self.readout.setRowCount(len(self.series))
        for row, series in enumerate(self.series):
            item = QTableWidgetItem(series.ref.label)
            item.setForeground(QColor(self._theme.curves[row % len(self._theme.curves)]))
            item.setToolTip(series.ref.label)
            self.readout.setItem(row, 0, item)
        self._update_readout()

    def _update_readout(self) -> None:
        measuring = self._measuring
        first, second = self.cursor_time
        for row, series in enumerate(self.series):
            values = [series.text_at(first), series.text_at(second) if measuring else ""]
            delta = ""
            if measuring:
                a, b = series.value_at(first), series.value_at(second)
                if a is not None and b is not None:
                    delta = f"{b - a:.6g}"
            for column, text in enumerate((*values, delta), start=1):
                item = self.readout.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.readout.setItem(row, column, item)
                item.setText(text)
        self.delta_label.setText(
            self._binder.tr("Δt = {delta} s", delta=f"{second - first:.6f}") if measuring else ""
        )
