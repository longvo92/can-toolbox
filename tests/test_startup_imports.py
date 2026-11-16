"""Opening the window must not load the heavy engine stacks; they load on first use."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.gui

_SRC = Path(__file__).resolve().parents[1] / "src"
_PROBE = """
import sys
from PySide6.QtWidgets import QApplication
app = QApplication([])
from can_toolbox.ui.main_window import MainWindow
window = MainWindow()
heavy = ("numba", "llvmlite", "cantools", "can", "asammdf", "pandas", "scipy")
print(",".join(sorted(name for name in heavy if name in sys.modules)))
"""


def test_main_window_defers_engine_imports():
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(_SRC), "QT_QPA_PLATFORM": "offscreen"},
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
