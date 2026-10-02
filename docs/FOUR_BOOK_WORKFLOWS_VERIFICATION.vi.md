# Kiểm chứng bốn luồng sách và sidebar trái

Ngày thực hiện: 2026-10-02. Nhánh: `plan/four-independent-books-sidebar`.
Môi trường: Linux, Python 3.12, Chromium hệ thống qua Playwright.

## Kết quả triển khai

Giao diện Liquid Glass/pywebview có **Sách 1–4** trong sidebar trái. Mỗi sách dùng một WebApi, controller, scheduler, worker subprocess, snapshot, tiến trình, nhóm tài khoản và log riêng. Chuyển sách chỉ đổi nội dung đang hiển thị; các sách nền tiếp tục chạy. Theme, ngôn ngữ và điều khiển cửa sổ dùng chung như trước.

Book 1 giữ `app_settings.json` tại thư mục dữ liệu gốc; Book 2 giữ `workflows/book-2/app_settings.json`. Book 3/Book 4 dùng `workflows/book-3` và `workflows/book-4`. Phiên phụ chưa có settings chỉ kế thừa các tùy chọn chạy giống Book 2 trước đây; nguồn/kết quả/ảnh bắt đầu trống, profile ChatGPT/Gemini riêng. Không clone cookie, account list hoặc kết quả từ sách cũ.

Form cấu hình, tài khoản, log và dock chạy batch tiếp tục áp dụng cho sách đang chọn. Sidebar hiển thị trạng thái, tiến trình batch và cả thư mục của bốn sách. Thông tin dịch vụ/tài khoản được thu gọn, tên dài có tooltip. Nhóm sách giữ bố cục dọc cả ở breakpoint nhỏ, hỗ trợ Up/Down, Left/Right và Home/End. Sidebar có thể cuộn để truy cập shortcut và preferences ở cửa sổ thấp.

Core worker, controller, runtime, scheduler, resource guard và các tiện ích progress không thay đổi. Giữ toàn bộ logic prompt, phản hồi, tạo/tải ảnh, retry/force, auto-next, quota fallback, schema CSV/checkpoint, quyền sở hữu output và protocol kết quả.

## Bằng chứng đã chạy

| Kiểm chứng | Kết quả |
| --- | --- |
| Toàn suite | **188 test: 185 đạt, 3 skip dành riêng cho Windows**, 38,091 giây; exit 0 |
| Session/bridge | 20 test đạt; bốn Start đồng thời tạo đúng một worker cho mỗi sách, snapshot/profile/output riêng; Start trùng cùng sách vẫn bị ngăn |
| Tương thích dữ liệu | Fixture settings đã lưu của cả bốn sách được nạp không đổi; đặc biệt đường dẫn và settings Book 1/Book 2 giữ nguyên. Bytes của file cấu hình, ảnh mẫu cũ, CSV và checkpoint không bị ghi đè khi khởi tạo |
| Độc lập điều khiển | Continue, Stop, clear/copy/export log đúng từng sách; ba phiên khác giữ process/log. Retry/force/login dùng đúng snapshot, profile và mode của cả bốn phiên |
| Auto-next/fallback | Bốn lịch riêng; hủy Book 3 không hủy ba lịch khác; fallback và batch tiếp theo nhận tài khoản của đúng sách. Theme/ngôn ngữ không hủy lịch |
| Xung đột tài nguyên | Kiểm tra cả sáu cặp sách với output trùng/lồng, profile đang dùng, profile fallback và Gemini; cấu hình xung đột bị chặn trước launch |
| Bốn subprocess thật, fixture offline | Bốn PID đồng thời sống; cùng tên `1_1.jpg` nhưng bốn nội dung khác tạo bốn hash khác, CSV/checkpoint/metadata đúng output. Kill Book 3 không làm chết hoặc đổi kết quả của ba sách khác; profile/output đang sống vẫn bị khóa, khóa phiên chết được thu hồi |
| Bốn worker nguồn, input rỗng | Khởi động bằng `build_process_launch` từ ngoài thư mục repo với bốn snapshot riêng; cả bốn exit 0, gửi `__BATCH_RESULT__`, tạo CSV và metadata nguồn đúng sách. Không mở browser hay gọi AI |
| Giao diện Chromium | 11 test workflow/frontend đạt: bốn sách chạy, draft/log/progress/callback đến muộn không trộn phiên; Stop Book 3 giữ Book 1/2/4 chạy; sidebar dịch vụ/tài khoản nền đúng; focus và vùng chọn log ổn định |
| Bố cục | Bốn nút dọc có thể chọn ở 900×620, 1180×820, 1440×1000 và 740×820; không tràn ngang toàn trang. Kiểm tra Việt/Anh, sáng/tối, tên tài khoản dài, tooltip và điều hướng bàn phím |
| Giao diện một phiên/cửa sổ | Ba test frontend một phiên và test thao tác touch cửa sổ đều đạt; payload không có `sessions` tiếp tục hoạt động. Test native shell Windows/macOS/Linux dùng mock không mở ứng dụng ngoài |
| Đóng app | Chỉ Book 3/Book 4 chạy hoặc chờ auto-next vẫn kích hoạt cảnh báo; shutdown dừng đủ bốn process, scheduler và dispatcher |
| Self-test và tĩnh | `app.pyw --self-test` exit 0, `four_sessions: true`; Python compile, `node --check ui/app.js`, `git diff --check` đạt |

