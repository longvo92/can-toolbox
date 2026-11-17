"""The DBC comparison code must stay vendorable into dbc-compare-tool.

`dbc_compare/**`, `ui/compare_tab.py` and `ui/ecu_focus.py` are copied verbatim
into the standalone dbc-compare-tool repository, so they may only use relative
imports and must never reach back into `can_toolbox`.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
_PACKAGE = _SRC / "can_toolbox"

_SYNCED = sorted(_PACKAGE.glob("dbc_compare/**/*.py")) + [
    _PACKAGE / "ui" / "compare_tab.py",
    _PACKAGE / "ui" / "ecu_focus.py",
]


def _imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names.append(node.module or "")
    return names


def test_synced_modules_exist():
    assert _SYNCED, "no synced modules found"
    for path in _SYNCED:
        assert path.is_file(), path


def test_synced_modules_never_import_the_host_package():
    offenders = {
        str(path.relative_to(_SRC)): [name for name in _imports(path) if name.split(".")[0] == "can_toolbox"]
        for path in _SYNCED
    }
    assert {path: names for path, names in offenders.items() if names} == {}


def test_engine_modules_do_not_import_a_gui_framework():
    gui = {"PySide6", "shiboken6", "tkinter", "PyQt5", "PyQt6"}
    offenders = {
        str(path.relative_to(_SRC)): sorted(gui.intersection(name.split(".")[0] for name in _imports(path)))
        for path in sorted(_PACKAGE.glob("dbc_compare/**/*.py"))
    }
    assert {path: names for path, names in offenders.items() if names} == {}


def test_compare_translations_are_self_contained():
    from can_toolbox.dbc_compare.i18n import VI as COMPARE_VI
    from can_toolbox.i18n import VI

    assert COMPARE_VI
    assert set(COMPARE_VI).issubset(VI)
    for key, value in COMPARE_VI.items():
        assert VI[key] == value, key
