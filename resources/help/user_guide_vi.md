# Hướng dẫn sử dụng

CAN Toolbox có ba tab. Mở **Cài đặt → Ngôn ngữ…** để đổi giữa English và Tiếng Việt.

## So sánh DBC

1. Chọn chế độ **File** hoặc **Folder**, rồi chọn hai baseline OLD và NEW.
2. Mở **Cài đặt → Ngôn ngữ…** để chọn **Ngôn ngữ GUI** và **Ngôn ngữ report**. Report mặc định theo GUI.
3. Để trống đường dẫn report để lưu cạnh NEW với tên `compared_<old>_vs_<new>.xlsx`. Tên tự động dùng tên folder hoặc tên file bỏ đuôi `.dbc`. Chọn đường dẫn `.xlsx` nếu muốn đặt tên riêng.
4. Trong chế độ Folder, dùng **Ghép cặp DBC thủ công…** khi cần chọn cặp cụ thể hoặc đánh dấu file OLD đã xóa. Dùng **Ghép cặp ECU…** để ghép các node đã đổi tên. Report giữ tên node gốc.
5. Bật **ECU focus** để quét node trong hai baseline. Chọn một hoặc nhiều node. Dùng **Chọn ECU…** để sửa danh sách. Đổi input hoặc cặp ECU sẽ xóa lựa chọn focus.
6. Report gồm tất cả loại thay đổi trong phạm vi ECU hiện tại. Bật **Gồm mục không đổi** để xuất thêm các message và signal không đổi.
7. Chọn **Chạy so sánh** rồi **Mở report**.

### ECU focus và report

- Tool xét route ở cả OLD và NEW để thấy cả trường hợp ECU có thêm hoặc mất Tx/Rx. Với Tx, focus gồm mọi signal do ECU phát. Với Rx, focus chỉ gồm từng signal ECU nhận, cùng các thay đổi cấp message liên quan.
- Chọn một đầu của cặp ECU đã đổi tên sẽ gồm đầu tương ứng ở baseline còn lại. Node cùng tên được áp dụng trên mọi DBC đã chọn.
- Sheet **Tổng quan** ghi đường dẫn baseline, danh sách node focus, tổng thay đổi, coverage và lỗi đọc DBC. Trong chế độ focus, **Tổng quan DBC** chỉ liệt kê các cặp file có dòng detail được xuất. Số message/signal tại đó vẫn tính trên toàn DBC.
- **Chưa đầy đủ** nghĩa là có file không đọc được. Kiểm tra lỗi trong sheet **Tổng quan** hoặc log. So sánh trực tiếp hai file dừng nếu một file lỗi.
- Lọc sheet chi tiết theo loại thay đổi, CAN ID hoặc ECU Tx/Rx. **Thuộc tính thay đổi** hiển thị giá trị cũ và mới, ví dụ `Start Bit: 56->57`. Đóng file Excel trước khi xuất lại cùng đường dẫn.

## BLF → MAT

1. Chọn **File / thư mục BLF**. Chọn thư mục sẽ lấy mọi file `.blf` bên trong, kể cả thư mục con.
2. Tùy chọn: thêm định nghĩa signal. Nếu không có, tool xuất CAN frame thô.
   - **File / thư mục DBC** để decode signal; mỗi message thành một nhóm signal.
   - **TXT schema input** và **TXT schema output** gồm các dòng `Interface.Element : datatype`; element khớp theo tên signal DBC.
   - **Workbook Excel** map element của model sang CAN signal. **Chọn sheet…** để chọn sheet input/output; cột và dòng header được tự nhận diện nếu bạn để trống (nhập tên header hoặc số thứ tự bắt đầu từ 1).
   - **Config YAML** thêm `input_mappings` (CAN signal, `status_mapping`, `formula` như `/10`), `input_forces` (giá trị input cố định) và `excel_skip_keywords`. Khi để trống, tool dùng `signal_mapping.yaml` cạnh ứng dụng nếu có. Xem mẫu trong thư mục `examples/blf` của repository.
