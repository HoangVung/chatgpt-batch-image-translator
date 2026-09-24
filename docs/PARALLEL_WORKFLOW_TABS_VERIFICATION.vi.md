# Kiểm chứng hai tab dịch sách

Ngày thực hiện: 2026-09-21, Windows 11, Python 3.12.10.

## Kết quả triển khai

Giao diện Liquid Glass có hai tab Sách 1 và Sách 2, dùng chung mã workflow. Mỗi tab sở hữu WebApi, DesktopController, scheduler, subprocess, stdin/stdout, cấu hình, tiến trình và log riêng. Chuyển tab chỉ thay phần hiển thị. Theme, ngôn ngữ và nút cửa sổ dùng chung.

Sách 1 tiếp tục đọc cấu hình hiện có; Sách 2 dùng thư mục dữ liệu `workflows/book-2`, profile riêng và để trống nguồn/kết quả cho đến khi người dùng chọn. Mỗi lần chạy tạo một JSON cấu hình đầy đủ, bất biến, bao gồm cả nhóm tài khoản dự phòng. Worker không quay về cấu hình gốc khi snapshot bị thiếu hoặc hỏng.

Các lệnh, sự kiện và phản hồi bất đồng bộ được gắn với phiên gốc. Thay đổi tab trong lúc lưu cấu hình, chọn thư mục hay bấm Chạy không chuyển tác dụng sang tab đang hiển thị. Lịch auto-next, dừng/tiếp tục và chuyển tài khoản độc lập.

## Bảo vệ kết quả

- Chặn đường dẫn trùng hoặc lồng nhau giữa output, nguồn và profile; chuẩn hóa đường dẫn thực, chữ hoa/thường trên Windows và junction.
- Tách toàn bộ nhóm profile, kể cả tài khoản fallback. Worker giữ khóa hệ điều hành trong suốt workflow; phiên khác không được mượn profile hay output đang dùng.
- Khóa hết hiệu lực khi tiến trình chết. Trước khi dùng lại profile, kiểm tra browser còn sống để tránh chiếm profile của browser mồ côi.
- `workflow_output.json` gắn thư mục kết quả với nguồn sách, ngăn tiếp tục nhầm output sách khác. Output cũ chưa có metadata cần người dùng xác nhận đúng nguồn bằng nút **Xác nhận kết quả cũ**; thao tác này không viết lại ảnh hoặc CSV.
- Chặn hai file nguồn ánh xạ cùng tên ảnh đầu ra. Log chỉ xuất vào output của tab tương ứng, kể cả khi worker của tab đang chạy.
- Giữ nguyên chuỗi prompt, cách tải/kiểm tra ảnh, schema `progress.csv`, checkpoint và protocol kết quả của worker.

Khóa phối hợp các tiến trình phiên bản mới cùng máy/cùng người dùng hệ điều hành. Đây không phải khóa phân tán giữa nhiều máy hoặc bộ bảo vệ trước phiên bản cũ/công cụ ngoài ghi vào cùng output. Không thay đổi nguồn hoặc di chuyển thư mục kết quả trong lúc chạy.

## Bằng chứng đã chạy

| Mức kiểm chứng | Kết quả |
| --- | --- |
| Toàn bộ suite | **136/136 đạt**, không skip; 37,376 giây trên lần chạy cuối |
| Controller/bridge/session | Hai Start đồng thời tạo hai worker riêng; hai Start cùng tab chỉ tạo một worker; snapshot đầy đủ; fallback và auto-next giữ đúng phiên; dừng/tiếp tục/log và chỉnh tab khác không ảnh hưởng phiên còn lại |
| Hai subprocess thật, fixture offline | Hai sách có ảnh `1_1.jpg` khác nội dung tạo hai kết quả khác hash; CSV/checkpoint đúng thư mục và profile. Worker thứ ba bị chặn khi tranh tài nguyên. Kill A không đổi hash/PID đang sống của B; khóa A được thu hồi |
| Browser thật, offline | Chromium headless với profile tiếng Việt/khoảng trắng được phát hiện qua Windows CIM; guard từ chối dùng profile đó |
| Giao diện trong Chromium | 6 test frontend đạt: chuyển tab, draft, sự kiện tab nền, phản hồi đến muộn, theme/ngôn ngữ, điều khiển, bố cục 900x620 / 1180x820 / 1440x1000; không lỗi JavaScript |
| Kiểm tra tĩnh | `node --check ui/app.js` và `git diff --check` đạt |

