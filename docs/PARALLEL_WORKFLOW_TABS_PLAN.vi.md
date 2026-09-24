# Kế hoạch thêm tab dịch sách thứ hai

Ngày khảo sát: 2026-09-21. Đã triển khai theo kế hoạch trong mã nguồn; xem [kết quả kiểm chứng](PARALLEL_WORKFLOW_TABS_VERIFICATION.vi.md). Các mục khảo sát bên dưới mô tả trạng thái trước khi sửa. Hai workflow đã được kiểm thử đồng thời bằng dữ liệu giả; chạy dịch thật qua ChatGPT/Gemini và thao tác cửa sổ native vẫn là MANUAL PENDING.

**1. Mục tiêu và quyết định kiến trúc**

Một cửa sổ app có hai tab “Sách 1” và “Sách 2”. Mỗi tab có đầy đủ chức năng hiện có: cấu hình nguồn/kết quả, dịch vụ, tài khoản, đăng nhập, chạy chính, chạy lại ảnh lỗi, chạy lại một ảnh, dừng, tiếp tục khi cần thao tác, tự chạy batch tiếp theo, chuyển tài khoản khi hết lượt, tiến trình và log.

Mỗi tab sở hữu một phiên độc lập: settings, DesktopController, scheduler, worker subprocess, stdin/stdout, hàng đợi sự kiện, trạng thái và lịch auto-next. Hai phiên dùng chung mã workflow và bộ cài; không cần sao chép thư mục chương trình. Worker tiếp tục chạy bằng hai tiến trình riêng vì module hiện giữ cấu hình trong các biến toàn cục như IMAGE_FOLDER, DOWNLOAD_FOLDER và PROFILE_DIR.

Chuyển tab chỉ đổi phần đang hiển thị; tab ẩn vẫn chạy, nhận sự kiện và có chỉ báo tiến trình/cần thao tác. Giao diện dùng chung một thành phần được gắn với session_id, tránh sao chép hai bộ code xử lý dễ lệch chức năng. Theme, ngôn ngữ và thao tác cửa sổ là cấu hình chung.

Phạm vi giao diện là shell pywebview/Liquid Glass hiện tại. Tk cũ vẫn tương thích chạy một phiên; không mở rộng thêm hai tab Tk trong cùng hạng mục. Bảo vệ tài nguyên ở đường vào worker phải áp dụng cả khi worker được mở từ Tk/CLI của phiên bản mới.

**2. Những điểm hiện tại chưa đáp ứng chạy song song**

| Điểm đã xác minh | Hệ quả | Vị trí mã |
| --- | --- | --- |
| WebApi có một settings, controller, scheduler và sequence; JavaScript có một state | Hai tab chỉ sao chép HTML sẽ vẫn điều khiển cùng phiên | desktop/web_api.py:74; ui/app.js:3 |
| Controller chỉ chặn chạy trùng trên chính nó | Chưa có phân xử tài nguyên giữa hai controller hoặc hai app | desktop_controller.py:98 |
| Runtime truyền nguồn, output, profile, mode qua env nhưng không truyền danh sách tài khoản/active account | Chỉ tách đường dẫn trong giao diện chưa đủ để cô lập fallback | desktop/runtime.py:197 |
| Worker vẫn đọc app_settings.json mặc định trước khi áp dụng env | Hai worker có thể lấy cùng danh sách fallback hoặc đọc cấu hình vừa bị tab khác thay đổi | run_chatgpt_batch.py:38,65 |
| Tên ảnh đầu ra chỉ dựa trên số trang/số thứ tự; trạng thái đọc theo tên nguồn và ảnh đầu ra hợp lệ | Hai sách cùng tên trang có thể ghi đè, hoặc bị nhận nhầm là đã dịch xong nếu chung output | run_chatgpt_batch.py:335,497,521 |
| progress.csv, job_checkpoint.json và process_log.txt nằm trong output | Chung output sẽ trộn tiến trình, checkpoint và log; ghi checkpoint nguyên tử không ngăn phiên khác thay thế nội dung | run_chatgpt_batch.py:260,410,425; desktop/web_api.py:670 |
| Fallback tự duyệt danh sách account và mở profile tiếp theo | Profile ban đầu khác nhau vẫn có thể va chạm về sau | run_chatgpt_batch.py:2483 |
| Dừng trên Windows dùng taskkill theo PID và cây tiến trình | Có sẵn nền tảng dừng riêng từng worker; cần xác minh hai cây tiến trình độc lập | desktop_controller.py:455 |

