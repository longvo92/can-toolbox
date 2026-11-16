"""Non-destructive runtime diagnostics; never start MATLAB or install packages."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable

from can_toolbox import __version__
from can_toolbox.blf_mat.options import find_matlab_executable

MODULES = ("numpy", "numba", "scipy.io", "can", "cantools", "openpyxl", "yaml")


def check_environment(
    matlab: str | None = None, emit: Callable[[str], None] = print, *, require_matlab: bool = False
) -> int:
    emit(f"CAN Toolbox {__version__} | Python {sys.version.split()[0]}")
    failures = 0
    supported = sys.version_info[:2] >= (3, 11)
    emit(f"[{'OK' if supported else 'FAIL'}] Python support: 3.11 or newer")
    failures += not supported
    for name in MODULES:
        try:
            module = importlib.import_module(name)
            emit(f"[OK] {name} {getattr(module, '__version__', '')}".rstrip())
        except Exception as exc:
            failures += 1
            emit(f"[FAIL] {name}: {exc}")
    try:
        emit(f"[OK] MATLAB executable: {find_matlab_executable(matlab)}")
    except Exception as exc:
        failures += require_matlab
        emit(f"[{'FAIL' if require_matlab else 'OPTIONAL'}] MATLAB: {exc}")
    emit("MATLAB/Simulink version, license and Dataset serialization require an actual conversion.")
    if failures:
        emit("Reinstall CAN Toolbox to restore missing Python packages.")
    return 1 if failures else 0
