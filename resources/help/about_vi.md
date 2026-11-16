# CAN Toolbox

**Phiên bản {version}** · Phát triển bởi **Long Vo Thien** · Giấy phép MIT

[longvo92/can-toolbox](https://github.com/longvo92/can-toolbox)

CAN Toolbox gom hai công việc CAN thường ngày vào một cửa sổ: kiểm tra thay đổi DBC trước khi tích hợp, và chuyển log BLF đã ghi thành dữ liệu MATLAB cho model và test harness.

## Bạn có thể làm gì

- **So sánh file hoặc folder DBC.** Xem message và signal được thêm, xóa, sửa hoặc đổi tên, cùng giá trị OLD và NEW của CAN ID, vị trí bit, hệ số scale và route Tx/Rx của ECU.
- **Tập trung vào ECU cần kiểm tra.** Giới hạn report theo các node đã chọn và ghép cặp các node ECU đã đổi tên.
- **Chia sẻ report Excel.** Tổng số thay đổi, chi tiết message và signal, cùng cảnh báo khi so sánh folder bỏ qua file không đọc được.
- **Chuyển đổi log BLF.** Xuất CAN frame thô, decode signal bằng DBC, map sang interface của model từ Excel, TXT hoặc YAML, và ghi file MAT hoặc Simulink Signal Editor Dataset.

Giao diện và report Excel có thể chọn English hoặc Tiếng Việt riêng.

## Tải bản phát hành và góp ý

[Tải bản phát hành](https://github.com/longvo92/can-toolbox/releases) · [Báo lỗi](https://github.com/longvo92/can-toolbox/issues)