3. Chọn **Định dạng output**. **File MAT** không cần MATLAB. **Simulink Dataset** chạy MATLAB một lần để đóng gói mọi log; để trống **File chạy MATLAB** để tool tự tìm.
4. Bấm **Chuyển đổi**, rồi **Mở thư mục output**. **Kiểm tra môi trường** liệt kê các package Python và MATLAB sẽ được dùng.

| Input | File trong thư mục output (mặc định `mat_output`) |
|---|---|
| Chỉ BLF | `<log>.mat` với struct `Frames`: thời gian, ID, data, DLC và các cờ frame |
| BLF + DBC | `<log>_signals.mat` |
| Có TXT, Excel hoặc YAML | `<log>_input.mat` và/hoặc `<log>_output.mat` |

Signal giữ timestamp CAN tính từ frame đầu tiên; tool không resample. Datatype số nguyên được làm tròn và bão hòa như MATLAB. File trùng tên sẽ bị ghi đè.

## Xem log

1. Bấm **Mở log…** hoặc kéo thả file `.blf`, `.asc`, `.mf4` vào tab. Log lớn được đọc ở nền; bấm **Hủy** để dừng.
2. Bấm **File DBC…** để thêm database và gán mỗi file cho **Mọi channel** hoặc một CAN channel. DBC gán cho channel cụ thể được ưu tiên; kéo thả file `.dbc` vào tab sẽ thêm cho mọi channel.
3. Trace liệt kê mọi frame: thời gian, channel, ID (ID extended có hậu tố `x` như CANoe), tên message, hướng, loại, DLC và dữ liệu. Error frame tô màu đỏ.
4. Chọn một frame để xem các signal đã giải mã: giá trị vật lý hoặc text của value table, giá trị raw và đơn vị.
5. **Lọc** nhận ID, khoảng ID và một phần tên, ví dụ `100, 200-2FF, 18FF00x, Engine`; nhấn Enter để áp dụng. **Channel**, **Hướng** và **Error frame** lọc thêm.
6. **Chế độ → Vị trí cố định** chỉ hiện frame mới nhất của mỗi channel và ID. **Thời gian → Tuyệt đối** hiện giờ thực khi log có ghi thời điểm bắt đầu.
7. **Đồ thị:** danh sách bên trái liệt kê mọi message có trong log và DBC, theo channel; gõ vào **Tìm signal** để lọc. Nhấp đúp vào signal, kéo thả lên đồ thị, hoặc chọn nhiều signal rồi bấm **Thêm vào đồ thị**. Mỗi signal có một plot riêng, dùng chung trục thời gian, và giữ giá trị đến frame kế tiếp. Di chuyển cursor sẽ chọn frame tương ứng trong trace và ngược lại. Bật **Đo (2 cursor)** để xem giá trị tại hai cursor, chênh lệch và Δt. **Vừa khung** để co giãn lại; **Bỏ plot** và **Xóa đồ thị** để bỏ plot.
8. **Tìm** nhảy tới frame kế tiếp hoặc trước đó khớp ID hoặc tên. **Thống kê** liệt kê số lượng và chu kỳ của từng message; **Thông tin log** hiện file, thời điểm bắt đầu, các DBC và những nội dung bị bỏ qua khi đọc, như marker hoặc object LIN trong BLF.
9. **Export…** để cắt log: toàn bộ log, đoạn giữa hai cursor của đồ thị, hoặc một khoảng tính bằng giây; có thể chỉ lấy các frame đang hiện theo filter của trace; đổi số channel bằng mapping như `1=2, 2=1`; giữ thời gian gốc hoặc bắt đầu lại từ 0. Phần mở rộng của file output quyết định định dạng: `.blf`, `.asc`, `.mf4`, `.csv` hoặc `.mat` (cấu trúc `Frames` giống BLF → MAT).

File BLF cắt ra giữ nguyên CAN và CAN FD frame, error frame, channel, hướng và thời gian tới nano giây. Marker, comment và các object không phải CAN không được sao chép; **Thông tin log** sẽ liệt kê chúng. ASC chỉ giữ thời điểm bắt đầu tới mili giây và không lưu ID hay data của error frame.
