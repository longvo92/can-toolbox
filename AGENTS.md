# DBC Compare Tool

Compare CAN DBC files or baseline folders and generate an engineering-grade Excel change report through a CLI and an optional GUI.

## Layout
- `src/dbc_compare_tool/`: `core/` (comparison engine), `report/` (Excel reports), `ui/` (PySide6 GUI), `cli.py`, `i18n.py`, `release_notes.py`.
- `scripts/` (`build.py`, `release_check.py`, `evaluate_pairing.py`), `examples/`, `resources/help/`, `tests/`; Windows launcher `run_gui.bat`.

## Runtime
- Python >=3.11; PySide6, cantools, openpyxl, numpy, pandas, scipy, python-can and PyYAML as declared in `pyproject.toml`. MATLAB only for Dataset export.

## Commands
- Environment: `PYTHONPATH=src` (tests must import the working tree, not an installed copy).
- Test: `python -m pytest -q` (`-m gui` / `-m "not gui"` split the Qt tests). Lint: `python -m ruff check .`
- Smoke: `python scripts/smoke.py` (headless engine stages; `--gui` also opens the window offscreen)
- Build: `python scripts/build.py`. Release gate: `python scripts/release_check.py <X.Y.Z> --notes <file>`.

## Invariants
- The app is GUI-only: no CLI entry point. Engines (`dbc_compare/`) stay independent of GUI frameworks and are exercised headlessly by `scripts/smoke.py` and the tests.
- The GUI drives the same engine entry points as `dbc_compare/pipeline.py`; no comparison logic lives in `ui/`.
- GUI options, report formats and configuration stay compatible unless a documented migration says otherwise.

Working rules live in the owner's global instructions.
