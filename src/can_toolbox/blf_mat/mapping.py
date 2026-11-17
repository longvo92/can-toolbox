"""Turn a mapping config and an optional Excel template into interfaces to decode."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from can_toolbox.blf_mat.config import (
    SIDES,
    InputCanMapping,
    InputForce,
    MappingConfig,
    parse_document,
)

from . import converter as core

# Cell texts treated as blank, as pandas.read_excel did before this reader replaced it.
NA_STRINGS = frozenset({
    "", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND", "1.#QNAN",
    "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null",
})


@dataclass
class MappingSetup:
    """Everything the converter needs after reading the definitions."""

    interfaces: list[dict[str, Any]] = field(default_factory=list)
    input_interfaces: list[dict[str, Any]] = field(default_factory=list)
    output_interfaces: list[dict[str, Any]] = field(default_factory=list)
    input_elements: dict[str, str] = field(default_factory=dict)
    output_elements: dict[str, str] = field(default_factory=dict)
    input_specific: dict[tuple[str, str], str] = field(default_factory=dict)
    output_specific: dict[tuple[str, str], str] = field(default_factory=dict)
    mappings: list[InputCanMapping] = field(default_factory=list)
    forces: list[InputForce] = field(default_factory=list)
    input_names: list[str] = field(default_factory=list)


def _cell_value(value: Any) -> Any:
    """Trim strings, treat NA-like texts as blank and keep integral floats as ints."""
    if isinstance(value, str):
        text = value.strip()
        return None if text in NA_STRINGS else text
    if isinstance(value, float) and math.isfinite(value) and float(value).is_integer():
        return int(value)
    return value


class Workbook:
    """Read-only workbook giving each sheet as a rectangular grid of cell values.

    Trailing empty rows and columns are dropped and NA-like texts become ``None``.
    """

    def __init__(self, path: Path) -> None:
        from openpyxl import load_workbook

        self._book = load_workbook(path, read_only=True, data_only=True, keep_links=False)

    def __enter__(self) -> Workbook:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._book.close()

    @property
    def sheet_names(self) -> list[str]:
        return list(self._book.sheetnames)

    def grid(self, sheet: str) -> list[list[Any]]:
        worksheet = self._book[sheet]
        if hasattr(worksheet, "reset_dimensions"):
            # Read-only sheets may carry wrong stored dimensions.
            worksheet.reset_dimensions()
        rows = []
        for values in worksheet.iter_rows(values_only=True):
            row = [_cell_value(value) for value in values]
            while row and row[-1] is None:
                row.pop()
            rows.append(row)
        while rows and not rows[-1]:
            rows.pop()
        width = max((len(row) for row in rows), default=0)
        return [row + [None] * (width - len(row)) for row in rows]


def cell(value: Any) -> str:
    return "" if value is None else str(value).strip()


def add_target(interfaces: list[dict[str, Any]], interface: str, element: str, dtype: str) -> None:
    if not core.is_valid_matlab_identifier(interface) or not core.is_valid_matlab_identifier(element):
        raise RuntimeError(f"Mapping target must use valid MATLAB identifiers: {interface}.{element}")
    bus = next((item for item in interfaces if core.norm(item["name"]) == core.norm(interface)), None)
    if bus is None:
        bus = {"name": interface, "elements": []}
        interfaces.append(bus)
    existing = next(
        (item for item in bus["elements"] if core.norm(item["name"]) == core.norm(element)), None
    )
    if existing:
        if dtype and core.normalize_dtype(existing["dataType"]) != core.normalize_dtype(dtype):
            raise RuntimeError(f"Conflicting datatype for {interface}.{element}")
    else:
        bus["elements"].append({"name": element, "dataType": dtype or "double"})


def safe_name(name: str, used: set[str]) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not name or not name[0].isalpha():
        name = "Signal_" + name
    base = name[:63]
    result, index = base, 2
    while core.norm(result) in used:
        suffix = f"_{index}"
        result = base[: 63 - len(suffix)] + suffix
        index += 1
    used.add(core.norm(result))
    return result


def infer_dbc(setup: MappingSetup, candidates: dict[str, list[core.DbcCandidate]]) -> None:
    """Without definitions, every DBC message becomes an interface of its signals."""
    buses, used_buses, used_elements = {}, set(), {}
    for entries in list(candidates.values()):
        for candidate in entries:
            key = (candidate.dbc_file, candidate.message_name, candidate.frame_id, candidate.is_extended)
            if key not in buses:
                buses[key] = safe_name(candidate.message_name, used_buses)
                used_elements[key] = set()
            bus = buses[key]
            element = safe_name(candidate.signal_name, used_elements[key])
            add_target(setup.input_interfaces, bus, element, "double")
            # Keep same-named signals from different DBC messages independent.
            alias = "blf2mat" + hashlib.sha256(repr(candidate.key).encode()).hexdigest()
            if alias in candidates:
                raise RuntimeError("Internal DBC decode key collision")
            candidates[alias] = [candidate]
            setup.input_specific[(core.norm(bus), core.norm(element))] = alias
            if bus not in setup.input_names:
                setup.input_names.append(bus)
    setup.interfaces = list(setup.input_interfaces)


def resolve_definitions(
    config: MappingConfig,
    excel: Path | None,
    candidates: dict[str, list[core.DbcCandidate]],
) -> MappingSetup:
    """Merge the mapping config with an Excel template, or infer interfaces from the DBCs.

    The config and the workbook describe the same thing; where both name an
    element, the config wins, because it is the file the user edits by hand.
    """
    from can_toolbox.blf_mat.excel_template import read_template

    setup = MappingSetup()
    sources: list[MappingConfig] = [config]
    if excel is not None:
        sources.append(parse_document(read_template(excel, config.excel_skip_keywords), source=excel))

    seen: dict[str, set[tuple[str, str]]] = {side: set() for side in SIDES}
    for source in sources:
        for side in SIDES:
            interfaces = getattr(setup, f"{side}_interfaces")
            specific = getattr(setup, f"{side}_specific")
            for bus in source.interfaces[side]:
                for element in bus["elements"]:
                    target = (core.norm(bus["name"]), core.norm(element["name"]))
                    if target in seen[side]:
                        continue
                    seen[side].add(target)
                    add_target(interfaces, bus["name"], element["name"], element["dataType"])
                    if element.get("canSignal"):
                        specific[target] = element["canSignal"]
            if side == "input":
                setup.input_names = [bus["name"] for bus in interfaces]

    mapped: dict[tuple[str, str], InputCanMapping] = {}
    forced: dict[tuple[str, str], InputForce] = {}
    for source in sources:
        for mapping in source.mappings:
            mapped.setdefault(mapping.target_key, mapping)
        for force in source.forces:
            forced.setdefault(force.target_key, force)
    both = set(mapped) & set(forced)
    if both:
        names = ", ".join(mapped[target].target_name for target in sorted(both))
        raise RuntimeError(f"These inputs have both a CAN source and a constant value: {names}")
    setup.mappings = list(mapped.values())
    setup.forces = list(forced.values())
    # A config may name a target no interface declares; it becomes an input element.
    declared = {
        (core.norm(bus["name"]), core.norm(element["name"]))
        for bus in setup.input_interfaces
        for element in bus["elements"]
    }
    for target, entry in (*mapped.items(), *forced.items()):
        if target not in declared:
            add_target(setup.input_interfaces, entry.interface, entry.element, "double")
            declared.add(target)
            if entry.interface not in setup.input_names:
                setup.input_names.append(entry.interface)
    for target, mapping in mapped.items():
        setup.input_specific.setdefault(target, mapping.can_signal)

    setup.interfaces = setup.input_interfaces + setup.output_interfaces
    if not setup.interfaces and candidates:
        infer_dbc(setup, candidates)
    return setup
