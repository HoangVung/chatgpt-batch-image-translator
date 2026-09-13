**Báo cáo nghiên cứu và kế hoạch bổ sung giao diện macOS Golden Gate trên Windows**

Ngày đối chiếu nguồn: **14/09/2026**. Dự án: ChatGPT Batch Image Translator.

**Đề xuất chọn CustomTkinter hiện tại để bổ sung phong cách Golden Gate.** Giữ giao diện Gốc làm mặc định, thêm lựa chọn mới và giữ nguyên workflow. Nếu ưu tiên hiệu ứng kính động ở mức cao hơn, PySide6 + Qt Quick/QML là phương án kỹ thuật đáng cân nhắc, nhưng chuyển framework không nằm trong kế hoạch thay giao diện này.

Tài liệu này là kết quả đọc mã nguồn và nghiên cứu tài liệu chính thức. Chưa triển khai theme, chưa chạy thử Golden Gate trên app, chưa đo hiệu năng hoặc độ giống bằng ảnh chụp. Những thông số thiết kế, lịch thực hiện và tiêu chí nghiệm thu dưới đây là đề xuất cho bước triển khai.

Phạm vi đã chốt theo yêu cầu: giữ CustomTkinter gốc ổn định; thêm lựa chọn Golden Gate; nghiên cứu công cụ chạy trên Windows; chỉ thay phần trình bày. Không thêm chức năng xử lý ảnh, thay quy tắc batch, retry, prompt, browser, tải ảnh hay điều kiện chạy tiếp.

**Hiện trạng đã xác minh trong mã nguồn**

Các liên kết dưới đây trỏ đến bản đang có trong workspace, bao gồm cả thay đổi chưa commit của người dùng. Khi triển khai phải lấy bản này làm mốc, không tự đưa repo về HEAD.

| Thành phần | Hiện trạng | Ý nghĩa đối với kế hoạch |
|---|---|---|
| Nền giao diện | [requirements.txt](D:/0-vung-apps/chatgpt-batch-image-translator/requirements.txt) khai báo `customtkinter>=5.2,<6`; [app.pyw](D:/0-vung-apps/chatgpt-batch-image-translator/app.pyw:10) dùng cả CustomTkinter và Tkinter | Tận dụng cùng widget và event loop; không cần cài framework mới |
| Cửa sổ | [Khởi tạo](D:/0-vung-apps/chatgpt-batch-image-translator/app.pyw:321): 1180×820, tối thiểu 900×620 | Đây là mốc kích thước kiểm tra; phải kiểm tra thêm DPI thực tế |
| Sáng/tối | [get_palette](D:/0-vung-apps/chatgpt-batch-image-translator/app.pyw:444), `setup_style`, `effective_theme_code` | Đã có nền tảng màu; phong cách mới phải độc lập với sáng/tối |
| Bố cục | [build_ui](D:/0-vung-apps/chatgpt-batch-image-translator/app.pyw:577): header, cấu hình, thao tác, tiến độ, log, trạng thái; có cuộn và bố cục thích ứng | Giữ thứ tự công việc và khả năng tiếp cận mọi nút |
| Ràng buộc giao diện–workflow | [build_ui](D:/0-vung-apps/chatgpt-batch-image-translator/app.pyw:691) tạo `StringVar`, gắn trace; có callback đổi dịch vụ/profile và đồng bộ progress | Không được coi toàn bộ `build_ui` là mã trang trí để viết lại tùy ý |
| Đổi theme/ngôn ngữ | [set_theme và set_language](D:/0-vung-apps/chatgpt-batch-image-translator/app.pyw:384) gọi `cancel_auto_next`, lưu cấu hình, hủy widget rồi dựng lại | Không tái sử dụng đường gọi này cho thao tác chọn phong cách mới |
| Điều phối | [start](D:/0-vung-apps/chatgpt-batch-image-translator/app.pyw:1484), xử lý log, timer, stop và continue nằm trong cùng lớp với UI | Chỉ giữ file worker nguyên vẹn là chưa đủ để chứng minh workflow không đổi |
| Đóng gói | [build_portable.ps1](D:/0-vung-apps/chatgpt-batch-image-translator/build_portable.ps1) dùng PyInstaller `--onedir --windowed`, worker `--worker` | Giữ cơ chế portable và khởi động worker; chỉ bổ sung tài nguyên UI nếu cần |
| Kiểm thử | [test_regressions.py](D:/0-vung-apps/chatgpt-batch-image-translator/tests/test_regressions.py), [test_image_results.py](D:/0-vung-apps/chatgpt-batch-image-translator/tests/test_image_results.py) đã có kiểm tra batch, progress, manual action, auto-next và ảnh | Tái sử dụng kiểm thử hiện có, bổ sung kiểm tra chuyển phong cách |

