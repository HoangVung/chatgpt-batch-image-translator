# Kế hoạch mở rộng thành 4 luồng sách và chuyển bộ chọn sách sang sidebar

Ngày khảo sát: 2026-10-02. Nhánh: `plan/four-independent-books-sidebar`.
Mốc mã nguồn: `1c833bf` trên nhánh `work`.

Trạng thái: **đã triển khai bốn phiên và sidebar trái**; xem [kết quả kiểm chứng](FOUR_BOOK_WORKFLOWS_VERIFICATION.vi.md). Các bảng khảo sát và bước triển khai bên dưới ghi lại kế hoạch từ mốc mã nguồn ban đầu.
Yêu cầu giữ nguyên logic được hiểu là giữ toàn bộ hành vi hiện có của hai phiên Book 1/Book 2.

## 1. Kết luận và phạm vi

Có thể thêm Book 3/Book 4 bằng cách mở rộng kiến trúc session hiện có. Mỗi sách tiếp tục có một `WebApi`, `DesktopController`, scheduler và worker subprocess riêng. Bốn worker dùng chung mã xử lý; không cần sao chép worker thành bốn bản hoặc chạy chung các biến toàn cục trong một tiến trình.

Giao diện cần hiển thị đủ bốn sách. Chuyển bộ chọn Book 1–4 sang sidebar trái là phương án đề xuất: tận dụng sidebar sẵn có, tránh ép bốn thẻ vào header và quan sát được sách nền. Đây là thay đổi bố cục điều hướng; không cần thiết kế lại form cấu hình, tài khoản, log hoặc dock chạy batch. Giữ tab ngang cũng khả thi về kỹ thuật, nhưng cần kiểm tra độ rộng và khả năng đọc trạng thái.

Phạm vi là giao diện Liquid Glass/pywebview đang dùng. Tk dự phòng hiện chỉ có một phiên; giữ phạm vi đó theo kiến trúc hiện hành. Không sửa bản thử nghiệm trong `poc/pywebview_ui`.

## 2. Những điểm đã xác minh trong mã nguồn

| Điểm khảo sát | Hiện trạng | Hướng xử lý |
| --- | --- | --- |
| `desktop/workflow_sessions.py:32–45` | Khởi tạo đúng hai session; dùng `first, second = self.sessions.values()` để đặt mặc định | Khai báo danh sách bốn ID theo thứ tự; thay khởi tạo phiên phụ bằng vòng lặp |
| `desktop/workflow_sessions.py:54–63` | Kiểm tra tài nguyên với tất cả session khác | Giữ cơ chế và bổ sung kiểm thử cả sáu cặp sách |
| `desktop/workflow_sessions.py:82–170` | Bridge định tuyến theo `session_id`; preferences, dispatcher, đóng app đã duyệt session | Giữ hợp đồng API; kiểm chứng vòng đời với bốn phiên |
| `desktop/web_api.py:84–113`, `:430` | Settings, controller, scheduler và launch snapshot thuộc từng phiên | Tái sử dụng nguyên cơ chế cho Book 3/Book 4 |
| `desktop/webview_app.py:149` | Self-test kiểm tra `two_sessions == 2` | Cập nhật kiểm tra đúng tập ID Book 1–4, không chỉ số lượng |
| `ui/index.html:34–67`, `:75` | Sidebar trái đã có; bộ chọn sách đang ở header | Di chuyển bộ chọn sách vào sidebar |
| `ui/app.js:38–118`, `:129–134`, `:352`, `:420–424` | Render, draft, chuyển sách và sự kiện sử dụng Map/session ID; số sách không bị cố định ở hai | Giữ xử lý phiên; bổ sung bàn phím theo bố cục dọc |
| `ui/styles.css:55–61`, `:243–255`, `:1085`, `:1647` | Tab ngang; sidebar có cuộn; dưới 760 px sidebar chuyển lên trên | Điều chỉnh layout dọc và trạng thái overflow cho bốn sách |
| `desktop/web_text.py:6–11`, `:93–98` | Một số chuỗi ghi rõ “hai phiên”/“both” | Sửa mô tả và cảnh báo đóng app cho bốn sách, cả Việt/Anh |
| `tests/test_workflow_sessions.py` | Barrier(2), unpack hai phiên và assertion số lượng 2 | Mở rộng fixture bốn phiên, giữ các kiểm chứng hành vi cũ |
| `tests/test_workflow_frontend.py:249–258` | Kiểm tra hai tab cạnh nhau ở ba kích thước cửa sổ | Thay assertion bố cục ngang bằng kiểm tra sidebar dọc và bốn nút có thể truy cập |
| `tests/verify_packaged_workflows.py:29`, `:84` | Smoke bản EXE khởi động hai worker | Mở rộng thành bốn worker độc lập |

