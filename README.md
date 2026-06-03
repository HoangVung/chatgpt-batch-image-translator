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

## Luồng xử lý

Với mỗi ảnh, app sẽ:

1. Mở cuộc chat mới.
2. Upload ảnh.
3. Gửi prompt `chép lại nguyên văn`.
4. Đợi ChatGPT phản hồi xong.
5. Gửi prompt `dịch bản chép lại`.
6. Đợi bản dịch.
7. Gửi prompt `Tạo ảnh với bản dịch`.
8. Tải ảnh kết quả về thư mục output.

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

## Workflow

For each image, the app will:

1. Open a new chat.
2. Upload the image.
3. Send the prompt `chép lại nguyên văn`.
4. Wait for ChatGPT to finish responding.
5. Send the prompt `dịch bản chép lại`.
6. Wait for the translation.
7. Send the prompt `Tạo ảnh với bản dịch`.
8. Download the generated image to the output folder.

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