Phát hiện cần chú ý: `on_run_configuration_changed` đánh dấu người dùng can thiệp và hủy auto-next. Vì vậy, ghi lại một `StringVar` nghiệp vụ dù giá trị trông giống trước đó vẫn có thể tác động workflow. Chuyển phong cách phải tránh mọi thao tác này. Đây là ranh giới triển khai, không phải đề xuất sửa hành vi cũ của nút sáng/tối hay ngôn ngữ.

**Kết quả nghiên cứu thiết kế Golden Gate**

Apple xác nhận tên **macOS 27 Golden Gate**, công bố khả dụng từ 14/9. Trang sản phẩm mô tả Liquid Glass được tinh chỉnh để tăng độ rõ và tương phản, toolbar nhất quán hơn, sidebar sát mép, thay đổi hình cửa sổ và biểu tượng menu bar; có thanh chỉnh độ trong. Đây là mốc thiết kế được dùng cho báo cáo, không chỉ dựa trên Tahoe 26. Chưa xác minh thời điểm bản cập nhật tới từng máy. [Apple — macOS Golden Gate](https://www.apple.com/os/macos/)

Hướng dẫn vật liệu của Apple đặt Liquid Glass ở lớp điều khiển và điều hướng, dùng có chọn lọc; nội dung cần nền phù hợp để dễ đọc. Với app này, có thể áp dụng tinh thần đó vào header và nhóm thao tác, còn log và trường cấu hình cần độ rõ ổn định. [Apple HIG — Materials](https://developer.apple.com/design/human-interface-guidelines/materials)

Toolbar nên nhóm các điều khiển theo mục đích và vị trí dễ dự đoán. Bố cục phải phân biệt điều khiển với nội dung, giữ căn hàng và thứ bậc thị giác. Vì app hiện không có hệ thống trang điều hướng, thêm sidebar chỉ để giống ảnh macOS sẽ tạo thêm thao tác không cần thiết. [Apple HIG — Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars), [Apple HIG — Layout](https://developer.apple.com/design/human-interface-guidelines/layout)

Bảng sau là **đề xuất chuyển ngôn ngữ thiết kế sang app hiện tại**, không phải bộ thông số pixel do Apple công bố:

| Yếu tố | Thiết kế đề xuất cho app Windows | Giới hạn và cách nghiệm thu |
|---|---|---|
| Phân lớp | Header nhẹ, nhóm thao tác rõ, vùng nội dung ít trang trí | Nhìn rõ cấu hình → thao tác → tiến độ → log |
| Vật liệu kính | Màu bề mặt có sắc nhẹ, viền sáng tối tinh tế ở vùng điều khiển | Bản CustomTkinter dùng bề mặt đục được phối màu; không gọi đây là khúc xạ thật |
| Vùng dữ liệu | Entry và log có nền ổn định; không đặt chữ lên wallpaper | Đọc tốt tên file, đường dẫn, thông báo dài |
| Hình dạng | Bo góc đồng nhất theo nhóm: control 8–10, card 12–16 đơn vị thiết kế | Hiệu chỉnh qua prototype; không khẳng định trùng bán kính native |
| Typography | Segoe UI có sẵn trên Windows; font monospace hiện tại cho log | Tiếng Việt có dấu rõ, không cắt dòng; không cần cài font Apple |
| Màu sắc | Bề mặt trung tính; accent xanh cho thao tác chính; màu cảnh báo có chữ đi kèm | Tên Golden Gate không được diễn giải thành yêu cầu phủ màu vàng |
| Nút | Giữ nguyên nhãn và command; thay nền, viền, hover, disabled | Không đổi điều kiện bật/tắt hoặc thứ tự ý nghĩa |
| Nhập liệu | Giữ ComboBox, Entry và Switch hiện có; focus dễ thấy | Không đổi validation, binding, trace hoặc hành vi đổi profile |
| Tiến độ | Thanh gọn, nhãn đếm và trạng thái đọc được | Giá trị vẫn do logic cũ cấp; không làm mượt bằng số tiến độ tự sinh |
| Log | Nền riêng, monospace; nút copy/export/open/clear giữ nguyên | Không sửa nội dung, thứ tự hoặc định dạng thông điệp workflow |
| Chuyển động | Bản đầu dùng phản hồi hover/focus có sẵn | Không thêm animation timer vào vòng xử lý hiện tại |
| Cửa sổ Windows | Giữ title bar và nút thu nhỏ/phóng to/đóng native | Giữ kéo cửa sổ, resize, snap, Alt+F4; không dùng cửa sổ frameless chỉ để vẽ ba chấm macOS |
| Sáng/tối/hệ thống | Golden Gate có palette sáng và tối; kế thừa cách chọn chế độ hiện tại | Không thêm watcher thay đổi hệ thống trong phạm vi này |
| Màn hình nhỏ | Giữ bố cục thích ứng và cuộn hiện có; header có thể xuống dòng | Nút chạy/dừng và trường nhập không bị che hoặc mất |

Mốc màu khởi đầu để dựng mẫu: sáng dùng nền `#F3F4F6`, bề mặt `#FFFFFF`, chữ `#1D1D1F`; tối dùng nền `#1C1C1E`, bề mặt `#2C2C2E`, chữ `#F5F5F7`. Màu phụ, accent, hover và disabled sẽ chốt thành bảng riêng sau khi đo tương phản trên từng nền. Các mã này là lựa chọn thiết kế cho dự án.

Đề xuất giữ cỡ chữ tương đương UI đang chạy; dùng khoảng cách theo nhịp 4/8, đệm card 16–20 và chiều cao control 36–42 đơn vị thiết kế. Phải quy đổi đúng theo cơ chế font/scaling của Tk/CustomTkinter, không lấy pixel ảnh macOS rồi áp thẳng sang Windows. CustomTkinter có hỗ trợ HighDPI cho Windows và macOS. [CustomTkinter — Scaling](https://customtkinter.tomschimansky.com/documentation/scaling/)

Lấy ngưỡng tương phản chữ thường 4,5:1 và thành phần thị giác thiết yếu của control 3:1 làm mục tiêu kiểm tra. Đây là cách dùng hướng dẫn W3C để đánh giá màu cho app; không phải tuyên bố app desktop đã được chứng nhận WCAG. [W3C — Contrast Minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), [W3C — Non-text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)

**So sánh công cụ và quyết định lựa chọn**

Mức phù hợp dưới đây là đánh giá kỹ thuật dựa trên cấu trúc repo và yêu cầu giữ workflow, không phải benchmark đã đo:

| Phương án | Điểm mạnh | Tác động khi áp dụng vào repo này | Kết luận |
|---|---|---|---|
| **CustomTkinter + lớp style riêng** | Tận dụng widget, biến Tk, callback, DPI và cách build hiện tại | Phạm vi nhỏ nhất; phải ánh xạ đầy đủ màu, font, viền, khoảng cách | **Chọn cho lần triển khai này** |
| **PySide6 + Qt Quick/QML** | Tùy biến giao diện sâu, hiệu ứng qua shader, blur và shadow | Phải thay widget/event loop, nối lại state và callback; nguy cơ đổi điều phối dù worker không đổi | Phương án tốt nếu sau này cho phép dự án chuyển lớp UI riêng |
| **WinUI 3 + Windows App SDK** | Nền tảng Microsoft khuyến nghị cho app Windows native mới; hỗ trợ Fluent | Stack C#/C++ và XAML khác Python/Tk; cần lớp giao tiếp với backend | Hợp app Windows mới; không tối ưu cho yêu cầu chỉ bổ sung style ở repo này |
| **pywebview + HTML/CSS/JavaScript** | Thiết kế bề mặt và bố cục linh hoạt | Thay lớp UI và thêm bridge JavaScript–Python, quản lý WebView runtime | Không chọn vì tăng số lớp cần giữ đồng bộ |

CustomTkinter hỗ trợ màu riêng cho widget, cặp màu sáng/tối và theme JSON. Tuy nhiên app hiện truyền nhiều màu và kích thước trực tiếp vào constructor. Chỉ thêm một JSON rồi gọi `set_default_color_theme()` sẽ không xử lý đầy đủ các giá trị đã ghi cứng; cần một lớp style gắn với các widget thật. [CustomTkinter — Color and Themes](https://customtkinter.tomschimansky.com/documentation/color/)

Các API công khai của CTkFrame và CTkButton cho phép đổi thuộc tính hiển thị qua `configure`. Tài liệu đã đối chiếu không cung cấp primitive Liquid Glass hay pipeline shader cho các widget này. Vì vậy kế hoạch khả thi là mô phỏng hình thức bề mặt, không cam kết hiệu ứng kính động giống macOS. [CustomTkinter — CTkFrame](https://customtkinter.tomschimansky.com/documentation/widgets/frame/), [CustomTkinter — CTkButton](https://customtkinter.tomschimansky.com/documentation/widgets/button/)

Qt Quick có `MultiEffect` để phối hợp blur, shadow và màu; khúc xạ riêng vẫn cần hiệu ứng tùy chỉnh. Qt cũng lưu ý blur/shadow tốn tài nguyên và cần hạn chế vùng xử lý. Quan trọng: style macOS native của Qt **chỉ khả dụng khi chạy trên macOS**; trên Windows vẫn phải tự dựng style đa nền tảng, chẳng hạn từ Basic. [Qt — MultiEffect](https://doc.qt.io/qt-6/qml-qtquick-effects-multieffect.html), [Qt — macOS Style](https://doc.qt.io/qt-6/qtquickcontrols-macos.html)

Microsoft khuyến nghị WinUI 3 cho ứng dụng Windows native mới, nhưng điều đó không đồng nghĩa một app Python đang ổn định nên chuyển sang WinUI để đổi theme. Với pywebview, bridge gọi Python có mô hình luồng riêng; không thể nối thẳng các callback đang thao tác Tk vào bridge rồi mặc định coi là tương đương. [Microsoft — Choose a Windows development path](https://learn.microsoft.com/en-us/windows/apps/get-started/), [pywebview — JavaScript–Python bridge](https://pywebview.flowrl.com/guide/interdomain.html)

**Bộ công cụ cần dùng cho phương án được chọn:** Python/Tkinter và CustomTkinter đang được dự án sử dụng; module Python riêng chứa các giá trị style; JSON cho sở thích giao diện; Pillow hiện có nếu cần icon raster; PyInstaller hiện có để đóng gói; `unittest`, mock subprocess/timer và ảnh chụp UI để xác minh. Dùng phiên bản môi trường ổn định đang chạy làm mốc, không nâng đồng loạt dependency trong đợt đổi giao diện. Không cần thêm Qt, Node.js hoặc WebView runtime.

Phần kiểm thử hình thức có thể dùng prototype CustomTkinter chứa dữ liệu giả và cùng loại control với app; công cụ thiết kế thuê bao không phải phụ thuộc bắt buộc. Assets mới nên nhỏ, đồng nhất, đóng gói nội bộ; nếu không cần icon mới thì giữ nhãn chữ hiện có.

DWM chỉ là tùy chọn nghiên cứu thêm: Windows 11 build 22621 trở lên có API backdrop với Mica/Acrylic. Đó là vật liệu Windows, không phải Liquid Glass. Tk vẽ bề mặt đục có thể che backdrop, nên gọi API thành công chưa chứng minh hiệu ứng hiển thị đúng. Bản đầu không phụ thuộc DWM; chỉ thêm sau một thử nghiệm riêng chứng minh resize/DPI/remote session và nền dự phòng ổn định. Không dùng API Windows không có tài liệu để đạt hiệu ứng. [Microsoft — DWM_SYSTEMBACKDROP_TYPE](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type)

**Kiến trúc triển khai giữ nguyên workflow**

Giao diện cung cấp hai lựa chọn độc lập: **Phong cách: Gốc / macOS Golden Gate** và lựa chọn sáng/tối/hệ thống đã có. Gốc vẫn là mặc định cho cấu hình cũ, và được khôi phục khi sở thích UI thiếu, hỏng hoặc chứa tên style không hợp lệ.

Luồng chọn phong cách mới chỉ đọc lựa chọn → lấy giá trị style → cấu hình thuộc tính hiển thị của widget hiện hữu → lưu sở thích UI. Mọi nút nghiệp vụ tiếp tục gọi đúng callback hiện tại.

| Vùng thay đổi dự kiến | Trách nhiệm |
|---|---|
| `ui/themes.py` — file mới dự kiến | Style Gốc giữ nguyên giá trị hiện tại; Golden Gate có palette, font, radius, spacing và màu theo trạng thái |
| `ui/style_controller.py` — file mới dự kiến | Ghi nhận widget theo vai trò; áp dụng thuộc tính qua API công khai; không sở hữu state nghiệp vụ |
| `ui/preferences.py` — file mới dự kiến | Đọc/ghi lựa chọn style, kiểm tra giá trị, quay về Gốc khi không hợp lệ |
| `app.pyw` — sửa giới hạn | Khởi tạo lớp style, thêm dropdown, đăng ký widget, thay đối số trình bày bằng giá trị style; giữ nguyên nội dung callback nghiệp vụ |
| `assets/ui/` — chỉ thêm nếu cần | Icon và tài nguyên giao diện |
| `tests/test_ui_style.py` — file mới dự kiến | Kiểm tra chuyển style không tạo tác dụng phụ lên workflow |
| Build/ignore/tài liệu — sửa nếu cần | Đóng gói tài nguyên và loại file sở thích UI cá nhân khỏi commit; không đổi worker |

Tên và đường dẫn trong bảng là đề xuất, chưa tạo mã triển khai. Dùng module Python cho bảng style giúp giảm rủi ro thiếu file theme khi đóng gói; JSON chỉ cần cho sở thích người dùng hoặc khi có lý do cụ thể để tách dữ liệu theme.

Chọn file riêng `ui_preferences.json` trong `DATA_DIR` hiện tại, dự kiến chứa `schema_version: 1` và `ui_style: classic|golden_gate`. Không đưa đường dẫn ảnh/profile hay tham số batch vào file này. Không gọi `save_settings()` để lưu riêng thao tác chọn style, vì hàm đó đọc và ghi cả cấu hình nghiệp vụ. Lỗi lưu sở thích chỉ cần thông báo tại phần UI và giữ app tiếp tục hoạt động; không đổi status/log của worker.

Đối với chuyển style trực tiếp, giữ nguyên đối tượng widget và biến Tk. Chỉ đổi màu, font, viền, radius, padding hoặc kích thước trình bày; không gọi `destroy`, `build_ui`, `set_theme`, `set_language`, `cancel_auto_next`, `start`, `stop` hay setter của biến nghiệp vụ. Việc cập nhật style chạy trên Tk main thread, không tạo event loop hoặc worker mới. Không cấu hình lại `command`, `state`, `variable`, `textvariable`, trace hay binding nghiệp vụ.

Các widget hiện được tạo cục bộ trong `build_ui` cần được đăng ký ngay lúc tạo với vai trò như nền, nhãn, nút chính, nút phụ, cảnh báo, entry, log. Cần cập nhật cả `tk.Canvas`, menu xổ xuống và scrollbar, không chỉ CTkFrame. Dùng API công khai; tránh sửa các thuộc tính riêng của CustomTkinter. Registry được tạo lại khi đường đổi sáng/tối/ngôn ngữ hiện tại dựng lại UI, và đọc style đã chọn để giữ hình thức nhất quán.

Giữ nguyên cơ chế đổi sáng/tối/ngôn ngữ hiện tại, kể cả tác dụng phụ đã có; không âm thầm sửa chúng trong dự án theme. Yêu cầu “chuyển phong cách không ảnh hưởng batch/timer” áp dụng cho dropdown mới. Nếu cần thay đổi cả hành vi cũ, phải ghi thành một yêu cầu riêng trước khi thực hiện.

Giữ nguyên các file [run_chatgpt_batch.py](D:/0-vung-apps/chatgpt-batch-image-translator/run_chatgpt_batch.py), [progress_utils.py](D:/0-vung-apps/chatgpt-batch-image-translator/progress_utils.py), [retry_failed.py](D:/0-vung-apps/chatgpt-batch-image-translator/retry_failed.py), [export_failed.py](D:/0-vung-apps/chatgpt-batch-image-translator/export_failed.py). Trong `app.pyw`, đóng băng nội dung điều phối: `start`, `stop`, `send_continue`, các hàm auto-next, đọc/parse log, xử lý kết thúc, progress, đóng cửa sổ, cấu hình nghiệp vụ và callback đổi dịch vụ/profile. Những đoạn trộn trong `__init__`/`build_ui` phải soát theo từng đoạn, không cho phép thay đổi cả hàm chỉ vì hàm tạo giao diện.

**Các bước thực hiện và đầu ra bắt buộc**

Ước lượng sơ bộ: **5–8 ngày công cho một người**, gồm dựng mẫu, triển khai và kiểm tra, với môi trường Windows sẵn có. Chưa bao gồm chuyển sang Qt, làm shader Liquid Glass hoặc thử nghiệm DWM. Đây là ước lượng công việc, chưa phải cam kết thời gian hoàn thành.

| Bước | Công việc | Đầu ra và điều kiện chuyển bước | Ước lượng |
|---|---|---|---|
| 1. Ghi nhận bản ổn định | Lưu diff và hash bản đang có, ghi phiên bản môi trường, chụp Gốc sáng/tối, chạy bộ test hiện tại | Có mốc so sánh và danh sách lỗi đã tồn tại; không ghi đè thay đổi chưa commit | 0,5 ngày |
| 2. Chốt mẫu thiết kế | Prototype cùng control, dữ liệu giả; Gốc/Golden Gate ở sáng và tối; đủ kích thước nhỏ và trạng thái disabled/manual/countdown | Có ảnh mẫu, bảng style và giới hạn kính được nêu rõ; mẫu không dùng tài khoản hoặc worker thật | 1 ngày |
| 3. Thêm lớp style | Tạo module UI và registry; áp dụng lại giá trị Gốc; thêm lưu sở thích riêng | Gốc khớp hình thức cũ ngoài phần chọn style mới; callback, biến, trace và binding giữ nguyên | 1–1,5 ngày |
| 4. Áp dụng Golden Gate | Cấu hình các vùng UI, menu, entry, button, progress, log; chuyển style tại chỗ | Đổi qua lại không mất dữ liệu đang nhập, focus, log, timer hay trạng thái nút | 1–2 ngày |
| 5. Kiểm tra hồi quy | Test cùng fixture trên hai style, kiểm tra nguồn bị đóng băng, DPI và trường hợp workflow nhạy cảm | Tất cả kiểm tra bắt buộc đạt; lỗi có sẵn được phân biệt rõ với lỗi mới | 1–2 ngày |
| 6. Đóng gói và bàn giao | Build portable trong bản sao/thư mục build riêng, kiểm tra assets và khởi động; hướng dẫn quay về Gốc | Bản portable mở được cả hai style, không cần môi trường dev; có báo cáo test và ảnh nghiệm thu | 0,5–1 ngày |

Bước 2 là mốc xem thiết kế cụ thể trước khi nối vào app. Không bắt đầu sửa workflow để khắc phục giới hạn của prototype. Nếu chuyển style trực tiếp đòi hỏi dựng lại widget hoặc thay scheduler, không đưa cách đó vào bản chính; báo rõ giới hạn và đề xuất áp dụng style ở lần mở app kế tiếp như một thay đổi trải nghiệm cần chốt riêng.

Giữ PyInstaller `--onedir`; kiểm tra tài nguyên CustomTkinter và assets mới thực sự có trong output. Chỉ bổ sung data/hook khi cần, không đổi bộ công cụ đóng gói hoặc suy luận bản build đúng chỉ vì source chạy được. Tài liệu CustomTkinter yêu cầu lưu ý data files; PyInstaller cung cấp hook để bổ sung dữ liệu mà quá trình phân tích không tự tìm thấy. [CustomTkinter — Packaging](https://customtkinter.tomschimansky.com/documentation/packaging/), [PyInstaller — Hooks](https://pyinstaller.org/en/stable/hooks.html)

**Tiêu chí chứng minh workflow không đổi**

| Tình huống | Bằng chứng cần có |
|---|---|
| Mở app với cấu hình cũ | Mặc định Gốc; mọi tham số nghiệp vụ giữ nguyên |
| Chuyển Gốc ↔ Golden Gate khi đang nhập | Giá trị chưa lưu, selection, focus và vị trí cuộn giữ nguyên; không kích hoạt trace nghiệp vụ |
| Đang chạy batch | Cùng process/PID; không tạo lần chạy mới; hàng đợi log và trạng thái nút không bị reset |
| Đang đếm ngược auto-next | Không hủy hoặc đăng ký lại timer; token/deadline giữ nguyên; batch kế tiếp chạy đúng một lần theo điều kiện cũ |
| Đang chờ thao tác thủ công | `manual_action_required` và nút Continue giữ trạng thái; thao tác Continue vẫn gửi đúng tín hiệu cũ |
| Main / Retry / Force | Cùng command, cwd, môi trường nghiệp vụ và tín hiệu stdin trước/sau đổi style |
| Đổi dịch vụ hoặc thư mục | Callback đổi profile, validation, lưu cấu hình vẫn có hành vi cũ |
| Progress và kết thúc job | Cùng log đầu vào tạo cùng số đếm, trạng thái, exit handling và điều kiện chạy tiếp |
| Dừng và đóng cửa sổ | Cùng cách dừng process và timer như bản nền; title bar native vẫn dùng được |
| Lưu style hoặc lỗi file UI | Chỉ file sở thích UI thay đổi; `app_settings.json`, `progress.csv`, profile và output không bị ghi do chuyển style |
| Quay lại Gốc | Trả đúng giá trị style gốc; không cần cài lại hoặc thay dữ liệu |
| Mã nguồn | Hash các file nghiệp vụ khớp mốc; so sánh nội dung/AST của các hàm điều phối trong `app.pyw`; review riêng phần callback lồng trong UI |

Kiểm thử có kiểm soát bằng mock subprocess, fake clock và log fixture để so sánh cùng dữ liệu trước/sau. Không dùng phiên ChatGPT/Gemini thật để thử theme. Với clock giả, đo bất biến timer ngay quanh thao tác đổi style; sau đó mới tăng thời gian để kiểm tra auto-next hoạt động đúng. Không đòi timestamp đứng yên khi đồng hồ thực vẫn chạy.

Chạy lại bộ kiểm thử có sẵn bằng `python -m unittest discover -s tests -v` trong môi trường dự án; phần kiểm thử ảnh cần Chromium theo README. Nếu thiếu runtime hoặc test nền đã lỗi, ghi đúng trạng thái, không tính là đã đạt. Không sửa nghiệp vụ để làm xanh test trong phạm vi giao diện này.

**Tiêu chí giao diện và phát hành**

- Kiểm tra cả Gốc/Golden Gate × Sáng/Tối; chế độ Hệ thống lấy đúng nhánh màu theo cơ chế hiện có. Tiếng Việt và tiếng Anh hiển thị đủ.
- Kiểm tra Windows 10 nếu còn nằm trong tập máy mục tiêu của app và Windows 11; ghi rõ phiên bản thực sự đã thử. DWM không là điều kiện để theme chạy.
- Kiểm tra DPI 100%, 125%, 150%, 200%; chuyển màn hình nếu có; cửa sổ 1180×820, tối thiểu 900×620 và màn hình 1366×768. Phân biệt đơn vị thiết kế với pixel vật lý. Nếu kích thước tối thiểu hiện tại đã vượt vùng làm việc ở DPI cao, ghi thành giới hạn nền và đánh giá điều chỉnh hình học UI có mục tiêu; không tuyên bố mọi tổ hợp đều vừa màn hình.
- Kiểm tra đường dẫn Unicode dài, thông báo lỗi dài, log nhiều dòng, header xuống dòng, dropdown mở, trạng thái normal/hover/focus/disabled. Không thay nhãn bằng icon khó hiểu.
- Giữ thao tác bàn phím và cuộn chuột/cảm ứng đang có; kiểm tra khả năng đọc bằng công cụ hỗ trợ trên máy thử, không mặc định CustomTkinter đạt mọi tiêu chí accessibility.
- Mục tiêu hiệu năng đề xuất: không thêm tác vụ nền khi rảnh; không tăng rõ rệt bộ nhớ khi chuyển qua lại 50 lần; khởi động và thao tác style không gây khựng log. Đo trên cùng máy và cùng dữ liệu; chốt ngưỡng cụ thể sau khi có baseline, không đưa số đo ước đoán thành kết quả.
- Bàn giao kèm ảnh so sánh, danh sách file thay đổi, kết quả test, những máy/DPI đã kiểm tra và hướng dẫn chọn lại Gốc. Không gộp cải tiến workflow vào bản này.

**Kết quả của lượt lập kế hoạch này:** đã đối chiếu cấu trúc mã nguồn và tài liệu Apple, CustomTkinter, Qt, Microsoft, pywebview, PyInstaller, W3C; đã xác định hướng công cụ, ranh giới thay đổi, các bước và điều kiện nghiệm thu. Chỉ tạo báo cáo này; chưa cài thư viện, sửa mã ứng dụng, thay cấu hình người dùng hoặc chạy workflow.