Các vị trí trên tham chiếu mốc khảo sát; số dòng có thể đổi khi triển khai. Kết quả kiểm chứng hai phiên trước đây nằm tại [PARALLEL_WORKFLOW_TABS_VERIFICATION.vi.md](PARALLEL_WORKFLOW_TABS_VERIFICATION.vi.md).

## 3. Các hành vi phải giữ nguyên

- Book 1 tiếp tục đọc `app_settings.json` trong `data_dir` gốc. Book 2 tiếp tục đọc `workflows/book-2/app_settings.json`. Không di chuyển, reset hoặc thay đường dẫn profile của hai sách này.
- Giữ quy tắc khởi tạo Book 2 hiện có: khi chưa có settings thì kế thừa một nhóm tùy chọn từ Book 1, có profile riêng, để trống nguồn/kết quả/ảnh bắt đầu. Không ghi đè settings đã lưu khi khởi động.
- Giữ nguyên chuỗi prompt, chờ phản hồi, tạo/tải/kiểm tra ảnh, quy tắc đặt tên file, phát hiện ảnh hoàn thành và các cơ chế tải dự phòng trong worker.
- Giữ chạy chính, retry ảnh lỗi, force rerun một ảnh, dừng, tiếp tục khi cần thao tác, auto-next, hủy/chạy ngay lịch và chuyển tài khoản khi hết quota.
- Giữ schema `progress.csv`, checkpoint, `workflow_output.json`, exit code và protocol kết quả/sự kiện. Giữ xác nhận kết quả cũ như hiện tại.
- Lệnh, callback, draft, tài khoản, sequence, tiến trình và log phải thuộc phiên ban đầu dù người dùng đổi sách trong lúc đợi phản hồi.
- Ngôn ngữ, theme và thao tác cửa sổ vẫn dùng chung toàn app. Các nút thao tác sách áp dụng cho sách đang chọn.
- Giữ khóa và kiểm tra xung đột tài nguyên hiện có. Không đổi quy tắc cho phép nguồn dùng chung; với bốn sách khác nhau nên chọn bốn bộ nguồn riêng. Output và nhóm profile phải tách biệt theo guard hiện hành.

Việc “clone tab” nghĩa là thêm hai instance của workflow hiện có. Không clone thư mục trình duyệt, cookie, tài khoản, ảnh hoặc kết quả của Book 1/Book 2 sang sách mới.

## 4. Kiến trúc bốn phiên

| ID ổn định | Thư mục dữ liệu | Settings | Khởi tạo |
| --- | --- | --- | --- |
| `book-1` | `data_dir` | `data_dir/app_settings.json` | Giữ nguyên |
| `book-2` | `data_dir/workflows/book-2` | `workflows/book-2/app_settings.json` | Giữ nguyên |
| `book-3` | `data_dir/workflows/book-3` | `workflows/book-3/app_settings.json` | Mới, độc lập |
| `book-4` | `data_dir/workflows/book-4` | `workflows/book-4/app_settings.json` | Mới, độc lập |

`data_dir` vẫn được xác định bởi runtime hiện tại: Windows/source/portable theo thư mục app, macOS theo Application Support. Không đổi cơ chế này.

1. Định nghĩa danh sách session có thứ tự `book-1`, `book-2`, `book-3`, `book-4` tại bộ quản lý. Book 1 là phiên mặc định và nguồn preferences chung, giữ tương thích với lệnh không truyền ID.
2. Khởi tạo từng `WebApi` bằng `data_dir` tương ứng. Các phiên phụ chưa có settings chỉ kế thừa đúng whitelist hiện dùng: `service`, `batch_size`, `auto_next_enabled`, `auto_next_delay_minutes`, `auto_account_fallback_enabled`. Đồng bộ theme/ngôn ngữ như trước. Không kế thừa danh sách tài khoản hay đường dẫn.
3. Book 3/Book 4 chưa cấu hình có nguồn, output, `start_from` trống; profile ChatGPT/Gemini và tài khoản mặc định được tạo từ thư mục dữ liệu riêng. Cấu hình đã tồn tại ở Book 3/Book 4 được nạp như các phiên khác.
4. Mỗi phiên sở hữu controller, scheduler, process handle, stdin/stdout, hàng đợi sự kiện, bộ đếm sequence, draft và snapshot riêng. Mỗi lần chạy dùng JSON snapshot đầy đủ trong `run_configs` của phiên đó, kể cả nhóm tài khoản fallback.
5. Giữ `SessionManager._lock` dùng chung để bảo vệ lệnh điều khiển và khởi chạy. Worker xử lý ảnh vẫn là bốn tiến trình chạy đồng thời; không cần bỏ khóa để tăng số phiên. Hộp chọn thư mục tiếp tục nằm ngoài khóa chung theo cơ chế hiện tại.
6. Giữ `_validate_layout` đối chiếu với mọi phiên, guard ở cửa vào worker và quyền sở hữu output. Profile của tài khoản fallback cũng phải tách biệt giữa sách. Lệnh có ID lạ tiếp tục bị từ chối.
7. Dispatcher, gắn renderer, preferences và shutdown phải bao phủ cả bốn phiên. Cảnh báo đóng app tính cả phiên đang chạy và phiên đang chờ auto-next; đóng app dừng đủ các phiên.

