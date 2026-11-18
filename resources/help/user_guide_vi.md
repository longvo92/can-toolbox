# Hướng dẫn sử dụng

Cửa sổ chính là Log Viewer. Menu **File** gom mọi thao tác với log đang mở, **Công cụ** mở
So sánh DBC trong cửa sổ riêng, còn **Cài đặt → Cài đặt…** gồm ngôn ngữ, chủ đề (theo Windows,
Sáng hoặc Tối), độ dày đường đồ thị và đường dẫn MATLAB.

## Log Viewer

1. Chọn **File → Mở log…** (Ctrl+O) hoặc kéo thả file `.blf`, `.asc`, `.mf4` vào cửa sổ. Có thể chọn hoặc kéo thả nhiều file một lần; mỗi file đọc lần lượt ở luồng nền, **Hủy** dừng cả hàng đợi. **File → Log gần đây** mở lại tám log gần nhất, **Nạp lại** (F5) đọc lại log hiện tại.
2. Log mở thêm chứ không thay thế: tab **Danh sách log** cạnh Trace liệt kê mọi log đang mở kèm thời lượng, số frame, channel và đường dẫn; log hiện tại in đậm. Nhấp đúp một dòng hoặc chọn **Chọn làm log hiện tại** để xem log đó trong Trace và đồ thị. Menu chuột phải còn có **Export…**, **Tải lại** và **Đóng** (chọn được nhiều dòng). Mỗi log giữ toàn bộ frame trong RAM nên đóng bớt log không dùng sẽ giải phóng bộ nhớ.
3. Danh sách signal giữ nguyên khi đổi log. Signal không có trong log hiện tại hiện màu xám, tooltip ghi *không có trong log này*, và không được vẽ.
4. Chọn **File → File DBC…** để thêm database và gán cho **Mọi channel** hoặc một channel CAN. DBC gán theo channel được ưu tiên; kéo thả file `.dbc` sẽ thêm cho mọi channel.
5. Trace liệt kê từng frame: thời gian, channel, ID (ID extended kết thúc bằng `x` như CANoe), tên message, hướng, loại, DLC và dữ liệu. Error frame hiển thị màu đỏ.
6. **Mở rộng một frame** (bấm mũi tên, nhấp đúp hoặc phím →) để xem signal đã decode ngay dưới frame đó: tên signal ở cột **Name**, giá trị vật lý hoặc text theo value table ở cột **Data**. Frame không có message trong DBC thì không mở rộng được. Nút **+** và **−** ở cuối thanh lọc, hoặc menu chuột phải, mở hết và thu hết; quá 100.000 dòng sẽ hỏi trước vì mỗi dòng mở ra đều phải decode.
7. Menu **Hiển thị** bật lại những phần không có trong màn hình mặc định: **Danh sách signal**, **Thống kê** và **Thông tin log**. Nhấp chuột phải vào trace để mở một panel thành cửa sổ riêng, vẽ mọi signal của message, hoặc đưa cursor tới frame đang chọn. Kéo panel trở lại cửa sổ để dock; bố cục được nhớ cho lần sau.
8. **Thanh lọc** nằm trong panel Trace. Ô lọc nhận ID, khoảng ID và một phần tên, ví dụ `100, 200-2FF, 18FF00x, Engine`; nhấn Enter để áp dụng. **Channel**, **Hướng** và **Error frame** thu hẹp thêm. **Tìm** nhảy tới frame khớp kế tiếp hoặc trước đó.
9. **Chế độ → Vị trí cố định** chỉ hiện frame mới nhất của mỗi channel và ID. **Thời gian → Tuyệt đối** hiện giờ thực khi log có mốc bắt đầu.
10. **Thống kê** liệt kê số lượng và chu kỳ theo message. **Thông tin log** hiện file, thời điểm bắt đầu, DBC, log của lần export gần nhất và những đối tượng reader bỏ qua, ví dụ marker BLF hoặc frame LIN.

### Đồ thị

Mở **Hiển thị → Danh sách signal**: đây là cửa sổ riêng, có ô tìm kiếm và bộ lọc
**Channel**, **Message**. Nhấp đúp một signal, kéo thả cả nhóm đã chọn vào đồ thị, hoặc bấm
**Thêm vào đồ thị**. Mỗi signal có một plot riêng trên cùng trục thời gian và giữ giá trị
cho tới frame kế tiếp.

