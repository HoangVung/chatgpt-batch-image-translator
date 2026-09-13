# Kết thúc job và tự chạy batch

Job gồm các ảnh nguồn được hỗ trợ trong thư mục đã chọn, tính từ ô “Bắt đầu từ ảnh” nếu có. Ảnh trước điểm bắt đầu không thuộc phạm vi job này.

Mỗi lần chạy đối chiếu từng ảnh nguồn với ảnh kết quả hợp lệ. Dòng `done` trong CSV nhưng thiếu/hỏng ảnh kết quả vẫn được coi là chưa hoàn tất. Ảnh lỗi chưa có kết quả hợp lệ được giữ cho thao tác chạy lại ảnh lỗi.

- Exit code 0: lần chạy kết thúc bình thường. Trường `job.state=complete` xác nhận toàn bộ job đã xong; code 0 riêng lẻ cũng có thể chỉ là một batch thành công.
- Exit code 2: batch có ảnh lỗi hoặc hết ảnh chờ nhưng còn ảnh lỗi cần chạy lại.
- Exit code 3: batch chính không làm giảm số ảnh chờ; dừng để tránh lặp lại vô hạn.
- Exit code 1: ngoại lệ không xử lý được, chẳng hạn không đọc được thư mục hoặc không khởi động được trình duyệt.

Giao diện chỉ tự hẹn batch tiếp theo sau một batch chính đủ ảnh, thành công và còn ảnh chờ. Batch cuối có ít ảnh hơn cấu hình vẫn được xác nhận hoàn tất job khi toàn bộ kết quả hợp lệ. Không còn ảnh thì worker thoát trước khi mở trình duyệt. Giao diện giữ mở để xem log; không tự hẹn thêm sau khi job hoàn tất hoặc cần chạy lại lỗi.

Danh sách nguồn được đọc lại khi worker bắt đầu. Nếu thêm ảnh nguồn giữa các batch, các ảnh mới được tính vào lần chạy kế tiếp. Nên giữ nguyên thư mục nguồn trong lúc chạy một job.