Không cần thêm port trình duyệt riêng trong phạm vi này: worker hiện dùng `launch_persistent_context` với `user_data_dir` của profile, không có cặp port cố định cho hai sách.

## 5. Bố cục sidebar đề xuất

Phác thảo sau minh họa bố cục và trạng thái giả, không phải ảnh giao diện đã triển khai:

```text
┌──────────────────────────┬──────────────────────────────────────┐
│ Batch Image Translator   │ Cấu hình / tài khoản của sách chọn  │
│                          │                                      │
│ SÁCH                     │ Nội dung form hiện có                │
│ ▣ Sách 1   Đang chạy 3/10 │                                      │
│   Cả thư mục: 13/100      │                                      │
│ ▢ Sách 2   Chờ batch sau  │                                      │
│   Cả thư mục: 42/200      │ Log riêng của sách chọn              │
│ ▢ Sách 3   Cần thao tác   │                                      │
│   Cả thư mục: 6/80        │                                      │
│ ▢ Sách 4   Sẵn sàng       │                                      │
│   Cả thư mục: 0/120       │                                      │
│                          │                                      │
│ Dashboard / Tài khoản /  │                                      │
│ Cấu hình                 │                                      │
│ Dịch vụ / tài khoản      │                                      │
│ Ngôn ngữ / Theme         │                                      │
├──────────────────────────┴──────────────────────────────────────┤
│ Dock hiện có: Sách đang chọn · Retry · Force · Chạy · Tiếp · Dừng│
└─────────────────────────────────────────────────────────────────┘
```

- Đặt nhóm Sách dưới brand, trước các shortcut Dashboard/Tài khoản/Cấu hình. Bốn sách là bốn nút chọn; nhóm đang chọn có highlight rõ.
- Di chuyển một container `#workflow-tabs` vào sidebar, giữ ID `tab-book-N` và panel `#workflow-panel`. Không tạo thêm bộ chọn thứ hai ở header, không nhân bản bốn form hoặc bốn dock.
- Mỗi nút giữ tên sách, trạng thái chạy/chờ/cần thao tác và tiến trình cả thư mục như hiện tại. Tooltip cung cấp thông tin đầy đủ khi chữ dài. Sự kiện nền vẫn cập nhật đúng nút và không tự chuyển sách đang chọn.
- Giữ `#service-contexts` và `renderServiceContexts()` hiện có; thu gọn từng `.book-service-context` bằng CSS để tên sách và dịch vụ/tài khoản dễ đọc, tên tài khoản dài có ellipsis và tooltip đầy đủ. Không ghép thêm phần tử con vào nút sách vì `renderTabs()` đang dùng vị trí con để cập nhật trạng thái/tiến trình. Kiểm tra chiều cao ở cửa sổ tối thiểu, gồm tên tài khoản dài và cảnh báo.
- Giữ tương thích frontend một phiên: payload không có `sessions`, API không truyền ID và các ID `#service-context`/`#account-context` vẫn hoạt động. Trường hợp này đã được kiểm thử trong `tests/test_web_frontend.py`.
- Giữ `role=tablist`, `role=tab`, `aria-selected`, `aria-controls`, roving tabindex và liên kết panel với sách chọn. Thêm `aria-orientation=vertical` cùng ArrowUp/ArrowDown; giữ Home/End và hỗ trợ Left/Right để tương thích thao tác hiện có.
- Khi thu nhỏ dưới breakpoint hiện có, sidebar có thể chuyển lên trên như trước. Bốn nút phải có thể truy cập, không gây cuộn ngang toàn trang; cập nhật orientation/bàn phím theo bố cục thực tế nếu đổi sang hàng ngang.
- CSS cần xử lý `flex-shrink`, chiều cao nút, overflow và vùng cuộn để bốn sách, shortcut và preferences không bị che bởi dock, đặc biệt ở 900×620. Tránh để cập nhật log tạo lại nút, làm mất focus hoặc vùng chọn log.