Bảng bên trái đồ thị là danh sách đang vẽ. Mỗi dòng hiện tên signal theo màu đường vẽ, giá
trị tại **Cursor 1** và **Cursor 2**, cùng **Min**, **Max** và **Chênh lệch** — tính trên
khoảng giữa hai cursor khi đang đo, còn lại tính trên khoảng thời gian đang hiển thị. Bỏ tick
một dòng để giữ signal trong danh sách mà không vẽ; cột Cursor 2 và Chênh lệch chỉ hiện khi
bật cursor thứ hai, các cột khác ẩn/hiện qua menu chuột phải trên header.

Hàng tên nhóm được tô nền cả dòng nên dễ phân biệt với signal.

Chuột phải vào danh sách có **Thêm signal…**, **Nhóm mới**, **Đổi tên**, **Xóa**,
**Chuyển sang nhóm**, **Mở hết/Thu hết** và **Chế độ vẽ theo lựa chọn**. Khi bật chế độ này,
các dòng đang chọn chính là các plot đang vẽ: mọi checkbox được tick và không còn tác dụng,
nên hai cách chọn plot không chồng chéo nhau. Tắt chế độ thì quyền quyết định trả lại cho
checkbox, lúc đó tất cả đang bật. Kéo thả để sắp xếp hoặc chuyển nhóm, nhấn Delete để gỡ. Đồ thị vẽ
tối đa 16 plot cùng lúc; danh sách thì không giới hạn.

Đồ thị có toolbar riêng:

| Nút | Tác dụng |
|---|---|
| **Vừa khung ▾** | Trục X theo toàn bộ log, rồi chỉnh trục Y mọi plot theo khoảng đó; menu có **Vừa trục X** và **Vừa trục Y** |
| **Phóng to / Thu nhỏ** | Co giãn trục thời gian quanh cursor 1 |
| **Cursor 1 / Cursor 2** | Hiện cursor chính và cursor đo |
| **◀ / ▶** | Đưa cursor 1 tới lần đổi giá trị trước hoặc sau của signal đang chọn |
| **Bỏ plot / Xóa đồ thị** | Gỡ plot đang chọn, hoặc gỡ tất cả |
| **Ảnh ▾** | Lưu đồ thị thành file PNG, hoặc chép vào clipboard |

Tên signal nằm trên trục trái của từng plot, theo màu đường vẽ; tooltip hiện tên đầy đủ và
đơn vị. Di chuyển cursor sẽ chọn frame tương ứng trong trace và ngược lại. Khi bật
**Cursor 2**, bảng readout hiện giá trị tại hai cursor, chênh lệch và Δt ở cuối toolbar.

### Workspace

**Workspace → Lưu workspace…** lưu log, DBC đã gán, thiết lập trace, signal đang vẽ và
cursor vào file `.cantoolbox.json`; **Mở workspace…** (hoặc kéo thả file vào cửa sổ) khôi
phục lại tất cả. Đường dẫn lưu tương đối so với file workspace nên có thể di chuyển hoặc
chia sẻ cả thư mục dự án.

## Export

**Export…** làm việc trên log đang mở và ghi mọi định dạng đã chọn từ cùng một lát cắt.

1. **Khoảng:** toàn bộ log, đoạn giữa hai cursor của đồ thị, hoặc nhập từ/đến theo giây. Tích **Chỉ các frame đang hiện trong trace** để áp dụng bộ lọc hiện tại. **Đổi channel** đánh số lại bus (`1=2, 2=1`), **Mốc thời gian** giữ nguyên hoặc bắt đầu lại từ 0.
2. **Định dạng output:** BLF, ASC, MF4, CSV, **MAT frames**, **MAT signals**, **Simulink Dataset**. Hai định dạng signal cần định nghĩa: DBC đã gán trong Log Viewer, file config mapping, Excel template, hoặc kết hợp.
3. **Định nghĩa signal:** **Config mapping** (`.yaml`, `.yml`, `.json` hoặc `.txt`) và **Excel template** tùy chọn. **Lưu Excel template…** tạo workbook rỗng đúng cột; **Lưu config nâng cấp…** ghi lại file cũ theo schema hiện tại.
4. **Output:** chọn thư mục và một tên file. Mỗi định dạng tự thêm phần mở rộng; Dataset ghi thành `<tên>_dataset.mat`.

| Input | File kết quả |
|---|---|
| Không có định nghĩa | `<tên>.mat` với struct `Frames`, cùng các định dạng frame đã tích |
| Chỉ có DBC | `<tên>_signals.mat`: mỗi message một nhóm, signal nằm bên trong |
| Config mapping hoặc Excel template | `<tên>_input.mat` và/hoặc `<tên>_output.mat` theo interface đã khai báo |