Lệnh tái hiện:

```powershell
python -m unittest discover -s tests -v
python app.pyw --self-test
python tests/verify_packaged_workflows.py '<đường dẫn EXE>'
```

Log và ảnh kiểm thử cục bộ nằm ở `output/parallel-tabs-verification/`: `tests.log`, `build-final.log`, `two-tabs-dark.png`, `two-tabs-light-small.png`. Ảnh chụp dùng backend giả với số liệu minh họa; không phải phiên dịch sách thật.

## Bản Windows portable đã kiểm tra

Thư mục: `output/parallel-tabs-build/dist/ChatGPT Batch Translator Parallel/`.

Mở `ChatGPT Batch Translator Parallel.exe` và giữ nguyên `_internal` cùng `ms-playwright` bên cạnh. Đây là bản build riêng, không thay thế release cũ và không chứa cấu hình, cookie hoặc profile cá nhân. Bản EXE ở thư mục mới cần chọn nguồn/kết quả và đăng nhập lại; chạy app từ source hiện tại tiếp tục dùng cấu hình đã có.

- Source và EXE `--self-test`: exit 0, kiểm tra đủ hai session và tài nguyên giao diện.
- Hai tiến trình EXE `--worker` được khởi động từ ngoài thư mục app, dùng hai snapshot và hai nguồn rỗng tạm riêng: cả hai exit 0, gửi protocol kết quả qua stdout, tạo CSV và metadata nguồn đúng output. Đây là kiểm tra đường đóng gói, không phải thử dịch ảnh.
- EXE nhận snapshot không tồn tại và EXE tranh tài nguyên đang bị khóa: cả hai exit 1, có lỗi trong pipe, không chờ hộp thoại ngoại lệ của PyInstaller.
- Chromium đi kèm (148.0.7778.96) mở thành công trang offline bằng profile tạm qua Playwright của Python nguồn, chỉ rõ executable trong gói portable. Kiểm tra này xác minh browser đã sao chép chạy được; chưa thay thế kiểm tra toàn bộ phiên đăng nhập từ EXE.
- Bằng chứng bổ sung: `packaged-self-test.log`, `packaged-smoke.json`, `browser-smoke.json` trong thư mục kiểm chứng. `SHA256SUMS.txt` trong gói ghi hash của EXE.

## Những việc vẫn cần nghiệm thu thủ công

**MANUAL PENDING:** thao tác cửa sổ pywebview/WebView2 thật (đóng, thu nhỏ, hộp chọn thư mục), đăng nhập và dịch đồng thời qua ChatGPT/Gemini. Chưa đo CPU/RAM, tốc độ và chất lượng dịch thật khi chạy hai browser. Các thử nghiệm tự động không tiêu lượt dịch và không sửa ảnh, CSV hoặc profile sản xuất.

Để nghiệm thu dịch thật, dùng hai bộ ảnh thử tách biệt có cùng tên file nhưng dấu nhận biết A/B; batch size 1. Chạy hai tab, chuyển tab, dừng một bên, tiếp tục và kiểm tra ảnh đúng sách, output riêng, auto-next đúng phiên. Chỉ dùng profile thử riêng hoặc profile đã được người dùng chọn cho mỗi tab. Không cố làm cạn quota để thử fallback.

Hai profile đăng nhập cùng một tài khoản không tạo ra hai hạn mức độc lập. Việc tách phiên bảo vệ dữ liệu và điều khiển, không đảm bảo AI sinh ảnh giống hệt giữa các lần hoặc tốc độ tăng gấp đôi.

