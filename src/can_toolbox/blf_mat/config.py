"""One mapping schema, written as YAML, JSON or TXT.

The canonical form is a mapping with ``version: 2``::

    version: 2
    excel_skip_keywords: []
    interfaces:
      - name: VehicleInputs
        side: input                    # input | output
        elements:
          - element: VehicleSpeed
            dtype: single
            can_signal: VehicleSpeedCAN   # optional CAN source
            formula: "/10"                # optional transform
            status_mapping: {0: 0, 1: 1}  # optional CAN -> model values
            enabled: true
          - element: Enable
            dtype: boolean
            value: true                   # constant, never decoded from CAN

The 0.x files (``input_mappings`` / ``input_forces``, no ``version``) still load;
:func:`upgraded_document` writes the same content as version 2.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
SIDES = ("input", "output")
SUFFIXES = (".yaml", ".yml", ".json", ".txt")
DEFAULT_DTYPE = "double"

_TARGET_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\.([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.*)$")
_OPTION_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_SECTION_RE = re.compile(r"^\[\s*(input|output|options)\s*\]$", re.IGNORECASE)


class ConfigError(ValueError):
    """A mapping file the user has to correct, with the place that is wrong."""


@dataclass(frozen=True)
class InputCanMapping:
    """An input element decoded from a CAN signal, with optional transforms."""

    interface: str
    element: str
    can_signal: str
    formula: str = ""
    status_mapping: dict[float, float] | None = None

    @property
    def target_key(self) -> tuple[str, str]:
        return norm(self.interface), norm(self.element)

    @property
    def target_name(self) -> str:
        return f"{self.interface}.{self.element}"


@dataclass(frozen=True)
class InputForce:
    """Constant value for an input element that is not sourced from CAN."""

    interface: str
    element: str
    value: float

    @property
    def target_key(self) -> tuple[str, str]:
        return norm(self.interface), norm(self.element)

    @property
    def target_name(self) -> str:
        return f"{self.interface}.{self.element}"


@dataclass(frozen=True)
class MappingConfig:
    """Interfaces and their CAN sources, however the file was written."""

    version: int = SCHEMA_VERSION
    source: Path | None = None
    interfaces: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {side: [] for side in SIDES}
    )
    mappings: tuple[InputCanMapping, ...] = ()
    forces: tuple[InputForce, ...] = ()
    excel_skip_keywords: tuple[str, ...] = ()

    @property
    def has_interfaces(self) -> bool:
        return any(self.interfaces[side] for side in SIDES)

    @property
    def is_legacy(self) -> bool:
        return self.version < SCHEMA_VERSION

    def specific_map(self, side: str) -> dict[tuple[str, str], str]:
        """``(interface, element) -> CAN signal`` for the elements that name one."""
        return {
            (norm(bus["name"]), norm(element["name"])): element["canSignal"]
            for bus in self.interfaces[side]
            for element in bus["elements"]
            if element.get("canSignal")
        }


def empty_config() -> MappingConfig:
    return MappingConfig()


# -- reading ------------------------------------------------------------------------


def load_config(path: Path | None) -> MappingConfig:
    """Read a mapping file in any supported syntax; ``None`` gives an empty config."""
    if path is None:
        return empty_config()
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        raise ConfigError(f"{path.name}: mapping files are .yaml, .yml, .json or .txt.")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp1252")
    except OSError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if suffix == ".txt":
        document = parse_txt(text, source=path)
    elif suffix == ".json":
        try:
            document = json.loads(text) if text.strip() else {}
        except ValueError as exc:
            raise ConfigError(f"{path.name}: invalid JSON: {exc}") from exc
    else:
        import yaml

        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigError(f"{path.name}: invalid YAML: {exc}") from exc
    return parse_document(document, source=path)


def parse_document(document: Any, source: Path | None = None) -> MappingConfig:
    """Validate one canonical document (version 2 or a 0.x file) into a config."""
    where = source.name if source is not None else "mapping config"
    if document is None:
        return MappingConfig(source=source)
    if not isinstance(document, dict):
        raise ConfigError(f"{where}: the document must be a mapping of keys to values.")
    version = document.get("version", 1)
    if not isinstance(version, int) or version < 1 or version > SCHEMA_VERSION:
        raise ConfigError(f"{where}: unsupported version {version!r}; this build writes {SCHEMA_VERSION}.")

    interfaces: dict[str, list[dict[str, Any]]] = {side: [] for side in SIDES}
    mappings: list[InputCanMapping] = []
    forces: list[InputForce] = []
    seen_targets: dict[tuple[str, str], str] = {}

    raw_interfaces = document.get("interfaces") or []
    if not isinstance(raw_interfaces, list):
        raise ConfigError(f"{where}: 'interfaces' must be a list.")
    for position, entry in enumerate(raw_interfaces, start=1):
        label = f"{where}: interfaces[{position}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{label} must be a mapping with 'name' and 'elements'.")
        name = str(entry.get("name", "") or "").strip()
        side = str(entry.get("side", "input") or "input").strip().lower()
        if side not in SIDES:
            raise ConfigError(f"{label}: side must be 'input' or 'output', not {side!r}.")
        _check_identifier(name, f"{label}: interface name")
        elements = entry.get("elements") or []
        if not isinstance(elements, list) or not elements:
            raise ConfigError(f"{label} ({name}) needs a non-empty 'elements' list.")
        bus = {"name": name, "elements": []}
        for index, raw_element in enumerate(elements, start=1):
            element_label = f"{label}.elements[{index}]"
            if not isinstance(raw_element, dict):
                raise ConfigError(f"{element_label} must be a mapping.")
            if raw_element.get("enabled", True) is False:
                continue
            element_name = str(raw_element.get("element", "") or "").strip()
            _check_identifier(element_name, f"{element_label}: element name")
            dtype = str(raw_element.get("dtype", "") or DEFAULT_DTYPE).strip()
            can_signal = str(raw_element.get("can_signal", "") or "").strip()
            formula = str(raw_element.get("formula", "") or "").strip()
            status_mapping = _status_mapping(raw_element.get("status_mapping"), element_label)
            value = raw_element.get("value", None)
            target = (norm(name), norm(element_name))
            if target in seen_targets:
                raise ConfigError(
                    f"{element_label}: {name}.{element_name} is already defined in {seen_targets[target]}."
                )
            seen_targets[target] = f"interfaces[{position}]"
            if can_signal and value not in (None, ""):
                raise ConfigError(
                    f"{element_label}: give either 'can_signal' or a constant 'value', not both."
                )
            if formula and not can_signal:
                raise ConfigError(f"{element_label}: 'formula' needs a 'can_signal' to transform.")
            _check_formula(formula, element_label)
            bus["elements"].append({
                "name": element_name,
                "dataType": dtype,
                "canSignal": can_signal,
            })
            if side == "input" and can_signal:
                mappings.append(InputCanMapping(name, element_name, can_signal, formula, status_mapping or None))
            elif side == "input" and value not in (None, ""):
                forces.append(InputForce(name, element_name, _number(value, element_label)))
        if bus["elements"]:
            interfaces[side].append(bus)

    legacy_mappings, legacy_forces = _legacy_entries(document, where, seen_targets)
    mappings.extend(legacy_mappings)
    forces.extend(legacy_forces)

    keywords = document.get("excel_skip_keywords", [])
    if keywords is None:
        keywords = []
    if not isinstance(keywords, list) or any(
        not isinstance(keyword, str) or not keyword.strip() for keyword in keywords
    ):
        raise ConfigError(f"{where}: 'excel_skip_keywords' must be a list of non-empty strings.")

    return MappingConfig(
        version=version,
        source=source,
        interfaces=interfaces,
        mappings=tuple(mappings),
        forces=tuple(forces),
        excel_skip_keywords=tuple(dict.fromkeys(keyword.strip().casefold() for keyword in keywords)),
    )


def _legacy_entries(
    document: dict[str, Any], where: str, seen_targets: dict[tuple[str, str], str],
) -> tuple[list[InputCanMapping], list[InputForce]]:
    """``input_mappings`` and ``input_forces`` as 0.x wrote them, still supported."""
    mappings: list[InputCanMapping] = []
    forces: list[InputForce] = []
    for key, is_force in (("input_mappings", False), ("input_forces", True)):
        entries = document.get(key) or []
        if not isinstance(entries, list):
            raise ConfigError(f"{where}: '{key}' must be a list.")
        for index, entry in enumerate(entries, start=1):
            label = f"{where}: {key}[{index}]"
            if not isinstance(entry, dict):
                raise ConfigError(f"{label} must be a mapping.")
            if entry.get("enabled", True) is False:
                continue
            interface = str(entry.get("interface", "") or "").strip()
            element = str(entry.get("element", "") or "").strip()
            if not interface or not element:
                raise ConfigError(f"{label} needs 'interface' and 'element'.")
            target = (norm(interface), norm(element))
            if target in seen_targets:
                raise ConfigError(
                    f"{label}: {interface}.{element} is already defined in {seen_targets[target]}."
                )
            seen_targets[target] = f"{key}[{index}]"
            if is_force:
                value = entry.get("value", None)
                if value is None or value == "":
                    raise ConfigError(f"{label} needs a numeric 'value'.")
                forces.append(InputForce(interface, element, _number(value, label)))
                continue
            can_signal = str(entry.get("can_signal", "") or "").strip()
            if not can_signal:
                raise ConfigError(f"{label} needs 'can_signal'.")
            formula = str(entry.get("formula", "") or "").strip()
            _check_formula(formula, label)
            status_mapping = _status_mapping(entry.get("status_mapping"), label)
            mappings.append(InputCanMapping(interface, element, can_signal, formula, status_mapping or None))
    return mappings, forces


def parse_txt(text: str, source: Path | None = None) -> dict[str, Any]:
    """The TXT syntax of the same schema.

    ``[input]`` / ``[output]`` sections, one ``Interface.Element: dtype`` line per
    element and indented ``key = value`` options below it. Files written for 0.x,
    which have no sections and no options, read as input interfaces.
    """
    where = source.name if source is not None else "mapping config"
    interfaces: dict[tuple[str, str], dict[str, Any]] = {}
    document: dict[str, Any] = {"version": SCHEMA_VERSION, "interfaces": []}
    side = "input"
    current: dict[str, Any] | None = None
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        section = _SECTION_RE.match(line.strip())
        if section:
            name = section.group(1).lower()
            if name == "options":
                side, current = name, None
                continue
            side, current = name, None
            continue
        option = _OPTION_RE.match(line.strip()) if line[:1].isspace() else None
        if option:
            key, value = option.group(1).lower(), option.group(2).strip()
            if side == "options":
                if key != "excel_skip_keywords":
                    raise ConfigError(f"{where}:{number}: unknown option {key!r} in [options].")
                document["excel_skip_keywords"] = [
                    word.strip() for word in value.split(",") if word.strip()
                ]
                continue
            if current is None:
                raise ConfigError(f"{where}:{number}: '{line.strip()}' does not belong to an element.")
            if key not in {"can_signal", "formula", "status_mapping", "value", "enabled"}:
                raise ConfigError(f"{where}:{number}: unknown option {key!r}.")
            current[key] = _txt_value(key, value, f"{where}:{number}")
            continue
        if side == "options":
            raise ConfigError(f"{where}:{number}: [options] holds settings, not elements.")
        target = _TARGET_RE.match(line.strip())
        if not target:
            raise ConfigError(
                f"{where}:{number}: expected 'Interface.Element: datatype', got {line.strip()!r}."
            )
        interface_name, element_name, dtype = target.groups()
        dtype = dtype.strip() or DEFAULT_DTYPE
        key = (side, norm(interface_name))
        bus = interfaces.get(key)
        if bus is None:
            bus = {"name": interface_name, "side": side, "elements": []}
            interfaces[key] = bus
            document["interfaces"].append(bus)
        current = {"element": element_name, "dtype": dtype}
        bus["elements"].append(current)
    return document


def _txt_value(key: str, value: str, where: str) -> Any:
    if key == "enabled":
        return value.strip().lower() not in {"false", "0", "no"}
    if key == "value":
        lowered = value.strip().lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        return value.strip()
    if key == "status_mapping":
        pairs: dict[str, str] = {}
        for part in value.split(","):
            if not part.strip():
                continue
            if ":" not in part:
                raise ConfigError(f"{where}: status_mapping needs 'can:model' pairs, got {part.strip()!r}.")
            can_value, model_value = part.split(":", 1)
            pairs[can_value.strip()] = model_value.strip()
        return pairs
    return value


# -- writing ------------------------------------------------------------------------


def upgraded_document(config: MappingConfig) -> dict[str, Any]:
    """The same content as a version 2 document, ready to be written out."""
    document: dict[str, Any] = {"version": SCHEMA_VERSION}
    if config.excel_skip_keywords:
        document["excel_skip_keywords"] = list(config.excel_skip_keywords)
    mapped = {mapping.target_key: mapping for mapping in config.mappings}
    forced = {force.target_key: force for force in config.forces}
    used: set[tuple[str, str]] = set()
    interfaces: list[dict[str, Any]] = []
    for side in SIDES:
        for bus in config.interfaces[side]:
            elements = []
            for element in bus["elements"]:
                target = (norm(bus["name"]), norm(element["name"]))
                used.add(target)
                entry: dict[str, Any] = {"element": element["name"], "dtype": element["dataType"]}
                mapping = mapped.get(target)
                force = forced.get(target)
                if element.get("canSignal"):
                    entry["can_signal"] = element["canSignal"]
                if mapping is not None:
                    entry["can_signal"] = mapping.can_signal
                    if mapping.formula:
                        entry["formula"] = mapping.formula
                    if mapping.status_mapping:
                        entry["status_mapping"] = {
                            _plain(key): _plain(value) for key, value in mapping.status_mapping.items()
                        }
                elif force is not None:
                    entry["value"] = _plain(force.value)
                elements.append(entry)
            interfaces.append({"name": bus["name"], "side": side, "elements": elements})
    for target, mapping in mapped.items():
        if target in used:
            continue
        entry = {"element": mapping.element, "dtype": DEFAULT_DTYPE, "can_signal": mapping.can_signal}
        if mapping.formula:
            entry["formula"] = mapping.formula
        if mapping.status_mapping:
            entry["status_mapping"] = {
                _plain(key): _plain(value) for key, value in mapping.status_mapping.items()
            }
        _append_element(interfaces, mapping.interface, entry)
    for target, force in forced.items():
        if target in used:
            continue
        _append_element(interfaces, force.interface,
                        {"element": force.element, "dtype": DEFAULT_DTYPE, "value": _plain(force.value)})
    if interfaces:
        document["interfaces"] = interfaces
    return document


def _plain(value: float) -> float | int:
    """Write 2.0 as 2, so a round trip through JSON or TXT stays readable."""
    return int(value) if float(value).is_integer() else float(value)


def _append_element(interfaces: list[dict[str, Any]], name: str, entry: dict[str, Any]) -> None:
    for bus in interfaces:
        if norm(bus["name"]) == norm(name) and bus["side"] == "input":
            bus["elements"].append(entry)
            return
    interfaces.append({"name": name, "side": "input", "elements": [entry]})


def write_config(path: Path, config: MappingConfig) -> Path:
    """Write ``config`` as version 2, in the syntax the file name asks for."""
    document = upgraded_document(config)
    suffix = path.suffix.lower()
    if suffix == ".json":
        text = json.dumps(document, indent=2) + "\n"
    elif suffix == ".txt":
        text = _txt_text(document)
    elif suffix in (".yaml", ".yml"):
        import yaml

        text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    else:
        raise ConfigError(f"{path.name}: mapping files are .yaml, .yml, .json or .txt.")
    path.write_text(text, encoding="utf-8")
    return path


def _txt_text(document: dict[str, Any]) -> str:
    lines = ["# CAN Toolbox mapping, schema version 2"]
    if document.get("excel_skip_keywords"):
        lines.append("[options]")
        lines.append("    excel_skip_keywords = " + ", ".join(document["excel_skip_keywords"]))
    for side in SIDES:
        buses = [bus for bus in document.get("interfaces", []) if bus["side"] == side]
        if not buses:
            continue
        lines.append(f"[{side}]")
        for bus in buses:
            for element in bus["elements"]:
                lines.append(f"{bus['name']}.{element['element']}: {element.get('dtype', DEFAULT_DTYPE)}")
                for key in ("can_signal", "formula", "value"):
                    if element.get(key) not in (None, ""):
                        lines.append(f"    {key} = {element[key]}")
                if element.get("status_mapping"):
                    pairs = ", ".join(f"{key}:{value}" for key, value in element["status_mapping"].items())
                    lines.append(f"    status_mapping = {pairs}")
    return "\n".join(lines) + "\n"


# -- helpers ------------------------------------------------------------------------


def norm(value: Any) -> str:
    """Compare names the way the converter does: letters and digits, lower case."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _check_identifier(name: str, label: str) -> None:
    if not name:
        raise ConfigError(f"{label} is empty.")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
        raise ConfigError(f"{label} must be a MATLAB identifier, got {name!r}.")


def _check_formula(formula: str, label: str) -> None:
    if not formula:
        return
    from can_toolbox.blf_mat.converter import validate_signal_formula

    try:
        validate_signal_formula(formula)
    except Exception as exc:  # the converter raises RuntimeError with its own wording
        raise ConfigError(f"{label}: {exc}") from exc


def _status_mapping(value: Any, label: str) -> dict[float, float]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{label}: status_mapping must be a mapping of CAN value to model value.")
    mapping: dict[float, float] = {}
    for key, model_value in value.items():
        mapping[_number(key, f"{label}.status_mapping key")] = _number(
            model_value, f"{label}.status_mapping value"
        )
    return mapping


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        return float(int(value))
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{label} must be a number, got {value!r}.") from exc
    if not math.isfinite(number):
        raise ConfigError(f"{label} must be finite, got {value!r}.")
    return number