Bản cắt BLF giữ frame CAN và CAN FD, error frame, channel, hướng và thời gian nanosecond.
Marker, comment và đối tượng không phải CAN không được chép sang; **Thông tin log** liệt kê
chúng. ASC giữ mốc bắt đầu tới millisecond và không ghi ID hay data cho error frame.
Signal giữ timestamp CAN tính từ frame đầu tiên, không resample. Kiểu số nguyên làm tròn và
bão hòa như MATLAB; file trùng tên sẽ bị ghi đè.

### File mapping

Một schema duy nhất, viết bằng YAML, JSON hoặc TXT. Mỗi element khai báo datatype và tùy chọn
CAN signal nguồn, `status_mapping` (áp dụng trước), `formula` (áp dụng sau) hoặc `value` là
hằng số không decode từ CAN.

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

Excel dùng template cố định: sheet **Inputs** và **Outputs**, header ở dòng 1, các cột
`Interface | Data Element | CAN Signal | Datatype | Formula | Status Mapping | Enabled`.
Khi config và template mô tả cùng một element thì config được ưu tiên. `excel_skip_keywords`
bỏ các dòng template chứa từ khóa. Nếu không chọn config, tool dùng `signal_mapping.yaml`
(hoặc `.json`, `.txt`) đặt cạnh ứng dụng. File viết cho bản 1.0 vẫn đọc được; xem
[hướng dẫn chuyển đổi](https://github.com/longvo92/can-toolbox/blob/main/docs/migration-2.0.md).

## So sánh DBC

1. **Công cụ → So sánh DBC…**, chọn chế độ **File** hoặc **Folder**, rồi chọn hai baseline OLD và NEW cùng loại.
2. Mở **Cài đặt → Cài đặt…** để chọn **Ngôn ngữ GUI** và **Ngôn ngữ report**. Report mặc định theo GUI.
3. Để trống đường dẫn report để lưu cạnh NEW với tên `compared_<old>_vs_<new>.xlsx`, hoặc chọn đường dẫn `.xlsx` riêng.
4. Trong chế độ Folder, dùng **Ghép cặp DBC thủ công…** khi cần chọn cặp cụ thể hoặc đánh dấu file OLD đã xóa. Dùng **Ghép cặp ECU…** để ghép các node đã đổi tên; report giữ tên node gốc.
5. Bật **ECU focus** để quét node trong hai baseline, rồi chọn node cần xem. Dùng **Chọn ECU…** để sửa danh sách. Đổi input hoặc cặp ECU sẽ xóa lựa chọn focus.
6. Report gồm tất cả loại thay đổi trong phạm vi ECU hiện tại. Bật **Gồm mục không đổi** để xuất thêm message và signal không đổi.
7. Chọn **Chạy so sánh** rồi **Mở report**.

### ECU focus và report

- Tool xét route ở cả OLD và NEW để thấy cả trường hợp ECU có thêm hoặc mất Tx/Rx. Với Tx, focus gồm mọi signal do ECU phát. Với Rx, focus chỉ gồm từng signal ECU nhận, cùng các thay đổi cấp message liên quan.
- Chọn một đầu của cặp ECU đã đổi tên sẽ gồm đầu tương ứng ở baseline còn lại. Node cùng tên được áp dụng trên mọi DBC đã chọn.
- Sheet **Tổng quan** ghi đường dẫn baseline, danh sách node focus, tổng thay đổi, coverage và lỗi đọc DBC. Trong chế độ focus, **Tổng quan DBC** chỉ liệt kê các cặp file có dòng detail được xuất; số message/signal tại đó vẫn tính trên toàn DBC.
- **Chưa đầy đủ** nghĩa là có file không đọc được. Kiểm tra lỗi trong sheet **Tổng quan** hoặc log. So sánh trực tiếp hai file sẽ dừng nếu một file lỗi.
- Lọc sheet chi tiết theo loại thay đổi, CAN ID hoặc ECU Tx/Rx. **Thuộc tính thay đổi** hiển thị giá trị cũ và mới, ví dụ `Start Bit: 56->57`. Đóng file Excel trước khi xuất lại cùng đường dẫn.

### Ghép cặp

`classic-v067` ghép trước các DBC cùng đường dẫn, sau đó tìm file đã đổi tên. Trong cặp file,
message ghép theo frame key, rồi theo tên, rồi theo điểm rename. Trong cặp message, signal ghép
theo tên rồi theo điểm rename. Ngưỡng điểm: 0.55 cho DBC, 0.60 cho message, 0.65 cho signal và
0.55 cho signal dạng event. Mục không ghép được thành Thêm mới/Đã xóa. Mức tin cậy
**Cao/Trung bình/Thấp** là ước lượng; khi có nhiều ứng viên, mức tin cậy giảm. Message chuyển
giữa các DBC hoặc signal chuyển giữa các message hiện thành Thêm mới/Đã xóa.
