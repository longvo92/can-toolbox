"""Headless smoke test of the CAN Toolbox engines.

The app is GUI-only; this developer script exercises the same Qt-free engine
entry points the GUI tabs call, so CI and release builds prove the engines work
without driving the window. It never launches MATLAB.

Usage:
    python scripts/smoke.py              # all engine stages
    python scripts/smoke.py --gui        # also open the main window offscreen
    python scripts/smoke.py --stage compare
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

EXAMPLES = REPO_ROOT / "examples"


def _assert_sheets(path: Path, expected: list[str]) -> None:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True)
    try:
        if workbook.sheetnames != expected:
            raise AssertionError(f"{path.name}: sheets {workbook.sheetnames}, expected {expected}")
    finally:
        workbook.close()


def stage_compare(workdir: Path) -> None:
    from can_toolbox.dbc_compare.pipeline import run_comparison

    folders = ["Summary", "DBC Overview", "Message Details", "Signal Details"]
    files = ["Summary", "Message Details", "Signal Details"]
    cases = (
        ("folders", EXAMPLES / "old", EXAMPLES / "new", {}, folders),
        ("unchanged", EXAMPLES / "old", EXAMPLES / "new", {"include_unchanged": True}, folders),
        ("files", EXAMPLES / "old" / "Bus_A.dbc", EXAMPLES / "new" / "Bus_A.dbc", {}, files),
    )
    for name, old, new, options, sheets in cases:
        result, report = run_comparison(old, new, workdir / f"{name}.xlsx", **options)
        _assert_sheets(report, sheets)
        print(f"compare/{name}: {result.completeness}, {result.summary()['Total Changes']} changes")


def stage_convert(workdir: Path) -> None:
    import can
    from openpyxl import Workbook
    from scipy.io import loadmat

    from can_toolbox.blf_mat.options import ConversionOptions, run_conversion

    root = workdir / "convert"
    root.mkdir()
    dbc = root / "bus.dbc"
    dbc.write_text(
        'VERSION ""\nNS_ :\nBS_:\nBU_: ECU\nBO_ 256 Sample: 2 ECU\n'
        ' SG_ SpeedCAN : 0|8@1+ (1,0) [0|255] "" ECU\n SG_ RequestCAN : 8|8@1+ (1,0) [0|255] "" ECU\n',
        encoding="ascii",
    )
    blf = root / "capture.blf"
    with can.BLFWriter(blf) as writer:
        for timestamp, data in ((10.0, [10, 2]), (10.5, [30, 3])):
            writer.on_message_received(can.Message(timestamp=timestamp, arbitration_id=256, data=data))
    excel = root / "interfaces.xlsx"
    book = Workbook()
    book.remove(book.active)
    for sheet, interface, signal in (("SWC_INF", "Inputs", "SpeedCAN"), ("SWC_OUTF", "Outputs", "RequestCAN")):
        rows = book.create_sheet(sheet)
        rows.append(["Interface", "Data Element", "CAN Signal"])
        rows.append([interface, signal.removesuffix("CAN"), signal])
    book.save(excel)

    cases = (
        ("frames", {}, {"capture.mat": "Frames"}),
        ("dbc", {"dbc": str(dbc)}, {"capture_signals.mat": "Scenario"}),
        ("excel", {"dbc": str(dbc), "excel": str(excel)},
         {"capture_input.mat": "Scenario", "capture_output.mat": "Scenario"}),
    )
    for name, fields, expected in cases:
        output = root / name
        run_conversion(ConversionOptions(blf=str(blf), output_folder=str(output), **fields), log_callback=lambda _: None)
        for filename, variable in expected.items():
            if variable not in loadmat(output / filename):
                raise AssertionError(f"{name}: {filename} has no {variable}")
        print(f"convert/{name}: {', '.join(expected)}")


def stage_gui(_workdir: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from can_toolbox.ui.app import configure_appearance
    from can_toolbox.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    configure_appearance(app)
    window = MainWindow()
    try:
        titles = [window.tabs.tabText(index) for index in range(window.tabs.count())]
        if not titles:
            raise AssertionError("main window has no tabs")
        window.show()
        app.processEvents()
        print(f"gui: tabs {titles}")
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


STAGES: dict[str, Callable[[Path], None]] = {"compare": stage_compare, "convert": stage_convert}


def main() -> int:
    # Windows consoles often use cp1252; tab titles such as "BLF → MAT" must not crash the run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=sorted(STAGES), action="append", help="Run only these stages")
    parser.add_argument("--gui", action="store_true", help="Also open the main window offscreen")
    args = parser.parse_args()
    selected = [(name, STAGES[name]) for name in (args.stage or STAGES)]
    if args.gui:
        selected.append(("gui", stage_gui))
    with tempfile.TemporaryDirectory(prefix="can_toolbox_smoke_") as tmp:
        for name, stage in selected:
            try:
                stage(Path(tmp))
            except Exception as exc:  # report the failing stage by name
                print(f"FAILED {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 1
    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