Ba test skip: Windows junction alias, Windows process command-line inventory, và phát hiện browser thật qua Windows process inventory. Các mock Windows về taskbar và mở output vẫn chạy trên Linux.

Hạ tầng test frontend phục vụ tài nguyên UI trên HTTP loopback, hỗ trợ `BATCH_TEST_BROWSER` cho Chromium đã cài. Việc này cho phép chạy trong môi trường Chromium hạn chế URL `file://`; không đổi cách khởi động giao diện production. Test Win32 mock tạo `ctypes.windll` khi Linux không có thuộc tính đó; test mở output chọn đúng nhánh hệ điều hành và không thực sự gọi native shell.

## Tái hiện

Cài `requirements.txt`, chuẩn bị Chromium của Playwright hoặc đặt `BATCH_TEST_BROWSER` tới Chromium có sẵn, rồi chạy:

```text
python -m unittest discover -s tests -v
python -m py_compile app.pyw run_chatgpt_batch.py desktop/workflow_sessions.py desktop/webview_app.py desktop/web_text.py tests/verify_packaged_workflows.py
node --check ui/app.js
git diff --check
python app.pyw --self-test
```

Lần kiểm chứng Linux này dùng virtualenv `/tmp/four-books-venv` với requirements của repo, `BATCH_TEST_BROWSER=/usr/bin/chromium` và `PARALLEL_SCREENSHOT_DIR` để xuất ảnh UI. Hạ tầng chạy test cần cho phép socket loopback.

Bằng chứng cục bộ nằm tại `output/four-books-verification/` (được gitignore): `tests.log`, `source-smoke.json`, `self-test.json`, `screenshots/four-books-dark.png` và `screenshots/four-books-light-small.png`. Ảnh chụp dùng bridge giả và số liệu minh họa, không phải dịch sách thật. Thư mục ảnh và snapshot dùng trong smoke/test được tạo tạm, không sử dụng dữ liệu sản xuất.

## Cập nhật bố cục Tài khoản và Nhật ký

Cấu hình nằm ở cột trái; Tài khoản và Nhật ký xếp liền nhau ở cột phải, thay cho Nhật ký toàn chiều ngang bên dưới. Hai cột kết thúc cùng hàng, tận dụng vùng trống dưới Tài khoản. Khi chọn Gemini, Tài khoản được ẩn và Nhật ký dùng toàn bộ chiều cao cột phải. Cửa sổ rộng không quá 1080px chuyển thành một cột: Cấu hình, Tài khoản (nếu có), Nhật ký.

Chỉ thay đổi CSS bố cục; giữ nguyên form, ID điều khiển, bridge, dữ liệu và logic bốn sách. Vùng log có kích thước giới hạn và cuộn riêng; nội dung mới không làm card dài ra hay đẩy cấu hình xuống.

