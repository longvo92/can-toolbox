"""Validate conversion inputs and find MATLAB; the engine itself takes resolved paths."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from can_toolbox.app_paths import application_directory
from can_toolbox.blf_mat.config import SUFFIXES as CONFIG_SUFFIXES
from can_toolbox.blf_mat.config import ConfigError, load_config
from can_toolbox.blf_mat.converter import SelectedPaths, convert

OUTPUT_FORMATS = ("mat", "dataset")
LOG_SUFFIXES = (".blf",)
EXCEL_SUFFIXES = (".xlsx", ".xlsm")
DEFAULT_CONFIG_NAMES = ("signal_mapping.yaml", "signal_mapping.yml", "signal_mapping.json",
                        "signal_mapping.txt")
DEFAULT_OUTPUT_FOLDER = "mat_output"


class OptionError(ValueError):
    """An input the user has to correct before a conversion can start."""


@dataclass(frozen=True)
class ConversionOptions:
    """Conversion inputs as text, the way a window holds them; blank means "not set"."""

    blf: str
    dbc: str = ""
    excel: str = ""
    config: str = ""
    output_folder: str = ""
    matlab: str = ""
    output_format: str = "mat"
    base_name: str = ""
    dbcs: tuple[str, ...] = field(default_factory=tuple)


def existing_file(value: str, label: str, suffixes: tuple[str, ...] = ()) -> Path:
    path = Path(value).expanduser()
    if not path.is_file():
        raise OptionError(f"{label} does not exist: {path}")
    if suffixes and path.suffix.lower() not in suffixes:
        raise OptionError(f"{label} must have one of these extensions: {', '.join(suffixes)}. Got: {path}")
    return path.resolve()


def existing_dbc_source(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_file():
        if path.suffix.lower() != ".dbc":
            raise OptionError(f"DBC file must be a .dbc file. Got: {path}")
        return path.resolve()
    if path.is_dir():
        return path.resolve()
    raise OptionError(f"DBC source does not exist: {path}")


def default_output_folder(log: Path) -> Path:
    base = log.parent if log.is_file() else log
    return (base / DEFAULT_OUTPUT_FOLDER).resolve()


def default_config_path() -> Path | None:
    """A mapping file beside the executable, used when the user names none."""
    for name in DEFAULT_CONFIG_NAMES:
        candidate = application_directory() / name
        if candidate.is_file():
            return candidate
    return None


def find_matlab_executable(explicit: str | None = None) -> Path:
    """MATLAB from the setting, PATH or the usual install folders."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise OptionError(f"MATLAB executable does not exist: {path}")
        return path.resolve()
    found = shutil.which("matlab")
    if found:
        return Path(found).resolve()
    roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "MATLAB"]
    candidates = []
    for root in roots:
        if root.is_dir():
            candidates.extend(sorted(root.glob("R*/bin/matlab.exe"), reverse=True))
    if candidates:
        return candidates[0].resolve()
    raise OptionError(
        "MATLAB was not found. Set the executable in Settings, or export MAT files instead of a Dataset."
    )


def build_selected_paths(options: ConversionOptions) -> SelectedPaths:
    """Validate ``options`` and resolve them into converter inputs; raises :class:`OptionError`."""
    if options.output_format not in OUTPUT_FORMATS:
        raise OptionError(f"Unknown output format: {options.output_format}")
    log = existing_file(options.blf, "BLF file", LOG_SUFFIXES)
    sources = [options.dbc, *options.dbcs] if options.dbc else list(options.dbcs)
    dbc_sources = [existing_dbc_source(value) for value in sources if value]
    excel = existing_file(options.excel, "Excel template", EXCEL_SUFFIXES) if options.excel else None
    config_path = (
        existing_file(options.config, "Mapping config", CONFIG_SUFFIXES) if options.config
        else default_config_path()
    )
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise OptionError(str(exc)) from exc
    matlab_exe = find_matlab_executable(options.matlab or None) if options.output_format == "dataset" else None
    output_folder = (
        Path(options.output_folder).expanduser().resolve() if options.output_folder
        else default_output_folder(log)
    )
    return SelectedPaths(
        blf_files=[log],
        output_folder=output_folder,
        dbc_sources=dbc_sources,
        excel=excel,
        config=config,
        matlab_exe=matlab_exe,
        output_format=options.output_format,
        base_name=options.base_name,
    )


def run_conversion(options: ConversionOptions, log_callback: Callable[[str], None] | None = None) -> SelectedPaths:
    """Validate and convert; returns the resolved inputs. Validation and conversion errors propagate."""
    paths = build_selected_paths(options)
    convert(paths, log_callback=log_callback)
    return paths