## 6. Thứ tự triển khai

| Bước | Công việc | Điều kiện hoàn thành |
| --- | --- | --- |
| 1. Ghi nhận tương thích | Fixture settings cũ cho Book 1/Book 2; mốc đường dẫn, dữ liệu và hành vi; giữ các case hiện có | Nâng lên bốn phiên không reset hoặc đổi cấu hình của hai sách cũ |
| 2. Mở rộng session | Sửa khởi tạo tại `desktop/workflow_sessions.py`; bốn ID và dữ liệu riêng; cập nhật self-test | Initial state có đúng bốn ID, mỗi phiên có controller/scheduler riêng; bốn Start tạo bốn worker |
| 3. Bố trí sidebar | Sửa `ui/index.html`, `ui/styles.css`, bổ sung điều hướng trong `ui/app.js` | Chọn sách không dừng sách nền; form/dock/log đúng phiên; bàn phím và cửa sổ nhỏ dùng được |
| 4. Cập nhật chữ | Sửa Việt/Anh trong `desktop/web_text.py`; cập nhật mô tả HTML | Không còn cảnh báo nói chỉ dừng hai phiên hoặc mô tả chỉ có hai sách |
| 5. Kiểm chứng | Mở rộng session/frontend/guard/package tests; chạy regression | Đạt các tiêu chí ở phần 7; ghi rõ kiểm thử thật còn thiếu |
| 6. Tài liệu và bản build | Cập nhật README Việt/Anh thành bốn sách; viết tài liệu kiểm chứng mới; build Windows/macOS theo môi trường có sẵn | Tài liệu phản ánh kết quả thực tế; self-test và smoke gói build kiểm tra đủ bốn phiên |

Các file dự kiến sửa chính: `desktop/workflow_sessions.py`, `desktop/webview_app.py`, `desktop/web_text.py`, `ui/index.html`, `ui/app.js`, `ui/styles.css`, các test workflow/guard/package và `README.md`.

`run_chatgpt_batch.py`, `desktop_controller.py`, `desktop/runtime.py`, `desktop/web_scheduler.py`, `resource_guard.py` và `progress_utils.py` được tái sử dụng theo logic hiện tại. Nếu kiểm thử phát hiện lỗi buộc sửa những module này, phải mô tả tác động và bổ sung kiểm chứng tương thích trước khi gộp thay đổi.

## 7. Kiểm thử và tiêu chí nghiệm thu

| Nhóm | Kiểm chứng bắt buộc |
| --- | --- |
| Tương thích dữ liệu | Nạp settings Book 1/Book 2 đã lưu; đường dẫn nguồn/output/ChatGPT/Gemini, danh sách tài khoản, lựa chọn tài khoản và tùy chọn chạy không đổi. Khởi tạo bốn phiên không viết đè cấu hình cũ; ảnh/CSV/checkpoint cũ không bị sửa |
| Mặc định phiên mới | Book 3/Book 4 nguồn/output/start trống, profile và settings riêng; không clone tài khoản/profile của hai sách cũ; khởi động lại giữ cấu hình đã lưu |
| Khởi chạy song song | Barrier bốn Start trên bốn ID; assert đủ bốn phản hồi thành công và đúng một process mỗi sách. So sánh snapshot/env cho tất cả cặp. Hai Start cùng một sách vẫn chỉ tạo một worker |
| Điều khiển độc lập | Lặp sách đích qua cả bốn ID: stop/continue/retry/force/clear/copy/export log đúng sách; các process và log của ba sách còn lại không đổi |
| Lịch và tài khoản | Cả bốn scheduler có thể chờ lịch; hủy/chạy ngay một sách không đổi ba sách khác. Fallback và snapshot batch kế tiếp đúng danh sách tài khoản của sách đó, gồm Book 3/Book 4 |
| Xung đột tài nguyên | Kiểm tra cả sáu cặp: output trùng/lồng, profile chính/fallback/Gemini trùng hoặc alias bị chặn theo guard hiện tại; cấu hình không xung đột chạy được. Giữ kiểm tra quyền sở hữu output và xác nhận dữ liệu cũ |
| Bốn subprocess offline | Mở rộng fixture hiện có thành bốn sách có cùng tên `1_1.jpg`, nội dung khác nhau. Bốn PID cùng sống, bốn output khác hash, CSV/checkpoint đúng sách. Kill một worker không đổi PID/kết quả ba worker còn lại; khóa của phiên chết được thu hồi, tài nguyên của phiên còn sống vẫn bị bảo vệ |
| Frontend bất đồng bộ | Sự kiện xen kẽ và callback đến muộn khi đổi qua bốn sách không trộn log/progress/draft hoặc chuyển tác dụng lệnh. Thông tin dịch vụ/tài khoản nền vẫn đúng; lỗi/cần thao tác nền không tự chuyển sách. Giữ các test một phiên với payload không có `sessions`, API không truyền ID và `#service-context`/`#account-context` |
| Bố cục và accessibility | Bốn sách xuất hiện trong sidebar, chọn bằng chuột/bàn phím; focus/log selection ổn định. Kiểm tra sáng/tối/hệ thống, Việt/Anh, 900×620, 1180×820, 1440×1000 và dưới breakpoint 760 px; không tràn ngang hoặc mất nút/preferences vì dock |
| Preferences và đóng app | Theme/ngôn ngữ đồng bộ cả bốn; đổi preferences không hủy lịch. Đóng khi chỉ Book 3 hoặc Book 4 chạy/chờ lịch vẫn cảnh báo; shutdown dừng đủ bốn controller/scheduler/dispatcher |
| Source và portable | Self-test đúng tập bốn ID; smoke bốn worker đóng gói với snapshot/output riêng và nguồn rỗng; giữ case snapshot lỗi và tranh tài nguyên, không chờ dialog lỗi ẩn |
| Regression worker | Chạy lại suite hiện có về launcher, controller, quota fallback, response/image detection, progress/checkpoint, retry/force và resource guard |

