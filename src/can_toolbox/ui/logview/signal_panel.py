"""The signal panel beside the graph: groups, visibility and the values at the cursors."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QInputDialog,
    QMenu,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from can_toolbox.ui import theme as app_theme
from can_toolbox.ui.graphics import refs_from_mime, refs_to_mime
from can_toolbox.ui.logview.signal_set import Entry, Group, SignalSet
from can_toolbox.ui.widgets import TextBinder

COLUMNS = ("Signal", "Cursor 1", "Cursor 2", "Min", "Max", "Delta")
CURSOR2_COLUMN = 2
DELTA_COLUMN = 5
HEADER_KEY = "graph/signal_header"
NAME_WIDTH = 200
MIME = "application/x-can-toolbox-signal"


class SignalTreeModel(QAbstractItemModel):
    """Two levels: groups, then the signals in them; loose signals sit at the root."""

    def __init__(self, signals: SignalSet, parent=None) -> None:
        super().__init__(parent)
        self.signals = signals
        self.headers = list(COLUMNS)
        # (cursor 1, cursor 2, min, max, delta) per entry, filled by the panel.
        self.values: dict[int, tuple[str, str, str, str, str]] = {}
        self.missing: set[int] = set()
        self._theme = app_theme.current_theme()

    # -- structure -----------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        if not parent.isValid():
            return len(self.signals.groups) + len(self.signals.root)
        owner = parent.internalPointer()
        return len(owner.entries) if isinstance(owner, Group) else 0

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.headers)

    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if not parent.isValid():
            groups = self.signals.groups
            item = groups[row] if row < len(groups) else self.signals.root[row - len(groups)]
            return self.createIndex(row, column, item)
        owner = parent.internalPointer()
        return self.createIndex(row, column, owner.entries[row])

    def parent(self, index: QModelIndex) -> QModelIndex:  # noqa: A003 - Qt's name
        if not index.isValid():
            return QModelIndex()
        item = index.internalPointer()
        if isinstance(item, Group):
            return QModelIndex()
        group = self.signals.group_of(item)
        if group is None:
            return QModelIndex()
        return self.createIndex(self.signals.groups.index(group), 0, group)

    def item(self, index: QModelIndex):
        return index.internalPointer() if index.isValid() else None

    def index_of(self, item) -> QModelIndex:
        if isinstance(item, Group):
            return self.createIndex(self.signals.groups.index(item), 0, item)
        group = self.signals.group_of(item)
        if group is None:
            row = len(self.signals.groups) + self.signals.root.index(item)
            return self.createIndex(row, 0, item)
        return self.createIndex(group.entries.index(item), 0, item)

    # -- data ----------------------------------------------------------------------

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = index.internalPointer()
        column = index.column()
        if isinstance(item, Group):
            if role == Qt.ItemDataRole.DisplayRole and column == 0:
                return f"{item.name}  ({len(item.entries)})"
            if role == Qt.ItemDataRole.CheckStateRole and column == 0:
                return self._group_check_state(item)
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return item.ref.signal
            return self.values.get(id(item), ("", "", "", "", ""))[column - 1]
        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            return Qt.CheckState.Checked if item.visible else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ForegroundRole and column == 0:
            if id(item) in self.missing:
                return QColor(self._theme.disabled_text)
            curves = self._theme.curves
            return QColor(curves[item.color_index % len(curves)])
        if role == Qt.ItemDataRole.ToolTipRole:
            if id(item) in self.missing:
                return f"{item.ref.label} — not in this log"
            return item.ref.label
        if role == Qt.ItemDataRole.UserRole:
            return item.ref
        return None

    def _group_check_state(self, group: Group):
        if not group.entries:
            return Qt.CheckState.Unchecked
        visible = sum(entry.visible for entry in group.entries)
        if visible == len(group.entries):
            return Qt.CheckState.Checked
        return Qt.CheckState.Unchecked if visible == 0 else Qt.CheckState.PartiallyChecked

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.CheckStateRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole or index.column():
            return False
        checked = Qt.CheckState(value) == Qt.CheckState.Checked
        item = index.internalPointer()
        if isinstance(item, Group):
            self.signals.set_group_visible(item, checked)
        else:
            self.signals.set_visible(item, checked)
        return True

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        if not index.column():
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        if isinstance(index.internalPointer(), Group):
            flags |= Qt.ItemFlag.ItemIsDropEnabled
        return flags

    def apply_theme(self, theme) -> None:
        self._theme = theme
        self.refresh()

    def refresh(self) -> None:
        top = self.index(0, 0)
        if self.rowCount():
            self.dataChanged.emit(top, self.index(self.rowCount() - 1, self.columnCount() - 1),
                                  [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole])
        for row, group in enumerate(self.signals.groups):
            if group.entries:
                parent = self.createIndex(row, 0, group)
                self.dataChanged.emit(self.index(0, 0, parent),
                                      self.index(len(group.entries) - 1, self.columnCount() - 1, parent))

    # -- drag & drop ---------------------------------------------------------------

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def mimeTypes(self) -> list[str]:
        return [MIME]

    def mimeData(self, indexes):
        entries = [item for index in indexes if index.column() == 0
                   and isinstance(item := index.internalPointer(), Entry)]
        return refs_to_mime([entry.ref for entry in entries])

    def dropMimeData(self, data, action, row, _column, parent) -> bool:
        refs = refs_from_mime(data)
        if not refs:
            return False
        owner = parent.internalPointer() if parent.isValid() else None
        group = owner if isinstance(owner, Group) else self.signals.group_of(owner) if owner else None
        known = [entry for ref in refs if (entry := self.signals.entry_for(ref))]
        self.beginResetModel()
        try:
            if known:
                self.signals.move(known, group, None if row < 0 else row)
            for ref in refs:
                if self.signals.entry_for(ref) is None:
                    self.signals.add(ref, group)
        finally:
            self.endResetModel()
        return True


class SignalPanel(QWidget):
    """The list beside the graph: groups, visibility checkboxes and cursor values."""

    add_requested = Signal()
    focus_changed = Signal(object)

    def __init__(self, signals: SignalSet, binder: TextBinder, settings: QSettings,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._binder = binder
        self._settings = settings
        self.signals = signals
        self.plot_mode = False
        self.series_for: Callable[[object], object] | None = None
        self._cursors = (0.0, 0.0)
        self._measuring = False
        self._range = (0.0, 0.0)

        self.model = SignalTreeModel(signals, self)
        self.view = QTreeView(self)
        self.view.setModel(self.model)
        self.view.setUniformRowHeights(True)
        self.view.setAllColumnsShowFocus(True)
        self.view.setRootIsDecorated(True)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.view.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.view.setAcceptDrops(True)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_menu)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        header = self.view.header()
        # Values take what they need; the name column is the one the user drags.
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(48)
        header.resizeSection(0, NAME_WIDTH)
        self.setMinimumWidth(260)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        signals.changed.connect(self._rebuild)
        self.view.selectionModel().selectionChanged.connect(self._selection_changed)
        app_theme.manager.changed.connect(self.model.apply_theme)
        self.update_language()
        self._restore_header()
        self._apply_measure_columns()

    # -- state ---------------------------------------------------------------------

    def set_series_lookup(self, lookup: Callable[[object], object] | None) -> None:
        """``lookup(ref)`` returns the series for a signal, or ``None`` if the log has none."""
        self.series_for = lookup
        self.refresh_values()

    def set_cursors(self, first: float, second: float, measuring: bool) -> None:
        self._cursors = (first, second)
        if measuring != self._measuring:
            self._measuring = measuring
            self._apply_measure_columns()
        self.refresh_values()

    def set_range(self, low: float, high: float) -> None:
        self._range = (low, high)
        self.refresh_values()

    def _rebuild(self) -> None:
        self.model.beginResetModel()
        self.model.endResetModel()
        for row, group in enumerate(self.signals.groups):
            self.view.setExpanded(self.model.index(row, 0), group.expanded)
        self.refresh_values()

    def refresh_values(self) -> None:
        """Recompute the value columns; min and max follow the cursors or the view."""
        first, second = self._cursors
        low, high = (min(first, second), max(first, second)) if self._measuring else self._range
        values: dict[int, tuple[str, str, str, str, str]] = {}
        missing: set[int] = set()
        for entry in self.signals.entries():
            series = self.series_for(entry.ref) if self.series_for else None
            # No samples means the active log does not carry this signal.
            if series is None or not len(series.time):
                missing.add(id(entry))
                values[id(entry)] = ("", "", "", "", "")
                continue
            delta = ""
            if self._measuring:
                start, stop = series.value_at(first), series.value_at(second)
                if start is not None and stop is not None:
                    delta = f"{stop - start:.6g}"
            extrema = series.extrema(low, high) if high > low else None
            values[id(entry)] = (
                series.text_at(first),
                series.text_at(second) if self._measuring else "",
                f"{extrema[0]:.6g}" if extrema else "",
                f"{extrema[1]:.6g}" if extrema else "",
                delta,
            )
        self.model.values = values
        self.model.missing = missing
        self.model.refresh()

    def _apply_measure_columns(self) -> None:
        """Cursor 2 and Delta only mean something while measuring."""
        for column in (CURSOR2_COLUMN, DELTA_COLUMN):
            self.view.setColumnHidden(column, not self._measuring)

    def update_language(self) -> None:
        self.model.headers = [self._binder.tr(column) for column in COLUMNS]
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(COLUMNS) - 1)

    # -- selection -----------------------------------------------------------------

    def selected_entries(self) -> list[Entry]:
        items = [self.model.item(index) for index in self.view.selectedIndexes() if index.column() == 0]
        return [item for item in items if isinstance(item, Entry)]

    def selected_groups(self) -> list[Group]:
        items = [self.model.item(index) for index in self.view.selectedIndexes() if index.column() == 0]
        return [item for item in items if isinstance(item, Group)]

    def current_group(self) -> Group | None:
        """Where Add Signals… puts what it adds."""
        groups = self.selected_groups()
        if groups:
            return groups[0]
        entries = self.selected_entries()
        return self.signals.group_of(entries[0]) if entries else None

    def _selection_changed(self, *_args) -> None:
        entries = self.selected_entries()
        if self.plot_mode:
            self.signals.show_only(entries)
        self.focus_changed.emit(entries[0].ref if entries else None)

    def set_plot_mode(self, enabled: bool) -> None:
        """CANoe's Ctrl+click behaviour: the selection is what the graph shows."""
        self.plot_mode = enabled
        if enabled:
            self.signals.show_only(self.selected_entries())

    # -- menus ---------------------------------------------------------------------

    def _show_header_menu(self, point) -> None:
        menu = QMenu(self)
        for column in range(1, len(COLUMNS)):
            action = menu.addAction(self.model.headers[column])
            action.setCheckable(True)
            action.setChecked(not self.view.isColumnHidden(column))
            action.setData(column)
        chosen = menu.exec(self.view.header().mapToGlobal(point))
        if chosen is not None:
            self.view.setColumnHidden(int(chosen.data()), not chosen.isChecked())
            self._save_header()

    def _show_menu(self, point) -> None:
        tr = self._binder.tr
        entries = self.selected_entries()
        groups = self.selected_groups()
        menu = QMenu(self)
        add_action = menu.addAction(tr("Add Signals…"))
        new_group_action = menu.addAction(tr("New Group"))
        rename_action = menu.addAction(tr("Rename"))
        rename_action.setEnabled(len(groups) == 1)
        delete_action = menu.addAction(tr("Delete"))
        delete_action.setEnabled(bool(entries or groups))

        move_menu = menu.addMenu(tr("Move to Group"))
        move_menu.setEnabled(bool(entries))
        move_targets = {}
        for group in self.signals.groups:
            move_targets[move_menu.addAction(group.name)] = group
        move_menu.addSeparator()
        to_root_action = move_menu.addAction(tr("No group"))

        menu.addSeparator()
        plot_mode_action = menu.addAction(tr("Ctrl+click plot mode"))
        plot_mode_action.setCheckable(True)
        plot_mode_action.setChecked(self.plot_mode)
        menu.addSeparator()
        expand_action = menu.addAction(tr("Expand All"))
        collapse_action = menu.addAction(tr("Collapse All"))

        chosen = menu.exec(self.view.viewport().mapToGlobal(point))
        if chosen is None:
            return
        if chosen is add_action:
            self.add_requested.emit()
        elif chosen is new_group_action:
            self._new_group(entries)
        elif chosen is rename_action:
            self._rename_group(groups[0])
        elif chosen is delete_action:
            self._delete(entries, groups)
        elif chosen in move_targets:
            self.signals.move(entries, move_targets[chosen])
        elif chosen is to_root_action:
            self.signals.move(entries, None)
        elif chosen is plot_mode_action:
            self.set_plot_mode(chosen.isChecked())
        elif chosen is expand_action:
            self._set_all_expanded(True)
        elif chosen is collapse_action:
            self._set_all_expanded(False)

    def _new_group(self, entries) -> None:
        name, accepted = QInputDialog.getText(self, self._binder.tr("New Group"), self._binder.tr("Group name"),
                                              text=self._binder.tr("Group"))
        if not accepted or not name.strip():
            return
        group = self.signals.new_group(name.strip())
        if entries:
            self.signals.move(entries, group)

    def _rename_group(self, group: Group) -> None:
        name, accepted = QInputDialog.getText(self, self._binder.tr("Rename"), self._binder.tr("Group name"),
                                              text=group.name)
        if accepted and name.strip():
            self.signals.rename_group(group, name.strip())

    def _delete(self, entries, groups) -> None:
        if entries:
            self.signals.remove(entries)
        for group in groups:
            self.signals.delete_group(group)

    def _set_all_expanded(self, expanded: bool) -> None:
        for group in self.signals.groups:
            group.expanded = expanded
        for row in range(len(self.signals.groups)):
            self.view.setExpanded(self.model.index(row, 0), expanded)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete(self.selected_entries(), self.selected_groups())
            event.accept()
            return
        super().keyPressEvent(event)

    # -- header state --------------------------------------------------------------

    def _restore_header(self) -> None:
        state = self._settings.value(HEADER_KEY)
        if state:
            self.view.header().restoreState(state)
        self.view.header().sectionResized.connect(lambda *_args: self._save_header())
        self.view.header().sectionMoved.connect(lambda *_args: self._save_header())

    def _save_header(self) -> None:
        self._settings.setValue(HEADER_KEY, self.view.header().saveState())
