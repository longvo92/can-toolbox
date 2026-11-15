# DBC Compare Tool

Compare CAN DBC files or baseline folders and generate an engineering-grade Excel change report through a CLI and an optional GUI.

## Layout
- `src/dbc_compare_tool/`: `core/` (comparison engine), `report/` (Excel reports), `ui/` (PySide6 GUI), `cli.py`, `i18n.py`, `release_notes.py`.
- `scripts/` (`build.py`, `release_check.py`, `evaluate_pairing.py`), `examples/`, `resources/help/`, `tests/`; Windows launchers `run_gui.bat` and `run_cli.bat`.

## Runtime
- Python >=3.9, cantools and openpyxl as declared in `pyproject.toml`; PySide6 is optional.

## Commands
- Environment: `PYTHONPATH=src` (tests must import the working tree, not an installed copy).
- Test: `python -m unittest discover -s tests -v`. Lint: `python -m ruff check .`
- Smoke: `python -m dbc_compare_tool.cli --old examples/old --new examples/new --out <temporary-report.xlsx>`
- Build: `python scripts/build.py`. Release gate: `python scripts/release_check.py <X.Y.Z> --notes <file>`.

## Invariants
- The comparison engine and report generation stay independent of GUI frameworks; the headless CLI works without PySide6.
- CLI and GUI produce the same comparison results and reports.
- Public CLI options, report formats and configuration stay compatible unless a documented migration says otherwise.

Working rules live in the owner's global instructions.
