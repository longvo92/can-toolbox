# Architecture

CAN Toolbox is a GUI-only PySide6 app. One shell window hosts one tab per tool; each tab drives a Qt-free engine that tests and `scripts/smoke.py` also call directly. Python 3.11+ is supported.

## Components and flow

| Module | Responsibility |
|---|---|
| `app_paths.py` | Resource lookup (source, zipapp, PyInstaller) and the folder searched for user configuration |
| `dbc_compare/core/parser.py` | Parse DBCs and reject duplicate message names, signal names and frame keys before dictionary loss |
| `dbc_compare/core/discovery.py`, `pairing.py` | Discover DBC files and select renamed file pairs |
| `dbc_compare/core/rename.py` | Score message and signal renames using the 0.6.7 detectors |
| `dbc_compare/core/comparator.py`, `models.py` | Compare entities, account for known inventory, record file diagnostics and filter changes |
| `dbc_compare/report/excel.py` | Export a formatted workbook atomically |
| `dbc_compare/pipeline.py` | `compare_inputs` and `run_comparison`: the entry points the Compare tab, tests and smoke script share |
| `blf_mat/converter.py`, `mapping.py`, `frames.py` | Decode BLF logs, resolve DBC/Excel/TXT/YAML definitions and write MAT files or package Datasets through MATLAB |
| `blf_mat/options.py` | `ConversionOptions`, validation (`OptionError`), MATLAB discovery and `run_conversion` |
| `blf_mat/checks.py` | Non-destructive environment report; never starts MATLAB |
| `ui/main_window.py` | Shell: header, Settings/Help menus, tab widget, language propagation, close guard |
| `ui/compare_tab.py`, `ui/blf_tab.py` | One tab per tool with its own cards, workers, progress, status and log |
| `ui/widgets.py`, `ui/style.py`, `ui/app.py` | Shared widgets and text binding, theme, entry point |

A tab exposes `title_key`, `subtitle_key`, `busy_changed`, `set_languages`, `is_busy`, `stop_workers` and `wait_for_workers`. The shell disables language changes while any tab is busy and asks before quitting while a worker runs. Settings live in `QSettings("CanToolbox", "CANToolbox")`: languages at the top level, tab inputs under `compare/` and `blf/`.

`tests/test_engine_is_qt_free.py` imports every engine module in a fresh interpreter and fails if PySide6, shiboken6 or tkinter is loaded. The `engine` CI job installs everything except PySide6.

## DBC comparison

The `classic-v067` pipeline matches same-relative-path files first, then considers remaining files for rename pairing. Within each file pair it reserves equal frame keys, then equal message names, then applies the message rename detector. Within each message pair it reserves equal signal names and applies the signal rename detector to the remainder. Scores and thresholds are those of 0.6.7: DBC 0.55, message 0.60, signal 0.65 and event-like signal 0.55. A uniquely matching full signal-property set can be reserved before heuristic matching; ambiguity lowers heuristic confidence. Unmatched entities become Added/Removed. Cross-parent moves are not paired.

`compare_paths`, `compare_files`, `compare_folders`, `compare_manual` and `compare_databases` remain the comparator entry points. Direct file selection pairs the chosen files and aborts on a parse error. Saved manual DBC mappings are fixed constraints, including `None` for Removed and unreferenced NEW files for Added. Valid peers of failed fixed pairs are Not compared. Folder parse failures yield Incomplete reports with side/path/reason and Unknown inventory counts. ECU mapping is validated against every readable side.

`apply_ecu_focus(result, nodes)` filters rows after matching using the original OLD/NEW route context and one step of ECU pairing; coverage and diagnostics remain full-input. `write_excel_report(result, path, *, language="en")` localizes presentation only. `default_report_path(old, new)` places `compared_<old>_vs_<new>.xlsx` beside NEW. Export writes a sibling temporary workbook and replaces the destination only after a successful save.

## BLF conversion

Imported from blf2mat 0.1.3 (`github.com/longvo92/blf2mat` @ `56fdfa9`). `run_conversion(options)` validates with `build_selected_paths` and calls `converter.convert(paths, log_callback=...)`, which logs five `[n/5]` steps. numpy, scipy, python-can, cantools and PyYAML load on the first conversion so the window opens quickly.

Without definitions a BLF becomes a `Frames` struct. With a DBC, signals are decoded per message. TXT schemas, Excel sheets and YAML `input_mappings`/`input_forces` select interfaces; only signals feeding a selected interface are decoded. Each signal passes CAN decode, `status_mapping`, the AST-validated `formula` and a MATLAB-like datatype cast. Duplicate timestamps keep the last value; input signals from Excel or TXT get a zero sample at time 0. Excel sheets are read by `mapping.Workbook`, an openpyxl grid that reproduces the former pandas reader (trimmed blanks, NA texts as blank, integral floats as int). The Dataset format writes raw MAT files, generates one MATLAB script and runs `matlab -batch` once without a console window.

Engine log text stays English in both tabs; the GUI chrome and the Excel report are localized.

## Verification

```powershell
$env:PYTHONPATH = "src"
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
python -m ruff check .
python scripts/smoke.py --gui
python scripts/evaluate_pairing.py --benchmark
```

`-m gui` selects the Qt tab tests. The smoke script compares the bundled examples and converts a synthesized BLF to MAT three ways; it never launches MATLAB. Dataset tests mock MATLAB, so a Dataset export still needs a manual run against a licensed MATLAB. The pairing benchmark is synthetic and does not claim production-data accuracy or machine-independent timing.

## Build and release

`python scripts/build.py` creates the Windows executable and zipapp in `dist/`. Both bundles include only dated release history for **Help → Release note**. `scripts/release_check.py` checks release metadata and changelog consistency. The release workflow tests, smoke-tests, builds and starts both artifacts from `main`; publishing requires an explicit release action.
