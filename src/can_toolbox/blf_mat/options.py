"""Validate BLF conversion inputs and run a conversion (no argparse, no Qt).

The BLF -> MAT tab builds a :class:`ConversionOptions` from its fields; tests and
the smoke script use the same entry points.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from can_toolbox.app_paths import application_directory
from can_toolbox.blf_mat.converter import SelectedPaths, convert

OUTPUT_FORMATS = ("mat", "dataset")
DEFAULT_CONFIG_NAME = "signal_mapping.yaml"
DEFAULT_OUTPUT_FOLDER = "mat_output"


class OptionError(ValueError):
    """An input the user has to correct before a conversion can start."""


@dataclass(frozen=True)
class ConversionOptions:
    """Conversion inputs as entered in the GUI; blank strings mean "not set"."""

    blf: str
    dbc: str = ""
    excel: str = ""
    input_schema: str = ""
    output_schema: str = ""
    # TXT schemas without a fixed side; with Excel the workbook decides the side.
    schema: tuple[str, ...] = ()
    output_folder: str = ""
    config: str = ""
    matlab: str = ""
    output_format: str = "mat"
    input_sheets: tuple[str, ...] = ()
    output_sheets: tuple[str, ...] = ()
    element_column: str = ""
    can_column: str = ""
    interface_column: str = ""
    dtype_column: str = ""
    header_row: int | None = None


def existing_file(value: str, label: str, suffixes: tuple[str, ...] = ()) -> Path:
    path = Path(value).expanduser()
    if not path.is_file():
        raise OptionError(f"{label} does not exist: {path}")
    if suffixes and path.suffix.lower() not in suffixes:
        raise OptionError(f"{label} must have one of these extensions: {', '.join(suffixes)}. Got: {path}")
    return path.resolve()


def existing_dbc_source(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_dir():
        return path.resolve()
    return existing_file(value, "DBC file or folder", (".dbc",))


def collect_blf_files(value: str) -> tuple[Path, list[Path]]:
    """Return the BLF source and the ``.blf`` files it names (folders recurse)."""
    if not value.strip():
        raise OptionError("Select a BLF file or folder.")
    source = Path(value).expanduser().resolve()
    if source.is_file() and source.suffix.lower() == ".blf":
        return source, [source]
    if source.is_dir():
        files = sorted(
            (path for path in source.rglob("*") if path.is_file() and path.suffix.lower() == ".blf"),
            key=lambda path: str(path).lower(),
        )
        if not files:
            raise OptionError(f"No .blf files found in {source}")
        return source, files
    raise OptionError(f"BLF file/folder does not exist: {source}")


def default_output_folder(blf_source: Path) -> Path:
    """``mat_output`` inside a BLF folder, or beside a single BLF file."""
    return (blf_source if blf_source.is_dir() else blf_source.parent) / DEFAULT_OUTPUT_FOLDER


def default_config_path() -> Path | None:
    """``signal_mapping.yaml`` beside the application, when present."""
    candidate = application_directory() / DEFAULT_CONFIG_NAME
    return candidate if candidate.is_file() else None


def find_matlab_executable(explicit: str | None = None) -> Path:
    """Resolve the MATLAB executable without opening any dialog."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise OptionError(f"MATLAB executable does not exist: {path}")
        return path.resolve()

    for name in ("matlab.exe", "matlab"):
        found = shutil.which(name)
        if found:
            return Path(found).resolve()

    candidates: list[Path] = []
    for root in (
        Path(r"C:\Program Files\MATLAB"),
        Path(r"C:\Program Files (x86)\MATLAB"),
        Path(r"C:\Tools"),
        Path(r"C:\Tools\MATLAB"),
    ):
        if root.exists():
            candidates.extend(root.glob("R*/bin/matlab.exe"))
    # Prefer the newest release-like path when several installations exist.
    candidates = sorted({candidate.resolve() for candidate in candidates}, reverse=True)
    if candidates:
        return candidates[0]
    raise OptionError(
        "MATLAB was not found. Add MATLAB to PATH or select matlab.exe, for example "
        r'"C:\Program Files\MATLAB\R2024b\bin\matlab.exe".'
    )


def build_selected_paths(options: ConversionOptions) -> SelectedPaths:
    """Validate ``options`` and resolve them into converter inputs; raises :class:`OptionError`."""
    if options.output_format not in OUTPUT_FORMATS:
        raise OptionError(f"Unknown output format: {options.output_format}")
    blf_source, blf_files = collect_blf_files(options.blf)
    excel = existing_file(options.excel, "Excel file", (".xlsx", ".xlsm")) if options.excel else None
    dbc_folder = existing_dbc_source(options.dbc) if options.dbc else None

    schema_files = [existing_file(value, "Schema TXT", (".txt",)) for value in options.schema]
    if schema_files and (options.input_schema or options.output_schema):
        raise OptionError("Use input/output TXT schemas or shared TXT schemas, not both.")
    input_schema = existing_file(options.input_schema, "Input schema TXT", (".txt",)) if options.input_schema else None
    output_schema = (
        existing_file(options.output_schema, "Output schema TXT", (".txt",)) if options.output_schema else None
    )
    if not excel and schema_files:
        if len(schema_files) > 2:
            raise OptionError("Without Excel, give at most an input TXT and an output TXT schema.")
        input_schema = schema_files[0]
        output_schema = schema_files[1] if len(schema_files) == 2 else None
    if input_schema or output_schema:
        schema_files = [path for path in (input_schema, output_schema) if path]

    mapping_config = (
        existing_file(options.config, "Mapping config", (".yaml", ".yml")) if options.config else default_config_path()
    )

    excel_options = (
        options.input_sheets, options.output_sheets, options.element_column, options.can_column,
        options.interface_column, options.dtype_column, options.header_row,
    )
    if excel is None and any(value not in (None, "", ()) for value in excel_options):
        raise OptionError("Excel sheet, column and header row options need an Excel workbook.")
    if options.header_row is not None and options.header_row < 1:
        raise OptionError("Header row must be at least 1.")

    matlab_exe = find_matlab_executable(options.matlab or None) if options.output_format == "dataset" else None
    output_folder = (
        Path(options.output_folder).expanduser().resolve() if options.output_folder else default_output_folder(blf_source)
    )
    return SelectedPaths(
        excel=excel,
        dbc_folder=dbc_folder,
        blf_files=blf_files,
        schema_files=schema_files,
        input_schema=input_schema,
        output_schema=output_schema,
        output_folder=output_folder,
        mapping_config=mapping_config,
        matlab_exe=matlab_exe,
        output_format=options.output_format,
        input_sheets=tuple(options.input_sheets),
        output_sheets=tuple(options.output_sheets),
        element_column=options.element_column or None,
        can_column=options.can_column or None,
        interface_column=options.interface_column or None,
        dtype_column=options.dtype_column or None,
        header_row=options.header_row,
    )


def run_conversion(options: ConversionOptions, log_callback: Callable[[str], None] | None = None) -> SelectedPaths:
    """Validate and convert; returns the resolved inputs. Validation and conversion errors propagate."""
    paths = build_selected_paths(options)
    convert(paths, log_callback=log_callback)
    return paths
