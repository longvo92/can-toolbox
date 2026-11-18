# User Guide

The window is the Log Viewer. **File** holds everything about the open log, **Tools**
opens DBC Compare in its own window, and **Settings → Settings…** holds the language, the
theme (follow Windows, Light or Dark), the graph line width and the MATLAB executable.

## Log Viewer

1. **File → Open Log…** (Ctrl+O) or drop `.blf`, `.asc` or `.mf4` files on the window. Several files can be chosen or dropped at once; each one is read in turn, in the background, and **Cancel** stops the queue. **File → Recent Logs** reopens the last eight logs, and **Reload** (F5) reads the active one again.
2. Logs add up: the **Logs** tab beside the trace lists every open log with its duration, frames, channels and path, in bold for the active one. Double-click a row, or use **Set Active**, to show that log in the trace and the graph. Its menu also has **Export…**, **Reload** and **Close** (several rows at once). Every log keeps its frames in memory, so closing the ones you are done with frees it.
3. The signal list does not change when you switch logs. A signal the active log does not carry is greyed out, with *not in this log* in its tooltip, and its lane is not drawn.
4. **File → DBC Files…** adds databases and assign each to **All channels** or one CAN channel. A channel-specific DBC wins; dropping `.dbc` files on the window adds them for all channels.
5. The trace lists every frame: time, channel, ID (extended IDs end in `x`, as in CANoe), message name, direction, type, DLC and data. Error frames are red.
6. **Expand a frame** (the arrow, double-click or →) to read its decoded signals under it: the signal name in **Name** and its physical value, or the value-table text, in **Data**. Frames without a DBC message have nothing to expand. **Expand All** and **Collapse All** are the **+** and **−** buttons at the end of the filter bar and in the right-click menu; above 100,000 rows they ask first, because every expanded row is decoded.
7. **View** shows what the first screen leaves out: **Signal Browser**, **Statistics** and **Log Info**. Right-click the trace to open one as its own window, to plot every signal of a message, or to move the cursor to a frame. Drag a panel back onto the window to dock it; the layout comes back next time.
8. The **filter bar** is part of the Trace panel. It accepts IDs, ranges and name fragments, for example `100, 200-2FF, 18FF00x, Engine`; press Enter to apply. **Channel**, **Direction** and **Errors** narrow the trace further. **Find** jumps to the next or previous matching frame.
9. **Mode → Fixed position** shows only the newest frame per channel and ID. **Time → Absolute** shows wall-clock time when the log records its start.
10. **Statistics** lists counts and cycle times per message. **Log Info** shows the file, start time, DBCs, the engine log of the last export and anything the reader skipped, such as BLF markers or LIN objects.

### Graphics

Open **View → Signal Browser** — its own window, with a search box and **Channel** and
**Message** filters. Double-click a signal, drag a selection onto the graph, or click
**Add to Graph**. Each signal gets its own plot on a shared time axis and holds its value
until the next frame.

The list beside the graph is what is plotted. Each row shows the signal in the colour of
its curve, its value at **Cursor 1** and **Cursor 2**, and **Min**, **Max** and **Delta** —
over the span between the cursors while measuring, otherwise over the time range on screen.
Untick a row to keep a signal in the list without drawing it; the Cursor 2 and Delta columns
appear with the second cursor, and the header's right-click menu hides the rest.

Group rows carry a tinted band across the whole row, so a group is easy to pick out.

Right-click the list for **Add Signals…**, **New Group**, **Rename**, **Delete**,
**Move to Group**, **Expand/Collapse All** and **Ctrl+click plot mode**. In plot mode the
selected rows are exactly what the graph draws: every checkbox is ticked and they stop doing
anything, so the two ways of choosing lanes never fight. Switching the mode off hands the
decision back to the checkboxes, with everything ticked. Drag rows to reorder them or to move them between
groups, and press Delete to remove them. Sixteen lanes are drawn at a time; the list itself
is not limited.

The graph has its own toolbar:

| Button | Does |
|---|---|
| **Fit ▾** | Whole log on the time axis, then rescale every plot to it; the menu holds **Fit X** (time axis only) and **Fit Y** (plots only) |
| **Zoom in / out** | Scale the time axis around cursor 1 |
| **Cursor 1 / Cursor 2** | Show the main cursor and the measurement cursor |
| **◀ / ▶** | Move cursor 1 to the previous or next time the selected signal changes value |
| **Remove plot / Clear** | Drop the selected plot, or all of them |
| **Image ▾** | Save the plots as a PNG, or copy them to the clipboard |

Each plot is named on its left axis, in the colour of its curve; the full name and unit are
in its tooltip. Moving a cursor selects the matching frame in the trace, and selecting a
frame moves the cursor. With **Cursor 2** on, the readout lists the value at each cursor,
their difference and Δt, shown at the end of the toolbar.

### Workspaces

**Workspace → Save Workspace…** stores the log, DBC assignments, trace settings, plotted
signals and cursors in a `.cantoolbox.json` file; **Open Workspace…** (or dropping the file
on the window) brings it all back. Paths are stored relative to the workspace file, so a
project folder can be moved or shared.

## Export

**Export…** works on the log that is open and writes every selected format from the same cut.

1. **Range:** the whole log, the span between the two graph cursors, or a from/to in seconds. Tick **Only frames shown in the trace** to apply the current filter. **Channel mapping** renumbers buses (`1=2, 2=1`), and **Time base** keeps the original times or restarts at 0.
2. **Output formats:** BLF, ASC, MF4, CSV, **MAT frames**, **MAT signals**, **Simulink Dataset**. The two signal formats decode the cut and need definitions: the DBCs assigned in the viewer, a mapping config, an Excel template, or any combination.
3. **Signal definitions:** a **Mapping config** (`.yaml`, `.yml`, `.json` or `.txt`) and an optional **Excel template**. **Save Excel template…** writes an empty workbook with the right columns; **Save upgraded config…** rewrites an older config in the current schema.
4. **Output:** a folder and one file name. Each format adds its own extension; a Dataset is written as `<name>_dataset.mat`.

