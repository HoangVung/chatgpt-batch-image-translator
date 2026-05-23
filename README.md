# ChatGPT Batch Image Translator

**Tiếng Việt** | [English](#english)

Ứng dụng desktop giúp xử lý hàng loạt ảnh sách/truyện bằng ChatGPT: upload ảnh, yêu cầu chép lại nguyên văn, dịch bản chép lại, tạo ảnh Việt hóa, tải ảnh kết quả và ghi tiến trình để có thể chạy tiếp hoặc retry.

<img width="1283" height="886" alt="image" src="https://github.com/user-attachments/assets/4b6ab3b8-17e1-4eda-a227-7467dd7573b3" />

> Dự án này là công cụ tự động hóa cá nhân, không phải sản phẩm chính thức của OpenAI/ChatGPT. Người dùng chịu trách nhiệm đảm bảo họ có quyền xử lý, dịch, tạo lại, lưu trữ và phân phối nội dung được đưa vào app.

## Tính năng

- Chọn thư mục ảnh gốc và thư mục lưu ảnh đã Việt hóa.
- Chạy theo batch, lưu tiến trình vào `progress.csv`.
- Tiếp tục từ ảnh bất kỳ bằng ô `Bắt đầu từ ảnh`.
- Chạy lại ảnh lỗi hoặc chạy lại một ảnh được chỉ định.
- Tự động mở ChatGPT bằng Playwright Chromium với profile riêng.
- Hỗ trợ theme Sáng, Tối và Hệ thống.
- Hỗ trợ build portable trên Windows và `.app` trên macOS.

## Các chế độ hoạt động (Output Modes)

Ứng dụng hỗ trợ 2 chế độ đầu ra chính được cấu hình qua biến `OUTPUT_MODE` trong `app_settings.json` hoặc biến môi trường:

### 1. Image Mode (`OUTPUT_MODE = "image"`)
* **Luồng xử lý:** App upload ảnh gốc, gửi prompt chép lại, dịch và yêu cầu ChatGPT tự tạo ảnh kết quả, sau đó tải ảnh kết quả về.
* **Cách hoạt động:** Giữ nguyên luồng cũ, ChatGPT tạo ảnh và app tải về `output/images_vn`.

### 2. SVG JSON Mode (`OUTPUT_MODE = "svg_json"`)
* **Luồng xử lý:** App upload ảnh gốc, gửi prompt chép lại, dịch và gửi prompt JSON Layout.
* **Cách hoạt động:** AI không tạo ảnh trực tiếp mà chỉ xuất cấu trúc `JSON_LAYOUT`. App local sẽ tự động dựng file SVG dựa trên JSON này.
* **Ưu điểm:** Hạn chế triệt để lỗi chữ chồng chữ, chữ tràn khung, hoặc lệch bảng biểu thường gặp khi ChatGPT tự vẽ SVG.
* **Lưu ý:**
  * Chất lượng SVG phụ thuộc hoàn toàn vào độ chính xác tọa độ JSON do AI xuất.
  * Nếu JSON bị lỗi cấu trúc hoặc có lỗi kiểm tra nghiêm trọng, file gốc và log lỗi sẽ bị đưa vào thư mục `failed`.
  * Trình dựng SVG của app không sử dụng thẻ `foreignObject` để đảm bảo độ tương thích và hiển thị tốt trên mọi phần mềm đọc SVG.

---

## Cấu trúc thư mục Output

Khi chạy, app sẽ tự động tạo cấu trúc thư mục đầu ra trong thư mục dự án:
```text
output/
├── images_vn/     # Lưu ảnh kết quả từ Image Mode
├── json_layout/   # Lưu file layout JSON nhận được từ AI (SVG JSON Mode)
├── svg/           # Lưu file SVG được dựng local (SVG JSON Mode)
├── png_preview/   # Lưu file PNG preview chuyển đổi từ SVG (SVG JSON Mode)
├── pdf/           # Lưu file PDF xuất bản từ SVG (SVG JSON Mode)
├── logs/          # Ghi nhật ký tiến trình chạy
└── failed/        # Lưu ảnh gốc và thông tin lỗi của các ảnh xử lý thất bại
```

---

## Biến cấu hình bổ sung (cho SVG JSON Mode)

Bạn có thể cấu hình các biến này trong `app_settings.json` hoặc thông qua biến môi trường:
* `EXPORT_PNG_PREVIEW = true / false`: Bật/tắt tự động xuất ảnh PNG preview từ SVG (Mặc định: `true`).
* `EXPORT_PDF = true / false`: Bật/tắt tự động xuất file PDF từ SVG (Mặc định: `false`).

---

## Cách chạy thử với 1 ảnh

Để chạy thử nghiệm nhanh với 1 ảnh duy nhất ở chế độ SVG JSON Mode:
* **PowerShell:**
  ```powershell
  $env:OUTPUT_MODE="svg_json"
  $env:BATCH_SIZE="1"
  python run_chatgpt_batch.py
  ```
* **Command Prompt (cmd):**
  ```cmd
  set OUTPUT_MODE=svg_json
  set BATCH_SIZE=1
  python run_chatgpt_batch.py
  ```

---

## Xử lý khi file bị đưa vào thư mục failed

Nếu một ảnh gặp lỗi và bị đưa vào thư mục `output/failed/`:
1. Mở file `<tên_file>_error.txt` tương ứng trong thư mục `failed` để xem chi tiết lỗi kiểm tra layout (layout validation errors).
2. Kiểm tra xem prompt hoặc cấu hình tọa độ trên ChatGPT có bị lệch nhiều không.
3. Chạy lại ảnh lỗi bằng cách đặt chế độ chạy `RUN_MODE = "retry"` để chạy lại tất cả các file bị lỗi trong progress.csv.

## Yêu cầu

- Python 3.9 trở lên.
- Tài khoản ChatGPT đăng nhập trong browser do Playwright mở.
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

## Ghi chú về Windows ARM64 & CairoSVG

Thư viện `cairosvg` yêu cầu các thư viện hệ thống C (như Cairo, Glib,...) để xuất ảnh PNG/PDF từ file SVG. 
* Trên Windows ARM64, việc cài đặt cairo có thể gặp khó khăn.
* Nếu gặp lỗi cài đặt hoặc lỗi chạy liên quan đến `cairosvg`, bạn có thể tắt tính năng xuất ảnh preview và PDF bằng cách cấu hình trong file `app_settings.json` (hoặc đặt biến môi trường):
  ```json
  "export_png_preview": false,
  "export_pdf": false
  ```
  App sẽ tự động bỏ qua bước CairoSVG và vẫn xuất đầy đủ file SVG & JSON Layout thành công.

---

## English

Desktop app for batch-processing book/comic images with ChatGPT: upload an image, ask ChatGPT to transcribe it verbatim, translate the copied text, generate a localized image, download the result, and keep progress so the batch can continue or retry later.

> This is a personal automation tool, not an official OpenAI/ChatGPT product. Users are responsible for making sure they have the rights to process, translate, recreate, store, and distribute any content they use with the app.

## Features

- Select input and output image folders.
- Run images in batches and track progress in `progress.csv`.
- Continue from a specific image via the `Start from image` field.
- Retry failed images or force rerun a selected image.
- Automatically opens ChatGPT through Playwright Chromium with a dedicated browser profile.
- Supports Light, Dark, and System themes.
- Supports Windows portable builds and macOS `.app` builds.

## Output Modes

The app supports 2 main output modes configured via `OUTPUT_MODE` in `app_settings.json` or environment variables:

### 1. Image Mode (`OUTPUT_MODE = "image"`)
* **Workflow:** The app uploads the original image, transcribes, translates, and requests ChatGPT to generate the final image, then downloads it.
* **How it works:** Keeps the legacy workflow, ChatGPT generates images and the app downloads them to `output/images_vn`.

### 2. SVG JSON Mode (`OUTPUT_MODE = "svg_json"`)
* **Workflow:** The app uploads the original image, transcribes, translates, and sends the JSON Layout prompt.
* **How it works:** The AI does not generate an image directly but only outputs a `JSON_LAYOUT` schema. The app then builds the SVG file locally.
* **Benefits:** Mitigates text overlap, text overflow, and table misalignments commonly seen when ChatGPT directly draws/generates SVG.
* **Notes:**
  * The SVG output quality depends entirely on the coordinates/JSON quality generated by the AI.
  * If the JSON has severe layout validation errors, the original image and error logs are copied to the `failed` folder.
  * The local SVG renderer does not use the `foreignObject` tag to ensure compatibility across various SVG viewers.

---

## Output Folder Structure

The app automatically generates the following output directories in the project root:
```text
output/
├── images_vn/     # Saved localized images (Image Mode)
├── json_layout/   # Saved layout JSON files received from AI (SVG JSON Mode)
├── svg/           # Saved SVG files built locally (SVG JSON Mode)
├── png_preview/   # Saved PNG preview files converted from SVG (SVG JSON Mode)
├── pdf/           # Saved PDF files converted from SVG (SVG JSON Mode)
├── logs/          # Run logs
└── failed/        # Saved original images & error logs for failed tasks
```

---

## Additional Configuration (for SVG JSON Mode)

You can customize these variables in `app_settings.json` or via environment variables:
* `EXPORT_PNG_PREVIEW = true / false`: Enable/disable automatic PNG preview generation from SVG (Default: `true`).
* `EXPORT_PDF = true / false`: Enable/disable automatic PDF generation from SVG (Default: `false`).

---

## How to Test with 1 Image

To quickly test a single image in SVG JSON Mode:
* **PowerShell:**
  ```powershell
  $env:OUTPUT_MODE="svg_json"
  $env:BATCH_SIZE="1"
  python run_chatgpt_batch.py
  ```
* **Command Prompt (cmd):**
  ```cmd
  set OUTPUT_MODE=svg_json
  set BATCH_SIZE=1
  python run_chatgpt_batch.py
  ```

---

## Handling Failed Files

If an image fails and is placed in `output/failed/`:
1. Check the corresponding `<filename>_error.txt` in the `failed` folder to view details of the layout validation errors.
2. Check if the coordinate estimates or prompt layout outputs on ChatGPT are significantly misaligned.
3. Rerun the failed image by setting the run mode `RUN_MODE = "retry"` to reprocess all failed entries in `progress.csv`.

## Requirements

- Python 3.9 or newer.
- A ChatGPT account signed in through the Playwright browser opened by the app.
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

## Windows ARM64 & CairoSVG Note

The `cairosvg` library requires C system libraries (such as Cairo, Glib, etc.) to export PNG/PDF files from SVG.
* Installing Cairo on Windows ARM64 can sometimes be challenging.
* If you encounter issues installing or running `cairosvg` on Windows ARM64, you can completely disable PNG/PDF export by setting the following in `app_settings.json` (or via environment variables):
  ```json
  "export_png_preview": false,
  "export_pdf": false
  ```
  The app will bypass the CairoSVG step and still successfully output SVG files and JSON Layouts.