Giữ các kiểm thử hành vi Book 1/Book 2 khi mở rộng fixture; không xóa case cũ chỉ để đạt assertion số lượng bốn. Các test hai worker vẫn có giá trị; bổ sung hoặc tổng quát hóa chúng để kiểm chứng bốn worker. Thay assertion “hai tab nằm cạnh nhau” bằng assertion đúng bố cục sidebar.

Lệnh kiểm chứng sau triển khai:

```text
python -m unittest discover -s tests -v
python -m py_compile app.pyw run_chatgpt_batch.py desktop/workflow_sessions.py desktop/webview_app.py desktop/web_text.py
node --check ui/app.js
git diff --check
python app.pyw --self-test
python tests/verify_packaged_workflows.py <PATH_TO_EXE>
```

Các test trình duyệt cần Playwright/Chromium; bản EXE và thao tác native cần môi trường Windows tương ứng. Chỉ ghi là đã đạt những kiểm chứng thực sự chạy được.

Nghiệm thu thủ công sau triển khai: chọn bốn bộ ảnh thử nhỏ có dấu nhận biết sách, batch size 1, bốn output và profile riêng; đăng nhập dịch vụ; chạy bốn sách đồng thời, chuyển sách, dừng/tiếp tục một bên, kiểm tra kết quả và auto-next. Kiểm tra cửa sổ native, hộp chọn thư mục và đóng app. Không cần làm cạn quota để kiểm chứng fallback. Ghi CPU/RAM và độ trễ UI lúc bốn browser hoạt động.

## 8. Giới hạn thực tế và trạng thái kiểm chứng

- Bốn luồng độc lập về dữ liệu và điều khiển, nhưng chia sẻ CPU/RAM/mạng của máy. Chưa có số đo để cam kết tốc độ tăng gấp bốn.
- Nhiều profile đăng nhập cùng một tài khoản vẫn chịu quota của tài khoản đó. Tách profile không tạo hạn mức dịch vụ riêng.
- Khóa hiện tại phối hợp các tiến trình phiên bản mới cùng máy/cùng người dùng OS; giữ giới hạn này, không mở rộng thành khóa phân tán giữa nhiều máy.
- Khóa quản lý chung có thể làm lệnh/sự kiện chờ nhau trong đoạn xử lý ngắn. Đo phản hồi khi bốn sách phát log/progress đồng thời trước khi quyết định tối ưu; không tự đổi mô hình khóa hoặc core worker.

Trong lần khảo sát này đã chạy:

```text
python -m unittest discover -s tests -p test_workflow_sessions.py -v
```

Kết quả khảo sát trước triển khai: **11/11 kiểm thử session hiện có đạt** trên môi trường Linux. Đây là mốc tương thích của phiên bản hai sách. Sau triển khai, toàn suite có **188 test: 185 đạt và 3 skip Windows**; đã kiểm chứng frontend Chromium, bốn subprocess offline, bốn worker nguồn và self-test. Bản portable và dịch thật vẫn cần nghiệm thu; xem [kết quả kiểm chứng](FOUR_BOOK_WORKFLOWS_VERIFICATION.vi.md).
