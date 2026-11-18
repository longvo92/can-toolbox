"""What the Graphics window shows: signals, the groups they sit in and their colours.

Plain model objects. The tree view and the plots both read this; neither owns it,
and nothing here imports a widget.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from can_toolbox.canlog.refs import SignalRef

MAX_COLORS = 16


@dataclass(eq=False)
class Entry:
    """One plotted signal: its colour is fixed when it is added.

    Compared by identity: two entries of the same signal would otherwise be the
    same object to a list, and the panel moves entries around by reference.
    """

    ref: SignalRef
    color_index: int
    visible: bool = True


@dataclass(eq=False)
class Group:
    """A named lane group. A signal belongs to exactly one group, or to none."""

    name: str
    entries: list[Entry] = field(default_factory=list)
    expanded: bool = True


class SignalSet(QObject):
    """Groups and loose signals, in display order.

    ``changed`` fires whenever the contents, the order, a colour or a
    visibility flag changes, so the panel and the graph can redraw.
    """

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.groups: list[Group] = []
        self.root: list[Entry] = []
        # Ctrl+click plot mode: the selection decides what is drawn and the
        # per-signal checkboxes are left alone, all of them ticked.
        self.plot_mode = False
        self._selected: list[Entry] = []

    # -- reading -------------------------------------------------------------------

    def entries(self) -> list[Entry]:
        """Every entry in display order: groups first, then the loose signals."""
        ordered: list[Entry] = []
        for group in self.groups:
            ordered.extend(group.entries)
        ordered.extend(self.root)
        return ordered

    def visible_entries(self) -> list[Entry]:
        """What the graph draws, in display order.

        In plot mode that is the selection; otherwise the ticked signals.
        """
        if self.plot_mode:
            chosen = set(self._selected)
            return [entry for entry in self.entries() if entry in chosen]
        return [entry for entry in self.entries() if entry.visible]

    def selection(self) -> list[Entry]:
        return [entry for entry in self.entries() if entry in set(self._selected)]

    def refs(self) -> list[SignalRef]:
        return [entry.ref for entry in self.entries()]

    def entry_for(self, ref: SignalRef) -> Entry | None:
        return next((entry for entry in self.entries() if entry.ref == ref), None)

    def group_of(self, entry: Entry) -> Group | None:
        return next((group for group in self.groups if entry in group.entries), None)

    def group_named(self, name: str) -> Group | None:
        return next((group for group in self.groups if group.name == name), None)

    def __len__(self) -> int:
        return len(self.entries())

    # -- editing -------------------------------------------------------------------

    def _free_color(self) -> int:
        used = {entry.color_index for entry in self.entries()}
        for index in range(MAX_COLORS):
            if index not in used:
                return index
        return len(self.entries()) % MAX_COLORS

    def add(self, ref: SignalRef, group: Group | None = None, *, visible: bool = True,
            color_index: int | None = None) -> Entry | None:
        """Add ``ref`` to ``group`` (or the root). ``None`` when it is already there."""
        if self.entry_for(ref) is not None:
            return None
        entry = Entry(ref, self._free_color() if color_index is None else color_index, visible)
        target = group.entries if group is not None else self.root
        target.append(entry)
        self.changed.emit()
        return entry

    def remove(self, entries) -> None:
        wanted = set(entries)
        if not wanted:
            return
        for group in self.groups:
            group.entries = [entry for entry in group.entries if entry not in wanted]
        self.root = [entry for entry in self.root if entry not in wanted]
        self._selected = [entry for entry in self._selected if entry not in wanted]
        self.changed.emit()

    def clear(self) -> None:
        if not self.groups and not self.root:
            return
        self.groups = []
        self.root = []
        self._selected = []
        self.changed.emit()

    def set_visible(self, entry: Entry, visible: bool) -> None:
        if self.plot_mode:
            return  # the selection decides; every checkbox stays ticked
        if entry.visible != visible:
            entry.visible = visible
            self.changed.emit()

    def set_group_visible(self, group: Group, visible: bool) -> None:
        if self.plot_mode:
            return
        if any(entry.visible != visible for entry in group.entries):
            for entry in group.entries:
                entry.visible = visible
            self.changed.emit()

    def set_expanded(self, group: Group, expanded: bool) -> None:
        if group.expanded != expanded:
            group.expanded = expanded
            self.changed.emit()

    def set_plot_mode(self, enabled: bool, selection=()) -> None:
        """Turn Ctrl+click plot mode on or off.

        Entering it ticks every signal, because the checkboxes stop deciding
        anything: from then on the selection is what the graph draws. Leaving
        it hands the decision back to the checkboxes, all of them on.
        """
        self._selected = [entry for entry in self.entries() if entry in set(selection)]
        if enabled:
            for entry in self.entries():
                entry.visible = True
        self.plot_mode = enabled
        self.changed.emit()

    def set_selection(self, entries) -> None:
        """What the panel has selected; it only matters in plot mode."""
        selected = [entry for entry in self.entries() if entry in set(entries)]
        if selected == self._selected:
            return
        self._selected = selected
        if self.plot_mode:
            self.changed.emit()

    def unique_group_name(self, base: str) -> str:
        if self.group_named(base) is None:
            return base
        index = 2
        while self.group_named(f"{base} {index}") is not None:
            index += 1
        return f"{base} {index}"

    def new_group(self, name: str) -> Group:
        group = Group(self.unique_group_name(name))
        self.groups.append(group)
        self.changed.emit()
        return group

    def rename_group(self, group: Group, name: str) -> None:
        name = name.strip()
        if not name or name == group.name:
            return
        group.name = self.unique_group_name(name)
        self.changed.emit()

    def delete_group(self, group: Group) -> None:
        """Remove the group and the signals in it."""
        if group in self.groups:
            self.groups.remove(group)
            self.changed.emit()

    def move(self, entries, group: Group | None, position: int | None = None) -> None:
        """Move ``entries`` into ``group`` (or the root), keeping their order."""
        wanted = set(entries)
        moving = [entry for entry in self.entries() if entry in wanted]
        if not moving:
            return
        moved = set(moving)
        for owner in self.groups:
            owner.entries = [entry for entry in owner.entries if entry not in moved]
        self.root = [entry for entry in self.root if entry not in moved]
        target = group.entries if group is not None else self.root
        index = len(target) if position is None else max(0, min(position, len(target)))
        target[index:index] = moving
        self.changed.emit()

    def move_group(self, group: Group, position: int) -> None:
        if group not in self.groups:
            return
        self.groups.remove(group)
        self.groups.insert(max(0, min(position, len(self.groups))), group)
        self.changed.emit()
