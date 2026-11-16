# CAN Toolbox

GUI-only Windows desktop app shipped as one PyInstaller exe: a CANoe-style log viewer (BLF/ASC/MF4 trace and signal graphics; log cutting planned; no simulation), DBC file/baseline comparison into an Excel change report, and BLF to MATLAB MAT/Simulink Dataset conversion.

## Layout
- `src/can_toolbox/`: `canlog/` (columnar `FrameTable`, Numba BLF reader, vectorized DBC decode), `dbc_compare/` (`core/` engine, `report/` Excel, `pipeline.py`), `blf_mat/` (converter, Excel/TXT/YAML mapping, `options.py` validation), `ui/` (shell `main_window.py`, `compare_tab.py`, `blf_tab.py`, `logview_tab.py`, `graphics.py`, `widgets.py`, `style.py`, `app.py`), `app_paths.py`, `i18n.py`, `release_notes.py`.
- `scripts/` (`build.py`, `release_check.py`, `smoke.py`, `evaluate_pairing.py`), `examples/` (DBC baselines, `blf/` mapping samples), `resources/help/`, `tests/`; Windows launcher `run_gui.bat`.

## Runtime
- Python >=3.11; PySide6, pyqtgraph, asammdf, cantools, openpyxl, numba, numpy, scipy, python-can and PyYAML as declared in `pyproject.toml`. MATLAB only for Dataset export.
- Distributed only as the exe: add runtime libraries freely when they help; no pyzw/zipapp or CLI builds.

## Commands
- Environment: `PYTHONPATH=src` and `QT_QPA_PLATFORM=offscreen` (tests must import the working tree, not an installed copy).
- Test: `python -m pytest -q` (`-m gui` / `-m "not gui"` split the Qt tests). Lint: `python -m ruff check .`
- Smoke: `python scripts/smoke.py` (headless compare and BLF stages; `--gui` also opens the window offscreen).
- Build: `python scripts/build.py` (exe only). Release gate: `python scripts/release_check.py <X.Y.Z> --notes <file>`.

## Invariants
- The app is GUI-only: no CLI entry point. `canlog/`, `dbc_compare/` and `blf_mat/` import no GUI framework (`tests/test_engine_is_qt_free.py`).
- `canlog` stays equivalent to python-can (frames) and cantools (signals); BLF objects it cannot represent are counted and reported, never dropped silently.
- Tabs drive the engines through `dbc_compare/pipeline.py` and `blf_mat/options.py`; no comparison or conversion logic lives in `ui/`.
- GUI options, report formats, MAT layouts and the YAML schema stay compatible unless a documented migration says otherwise.
- Engine log text stays English; GUI chrome and the Excel report are localized (EN/VI).
- Dataset export is verified only with a mocked MATLAB in tests; a licensed MATLAB run is separate evidence.

Working rules live in the owner's global instructions.
