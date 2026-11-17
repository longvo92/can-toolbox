"""The fixed Excel template: two sheets, seven columns, nothing to configure.

``Inputs`` and ``Outputs`` carry one element per row::

    Interface | Data Element | CAN Signal | Datatype | Formula | Status Mapping | Enabled

A workbook written by :func:`write_template` is the same thing a user can fill in,
and :func:`read_template` turns either back into the canonical mapping document.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from can_toolbox.blf_mat.config import SCHEMA_VERSION, ConfigError

SHEETS = {"Inputs": "input", "Outputs": "output"}
HEADERS = ("Interface", "Data Element", "CAN Signal", "Datatype", "Formula", "Status Mapping", "Enabled")
DATATYPES = ("double", "single", "int8", "uint8", "int16", "uint16", "int32", "uint32",
             "int64", "uint64", "boolean")
HEADER_ROW = 1
EXAMPLE = {
    "Inputs": ("VehicleInputs", "VehicleSpeed", "VehicleSpeedCAN", "single", "/10", "", "TRUE"),
    "Outputs": ("VehicleOutputs", "TorqueRequest", "TorqueReqCAN", "single", "", "", "TRUE"),
}


def write_template(path: Path) -> Path:
    """Write an empty workbook with the fixed columns, a datatype list and one example row."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    book = Workbook()
    book.remove(book.active)
    for title in SHEETS:
        sheet = book.create_sheet(title)
        sheet.append(list(HEADERS))
        for column in range(1, len(HEADERS) + 1):
            cell = sheet.cell(row=HEADER_ROW, column=column)
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="EEF2FB")
        sheet.append(list(EXAMPLE[title]))
        datatypes = DataValidation(type="list", formula1='"' + ",".join(DATATYPES) + '"', allow_blank=True)
        enabled = DataValidation(type="list", formula1='"TRUE,FALSE"', allow_blank=True)
        sheet.add_data_validation(datatypes)
        sheet.add_data_validation(enabled)
        datatypes.add("D2:D1000")
        enabled.add("G2:G1000")
        for column, width in zip("ABCDEFG", (22, 24, 26, 14, 16, 20, 10)):
            sheet.column_dimensions[column].width = width
        sheet.freeze_panes = "A2"
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    book.close()
    return path


def read_template(path: Path, skip_keywords: tuple[str, ...] = ()) -> dict[str, Any]:
    """Read a template workbook into the canonical mapping document."""
    from can_toolbox.blf_mat.mapping import Workbook

    document: dict[str, Any] = {"version": SCHEMA_VERSION, "interfaces": []}
    with Workbook(path) as book:
        names = {name.casefold(): name for name in book.sheet_names}
        missing = [title for title in SHEETS if title.casefold() not in names]
        if len(missing) == len(SHEETS):
            raise ConfigError(
                f"{path.name}: the template needs an 'Inputs' or an 'Outputs' sheet. "
                "Use Save Excel template… to create one."
            )
        for title, side in SHEETS.items():
            if title.casefold() not in names:
                continue
            rows = book.grid(names[title.casefold()])
            _read_sheet(path, names[title.casefold()], side, rows, skip_keywords, document)
    if not document["interfaces"]:
        raise ConfigError(f"{path.name}: no rows to read; fill in at least one element.")
    return document


def _read_sheet(path: Path, title: str, side: str, rows, skip_keywords, document) -> None:
    from can_toolbox.blf_mat.mapping import cell

    if not rows:
        return
    header = [cell(value).strip().casefold() for value in rows[HEADER_ROW - 1]]
    expected = [name.casefold() for name in HEADERS]
    if header[: len(expected)] != expected:
        raise ConfigError(
            f"{path.name}[{title}]: row {HEADER_ROW} must be {', '.join(HEADERS)}. "
            "Use Save Excel template… for a workbook with the right columns."
        )
    buses: dict[str, dict[str, Any]] = {}
    for number, row in enumerate(rows[HEADER_ROW:], start=HEADER_ROW + 1):
        values = [cell(value).strip() for value in (list(row) + [""] * len(HEADERS))[: len(HEADERS)]]
        interface, element, can_signal, dtype, formula, status, enabled = values
        if not any(values):
            continue
        if skip_keywords and any(
            keyword in " ".join(values).casefold() for keyword in skip_keywords
        ):
            continue
        if enabled.casefold() in {"false", "0", "no"}:
            continue
        if not interface or not element:
            raise ConfigError(
                f"{path.name}[{title}]:{number}: both Interface and Data Element are required."
            )
        bus = buses.get(interface.casefold())
        if bus is None:
            bus = {"name": interface, "side": side, "elements": []}
            buses[interface.casefold()] = bus
            document["interfaces"].append(bus)
        entry: dict[str, Any] = {"element": element, "dtype": dtype or "double"}
        if can_signal:
            entry["can_signal"] = can_signal
        if formula:
            entry["formula"] = formula
        if status:
            entry["status_mapping"] = _status_pairs(status, f"{path.name}[{title}]:{number}")
        bus["elements"].append(entry)


def _status_pairs(text: str, where: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for part in text.replace(";", ",").split(","):
        if not part.strip():
            continue
        if ":" not in part:
            raise ConfigError(f"{where}: Status Mapping needs 'can:model' pairs, got {part.strip()!r}.")
        can_value, model_value = part.split(":", 1)
        pairs[can_value.strip()] = model_value.strip()
    return pairs
