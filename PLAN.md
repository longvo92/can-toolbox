# Plan chi tiết — CAN Toolbox 2.0 (từ TODO.md)

Trạng thái gốc: `main` = 5dbfec5 (sau #46), version 1.0.0, shell 3 tab.
Thứ tự theo TODO: 0 → (1 + 2 + theme tokens) → 4 → 5 → 3 → 6. Mỗi mục = 1 PR `dev/<slug>`, squash merge sau khi CI xanh.

Gate mỗi PR (không ngoại lệ):

```bash
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m pytest -q && python -m ruff check . && python scripts/smoke.py --gui
```

---

## 0. Chốt PR #47 — XONG

Merged 2026-11-16 bằng squash: `601f24a feat: save and open Log Viewer workspaces (#47)` trên `main` (head PR `36fe6b0`, 5/5 CI job SUCCESS, +366/-4 trên 13 file).

Quyết định: **merge**, không bỏ.

- `canlog/workspace.py` là Qt-free, không dính vào phần UI sẽ bị viết lại; `GraphPanel.restore_cursors` là API công khai thay cho truy cập private, tốt cho phần restructure sắp tới.
- Workspace (log + DBC per channel + filter + plot + cursor) đúng là khái niệm "configuration" của kiến trúc CANoe-style ở mục 1 — bỏ đi thì mục 1 phải viết lại từ đầu.
- Conflict `logview_tab.py`: merge trước thì mục 1 viết lại **một lần** trên code đã có workspace; để PR mở rồi restructure thì phải rebase 366 dòng vào file đã nổ tung.

Còn lại: xoá worktree `.claude/worktrees/merge-blf-to-mat-gui-3e16cb` (đang giữ `dev/log-viewer-p4` đã merged) khi không còn session nào dùng. Mọi mục dưới đây tính trên `main` = 601f24a.

---

## 1. PR #48 — Shell mới: main window = Log viewer

Hiện tại `ui/main_window.py` tạo 3 tab widget trong `QTabWidget#toolTabs`, mỗi tab có contract `title_key`/`subtitle_key`/`busy_changed`/`set_languages`/`is_busy`/`stop_workers`/`wait_for_workers`. `logview_tab.py` đã ~1100 dòng và tự dựng toolbar bằng `QPushButton` + 2 hàng filter + `QSplitter` 2 cấp.

### Kiến trúc đích

Tách `ui/logview_tab.py` thành package `ui/logview/`:

| File | Nội dung |
|---|---|
| `window.py` | `LogViewerWindow(QMainWindow)`: menuBar (File, View, Tools, Settings, Help), `QToolBar`, status bar (status + progress + cancel), dock Trace và Graphics, workspace save/open, drop file, close guard |
| `controller.py` | State hiện do tab giữ: `LogView`, `Task` load/export, assignments, filter, `current_workspace()`, signal Qt cho các panel. Không dựng widget. |
| `trace.py` | `TraceModel` + `TraceView` (context menu, find, fixed position) |
| `panels.py` | Signal browser, Statistics, Info — mỗi cái là widget tự chứa, dùng được trong dock lẫn cửa sổ rời |
| `dialogs.py` | `DbcDialog`, `ExportDialog` (mục 5 sẽ thay) |

Dock: `QDockWidget` cho Trace (bottom), Graphics (center/top), Signal browser (left, mặc định ẩn), Filter bar (top, ẩn), Details (ẩn). Tool window riêng: `ui/tool_windows.py` — `ToolWindow(QMainWindow)` bọc một widget, single-instance theo key, nhớ geometry trong `QSettings`.

Tools menu: `DBC Compare…`, `Export…` mở `CompareTab`/export bằng `ToolWindow` — **không sửa nội dung `compare_tab.py`** ở PR này, chỉ bỏ `title_key/subtitle_key` khỏi contract và bọc lại. `blf_tab.py` cũng mở từ Tools (sẽ chết ở mục 5).

### Chi tiết cần quyết

- Close guard: `MainWindow.closeEvent` hiện hỏi khi có worker chạy. Chuyển vào `LogViewerWindow.closeEvent`, quét cả log viewer + mọi `ToolWindow` đang mở (`is_busy()` giữ nguyên trên widget con).
- Busy lock: hiện `busy_changed` khoá menu Settings. Giữ: controller + mỗi tool widget phát `busy_changed`, window khoá action Settings khi có việc chạy.
- Language propagation: `TextBinder` giữ nguyên; window cầm binder gốc, `ToolWindow` truyền `set_languages` xuống widget con.
- Geometry/dock state: `QSettings` key `window/geometry`, `window/state` (`saveState`/`restoreState`), version hoá bằng `saveState(1)` để lần sau đổi layout không nổ.
- Invariant `tests/test_startup_imports.py` (numba/llvmlite/cantools/can/asammdf/pandas/scipy) phải giữ nguyên. Hiện `graphics` (pyqtgraph) đã import ở `_build_layout` và test vẫn pass → không nới danh sách, chỉ giữ engine import lazy như cũ.
- `ui/app.py` đổi `MainWindow` → `LogViewerWindow`; giữ tên file `main_window.py` để diff dễ đọc, hoặc đổi sang `ui/logview/window.py` và để `main_window.py` chỉ còn migrate settings + re-export (chọn cách 2, `migrate_legacy_settings` ở lại `main_window.py`).

### Test

- Đổi `tests/test_logview_tab.py` → `test_logview_window.py`, fixture tạo `LogViewerWindow` thay vì tab.
- Mới: dock mặc định (Graphics + Trace hiện, phần còn lại ẩn), View menu toggle đúng dock, Tools mở đúng 1 instance và đóng sạch, close guard khi có worker, restore dock state.
- `scripts/smoke.py --gui` mở window mới.

Rủi ro: PR to (xoá contract tab + tách file 1100 dòng). Không chia nhỏ hơn được vì tab widget và shell chết cùng lúc; bù lại bằng cách **không** đổi nội dung compare/blf tab ở PR này.

---

## 2. PR #49 — Settings dialog + nền theme token

Hai việc gộp một PR vì cùng chạm `style.py` và `main_window.py`, và Settings cần sẵn ô Theme.

### 2a. Settings dialog

`ui/settings_dialog.py`, mở từ Settings → `Settings…` (thay `Language…`):

| Nhóm | Field | QSettings key |
|---|---|---|
| Language | GUI Language, Report Language | `gui_language`, `report_language` (giữ) |
| Appearance | Theme: System / Light / Dark | `theme` (mới, default `system`) |
| MATLAB | Executable + `Detect` + `Check Environment` | `matlab/executable` (mới) |

- `EnvironmentWorker` và `_detect_matlab` chuyển từ `ui/blf_tab.py:106,567` sang settings dialog; `blf_mat/checks.py` không đổi.
- Migrate key cũ: `blf/matlab` → `matlab/executable` (một lần, giống `migrate_legacy_settings`, giá trị mới thắng).
- Giữ **trên cửa sổ**, không đưa vào Settings: report path của DBC Compare, output của Export (đúng TODO 2).
- Áp dụng ngay khi Save: language như hiện tại, theme gọi `apply_theme(app, mode)`.

### 2b. Theme token

`ui/style.py` → `ui/theme.py`:

```python
@dataclass(frozen=True)
class Theme:
    name: str            # "light" | "dark"
    bg: str; surface: str; border: str
    text: str; muted: str; disabled: str
    accent: str; accent_text: str; accent_hover: str
    error: str
    plot_bg: str; plot_fg: str; grid: str
    cursor_primary: str; cursor_secondary: str
    curves: tuple[str, ...]
```

- `LIGHT` = đúng màu hiện tại (`#f4f6fb`, `#ffffff`, `#2563eb`, …) để PR này không đổi vẻ ngoài light.
- `DARK` = bộ tối tương ứng, plot_bg đen (`#0f1115`), curve/cursor chọn theo contrast ≥ 3:1 trên nền tối.
- `STYLESHEET` thành template, `stylesheet(theme)` substitute token (`{bg}`, `{accent}`…). `palette(theme)` cho Fusion palette. `apply_theme(app, mode)` resolve `system` qua `QApplication.styleHints().colorScheme()` và subscribe `colorSchemeChanged` để đổi live.
- Icon tint: `icon(name, theme)` load SVG từ `resources/icons/`, tint bằng `QPainter` `CompositionMode_SourceIn`, cache theo `(name, theme.name)`.
- `graphics.py`: bỏ màu hardcode, nhận token; thêm `GraphPanel.apply_theme(theme)` (pyqtgraph `setConfigOption('background'/'foreground')` + re-pen các curve/cursor hiện có).

### Test

- `tests/test_theme.py`: mọi placeholder trong template có mặt ở cả LIGHT và DARK; grep assertion "không còn hex màu trong `ui/` ngoài `theme.py`"; `stylesheet(DARK)` parse được (áp vào `QWidget` offscreen không warning).
- GUI: đổi theme trong Settings → `app.styleSheet()` đổi, `GraphPanel` background đổi; render offscreen `window.grab()` và kiểm pixel nền ở cả hai theme.
- Settings: Save ghi đúng key, migrate `blf/matlab`, Detect/Check Environment không chạm MATLAB thật (mock như test cũ của blf tab).

---

## 3. PR #50 — Log viewer UX (TODO mục 4)

### Layout mặc định tối giản

Hiện: 2 hàng button/filter + splitter 3 tầng (graph/trace/details) + signal browser trái — luôn hiện hết. Đích: toolbar + Graphics + Trace. Signal browser, filter bar, details (Signals/Statistics/Info) ẩn, bật qua View menu (action checkable 2 chiều với `QDockWidget.visibilityChanged`).

### Toolbar icon

- Bộ icon: **Tabler Icons (MIT)**, vendor SVG vào `resources/icons/` + `resources/icons/LICENSE`, `scripts/build.py` đã `--add-data resources` nên không sửa build.
- Action: Open log, Reload, DBC files, Export, Workspace (menu), | Fit, Fit X, Fit Y, Zoom in, Zoom out, | Cursor 1, Cursor 2. Tint theo theme qua `theme.icon()`.
- Cursor: hành vi giữ nguyên, chỉ bỏ `QCheckBox` "Measure (2 cursors)" (`graphics.py:160`) → 2 action checkable trên toolbar; `GraphPanel._toggle_measure` nhận từ action. Workspace schema v1 đã có `measure` → **không đổi schema**.

### Fit / Zoom (định nghĩa chốt)

| Action | Hành vi |
|---|---|
| Fit X | X range = toàn bộ thời gian log (`0 … view.duration`), không phụ thuộc dữ liệu đang plot |
| Fit Y | Với mỗi plot: autoscale Y **chỉ theo khoảng X đang xem** (slice `SignalSeries.time` bằng `np.searchsorted`, lấy min/max value trong slice, pad 5%) |
| Fit | Fit X rồi Fit Y |
| Zoom in/out | Nhân/chia X range quanh cursor 1 (hệ số 2), clamp trong `0 … duration` |

`GraphPanel.fit()` hiện gọi `autoRange` → thay bằng `fit_x(duration)`, `fit_y()`, `fit(duration)`; cần `duration` từ controller (view), nên API nhận tham số thay vì đọc global.

### Chuột phải → cửa sổ rời

- Trace: `Statistics…`, `Info…`, `Copy row`, `Set cursor here`, `Plot signals of this message`.
- Signal browser: `Add to Graph`, `Search signals…`.
- Statistics / Info / Signal search mở bằng `ToolWindow` (PR #48), single-instance, nhớ geometry. Statistics vẫn chạy trên `Task` thứ hai, nhưng trigger là "window mở" thay vì "tab được chọn" (`_refresh_statistics`).

### Flow kiểu CANoe/TSMaster

Open log → nếu channel chưa có DBC thì status bar gợi ý + context menu cột Channel có `Assign DBC…`; DBC dialog giữ nguyên (`DbcDialog`) nhưng mở được từ toolbar, menu File và context menu. Kéo signal từ browser vào Graphics: đã có, giữ.

### Test

Fit X/Fit Y range đúng trên dữ liệu dựng sẵn, zoom clamp, context menu mở đúng window, dock default + View toggle, icon tint đổi theo theme, cursor action đồng bộ workspace cũ (mở file workspace v1 từ #47 vẫn đúng).

---

## 4. PR #51 — Export một cửa sổ, một engine (TODO mục 5)

Mục lớn nhất, và là breaking change. Hiện có **hai** đường xuất độc lập:

- `canlog/export.py`: cut frame theo range/filter/channel map → `blf`, `asc`, `mf4`, `csv`, `mat` (layout `Frames` qua `frame_fields`).
- `blf_mat/converter.py` (1500+ dòng) + `options.py` + `mapping.py`: đọc BLF **lại từ file**, decode signal theo DBC/Excel/TXT/YAML → MAT signal hoặc Simulink Dataset qua `matlab -batch`.

### Hợp nhất

1. `canlog/export.py` nhận thêm "signal export": `ExportJob` = `{view, range, use_filter, channel_map, rebase, formats: set[str], output_dir, base_name, mapping, matlab}`.
2. Tách core của `converter.convert()` thành hàm nhận **FrameTable đã cut + LogDatabase + mapping đã resolve** (không đọc file, không nhận list BLF). Log viewer truyền thẳng table đang mở → bỏ việc đọc BLF hai lần, và range/filter áp dụng được cho MAT/Dataset (hiện không).
3. Xoá batch-theo-folder: `collect_blf_files`, `DEFAULT_OUTPUT_FOLDER`, `run_conversion`, `build_selected_paths` (phần folder), `ui/blf_tab.py`, `tests/test_blf_tab.py`. Input chỉ là log đang mở (chỉ BLF; ASC mở được nhưng Export signal chặn với lý do rõ ràng).
4. Xoá option Excel tự do khỏi `ConversionOptions`: `input_schema`, `output_schema`, `schema`, `input_sheets`, `output_sheets`, `element_column`, `can_column`, `interface_column`, `dtype_column`, `header_row`.

### Config schema v2 — một schema, ba syntax

`blf_mat/config.py` mới: canonical dict + validator + 3 loader.

```yaml
version: 2
excel_skip_keywords: []
input_mappings:
  - interface: VehicleInputs
    element: VehicleSpeed
    can_signal: VehicleSpeedCAN
    formula: "/10"
    status_mapping: {0: 0, 1: 1}
    dtype: single
    enabled: true
input_forces:
  - interface: VehicleInputs
    element: Enable
    value: true
```

- `.yaml`/`.yml` → `yaml.safe_load`; `.json` → `json.loads`; `.txt` → parser block kiểu INI (`[input_mappings]` + `Interface.Element: can_signal` + `key = value` cho formula/dtype/status/enabled), là superset của `_SCHEMA_RE` hiện tại nên `examples/blf/schema.txt` vẫn đọc được.
- Một validator duy nhất sau khi load (giữ `validate_signal_formula`, `parse_status_mapping`, `normalize_dtype`), lỗi kèm `file:line`.
- Migration v1 (không có `version`): auto-upgrade trong loader + log warning; Export dialog có `Save upgraded copy…`.

### Excel template cố định

`blf_mat/excel_template.py`:

- Sheet `Inputs`, `Outputs`; header row 1 cố định: `Interface | Data Element | CAN Signal | Datatype | Formula | Status Mapping | Enabled`.
- Datatype giới hạn (`double`, `single`, `int8…uint64`, `boolean`) bằng data validation dropdown; formula validate bằng AST hiện có; `Enabled` = TRUE/FALSE.
- Nút `Save Excel template…` sinh file xlsx mẫu (openpyxl đã có) gồm header, dropdown, 1 dòng ví dụ.
- `mapping.py`: bỏ `HEADERS` suy đoán tên cột và `column_index`, đọc theo vị trí cố định; giữ `Workbook` reader (trim blank, NA, int) và `infer_dbc`.

### Export dialog mới

| Phần | Nội dung |
|---|---|
| Source | log đang mở (read-only path), DBC đang gán |
| Range | Whole log / Between cursors / Trace filter (đã có từ #46) |
| Formats | checkbox: BLF, ASC, MF4, CSV, MAT (frames), MAT (signals), Simulink Dataset |
| Signal options | config mapping (optional, yaml/json/txt), Excel template (optional), `Save Excel template…`, `Save upgraded copy…` |
| Output | folder + base name → `<name>.<ext>` cho từng format; giữ **trên cửa sổ**, không vào Settings |
| MATLAB | chỉ hiện khi chọn Dataset, lấy từ Settings, thiếu thì báo và link sang Settings |

Chạy trên `Task` như export hiện tại, progress theo format đang ghi, cancel hợp tác.

### Test

- Tương đương 3 syntax: cùng canonical dict từ YAML/JSON/TXT (property-style, một fixture gốc).
- Migration v1→v2 giữ nguyên kết quả decode (so với test hiện có trong `test_blf_conversion.py`).
- Template: sinh → đọc lại → ra mapping đúng; file sai header báo lỗi rõ.
- Một cut → xuất cả 7 format; MAT (frames) giữ layout `frame_fields` cũ (`test_export.py` không được đổi kỳ vọng); MAT (signals) so với baseline của `test_blf_conversion.py`; Dataset mock MATLAB.
- Range/filter áp cho MAT signals (mới).
- Option cũ bị bỏ → `OptionError` nêu đúng tên option và chỉ sang migration.
- `tests/test_blf_engine_equivalence.py`, `test_blf_optional_inputs.py` retarget sang API mới; `scripts/smoke.py` bỏ stage batch, thêm stage export-from-view.

---

## 5. PR #52 — Theme sáng/tối hoàn chỉnh (TODO mục 3)

Token đã có từ #49; PR này là pass hoàn thiện trên **toàn bộ** surface mới:

- Mọi cửa sổ/dialog: Log viewer, Settings, DBC dialog, Export, Compare, Statistics, Info, Signal search, Help/About/Release note (`QTextBrowser` markdown cần màu riêng cho code block và link).
- Graphics dark: nền đen, axis/grid/label đọc rõ, curve cycle 8 màu phân biệt được ở cả hai theme, cursor 1/2 khác nhau rõ (giải pháp: cursor 1 accent, cursor 2 cam/vàng, dashed khác nhau), region giữa 2 cursor alpha thấp.
- Trace: alternating row, selection, màu error frame đọc rõ trên nền tối.
- Theo Windows mặc định + đổi live khi user đổi theme OS (`colorSchemeChanged`), override trong Settings thắng.
- Kiểm bằng render offscreen: screenshot từng window ở light/dark, so độ tương phản text/nền (tính WCAG ratio trong test, ngưỡng ≥ 4.5 cho text thường, ≥ 3 cho đường/curve).

---

## 6. PR #53 — Hoàn thiện & 2.0.0 (TODO mục 6)

- `CHANGELOG.md` 2.0.0: breaking = bỏ tab shell và tab BLF to MAT, bỏ convert batch theo folder, bỏ Excel tự do + TXT input/output schema riêng, config v2, MATLAB chuyển vào Settings. Mỗi dòng kèm migration.
- `docs/migration-2.0.md`: v1 YAML → v2 (ví dụ before/after), Excel tự do → template, batch folder → script hoặc mở từng log, key QSettings đổi.
- `README.md` + `resources/help/user_guide.md` + `user_guide_vi.md`: viết lại cho app một cửa sổ, 2–3 phút đọc; screenshot mới (light + dark) thay `docs/screenshot_logview.png`.
- `AGENTS.md` invariants mới: main window = Log viewer, Compare/Export mở bằng ToolWindow; một engine export duy nhất trong `canlog/export.py`; màu chỉ định nghĩa trong `ui/theme.py`; config v2 ba syntax một canonical dict; `blf_mat` không còn đọc file BLF trực tiếp.
- `docs/architecture.md` cập nhật bảng module (hiện còn ghi "one tab per tool").
- Version 2.0.0 trong `pyproject.toml`, `python scripts/release_check.py 2.0.0 --notes <file>`, build exe, smoke exe (`--help` không có vì GUI-only → kiểm startup), rồi release khi được yêu cầu.

---

## Giữ chỗ, chưa làm (TODO mục 1)

Overlay 2 log trên một graph, nhiều cửa sổ Graphics, replay offline, đo online, LIN/Ethernet, diagnostic. Chuẩn bị sẵn nhưng không code:

- `controller.py` giữ `LogView` theo key (dict) thay vì một biến → sau này thêm log thứ hai không phải sửa UI.
- `GraphPanel` nhận `series` có `ref` mang nguồn (`log_id`) → overlay chỉ là thêm log_id thứ hai.
- `ToolWindow` single-instance theo key → đổi sang multi-instance cho Graphics khi cần.
- `canlog/reader.py` đã tách `open_log`; LIN/Ethernet hiện đếm trong `BlfInfo.skipped_objects` → chỗ cắm sau này.

## Thứ tự & rủi ro

| PR | Mục | Size | Rủi ro chính |
|---|---|---|---|
| #47 | 0 | — | xong (601f24a) |
| #48 | 1 | L | tách file 1100 dòng; giữ invariant startup import |
| #49 | 2 + theme base | M | đổi toàn bộ stylesheet thành template, dễ lệch light |
| #50 | 4 | M | semantic Fit Y theo X đang xem; workspace v1 phải vẫn mở được |
| #51 | 5 | XL | hai engine gộp một, breaking schema; test baseline MAT phải giữ |
| #52 | 3 | M | contrast ở dark trên pyqtgraph |
| #53 | 6 | S | docs/screenshot đồng bộ với UI cuối |

Mỗi PR tự chứa và chạy được (app không bao giờ ở trạng thái nửa vời giữa hai PR). Nếu #51 quá to khi làm thật, cắt theo: #51a config v2 + template (engine only, blf tab vẫn sống), #51b export dialog hợp nhất + xoá blf tab.
