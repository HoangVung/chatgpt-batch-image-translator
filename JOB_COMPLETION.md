# Kết thúc job và tự chạy batch

Job gồm các ảnh nguồn được hỗ trợ trong thư mục đã chọn, tính từ ô “Bắt đầu từ ảnh” nếu có. Ảnh trước điểm bắt đầu không thuộc phạm vi job này.

Mỗi lần chạy đối chiếu từng ảnh nguồn với ảnh kết quả hợp lệ. Dòng `done` trong CSV nhưng thiếu/hỏng ảnh kết quả vẫn được coi là chưa hoàn tất. Ảnh lỗi chưa có kết quả hợp lệ được giữ cho thao tác chạy lại ảnh lỗi.

- Exit code 0: lần chạy kết thúc bình thường. Trường `job.state=complete` xác nhận toàn bộ job đã xong; code 0 riêng lẻ cũng có thể chỉ là một batch thành công.
- Exit code 2: batch có ảnh lỗi hoặc hết ảnh chờ nhưng còn ảnh lỗi cần chạy lại.
- Exit code 3: batch chính không làm giảm số ảnh chờ; dừng để tránh lặp lại vô hạn.
- Exit code 4: batch có thể tiếp tục nhưng đang chờ tài khoản ChatGPT khả dụng (`job.state=waiting_quota`); ảnh đang dở không bị ghi là lỗi và giao diện không tự chạy batch kế tiếp.
- Exit code 1: ngoại lệ không xử lý được, chẳng hạn không đọc được thư mục hoặc không khởi động được trình duyệt.

Khi bật “Tự chạy batch tiếp theo”, giao diện tự hẹn chạy lại ảnh lỗi sau thời gian chờ đã cấu hình, rồi quay về batch chính khi hết lỗi. Áp dụng cả khi người dùng bắt đầu bằng “Chạy lại ảnh lỗi”. Ảnh đã có kết quả hợp lệ không bị dịch lại. Không cần bấm chạy mới sau khi khôi phục ảnh lỗi.

Nếu 3 batch chạy lại liên tiếp không khôi phục được ảnh nào, chương trình giữ danh sách lỗi và chuyển sang ảnh chưa xử lý nếu còn. Sau batch chính tiếp theo, chương trình có thể thử khôi phục lỗi lần nữa. Khi hết ảnh chờ mà lỗi vẫn tồn tại sau giới hạn này, chương trình dừng và báo cần chạy lại lỗi; không báo hoàn tất giả. Một batch chạy lại có ảnh thành công sẽ đặt lại bộ đếm không tiến triển.

Batch cuối có ít ảnh hơn cấu hình vẫn được xác nhận hoàn tất job khi toàn bộ kết quả hợp lệ. Không còn ảnh thì worker thoát trước khi mở trình duyệt. Giao diện giữ mở để xem log. Hoàn tất job, hết quota, ngoại lệ worker hoặc người dùng Dừng/Hủy/đổi cấu hình đều không tự khởi động lượt mới. Nút chạy ngay và bộ đếm chờ áp dụng cho cả lượt chạy lại lỗi và batch chính.

Danh sách nguồn được đọc lại khi worker bắt đầu. Nếu thêm ảnh nguồn giữa các batch, các ảnh mới được tính vào lần chạy kế tiếp. Nên giữ nguyên thư mục nguồn trong lúc chạy một job.