Kiểm tra Chromium với 28 tổ hợp: Việt/Anh × ChatGPT/Gemini × 1180×820, 1440×1000, 1100×700, 1080×820, 900×620, 740×820 và 520×820. Tất cả không tràn ngang; Nhật ký liền ngay dưới Tài khoản ở màn hình rộng, lên đầu cột khi Gemini; log dài vẫn cuộn trong card và không đổi chiều cao bố cục. Ảnh sáng/tối và số đo nằm tại `output/account-log-layout/` (được gitignore), dùng bridge giả và nội dung minh họa.

Sau thay đổi CSS cuối, chạy lại `test_workflow_frontend`, `test_web_frontend` và `test_window_touch`: **15 test đạt**, 20,400 giây; exit 0. Bao gồm chọn/vùng cuộn log khi streaming, chuyển bốn sách, callback đến muộn, theme/ngôn ngữ và thao tác touch cửa sổ. `git diff --check` đạt. Không chạy lại toàn suite backend cho thay đổi chỉ gồm CSS và tài liệu này.

Thanh điều khiển batch được chuyển vào `main.workspace`, ngay dưới cụm card với khoảng cách 16px, cuộn cùng trang. Bỏ vị trí fixed, phép tính căn thanh nổi và phần padding dành cho thanh nổi; sidebar dùng chiều cao cửa sổ mà không trừ chiều cao thanh batch. Giữ nguyên ID, nút điều khiển, tiến trình và logic chạy của bốn sách.

Sau thay đổi thanh batch, **15 test frontend/cửa sổ đạt**, 21,481 giây. Kiểm tra lại 28 tổ hợp kích thước/dịch vụ/ngôn ngữ: thanh batch luôn bên dưới cụm card, không tràn ngang, nút Chạy cuộn đến được và không bị phần tử khác che. Banner chờ thao tác và auto-next tăng chiều cao thanh theo bố cục trang, không đè card; nút chạy ngay gọi đúng sách. `node --check ui/app.js` và `git diff --check` đạt. Ảnh và số đo lần này nằm tại `output/inline-batch-controls/` (được gitignore).

Khung Workspace dùng chung lớp `glass`, bo góc 24px và khoảng đệm 20px như card Cấu hình; bỏ nền chữ nhật đặc. Khung cách cụm card 16px, giữ vị trí sticky và phép tính khoảng cuộn tránh che nội dung khi điều hướng. Cửa sổ thấp thu gọn khoảng đệm dọc. Sau thay đổi này, **15 test frontend/cửa sổ đạt**, 20,678 giây; kiểm tra 28 tổ hợp kích thước/dịch vụ/ngôn ngữ xác nhận nền và bán kính khớp card, tiêu đề nằm trong khung, thanh batch vẫn bên dưới card. Ảnh sáng/tối và số đo nằm tại `output/rounded-workspace-header/` (được gitignore). `git diff --check` đạt; không thay đổi logic chạy sách.

## Những việc cần nghiệm thu trên máy đích

**Chưa kiểm chứng:** cửa sổ pywebview/WebView2 native, đăng nhập và dịch thật đồng thời qua ChatGPT/Gemini, CPU/RAM và chất lượng/tốc độ với bốn browser. Linux headless không thay thế các kiểm chứng này.

Chưa build bản EXE Windows hoặc `.app` macOS trong lần triển khai này. Script `tests/verify_packaged_workflows.py` đã mở rộng để kiểm tra bốn worker đóng gói, nhưng chưa được chạy với bản EXE mới. Trên Windows, rebuild portable từ mã nguồn này rồi chạy:

```text
python tests/verify_packaged_workflows.py <PATH_TO_EXE>
```

Nghiệm thu dịch thật bằng bốn bộ ảnh thử nhỏ có dấu nhận biết sách, cùng tên trang, batch size 1; chọn output và toàn bộ nhóm profile riêng cho mỗi sách. Chạy đồng thời, chuyển sách, dừng/tiếp tục một bên, thử retry/force/auto-next và kiểm tra kết quả đúng sách. Kiểm tra chọn thư mục, theme/ngôn ngữ và cảnh báo đóng app khi chỉ sách mới đang chạy. Không cần làm cạn quota để thử fallback.

Bốn luồng độc lập về dữ liệu/điều khiển nhưng dùng chung CPU/RAM/mạng. Các profile cùng đăng nhập một tài khoản vẫn chịu quota chung. Guard giữ phạm vi phối hợp cùng máy/cùng người dùng OS như trước.