Cấu hình tại thời điểm khảo sát có 3 profile ChatGPT, đang bật fallback và auto-next. Nguồn/kết quả nằm dưới G:\My Drive. Không thay đổi cấu hình này trong bước lập kế hoạch. Không mặc định rằng ba profile là ba tài khoản dịch vụ khác nhau; tên profile không chứng minh danh tính đăng nhập.

**3. Điều kiện bắt buộc để không lẫn hoặc ghi đè kết quả**

| Tài nguyên | Quy tắc cho hai tab |
| --- | --- |
| Nguồn sách | Chọn rõ nguồn của từng sách, giữ ổn định khi chạy. Đọc chung một nguồn về kỹ thuật không tự gây ghi đè, nhưng hai quyển khác nhau phải có lựa chọn nguồn đúng. |
| Output | Hai thư mục riêng; cấm cùng đường dẫn thực và cấm output chồng lên nguồn/profile của bất kỳ phiên nào. Bản đầu cũng chặn output lồng nhau để đơn giản hóa quản lý. |
| Tiến trình | progress.csv, checkpoint, log xuất và các file .part đi theo output của đúng tab; giữ nguyên định dạng hiện có. |
| Profile | Hai tập profile được phép sử dụng phải không giao nhau, kể cả account dự phòng và profile Gemini. Login cũng phải kiểm tra quyền sử dụng profile. |
| Cấu hình | Tách cấu hình lưu lâu dài; mỗi lần khởi động worker có một bản chụp đầy đủ, bất biến của cấu hình phiên đó. |
| Điều khiển | Mọi lệnh/sự kiện của phiên phải có session_id; thao tác Dừng/Tiếp tục/Xóa log/Mở kết quả chỉ tác động tab tương ứng. |
| Auto-next | Lịch, bộ đếm retry, tài khoản vừa fallback và cờ can thiệp tách theo phiên; chỉnh Sách 2 không hủy auto-next Sách 1. |
| Tài nguyên máy | Đo CPU/RAM, I/O và thời gian thực tế với hai browser; không đặt trước yêu cầu RAM hoặc hứa tăng tốc gấp đôi khi chưa đo. |

Playwright nêu rõ không được mở nhiều browser instance cùng một user data directory: [BrowserType.launch_persistent_context](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context).

