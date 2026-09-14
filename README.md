# ChatGPT Batch Image Translator

**Tiếng Việt** | [English](#english)

Ứng dụng desktop giúp xử lý hàng loạt ảnh sách/truyện bằng ChatGPT hoặc Google Gemini: upload ảnh, yêu cầu chép lại nguyên văn, dịch bản chép lại, tạo ảnh Việt hóa, tải ảnh kết quả và ghi tiến trình để có thể chạy tiếp hoặc retry.

<img width="1283" height="886" alt="image" src="https://github.com/user-attachments/assets/4b6ab3b8-17e1-4eda-a227-7467dd7573b3" />

> Dự án này là công cụ tự động hóa cá nhân, không phải sản phẩm chính thức của OpenAI/ChatGPT hay Google Gemini. Người dùng chịu trách nhiệm đảm bảo họ có quyền xử lý, dịch, tạo lại, lưu trữ và phân phối nội dung được đưa vào app.

## Tính năng

- Chọn thư mục ảnh gốc và thư mục lưu ảnh đã Việt hóa.
- Hỗ trợ 2 dịch vụ AI: **ChatGPT** và **Google Gemini** với profile trình duyệt riêng biệt.
- Quản lý nhiều tài khoản ChatGPT ngay trong app: thêm, đổi tên, chọn nhanh profile và mở phiên đăng nhập riêng cho từng tài khoản.
- Chạy theo batch, lưu tiến trình chi tiết vào `progress.csv`.
- Quy chuẩn định dạng tên file đầu vào và đầu ra để tránh xung đột hoặc ghi đè.
- Tiếp tục từ ảnh bất kỳ bằng ô `Bắt đầu từ ảnh`.
- Chạy lại ảnh lỗi hoặc chạy lại một ảnh được chỉ định (Force Rerun với cơ chế dừng an toàn nếu tên mơ hồ).
- Quản lý vòng đời job qua exit code chuẩn và tự động lập lịch chạy batch tiếp theo (xem [JOB_COMPLETION.md](JOB_COMPLETION.md)).
- Tự động mở trình duyệt bằng Playwright Chromium với profile riêng cho từng dịch vụ.
- Hỗ trợ theme Sáng, Tối và Hệ thống.
- Hỗ trợ phong cách giao diện Gốc hoặc macOS 27 Golden Gate.
- Xuất log (`Xuất log`) ra file và sao chép log (`Copy log`) nhanh vào clipboard.
- Bộ tiện ích đi kèm: xuất danh sách lỗi (`export_failed.py`), gom ảnh lỗi chạy lại (`retry_failed.py`) sử dụng module chung `progress_utils.py`.
- Bộ kiểm thử tự động tích hợp trong thư mục `tests/`.
- Hỗ trợ build portable trên Windows và `.app` trên macOS.

## Quy ước định dạng tên file

Để chương trình sắp xếp thứ tự và xử lý chính xác, file ảnh đầu vào **bắt buộc** phải tuân theo cấu trúc sau:

### 1. File đầu vào (Input)
- **Cấu trúc:** `<số_trang>_<số_thứ_tự>.<phần_mở_rộng>`
- **Các định dạng đuôi hỗ trợ:** `.jpg`, `.jpeg`, `.png`, `.webp` (không phân biệt chữ hoa/thường).
- **Ví dụ hợp lệ:**
  - `26_039.jpg`: Trang 26, ảnh thứ 39.
  - `74_100.jpg`: Trang 74, ảnh thứ 100.
  - `73_129.png`: Trang 73, ảnh thứ 129.
- *Lưu ý:* Cả phần số trang và số thứ tự ảnh bắt buộc phải là số nguyên (`int`).

### 2. File đầu ra (Output)
- Tên file đầu ra được tự động chuẩn hóa dạng 5 chữ số đệm 0 cùng hậu tố `VN.png`:  
  `{số_trang:05d}_{số_thứ_tự:05d}VN.png` (Ví dụ: `26_039.jpg` $\rightarrow$ `00026_00039VN.png`, `73_129.jpg` $\rightarrow$ `00073_00129VN.png`).
- Cơ chế này tránh ghi đè kết quả khi một trang có nhiều ảnh cắt. Kết quả theo tên cũ (như `00073VN.png`) chỉ được giữ nhận diện khi trang nguồn có đúng 1 ảnh duy nhất.

## Luồng xử lý

Với mỗi ảnh, app sẽ:

1. Mở cuộc chat mới trên dịch vụ đã chọn (**ChatGPT** hoặc **Google Gemini**).
2. Upload ảnh.
3. Gửi prompt `chép lại nguyên văn`.
4. Đợi AI phản hồi xong.
5. Gửi prompt `dịch bản chép lại`.
6. Đợi bản dịch.
7. Gửi prompt `Tạo ảnh với bản dịch`.
8. Tải ảnh kết quả về thư mục output (tự động fallback qua nhiều cơ chế tải nếu ảnh bị bảo vệ hoặc cần phiên đăng nhập).

Tên đầu ra bao gồm cả hai số của file nguồn để không ghi đè giữa các ảnh. Ví dụ: `73_129.jpg` được lưu là `00073_00129VN.png`.
Kết quả theo tên cũ như `00073VN.png` chỉ được tiếp tục nhận diện khi thư mục nguồn có đúng một ảnh của trang đó; các trang có nhiều ảnh sẽ được xử lý lại để tạo tên mới, tránh nhầm kết quả cũ.

## Yêu cầu

- Python 3.9 trở lên.
- Tài khoản ChatGPT hoặc Google đăng nhập trong browser do Playwright mở.
- Kết nối internet.
- Windows hoặc macOS.

## Chạy từ source

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python app.pyw
```

Nếu máy Windows dùng Python launcher:

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m playwright install chromium
py -3 app.pyw
```

## Khi ảnh đã hiện nhưng app vẫn chờ hoặc chưa lưu

- Nếu log còn ở `Chờ ảnh mới` và chưa có `Tải ảnh vào`, app chưa nhận diện được ảnh kết quả. Bộ nhận diện hỗ trợ cả khung tạo ảnh nằm ngoài phần văn bản trả lời; dòng `Nhận diện ảnh` giúp kiểm tra khi giao diện thay đổi.
- App kiểm tra quyền ghi thư mục VN trước khi mở trình duyệt. Khi tải trực tiếp thất bại, app thử tải bằng phiên đăng nhập, rồi đọc ảnh đã tải trên trang ở độ phân giải gốc. File được kiểm tra và chuyển sang PNG trước khi ghi; log `Đã lưu ảnh` ghi đường dẫn thực tế.
- Nút `Xuất log` lưu nhật ký hiện tại vào `process_log.txt` trong thư mục output; nút `Copy log` chép toàn bộ nhật ký vào clipboard.
- Khi retry, nếu tên file trong `progress.csv` không tồn tại tại thư mục ảnh gốc đang chọn, `failed_retry/missing_files.txt` liệt kê các tên cũ bị thiếu. Nếu đã đổi tên hoặc di chuyển ảnh, chọn lại thư mục nguồn và chạy chính với tên file hiện tại.
- Để kiểm tra một ảnh sau khi cập nhật: mở lại app, chọn đúng hai thư mục, nhập tên đầy đủ như `26_039.jpg` vào `Bắt đầu từ ảnh`, rồi bấm chạy lại một ảnh. Bản `.exe` cần được build lại để nhận thay đổi mã nguồn.

Chạy kiểm thử (có dùng Chromium để kiểm tra nhận diện và tải ảnh trên trang mô phỏng, không đăng nhập ChatGPT):

```powershell
python -m unittest discover -s tests -v
```

Có thể đặt biến môi trường `BATCH_TEST_BROWSER` tới đường dẫn Chrome/Chromium đã cài nếu không dùng Chromium của Playwright.

## Build Windows portable

```powershell
powershell -ExecutionPolicy Bypass -File .\build_portable.ps1
```

Hoặc chạy:

```powershell
.\build_portable.bat
```

Sau khi build, app nằm tại:

```text
dist\ChatGPT Batch Translator\
```

Hãy gửi cả thư mục `ChatGPT Batch Translator`, không chỉ gửi riêng file `.exe`.

## Build macOS app

Chạy trên máy Mac:

```bash
python3 -m venv .venv
source .venv/bin/activate
chmod +x build_macos.sh
./build_macos.sh
```

Hoặc double-click:

```text
build_macos.command
```

Khi clone source trên macOS, chạy một lần trước khi double-click:

```bash
chmod +x build_macos.command
```

Sau khi build, app nằm tại:

```text
dist/ChatGPT Batch Translator.app
```

Nếu macOS chặn app chưa sign/notarize, hãy right-click app, chọn **Open**, hoặc bỏ quarantine:

```bash
xattr -dr com.apple.quarantine "dist/ChatGPT Batch Translator.app"
```

## Dữ liệu cá nhân và file không nên commit

Không đưa các thư mục/file sau lên GitHub hoặc vào bản phát hành công khai:

- `chatgpt_auto_profile`
- `gemini_auto_profile`
- `images`
- `images_vn`
- `app_settings.json`
- `progress.csv`
- các thư mục output/build cá nhân

Mỗi người dùng nên có profile ChatGPT, thư mục ảnh và cấu hình riêng trên máy của họ.

## Public repo và đóng góp

- License: xem [LICENSE](LICENSE).
- Hướng dẫn đóng góp: xem [CONTRIBUTING.md](CONTRIBUTING.md).
- Báo cáo vấn đề bảo mật hoặc dữ liệu nhạy cảm: xem [SECURITY.md](SECURITY.md).
- Trước khi tạo release công khai: xem [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
- Quy định kết thúc job: xem [JOB_COMPLETION.md](JOB_COMPLETION.md).

Khi mở issue, đừng đăng cookie, session ChatGPT, profile browser, ảnh riêng tư, log có đường dẫn cá nhân, hoặc nội dung sách/truyện không có quyền chia sẻ.

## Ghi chú macOS

Trên macOS, settings và profile mặc định được lưu tại:

```text
~/Library/Application Support/ChatGPT Batch Translator/
```

Một số thư mục như Desktop, Documents hoặc Downloads có thể cần cấp quyền trong:

```text
System Settings > Privacy & Security > Files and Folders
```

---

## English

Desktop app for batch-processing book/comic images with ChatGPT or Google Gemini: upload an image, ask AI to transcribe it verbatim, translate the copied text, generate a localized image, download the result, and keep progress so the batch can continue or retry later.

> This is a personal automation tool, not an official OpenAI/ChatGPT or Google Gemini product. Users are responsible for making sure they have the rights to process, translate, recreate, store, and distribute any content they use with the app.

## Features

- Select input and output image folders.
- Supports two AI services: **ChatGPT** and **Google Gemini** with isolated browser profiles.
- Manages multiple ChatGPT accounts in the app: add, rename, quickly select profiles, and open an independent sign-in session for each account.
- Run images in batches and track progress in `progress.csv`.
- Strict file naming convention for input and output to prevent collisions.
- Continue from a specific image via the `Start from image` field.
- Retry failed images or force rerun a selected image with safe stopping on ambiguous names.
- Job lifecycle management with standard exit codes and automatic batch chaining (see [JOB_COMPLETION.md](JOB_COMPLETION.md)).
- Automatically opens ChatGPT or Gemini through Playwright Chromium with dedicated browser profiles.
- Supports Light, Dark, and System themes; includes Classic and macOS 27 Golden Gate visual styles.
- Export log to file (`Export log`) and copy log to clipboard (`Copy log`).
- Helper utilities included: export failures (`export_failed.py`), copy failed images for retry (`retry_failed.py`) backed by shared `progress_utils.py`.
- Automated test suite included in `tests/`.
- Supports Windows portable builds and macOS `.app` builds.

## File Naming Convention

To ensure proper ordering and collision-free processing, input images **must** adhere to the following convention:

### 1. Input Images
- **Format:** `<page_number>_<image_index>.<extension>`
- **Supported extensions:** `.jpg`, `.jpeg`, `.png`, `.webp` (case-insensitive).
- **Valid examples:**
  - `26_039.jpg`: Page 26, image #39.
  - `74_100.jpg`: Page 74, image #100.
  - `73_129.png`: Page 73, image #129.
- *Note:* Both the page number and image index must parse as integers.

### 2. Output Images
- Results are automatically normalized to 5 digits with leading zeros and the `VN.png` suffix:  
  `{page_number:05d}_{image_index:05d}VN.png` (e.g. `26_039.jpg` $\rightarrow$ `00026_00039VN.png`, `73_129.jpg` $\rightarrow$ `00073_00129VN.png`).
- This prevents overwriting when a single book page consists of multiple slices. Legacy outputs (e.g. `00073VN.png`) are recognized only when the source folder has exactly one image for that page.

## Workflow

For each image, the app will:

1. Open a new chat (ChatGPT or Google Gemini).
2. Upload the image.
3. Send the prompt `chép lại nguyên văn`.
4. Wait for AI to finish responding.
5. Send the prompt `dịch bản chép lại`.
6. Wait for the translation.
7. Send the prompt `Tạo ảnh với bản dịch`.
8. Download the generated image to the output folder (with multi-stage download fallbacks).

Output names include both source numbers to avoid collisions. For example, `73_129.jpg` is saved as `00073_00129VN.png`.
Legacy output names such as `00073VN.png` are reused only when the input has exactly one image for that page; pages with multiple images are processed again under their unique names to avoid treating an ambiguous legacy result as complete.

## Requirements

- Python 3.9 or newer.
- A ChatGPT or Google account signed in through the Playwright browser opened by the app.
- Internet connection.
- Windows or macOS.

## Run From Source

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python app.pyw
```

On Windows, if you use the Python launcher:

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m playwright install chromium
py -3 app.pyw
```

## Build Windows Portable App

```powershell
powershell -ExecutionPolicy Bypass -File .\build_portable.ps1
```

Or run:

```powershell
.\build_portable.bat
```

The built app will be in:

```text
dist\ChatGPT Batch Translator\
```

Distribute the whole `ChatGPT Batch Translator` folder, not only the `.exe` file.

## Build macOS App

Run on a Mac:

```bash
python3 -m venv .venv
source .venv/bin/activate
chmod +x build_macos.sh
./build_macos.sh
```

Or double-click:

```text
build_macos.command
```

When building from a source clone on macOS, run this once before double-clicking:

```bash
chmod +x build_macos.command
```

The built app will be in:

```text
dist/ChatGPT Batch Translator.app
```

If macOS blocks the unsigned/unnotarized app, right-click the app and choose **Open**, or remove quarantine:

```bash
xattr -dr com.apple.quarantine "dist/ChatGPT Batch Translator.app"
```

## Private Data and Files Not To Commit

Do not commit or publish these files/folders:

- `chatgpt_auto_profile`
- `gemini_auto_profile`
- `images`
- `images_vn`
- `app_settings.json`
- `progress.csv`
- personal output/build folders

Each user should keep their own ChatGPT profile, image folders, and local settings.

## Public Repository and Contributions

- License: see [LICENSE](LICENSE).
- Contribution guide: see [CONTRIBUTING.md](CONTRIBUTING.md).
- Security and sensitive-data reporting: see [SECURITY.md](SECURITY.md).
- Before publishing a public release: see [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
- Job completion specifications: see [JOB_COMPLETION.md](JOB_COMPLETION.md).

When opening an issue, do not post cookies, ChatGPT sessions, browser profiles, private images, logs with personal paths, or book/comic content you do not have permission to share.

## macOS Notes

On macOS, settings and the default browser profile are stored in:

```text
~/Library/Application Support/ChatGPT Batch Translator/
```

Some folders, such as Desktop, Documents, or Downloads, may require permissions in:

```text
System Settings > Privacy & Security > Files and Folders
```
