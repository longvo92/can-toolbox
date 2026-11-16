"""The engines must import without any GUI framework."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"

_PROBE = """
import importlib, pkgutil, sys
import can_toolbox.blf_mat, can_toolbox.canlog, can_toolbox.dbc_compare
for package in (can_toolbox.dbc_compare, can_toolbox.blf_mat, can_toolbox.canlog):
    for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        importlib.import_module(module.name)
import can_toolbox.blf_mat.converter as converter
converter.load_runtime_dependencies()
leaked = sorted(name for name in sys.modules if name.split(".")[0] in {"PySide6", "shiboken6", "tkinter"})
print(",".join(leaked))
"""


def test_engines_import_no_gui_framework():
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(_SRC)},
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
