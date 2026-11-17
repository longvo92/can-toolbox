# CAN Toolbox

GUI-only Windows desktop app shipped as one PyInstaller exe. The window is a CANoe-style log viewer (BLF/ASC/MF4 trace, signal graphics, no simulation) with one Export for every output format (BLF/ASC/MF4/CSV, MAT frames, MAT signals, Simulink Dataset); DBC file/baseline comparison into an Excel change report opens from the Tools menu.

## Layout
- `src/can_toolbox/`: `canlog/` (columnar `FrameTable`, Numba BLF reader, vectorized DBC decode, `export.py` jobs), `dbc_compare/` (`core/` engine, `report/` Excel, `pipeline.py`), `blf_mat/` (`config.py` schema v2, `excel_template.py`, converter, `mapping.py`, `options.py` validation), `ui/` (`logview/` window, panels, trace, tasks, dialogs, `signal_set.py` + `signal_panel.py` (the graph's signal list) and `export_dialog.py`; `main_window.py` shell, `tool_windows.py`, `compare_tab.py`, `graphics.py`, `settings_dialog.py`, `theme.py`, `widgets.py`, `app.py`), `app_paths.py`, `i18n.py`, `release_notes.py`.
- `scripts/` (`build.py`, `release_check.py`, `smoke.py`, `evaluate_pairing.py`), `examples/` (DBC baselines, `blf/` mapping samples), `resources/help/`, `resources/icons/` (toolbar SVGs tinted per theme), `tests/`; Windows launcher `run_gui.bat`.

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
- Opening the window imports no engine stack (numba, cantools/python-can, asammdf, scipy); engines import them on first use (`tests/test_startup_imports.py`).
- `canlog` stays equivalent to python-can (frames) and cantools (signals); BLF objects it cannot represent are counted and reported, never dropped silently.
- The window drives the engines through `dbc_compare/pipeline.py`, `canlog/export.py` and `blf_mat/options.py`; no comparison, cut or conversion logic lives in `ui/`.
- The graph draws what `ui/logview/signal_set.py` holds: groups, per-signal visibility and a colour fixed when the signal is added. The panel and the plots read that one model.
- One export engine: `run_export` cuts once and hands the same `FrameTable` to every format, signal formats included; nothing re-reads the log.
- A DBC assigned to one channel decodes only that channel, in the viewer and in signal export.
- Colours live only in `ui/theme.py`; `tests/test_theme.py` fails on a hex colour elsewhere under `ui/` and on contrast below WCAG AA.
- GUI options, report formats, MAT layouts and the mapping schema stay compatible unless a documented migration says otherwise (`docs/migration-2.0.md`). The schema is one document in YAML, JSON or TXT; 0.x files still load.
- Engine log text stays English; GUI chrome and the Excel report are localized (EN/VI).
- The DBC comparison code is vendored from the standalone [dbc-compare-tool](https://github.com/longvo92/dbc-compare-tool) repository, which is its source of truth: `dbc_compare/**` (translations included), `ui/compare_tab.py` and `ui/ecu_focus.py`. They use relative imports only and never import `can_toolbox` (`tests/test_dbc_compare_boundary.py`). Pulling an update means copying those files over and running the compare tests.
- Dataset export is verified only with a mocked MATLAB in tests; a licensed MATLAB run is separate evidence.

Working rules live in the owner's global instructions.