Profile riêng chỉ cô lập dữ liệu trình duyệt. Không coi việc đăng nhập cùng một tài khoản trong hai profile là có hai phần hạn mức độc lập. Đề xuất dùng hai tài khoản dịch vụ khác nhau nếu muốn giảm ảnh hưởng về hạn mức; vẫn phải xử lý giới hạn/mạng/dịch vụ chậm. OpenAI có giới hạn sử dụng theo gói và giới hạn tạo ảnh: [ChatGPT plans](https://chatgpt.com/pricing/). Không dự đoán số lượt hay thời điểm reset trong hạng mục này.

Với ba profile hiện có, có thể phân nhóm 2+1 hoặc 1+1 và để profile còn lại chưa gán. Một profile dự phòng chỉ được gán cho một nhóm khi cả hai nhóm đang hoạt động. Bản đầu không tự mượn profile của tab kia; hết profile dùng được thì tab đó chuyển sang chờ, giữ nguyên đầu ra đã có.

**4. Thiết kế dữ liệu, worker và sự kiện**

- Thêm WorkflowSession và SessionManager tại lớp desktop. SessionManager quản lý đúng hai session ổn định, không dùng biến “tab đang chọn” để quyết định nơi gửi lệnh đang xử lý.
- Tab 1 tiếp tục dùng app_settings.json và đường dẫn cũ. Tab 2 dùng workflows/book-2/app_settings.json, vùng profile riêng và output riêng được chọn rõ. Chỉ clone các lựa chọn thông thường như batch size/delay/service; không tự clone đường dẫn nguồn, output hoặc danh sách profile đang được Tab 1 sử dụng. Tab 2 chưa chọn sách thì chưa cho chạy.
- Mỗi session có data_dir riêng cho mặc định và việc tạo profile mới. build_process_launch phải nhận đúng data_dir/config của session, tránh quay về get_data_dir(app_dir) khi khởi tạo account hoặc Gemini profile.
- Trước mỗi lần start/main/retry/force/login/auto-next, backend tạo bản chụp cấu hình chứa đầy đủ settings của session, gồm danh sách account đã được gán và active account. Truyền đường dẫn tuyệt đối qua một biến môi trường riêng, dự kiến BATCH_TRANSLATOR_SETTINGS_FILE, trong env riêng của subprocess; không sửa os.environ chung.
- Sửa load_config của worker để ưu tiên bản chụp được chỉ định. Nếu đã chỉ định mà file thiếu/hỏng, dừng rõ lỗi trước khi mở browser/ghi output; tuyệt đối không âm thầm quay về app_settings.json chung. Luồng legacy không truyền biến mới vẫn giữ cách đọc cũ. Các env đã hỗ trợ tiếp tục được dựng từ cùng một bản chụp để tránh hai nguồn cấu hình mâu thuẫn.
- Snapshot và file quản lý phiên đặt trên ổ dữ liệu cục bộ, không đặt trong thư mục đồng bộ output. Ghi settings/snapshot bằng file tạm và replace; tuần tự hóa lưu cấu hình theo session. Giữ schema app_settings của từng phiên tương thích cũ và chỉ tách theme/language ở lớp quản lý chung.
- Mỗi lần start gắn một run_id mới. Lệnh frontend chụp session_id trước mọi await; phản hồi chọn thư mục/lưu/start đến muộn cập nhật đúng session ban đầu. Events gửi ra UI có session_id, run_id và sequence riêng; UI bỏ sự kiện cũ và nạp lại snapshot đúng session khi thiếu sequence. ID này nằm ở lớp bao sự kiện desktop, không cần đổi __BATCH_RESULT__= hoặc __ACCOUNT_EVENT__= của worker.
- Backend tuần tự hóa lệnh cùng session và xử lý cạnh tranh giữa Start, Stop, timer và sự kiện hoàn tất. Kiểm tra/chốt tài nguyên là thao tác nguyên tử giữa hai session; không chỉ dựa vào disabled của nút Start. Không giữ một khóa chung suốt thời gian dịch.
- Sự kiện account_switched chỉ cập nhật settings của session nguồn; lần auto-next dựng snapshot mới từ account đó. Đổi tab/theme/language hoặc mở output không được đánh dấu can thiệp vào workflow.

**5. Kiểm tra xung đột và vòng đời tài nguyên**

Thêm resource_guard dùng chung để chuẩn hóa đường dẫn tuyệt đối, chữ hoa/thường trên Windows, dấu phân cách và liên kết/junction. Với thư mục chưa tồn tại, chuẩn hóa tổ tiên đã tồn tại rồi xác minh lại sau khi tạo. Không dùng so sánh chuỗi prefix để kết luận hai thư mục trùng/chứa nhau. Trường hợp không xác định được danh tính đường dẫn phải báo rõ và chặn start.

Trước start, kiểm tra output với toàn bộ nguồn/output/profile của hai phiên và kiểm tra giao nhau giữa tập profile có thể mở. Nếu fallback bật, phạm vi bảo vệ là cả tập account dự phòng, vì worker tự chọn account bên trong; khóa profile hiện tại là chưa đủ. Login chỉ cần quyền trên profile được mở, không cần quyền ghi vào output.

Trong app, session giữ phần tài nguyên đã gán qua các khoảng chờ auto-next và không cho session khác thay đổi quyền gán giữa chừng. Tại worker, cần khóa độc quyền liên tiến trình trên output và tập profile trước khi khởi tạo progress/checkpoint/browser. Khóa phải có vòng đời theo tiến trình/handle, không chỉ tạo một file cờ, và dùng cùng định danh tài nguyên giữa các bản cài trên máy. Worker của CLI/Tk mới cũng dùng guard này. Kiểm tra lại mỗi lần auto-next; nếu app khác đã lấy tài nguyên thì dừng/chờ có lý do, không cố mở hoặc ghi chung.

Việc thu hồi khóa khi crash phải xét worker/browser còn sống: không chỉ nhìn PID của cửa sổ app và không xóa khóa “cũ” theo thời gian. Chỉ cho tái sử dụng profile sau khi chủ sở hữu đã kết thúc và browser cũ đã đóng. Khi app bị đóng bất thường, lần mở sau phát hiện tài nguyên còn bận thay vì tạo worker trùng. Bản app cũ không có guard và chương trình ngoài app không thể được coi là đã phối hợp khóa; không chạy chúng vào cùng tài nguyên.

Thêm metadata sở hữu output riêng (ví dụ workflow_output.json), ghi nguồn sách và phiên được gán, để ngăn tái dùng nhầm output của sách A cho sách B ở lần chạy sau. Không thay đổi CSV/checkpoint hiện hữu. Với output cũ chưa có metadata, kiểm tra checkpoint/CSV/nguồn trước khi nhận quản lý; nếu mâu thuẫn hoặc không đủ bằng chứng thì giữ nguyên và yêu cầu xác nhận đúng thư mục, không tự nhận nội dung cũ là của sách mới. Chuẩn hóa tên đầu ra và chặn hai file trong cùng nguồn ánh xạ thành một tên output.

Output trên G:\My Drive vẫn phải kiểm tra khả năng đọc/ghi và xác minh ảnh sau tải. Khóa cục bộ không phải khóa phân tán giữa nhiều máy: điều kiện vận hành là không để thiết bị khác cùng ghi vào các thư mục sách này. Không tự di chuyển output hiện tại để phục vụ tính năng mới.

Dừng một tab chỉ hủy lịch và cây tiến trình của tab đó, đợi hoàn tất dọn browser rồi mới giải phóng tài nguyên. Đóng cả cửa sổ có thông báo rõ nếu còn phiên hoạt động; nếu tiếp tục đóng thì dọn cả hai phiên. Sau khi mở lại, phục hồi cấu hình/tiến trình để người dùng chạy tiếp, không tự gửi lại tác vụ dịch chưa được kiểm tra.

**6. Các bước triển khai và phạm vi file**

| Bước | Công việc | File dự kiến |
| --- | --- | --- |
| 1 | Mô hình session, lưu cấu hình riêng, giữ tương thích Tab 1; bản chụp cấu hình đầy đủ | desktop/workflow_sessions.py (mới), desktop/runtime.py; phần load_config trong run_chatgpt_batch.py |
| 2 | Guard đường dẫn/profile/output, khóa liên tiến trình, metadata sách, chống start cạnh tranh | resource_guard.py (mới, không phụ thuộc UI), đường vào worker và SessionManager |
| 3 | Hai controller/scheduler, định tuyến lệnh/sự kiện, stop/continue/login/fallback/auto-next theo session | desktop/web_api.py, desktop/webview_app.py, desktop_controller.py nếu cần gắn vòng đời run; tái dùng desktop/web_scheduler.py |
| 4 | Thanh hai tab, một bộ component dùng chung, state/draft/log riêng, chỉ báo tab nền và thông báo xung đột tiếng Việt/Anh | ui/index.html, ui/app.js, ui/styles.css, desktop/web_text.py |
| 5 | Kiểm thử cách ly, hồi quy một phiên, thử thật trên dữ liệu riêng; kiểm tra bản đóng gói | tests hiện có, tests/test_workflow_sessions.py và tests/test_resource_guard.py (mới), self-test/đường đóng gói liên quan, README.md |

Giữ nguyên chuỗi chép → dịch → tạo ảnh → tải/kiểm tra; prompt, cách chọn ảnh, cách nhận diện ảnh kết quả và tên đầu ra đã hợp lệ. Thay đổi worker tập trung vào đầu vào cấu hình và quyền sử dụng tài nguyên. Các điều chỉnh khác chỉ thêm khi kiểm thử chứng minh cần thiết. Không đổi schema CSV/checkpoint hoặc protocol stdout để tiện việc thêm tab.

**7. Kiểm thử và tiêu chí nghiệm thu**

| Tình huống | Kết quả bắt buộc |
| --- | --- |
| Hai sách có file cùng tên, ví dụ 1_1.jpg, chạy đồng thời | Output/checkpoint/CSV mỗi bên chỉ chứa kết quả và đường dẫn của sách đó; không bỏ qua nhầm vì sách kia đã có ảnh |
| Hai Start đến gần đồng thời, hoặc Start gặp auto-next | Tối đa một worker trên một session; tối đa một chủ sở hữu trên mỗi tài nguyên |
| Trùng output/profile qua chữ hoa/thường, đường tương đối, junction; output nằm trong nguồn bên kia | Chặn trước khi ghi progress, gửi prompt hoặc mở profile |
| Snapshot B có account B nhưng app_settings.json gốc chỉ có account A | Worker B chỉ nhận account B; snapshot hỏng không fallback về A |
| A hết lượt và tự đổi profile; B đang dịch | A chỉ dùng nhóm đã gán, đúng ảnh đang dở; B không bị đổi tài khoản hay gián đoạn; không cố tiêu hết quota thật để kiểm thử |
| Dừng/tiếp tục/retry/force/xóa log/xuất log/mở output ở A | B giữ nguyên PID, tiến trình, cấu hình và lịch; ảnh B đã hoàn tất không đổi hash |
| Chuyển tab trong lúc lưu/chọn thư mục/khởi động; sự kiện đến muộn | Không ghi cấu hình hoặc log sang tab khác, không mất draft nhập dở |
| Một tab ẩn đang chờ thao tác hoặc lỗi | Thanh tab vẫn báo rõ; điều khiển tab còn lại hoạt động bình thường |
| Hai lịch auto-next khác nhau; thay theme/language; A dừng hoặc lỗi | Mỗi lịch và tài khoản sau fallback đúng session; B vẫn tiếp tục |
| Worker/app crash; browser còn sống; khởi động lại | Không chạy trùng, không giải phóng profile quá sớm; file đã hoàn tất còn nguyên; phần dở được kiểm tra trước chạy tiếp |
| Một nguồn có hai file ánh xạ cùng tên output; chọn lại output sách khác | Phát hiện sớm và báo rõ, không ghi đè hoặc nhận nhầm hoàn tất |
| Hồi quy một tab và Tk/CLI cũ tương thích | Cấu hình hiện có vẫn tải được; main/retry/force/login và protocol kết quả giữ đúng hành vi |

Thứ tự xác minh: unit test SessionManager/runtime/guard/controller bằng fake process và thư mục tạm; kiểm thử hai subprocess thật với dữ liệu giả trên đĩa; frontend fake bridge cho sự kiện xen kẽ; sau đó mới GUI/E2E thật và bản EXE.

Chạy lại các nhóm test hiện có: test_desktop_controller, test_web_api, test_web_scheduler, test_web_frontend, test_regressions, test_quota_fallback, test_image_results và test_launcher. Chỉ dùng fixture/thư mục test, không chạy cả sách sản xuất hoặc sửa progress.csv hiện có để thử.

E2E nghiệm thu: chuẩn bị hai nguồn thử riêng có dấu nhận biết A/B và tên file giống nhau, ít nhất 3 ảnh mỗi bên, batch size 1 để quan sát nhiều vòng auto-next. Xác minh ảnh mở được, đúng sách/đúng trang, đúng đường dẫn; thử dừng một tab, chuyển tab liên tục, chạy tiếp và khởi động lại. Ghi PID, đường dẫn profile, log từng phiên, SHA-256 của ảnh đã hoàn tất và CPU/RAM/thời gian quan sát được. Không so byte của hai lần AI sinh ảnh để kết luận chất lượng; hash dùng để phát hiện ảnh đã có bị thay đổi.

Bản EXE phải được kiểm tra truyền snapshot và chạy đúng --worker ngoài thư mục mã nguồn; self-test không thay thế tương tác GUI. Những mục chưa chạy thật phải ghi MANUAL PENDING. Chỉ kết luận đạt khả năng chạy song song sau khi có bằng chứng cho cả cách ly dữ liệu và vòng đời hai phiên.

**8. Giới hạn của cam kết**

Mục tiêu có thể nghiệm thu là không trộn nguồn, không ghi đè chéo, không nhầm tiến trình và không để thao tác một tab điều khiển tab kia. Việc giữ cùng workflow giúp giữ cơ chế xử lý hiện có, nhưng không đảm bảo AI luôn cho bản dịch/ảnh giống hệt giữa các lần chạy; tốc độ, quota, đăng nhập và lỗi dịch vụ vẫn có thể ảnh hưởng thời gian hoàn thành.

Đề xuất triển khai theo thứ tự: tách session/config → bảo vệ tài nguyên → nối hai tab → kiểm thử đồng thời → kiểm tra EXE. Không coi giao diện hai tab là hoàn thành nếu worker vẫn còn đọc cấu hình hoặc dùng profile chung.
