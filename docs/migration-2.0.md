# Migrating to CAN Toolbox 2.0

Version 2.0 keeps every job 1.0 could do, but the window and the conversion inputs
changed. Nothing is converted automatically except the settings listed below, so
read this once before you replace the executable.

## The window

| 1.0 | 2.0 |
|---|---|
| Three tabs in one window | The window **is** the Log Viewer |
| Tab bar → **DBC Compare** | **Tools → DBC Compare…**, in its own window |
| Tab bar → **BLF → MAT** | **Export…** in the Log Viewer (see below) |
| **Settings → Language…** | **Settings → Settings…**: language, theme and the MATLAB executable |
| Fixed layout | **View** hides or restores the filter bar, Signal Browser, Signal Values, Statistics and Log Info; the layout is remembered |

Your language, report language and the DBC Compare inputs carry over. The MATLAB
executable moves from the BLF → MAT window into Settings the first time 2.0 starts.

## Converting logs

**BLF → MAT is gone.** Open the log in the viewer and use **Export…**:

1. **Open Log…** (or drop the file on the window), assign DBCs with **DBC Files…**.
2. **Export…**, choose the range: whole log, between the graph cursors, or a from/to
   in seconds, optionally only the frames the trace filter shows.
3. Tick the formats: BLF, ASC, MF4, CSV, **MAT frames**, **MAT signals**,
   **Simulink Dataset**. Every file is written from the same cut.
4. Choose the output folder and one file name; each format adds its own extension.
   A Dataset is written as `<name>_dataset.mat`, so both MAT forms can be kept.

What this changes for you:

- **Converting a folder of logs in one run is gone.** Export works on the log you
  have open. Repeat it per log, or keep 1.0 for bulk runs.
- A range or trace filter now applies to decoded signals too, which 1.0 could not do.
- Non-BLF logs (ASC, MF4) can be opened and exported as frames; signal export still
  expects CAN frames from a BLF.

## Mapping files

One schema replaces the TXT schemas, the YAML config and the free-form Excel sheets.
It can be written as **YAML, JSON or TXT** — the file name decides.

```yaml
version: 2
excel_skip_keywords: []
interfaces:
  - name: VehicleInputs
    side: input                      # input | output
    elements:
      - element: VehicleSpeed
        dtype: single
        can_signal: VehicleSpeedCAN  # optional CAN source
        formula: "/10"               # optional, after status_mapping
        status_mapping: {10: 1}      # optional CAN value -> model value
      - element: Enable
        dtype: boolean
        value: true                  # constant, never decoded from CAN
```

The same content as TXT:

```text
[options]
    excel_skip_keywords = obsolete
[input]
VehicleInputs.VehicleSpeed: single
    can_signal = VehicleSpeedCAN
    formula = /10
VehicleInputs.Enable: boolean
    value = true
[output]
ControllerOutputs.Request: uint8
    can_signal = RequestCAN
```

### What to do with the files you have

| 1.0 input | 2.0 |
|---|---|
| `signal_mapping.yaml` with `input_mappings` / `input_forces` | Still loads. **Export… → Save upgraded config…** rewrites it as version 2 |
| `schema.txt` with `Interface.Element : datatype` lines | Still loads as input interfaces; add `[input]` / `[output]` sections to split sides |
| Separate **Input TXT schema** and **Output TXT schema** | One file with `[input]` and `[output]` sections |
| Excel with chosen sheets, guessed columns, custom header row | Fixed template, see below |

A file that mixes both styles is fine: an element in `interfaces` wins over an
`input_mappings` entry for the same target, and a target named twice is an error
that says where it was defined first.

### Excel

Workbooks now follow one template: sheets **Inputs** and **Outputs**, header in row 1,
columns `Interface | Data Element | CAN Signal | Datatype | Formula | Status Mapping | Enabled`.
Use **Export… → Save Excel template…** for an empty workbook with the datatype list,
then paste your rows into it. Sheet pickers, column names and header-row numbers are gone.

`excel_skip_keywords` still drops rows that contain one of the words.

## Settings keys

Stored under `HKEY_CURRENT_USER\Software\CanToolbox\CANToolbox`:

| 1.0 | 2.0 |
|---|---|
| `blf/matlab` | `matlab/executable` (migrated once, then removed) |
| — | `theme` (`system`, `light`, `dark`) |
| — | `window/geometry`, `window/state`, `tools/<tool>/geometry` |
| `blf/*` inputs of the old window | unused; Export keeps `logview/export_*` instead |

Workspaces (`*.cantoolbox.json`) written by 1.0 open unchanged.
