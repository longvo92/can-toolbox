<div align="center">

# CAN Toolbox

**Read CAN logs like a trace, plot the signals, cut and convert them — and compare DBC baselines in Excel.**

[![CI](https://github.com/longvo92/can-toolbox/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/longvo92/can-toolbox/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-22A699.svg)](LICENSE)

[Download](https://github.com/longvo92/can-toolbox/releases/latest) · [Quick start](#quick-start) · [User Guide](resources/help/user_guide.md) · [Migrating from 1.0](docs/migration-2.0.md) · [Changelog](CHANGELOG.md)

</div>

A Windows desktop app for CAN work. The window **is** a log viewer: BLF, ASC and MF4
logs as a CANoe-style trace decoded with your DBC files, signals plotted on a shared
time axis with measurement cursors, and one **Export** window that writes the cut as
BLF, ASC, MF4, CSV, MAT frames, MAT signals or a Simulink Dataset. **DBC Compare**
opens from the Tools menu and reports added, removed, modified and renamed messages
and signals in Excel.

![Log Viewer](docs/screenshot_logview.png)

## Features

| Area | Use it to |
|---|---|
| Trace | Open BLF, ASC and MF4 logs, assign DBCs per channel, read decoded signal values, filter by ID, range or name, find, fixed-position mode, per-message cycle statistics |
| Graphics | Plot signals as sample-and-hold steps, Fit / Fit X / Fit Y, zoom, two cursors with values and Δt, cursor and trace follow each other |
| Export | One window: range (whole log, between cursors, trace filter), channel map, time base, and as many output formats as you need from the same cut |
| DBC Compare | Compare DBC files or whole baselines, pair renamed files and ECU nodes, focus on selected ECUs, review OLD/NEW values in Excel |
| Everywhere | Light and dark theme (or follow Windows), English or Tiếng Việt, drag & drop, dockable panels, workspaces, settings remembered |

<div align="center">

![Export](docs/screenshot_export.png)

</div>

## Quick start

1. Download the Windows `.exe` from [Releases](https://github.com/longvo92/can-toolbox/releases/latest) and open it. No Python installation is needed.
2. **Open Log…** (or drop a `.blf`, `.asc` or `.mf4` on the window), then **DBC Files…** to assign databases to channels.
3. Select a frame to see its decoded signals. Open **View → Signal Browser** and double-click a signal to plot it.
4. **Export…** cuts the log and writes the formats you tick.
5. **Tools → DBC Compare…** opens the comparison in its own window; **Settings → Settings…** holds language, theme and the MATLAB executable.

Sample DBCs are in [examples/old](examples/old) and [examples/new](examples/new); mapping examples are in [examples/blf](examples/blf).

## Outputs

| Job | Output |
|---|---|
| Export, frame formats | `<name>.blf`, `.asc`, `.mf4`, `.csv` or `.mat` (the `Frames` struct: time, ID, data, DLC, flags) |
| Export, MAT signals | `<name>_signals.mat`, or `<name>_input.mat` and `<name>_output.mat` when a mapping names interfaces |
| Export, Simulink Dataset | `<name>_dataset_*.mat`, packaged by one headless MATLAB run |
| DBC Compare | `compared_<old>_vs_<new>.xlsx` beside NEW, or a path you choose: Summary, DBC Overview (folders), Message Details, Signal Details |

## Requirements

- Windows for the packaged app.
- MATLAB only for the Simulink Dataset format; MAT output needs no MATLAB.
- Python 3.11+ to run from source.

## Install from source

```powershell
git clone https://github.com/longvo92/can-toolbox.git
cd can-toolbox
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\run_gui.bat
```

## Limitations

- The app is GUI-only; there is no command line mode. Version 0.8.0 of DBC Compare Tool remains available for scripted comparisons.
- Export works on the log that is open. Converting a folder of logs in one run was removed in 2.0; see [Migrating from 1.0](docs/migration-2.0.md).
- DBC rename detection is heuristic; review Medium and Low confidence rows. Moves across messages or files appear as Added/Removed.
- Signals keep their native CAN timestamps; nothing is resampled.
- The viewer never replays or simulates. BLF objects other than CAN frames (markers, LIN, Ethernet) are listed in **Log Info**; they are not shown in the trace or copied into a cut.

## Documentation

- [User Guide](resources/help/user_guide.md) · [Hướng dẫn tiếng Việt](resources/help/user_guide_vi.md)
- [Migrating from 1.0](docs/migration-2.0.md) — the window, Export and the mapping schema
- [Architecture](docs/architecture.md) — components, rules, testing and builds
- [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE) · Long Vo Thien