| Inputs | Files |
|---|---|
| No definitions | `<name>.mat` with a `Frames` struct, and whatever frame formats you ticked |
| DBCs only | `<name>_signals.mat`: one group per message, its signals inside |
| Mapping config or Excel template | `<name>_input.mat` and/or `<name>_output.mat` with the interfaces you declared |

A BLF cut keeps CAN and CAN FD frames, error frames, channels, direction and nanosecond
times. Markers, comments and non-CAN objects are not copied; **Log Info** names them.
ASC keeps its start time to the millisecond and stores no ID or data for error frames.
Signals keep their CAN timestamps relative to the first frame; nothing is resampled.
Integer datatypes round and saturate like MATLAB, and existing files are overwritten.

### Mapping files

One schema, written as YAML, JSON or TXT. Each element names its datatype and, optionally,
the CAN signal it comes from, a `status_mapping` applied first, a `formula` applied after,
or a constant `value` that is never decoded.

```yaml
version: 2
interfaces:
  - name: VehicleInputs
    side: input
    elements:
      - element: VehicleSpeed
        dtype: single
        can_signal: VehicleSpeedCAN
        formula: "/10"
      - element: Enable
        dtype: boolean
        value: true
```

The Excel template is fixed: sheets **Inputs** and **Outputs**, header in row 1,
columns `Interface | Data Element | CAN Signal | Datatype | Formula | Status Mapping | Enabled`.
Where a config and a template describe the same element, the config wins.
`excel_skip_keywords` drops template rows containing one of the words.
A `signal_mapping.yaml` (or `.json`, `.txt`) beside the app is used when no config is chosen.
Files written for 1.0 still load; see [Migrating from 1.0](https://github.com/longvo92/can-toolbox/blob/main/docs/migration-2.0.md).

## DBC Compare

1. **Tools → DBC Compare…**, then choose **Files** or **Folders** and select the OLD and NEW inputs of the same type.
2. In **Settings → Settings…** choose the **GUI Language** and **Report Language**. The report follows the GUI by default. Leave **Report Path** empty to save `compared_<old>_vs_<new>.xlsx` beside NEW, or choose an explicit `.xlsx` path.
3. Optional: in folder mode, use **Manual Pairing…** to force DBC pairs or mark OLD files **Removed**. Saved mappings override automatic matching, including Removed rows. Unlisted OLD files are removed; unreferenced NEW files are added.
4. In **ECU Pairing…**, select nodes to rename; leave other nodes at **Keep original name**. Original names remain in the report.
5. Enable **ECU Focus** to scan both inputs, then check the nodes to include. Use **Select ECUs…** to edit the selection. Changing the inputs or the ECU mapping clears the selected nodes.
6. The report includes all change types within the current ECU scope. Enable **Include Unchanged** to also list unchanged messages and signals.
7. Click **Run Compare**. Export is automatic; then click **Open Report**.

The finished status shows file errors and pairs requiring review. **Report incomplete** means
some inputs could not be compared; zero changes in that report does not establish equality.

### Pairing

`classic-v067` pairs same-path DBCs first and then searches for renamed files. Within paired
files it matches messages by frame key, then name, then rename score. Within paired messages it
matches signals by name and then rename score. Selecting two files directly or saving a manual
DBC map forces those file pairs.

Rename scores must reach 0.55 for DBCs, 0.60 for messages, 0.65 for signals or 0.55 for
event-like signals. Unmatched entities become Added/Removed. **High/Medium/Low** confidence for
selected renames is heuristic; ambiguity can lower it. Message moves across DBCs and signal moves
across messages appear as Added/Removed. Split/merge matching and message/signal mapping editors
are not supported.

### ECU focus

Focus uses routes from both inputs, so the report includes changes that add or remove an ECU's Tx
or Rx role. A selected transmitter includes all its changed signals. A selected receiver includes
only its own signals and any message-level changes for the messages carrying them. Selecting an
endpoint of a saved ECU pair also includes its counterpart on the other baseline. The same node
name applies across all selected DBCs.

Summary lists the selected nodes, applicable mappings and change counts. DBC Overview shows only
file pairs represented in the detail sheets, with counts for the whole DBC. Coverage and parse
diagnostics still describe the full inputs.

### Excel report

- Begin with **Summary**: Complete/Incomplete, matching policy, change totals, coverage, file diagnostics and ECU mappings. Coverage accounts for known entities as paired, unmatched or not compared; unreadable inventory is **Unknown**.
- Folder reports include **DBC Overview**. Direct-file reports omit it. If a forced counterpart cannot be parsed, its valid peer is **Not compared**, not Added/Removed.
- Filter **Message Details** and **Signal Details** by type, CAN ID or ECU. Rename confidence and match reasons appear on selected rename rows. Unchanged rows appear only with Include Unchanged.
- Names and parent names have separate OLD/NEW columns. Other fields show equal values once or changes as `old->new`. Added/removed entries show only the existing side.
- **Changed Properties** combines deltas, e.g. `Start Bit: 56->57; Length: 8->16`. No property delta means a blank cell. Use **Text Filters → Contains** for cells listing several ECUs.
- Close the workbook before regenerating it. Duplicate message names/frame keys or signal names are parse errors. Direct-file errors stop export; folder errors allow a partial report.

Matching has synthetic regression coverage; no production corpus with labeled mappings is available.
