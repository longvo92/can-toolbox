# TODO

## 0. Trước khi bắt đầu
- [ ] Chốt PR #47 (workspaces): merge hoặc bỏ, tránh conflict với `logview_tab.py`

## 1. Kiến trúc UI mới (hướng CANoe/TSMaster, làm thẳng, không mockup)
- [ ] Main window = Log viewer: menu + icon toolbar + các panel dock được (Trace, Graphics)
- [ ] DBC Compare, Export mở từ menu Tools, mỗi cái một cửa sổ riêng
- [ ] Bỏ shell dạng tab hiện tại (tự giải quyết việc "đưa Log viewer lên đầu")
- [ ] Giữ chỗ cho hướng phát triển lâu dài, chưa làm: overlay 2 log, nhiều cửa sổ Graphics, replay offline, đo online, LIN/Ethernet, diagnostic

## 2. Settings
- [ ] Settings dialog gom: Language, Theme, MATLAB executable (+ Detect, Check Environment)
- [ ] DBC Compare: giữ nguyên report path trên cửa sổ (không đưa vào Settings)
- [ ] Export: giữ output trên cửa sổ, chỉ dời MATLAB vào Settings

## 3. Theme sáng/tối
- [ ] Mặc định theo Windows, override System/Light/Dark trong Settings
- [ ] Graphics nền đen ở dark, màu cursor/curve đọc rõ ở cả hai theme

## 4. Log viewer
- [ ] Thao tác check log, add DBC giống CANoe/TSMaster để dễ làm quen (open log, gán DBC theo channel, kéo signal vào Graphics, ...)
- [ ] Màn hình mặc định tối giản: toolbar + Graphics + Trace
- [ ] Statistics, Info, Signal search: mở bằng chuột phải, hiện thành cửa sổ riêng
- [ ] Các phần còn lại (filter, details, ...) ẩn, bật lại qua menu View
- [ ] Icon toolbar (bộ icon MIT, đổi màu theo theme): Fit, Fit X, Fit Y, Zoom in/out, 1/2 cursor
- [ ] Fit X = toàn bộ thời gian log; Fit Y = autoscale Y mọi plot theo khoảng X đang xem; Fit = cả hai
- [ ] Cursor: giữ hành vi hiện tại, chỉ đổi checkbox thành icon

## 5. Export (thay tab BLF to MAT)
- [ ] Gộp vào một Export dialog duy nhất của Log viewer, dùng chung một engine
- [ ] Input: log đang mở (chỉ BLF), DBC, config mapping (optional); bỏ convert hàng loạt theo folder
- [ ] Phạm vi: toàn log / giữa 2 cursor / theo filter (đã có từ #46)
- [ ] Output: MAT, Simulink Dataset, BLF, ASC, MF4, CSV
- [ ] Config mapping: YAML, JSON, TXT cùng một schema, đủ thông tin như YAML hiện tại
- [ ] Excel vẫn hỗ trợ nhưng theo template cố định (cột, công thức, datatype); có nút xuất file xlsx mẫu
- [ ] Bỏ input cũ: Excel tự do, input/output TXT schema riêng, cột/sheet tùy chỉnh

## 6. Hoàn thiện
- [ ] Ghi breaking change + migration (config cũ sang schema mới), cân nhắc bump 2.0.0
- [ ] Cập nhật user guide EN/VI, screenshot, CHANGELOG, invariants trong AGENTS.md

## Thứ tự làm
0 → 1 + 2 + nền theme (token màu) → 4 → 5 → 3 hoàn chỉnh → 6
