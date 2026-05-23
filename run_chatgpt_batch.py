import os
import sys
import time
import csv
import json
import base64
import functools
import shutil
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright
from layout_validator import validate_layout_classified
from svg_renderer import render_svg, export_svg_to_formats

try:
    import pygetwindow as gw
    import win32process
except Exception:
    gw = None
    win32process = None

print = functools.partial(print, flush=True)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


BASE_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / "app_settings.json"

DEFAULT_CONFIG = {
    "image_folder": str(BASE_DIR / "images"),
    "download_folder": str(BASE_DIR / "images_vn"),
    "profile_dir": str(BASE_DIR / "chatgpt_auto_profile"),
    "batch_size": "5",
    "start_from": "",
    "prompt_chep_lai": "chép lại nguyên văn",
    "prompt_dich": "dịch bản chép lại",
    "prompt_tao_anh": "tạo ảnh với bản dịch",
    "prompt_svg_instruction": "Trong cuộc chat này, khi tôi yêu cầu tạo ảnh/SVG với bản dịch: hãy tạo file SVG theo bố cục ảnh gốc, tự kiểm tra và sửa chữ chồng chữ/tràn khung trước khi gửi, câu dài phải xuống dòng và giữ giãn dòng hợp lý. Chỉ gửi link tải SVG cuối cùng.",
    "prompt_svg_json_layout": """Dựa trên ảnh gốc và bản dịch tiếng Việt ở trên, hãy xuất JSON_LAYOUT để app local dựng SVG.

Yêu cầu bắt buộc:
- Không tạo ảnh.
- Không viết SVG.
- Chỉ xuất một khối JSON hợp lệ, không giải thích thêm.
- Giữ đủ 100% nội dung bản dịch.
- Không bỏ tiêu đề, đoạn văn, bảng, số liệu, mũi tên, chú thích.
- Chia trang thành các block: title, paragraph, table, arrow, figure, caption, formula.
- Mỗi block phải có x, y, width, height theo hệ tọa độ trang.
- Page size mặc định: width = 2480, height = 3508.
- Với paragraph: chia sẵn thành nhiều dòng ngắn, mỗi dòng không quá 42 ký tự tiếng Việt.
- Với table: xuất rõ số dòng, số cột, nội dung từng ô, căn trái/phải/giữa.
- Với số tiền: giữ nguyên định dạng số, dấu phẩy, dấu ngoặc, và căn phải.
- Với mũi tên: xuất x1, y1, x2, y2, direction, label nếu có.
- Với công thức: giữ nguyên ký hiệu toán học/kế toán.
- Không dùng foreignObject.
- Nếu không chắc tọa độ tuyệt đối, hãy ước lượng theo tỷ lệ gần nhất với ảnh gốc.

Schema bắt buộc:
{
  "page": {
    "width": 2480,
    "height": 3508,
    "background": "#ffffff"
  },
  "meta": {
    "sourceFile": "",
    "language": "vi",
    "layoutType": "accounting_page"
  },
  "blocks": []
}""",
    "output_mode": "image",
    "export_png_preview": "True",
    "export_pdf": "False"
}


def prompt_value(env_key, cfg, cfg_key):
    value = os.getenv(env_key, "").strip()
    if value:
        return value

    value = str(cfg.get(cfg_key, "")).strip()
    if value:
        return value

    return DEFAULT_CONFIG[cfg_key]


def load_config():
    cfg = DEFAULT_CONFIG.copy()

    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass

    cfg["image_folder"] = os.getenv("IMAGE_FOLDER", cfg["image_folder"])
    cfg["download_folder"] = os.getenv("DOWNLOAD_FOLDER", cfg["download_folder"])
    cfg["profile_dir"] = os.getenv("PROFILE_DIR", cfg["profile_dir"])
    cfg["batch_size"] = int(os.getenv("BATCH_SIZE", cfg.get("batch_size", "5")))
    cfg["run_mode"] = os.getenv("RUN_MODE", "main")
    cfg["start_from"] = os.getenv("START_FROM", cfg.get("start_from", "")).strip()
    cfg["prompt_chep_lai"] = prompt_value("PROMPT_CHEP_LAI", cfg, "prompt_chep_lai")
    cfg["prompt_dich"] = prompt_value("PROMPT_DICH", cfg, "prompt_dich")
    cfg["prompt_svg_instruction"] = prompt_value("PROMPT_SVG_INSTRUCTION", cfg, "prompt_svg_instruction")
    cfg["prompt_tao_anh"] = prompt_value("PROMPT_TAO_ANH", cfg, "prompt_tao_anh")
    cfg["prompt_svg_json_layout"] = prompt_value("PROMPT_SVG_JSON_LAYOUT", cfg, "prompt_svg_json_layout")
    cfg["output_mode"] = os.getenv("OUTPUT_MODE", cfg.get("output_mode", "image")).strip().lower()

    cfg["export_png_preview"] = os.getenv("EXPORT_PNG_PREVIEW", str(cfg.get("export_png_preview", "True"))).strip().lower() == "true"
    cfg["export_pdf"] = os.getenv("EXPORT_PDF", str(cfg.get("export_pdf", "False"))).strip().lower() == "true"

    return cfg


CFG = load_config()

IMAGE_FOLDER = CFG["image_folder"]
DOWNLOAD_FOLDER = CFG["download_folder"]
PROFILE_DIR = CFG["profile_dir"]
BATCH_SIZE = CFG["batch_size"]
RUN_MODE = CFG["run_mode"]
START_FROM = CFG["start_from"]

# OUTPUT_MODE:
# - "image": chạy như cũ, ChatGPT tạo ảnh và app tải ảnh.
# - "svg_json": AI xuất JSON_LAYOUT, app local dựng SVG.
OUTPUT_MODE = CFG.get("output_mode", "image")
EXPORT_PNG_PREVIEW = CFG.get("export_png_preview", True)
EXPORT_PDF = CFG.get("export_pdf", False)

WAIT_AFTER_EACH_IMAGE = 30
MAX_RETRY_IMAGE = 3
MAX_RETRY_DICH = 3
IMAGE_WAIT_TIMEOUT = 1800
SEND_VERIFY_TIMEOUT = 45

PROMPT_CHEP_LAI = CFG["prompt_chep_lai"]
PROMPT_DICH = CFG["prompt_dich"]
PROMPT_SVG_INSTRUCTION = CFG["prompt_svg_instruction"]
PROMPT_TAO_ANH = CFG["prompt_tao_anh"]
PROMPT_SVG_JSON_LAYOUT = CFG["prompt_svg_json_layout"]
if not PROMPT_SVG_INSTRUCTION.strip() and PROMPT_TAO_ANH.lower().strip() in ["tạo ảnh với bản dịch", "tạo ảnh với bản dịch."]:
    PROMPT_TAO_ANH = "Tạo file SVG với bản dịch theo bố cục ảnh gốc"

IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp"]
PROGRESS_FILE = os.path.join(DOWNLOAD_FOLDER, "progress.csv")


def sleep(s):
    time.sleep(s)


def ensure_output_dirs():
    output_dir = BASE_DIR / "output"
    subdirs = [
        "images_vn",
        "json_layout",
        "svg",
        "png_preview",
        "pdf",
        "logs",
        "failed"
    ]
    for sd in subdirs:
        os.makedirs(output_dir / sd, exist_ok=True)


def ensure_dirs():
    os.makedirs(IMAGE_FOLDER, exist_ok=True)
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    os.makedirs(PROFILE_DIR, exist_ok=True)
    ensure_output_dirs()


def init_progress():
    if not os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["index", "file", "output", "status", "time", "note"])


def parse_source_numbers(img):
    """
    73_129.jpg -> (73, 129)
    left  = số trang thực tế
    right = số thứ tự ảnh
    """
    stem = img.stem
    parts = stem.split("_")

    try:
        left = int(parts[0])
    except Exception:
        left = 999999999

    try:
        right = int(parts[1]) if len(parts) > 1 else 999999999
    except Exception:
        right = 999999999

    return left, right


def get_images():
    folder = Path(IMAGE_FOLDER)

    return sorted(
        [
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        ],
        key=parse_source_numbers
    )


def get_output_name(img):
    """
    73_129.jpg -> 00073VN.png
    """
    left, _ = parse_source_numbers(img)

    if left == 999999999:
        raise Exception(f"Tên file nguồn không đúng dạng số_trang_sốthứtự: {img.name}")

    return f"{left:05d}VN.png"


def match_start_file(img, start_value):
    if not start_value:
        return False

    value = start_value.lower().strip()
    name = img.name.lower()
    stem = img.stem.lower()

    if value == name:
        return True

    if value == stem:
        return True

    left, right = parse_source_numbers(img)

    if left != 999999999 and value == str(left):
        return True

    if right != 999999999 and value == str(right):
        return True

    return False


def apply_start_from(images):
    if not START_FROM:
        return images

    for i, img in enumerate(images):
        if match_start_file(img, START_FROM):
            print(f"▶ Bắt đầu từ ảnh: {img.name}")
            return images[i:]

    print(f"⚠ Không tìm thấy ảnh bắt đầu: {START_FROM}")
    print("→ Sẽ chạy từ ảnh đầu tiên.")
    return images


def read_latest_status():
    init_progress()

    latest = {}

    with open(PROGRESS_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            file_name = row.get("file", "")
            if file_name:
                latest[file_name] = {
                    "status": (row.get("status") or "").strip().lower(),
                    "note": row.get("note", "")
                }

    return latest


def write_progress(index, file_name, output_name, status, note=""):
    init_progress()

    with open(PROGRESS_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            index,
            file_name,
            output_name,
            status,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            note
        ])


def get_svg_name_from_png(png_name):
    if png_name.endswith(".png"):
        return png_name[:-4] + ".svg"
    return png_name + ".svg"


def output_file_exists(img):
    try:
        if OUTPUT_MODE == "svg_json":
            svg_path = os.path.join(BASE_DIR, "output", "svg", f"{img.stem}.svg")
            if os.path.exists(svg_path) and os.path.getsize(svg_path) > 100:
                return True
            return False

        output_name = get_output_name(img)
        output_path = os.path.join(DOWNLOAD_FOLDER, output_name)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
            return True

        svg_name = get_svg_name_from_png(output_name)
        svg_path = os.path.join(DOWNLOAD_FOLDER, svg_name)
        if os.path.exists(svg_path) and os.path.getsize(svg_path) > 100:
            return True

        return False
    except Exception:
        return False


def get_next_batch(images):
    latest = read_latest_status()
    pending = []

    if RUN_MODE == "retry":
        for img in images:
            st = latest.get(img.name, {}).get("status", "")
            if st in ["fail", "failed", "manual", "error"]:
                pending.append(img)
        return pending[:BATCH_SIZE]

    if RUN_MODE == "force":
        return images[:BATCH_SIZE]

    for img in images:
        st = latest.get(img.name, {}).get("status", "")

        if st == "done":
            continue

        if output_file_exists(img):
            continue

        if st == "":
            pending.append(img)
        elif st in ["fail", "failed", "manual", "error"]:
            continue

    return pending[:BATCH_SIZE]


def minimize_own_browser(context):
    if gw is None or win32process is None:
        print("⚠️ Chưa cài pygetwindow/pywin32, bỏ qua thu nhỏ browser.")
        return

    try:
        browser_pid = context.browser.process.pid
    except Exception:
        return

    sleep(5)

    for w in gw.getAllWindows():
        try:
            hwnd = w._hWnd
            _, pid = win32process.GetWindowThreadProcessId(hwnd)

            if pid == browser_pid:
                w.minimize()
                print("✓ Đã thu nhỏ browser xuống taskbar")
                return
        except Exception:
            pass


def is_cloudflare(page):
    try:
        text = page.locator("body").inner_text(timeout=3000).lower()
        url = page.url.lower()

        return (
            "verify you are human" in text
            or "just a moment" in text
            or "cloudflare" in text
            or "challenge" in url
        )
    except Exception:
        return False


def wait_if_cloudflare(page):
    if not is_cloudflare(page):
        return

    print("\nMANUAL_ACTION_REQUIRED")
    print("⚠️ Gặp Cloudflare / Verify you are human.")
    print("👉 Hãy xác minh thủ công trong cửa sổ trình duyệt.")
    print("👉 Khi vào lại được ChatGPT bình thường, quay lại app bấm 'Tiếp tục sau can thiệp'.")
    input("Chờ app gửi ENTER sau khi xác minh xong... ")

    sleep(5)

    if is_cloudflare(page):
        raise Exception("Vẫn còn Cloudflare sau khi xác minh.")


def wait_page_ready(page, timeout=120):
    start = time.time()

    while time.time() - start < timeout:
        wait_if_cloudflare(page)

        try:
            text = page.locator("body").inner_text(timeout=3000)
        except Exception:
            text = ""

        if (
            "Ask anything" in text
            or "Message ChatGPT" in text
            or "Hỏi bất kỳ điều gì" in text
            or "Hôm nay bạn có ý tưởng gì" in text
            or page.locator("#prompt-textarea").count() > 0
        ):
            return True

        sleep(2)

    return False


def login_if_needed(page):
    page.goto("https://chatgpt.com/", wait_until="domcontentloaded")
    wait_if_cloudflare(page)

    if wait_page_ready(page, 90) and page.locator("text=Log in").count() == 0:
        print("✅ Đã vào được ChatGPT.")
        return

    print("\nMANUAL_ACTION_REQUIRED")
    print("⚠️ Chưa đăng nhập.")
    print("👉 Login thủ công trong cửa sổ trình duyệt.")
    print("👉 Khi thấy ô chat, quay lại app bấm 'Tiếp tục sau can thiệp'.")
    input("Chờ app gửi ENTER sau khi login xong... ")

    wait_if_cloudflare(page)


def reset_chat(page):
    print("→ Reset New chat")

    page.goto("https://chatgpt.com/", wait_until="domcontentloaded")
    wait_if_cloudflare(page)

    if not wait_page_ready(page, 120):
        raise Exception("ChatGPT chưa sẵn sàng.")

    try:
        page.locator("text=New chat").first.click(timeout=4000)
    except Exception:
        pass

    sleep(4)
    wait_if_cloudflare(page)


def upload_image(page, img):
    try:
        page.locator("#upload-files").set_input_files(str(img), timeout=8000)
        print("✓ Upload bằng #upload-files")
        sleep(6)
        return
    except Exception:
        pass

    file_inputs = page.locator('input[type="file"]')
    count = file_inputs.count()

    for i in range(count):
        try:
            file_inputs.nth(i).set_input_files(str(img), timeout=8000)
            print(f"✓ Upload bằng input thứ {i}")
            sleep(6)
            return
        except Exception:
            continue

    raise Exception("Không upload được ảnh")


def wait_upload_attached(page, timeout=90):
    """
    Chờ ảnh đã bám vào khung chat trước khi gửi prompt.
    Tránh tình huống upload chưa xong đã gõ/gửi prompt.
    """
    start = time.time()

    while time.time() - start < timeout:
        wait_if_cloudflare(page)

        try:
            ok = page.evaluate("""
                () => {
                    const prompt = document.querySelector('#prompt-textarea');
                    if (!prompt) return false;

                    let root = prompt.closest('form');
                    if (!root) {
                        root = prompt;
                        for (let i = 0; i < 6 && root.parentElement; i++) {
                            root = root.parentElement;
                            if (root.querySelectorAll('img').length > 0) break;
                        }
                    }

                    const imgs = Array.from(root.querySelectorAll('img'));
                    const hasRealImage = imgs.some(img => {
                        const src = img.getAttribute('src') || '';
                        const box = img.getBoundingClientRect();
                        const low = src.toLowerCase();
                        return box.width > 40 && box.height > 40 &&
                               !low.includes('avatar') &&
                               !low.includes('emoji') &&
                               !src.startsWith('data:image/svg');
                    });
                    return hasRealImage;
                }
            """)
            if ok:
                sleep(2)
                return True
        except Exception:
            pass

        sleep(1)

    raise Exception("Không xác nhận được ảnh đã attach vào composer sau khi upload.")


def wait_prompt_ready(page, timeout=120):
    start = time.time()

    while time.time() - start < timeout:
        wait_if_cloudflare(page)

        try:
            ready = page.evaluate("""
                () => {
                    const el = document.querySelector('#prompt-textarea');
                    if (!el) return false;

                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    const stopBtn = document.querySelector('button[data-testid="stop-button"]');

                    const disabled =
                        el.getAttribute('aria-disabled') === 'true' ||
                        el.getAttribute('disabled') !== null ||
                        style.pointerEvents === 'none' ||
                        style.visibility === 'hidden' ||
                        style.display === 'none';

                    return (
                        rect.width > 0 &&
                        rect.height > 0 &&
                        !stopBtn &&
                        !disabled
                    );
                }
            """)

            if ready:
                return True

        except Exception:
            pass

        sleep(1)

    return False


def safe_click_prompt(page, timeout=60):
    box = page.locator("#prompt-textarea")
    last_error = None
    start = time.time()

    while time.time() - start < timeout:
        wait_if_cloudflare(page)

        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass

        try:
            box.click(timeout=5000)
            sleep(0.3)
            return True
        except Exception as e:
            last_error = e

        try:
            box.click(timeout=5000, force=True)
            sleep(0.3)
            return True
        except Exception as e:
            last_error = e

        try:
            ok = page.evaluate("""
                () => {
                    const el = document.querySelector('#prompt-textarea');
                    if (!el) return false;

                    el.scrollIntoView({block: 'center'});
                    el.focus();

                    return document.activeElement === el;
                }
            """)

            if ok:
                sleep(0.3)
                return True

        except Exception as e:
            last_error = e

        sleep(2)

    raise Exception(f"Không click/focus được prompt-textarea: {last_error}")


def clear_prompt_box(page):
    box = page.locator("#prompt-textarea")

    try:
        box.click(timeout=5000, force=True)
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        sleep(0.3)
        return
    except Exception:
        pass

    try:
        page.evaluate("""
            () => {
                const el = document.querySelector('#prompt-textarea');
                if (!el) return;

                el.focus();
                el.innerHTML = '';
                el.textContent = '';

                el.dispatchEvent(new InputEvent('input', {
                    bubbles: true,
                    inputType: 'deleteContentBackward'
                }));
            }
        """)
        sleep(0.3)
    except Exception:
        pass


def fill_prompt_box(page, text):
    box = page.locator("#prompt-textarea")

    try:
        box.fill(text, timeout=8000)
        sleep(0.5)
        return
    except Exception:
        pass

    try:
        page.evaluate("""
            (value) => {
                const el = document.querySelector('#prompt-textarea');
                if (!el) throw new Error('Không thấy prompt-textarea');

                el.focus();
                el.innerHTML = '';
                el.textContent = value;

                el.dispatchEvent(new InputEvent('input', {
                    bubbles: true,
                    inputType: 'insertText',
                    data: value
                }));
            }
        """, text)
        sleep(0.5)
        return
    except Exception:
        pass

    try:
        page.keyboard.type(text, delay=20)
        sleep(0.5)
    except Exception as e:
        raise Exception(f"Không điền được prompt: {e}")


def get_prompt_text(page):
    try:
        return page.evaluate("""
            () => {
                const el = document.querySelector('#prompt-textarea');
                if (!el) return '';
                return (el.innerText || el.textContent || '').trim();
            }
        """)
    except Exception:
        return ""


def is_generating(page):
    """
    Nhận diện ChatGPT đang xử lý.

    Lưu ý: với tạo ảnh, ChatGPT có lúc mất nút stop hoặc không hiện chữ generating
    trong vài chục giây, nên hàm này chỉ dùng như một tín hiệu phụ.
    Không được dùng riêng hàm này để kết luận tạo ảnh đã fail.
    """
    try:
        if page.locator('button[data-testid="stop-button"]').count() > 0:
            return True
    except Exception:
        pass

    try:
        running = page.evaluate("""
            () => {
                const buttons = Array.from(document.querySelectorAll('button'));
                for (const button of buttons) {
                    const label = (
                        button.getAttribute('aria-label') ||
                        button.getAttribute('data-testid') ||
                        button.innerText ||
                        ''
                    ).toLowerCase();

                    if (
                        label.includes('stop-button') ||
                        label.includes('stop generating') ||
                        label.includes('stop streaming') ||
                        label.includes('dừng tạo') ||
                        label.includes('dừng phản hồi')
                    ) {
                        const rect = button.getBoundingClientRect();
                        const style = window.getComputedStyle(button);
                        if (
                            rect.width > 0 &&
                            rect.height > 0 &&
                            style.visibility !== 'hidden' &&
                            style.display !== 'none'
                        ) {
                            return true;
                        }
                    }
                }

                const liveRegions = Array.from(document.querySelectorAll(
                    '[aria-live], [role="status"], [data-testid*="status"], [data-testid*="toast"]'
                ));
                const statusText = liveRegions
                    .map((el) => el.innerText || el.textContent || '')
                    .join('\\n')
                    .toLowerCase();

                return [
                    'analyzing image',
                    'đang phân tích',
                    'thinking...',
                    'thinking…',
                    'đang suy nghĩ',
                    'creating image',
                    'đang tạo ảnh',
                    'generating',
                    'đang tạo',
                    'working on it',
                    'i’m working',
                    "i'm working"
                ].some((marker) => statusText.includes(marker));
            }
        """)
        if running:
            return True
    except Exception:
        pass

    return False


def has_clear_generation_error(page):
    """
    Chỉ coi là lỗi tạo ảnh khi có thông báo lỗi rõ ràng trên trang.
    Tránh nhầm trạng thái idle tạm thời là lỗi.
    """
    try:
        text = page.locator("body").inner_text(timeout=1500).lower()
        error_markers = [
            "something went wrong",
            "đã xảy ra lỗi",
            "unable to generate",
            "couldn't generate",
            "could not generate",
            "không thể tạo",
            "failed to generate",
            "generation failed",
            "try again later",
            "thử lại sau"
        ]
        return any(m in text for m in error_markers)
    except Exception:
        return False


def click_send_button(page):
    selectors = [
        'button[data-testid="send-button"]',
        'button[aria-label="Send message"]',
        'button[aria-label="Gửi tin nhắn"]',
        'button[aria-label="Submit message"]'
    ]

    for sel in selectors:
        try:
            btn = page.locator(sel).last
            if btn.count() > 0:
                btn.click(timeout=4000, force=True)
                sleep(0.8)
                return True
        except Exception:
            pass

    try:
        ok = page.evaluate("""
            () => {
                const candidates = [
                    'button[data-testid="send-button"]',
                    'button[aria-label="Send message"]',
                    'button[aria-label="Gửi tin nhắn"]',
                    'button[aria-label="Submit message"]'
                ];

                for (const sel of candidates) {
                    const btn = document.querySelector(sel);
                    if (btn && !btn.disabled && btn.getAttribute('aria-disabled') !== 'true') {
                        btn.click();
                        return true;
                    }
                }

                return false;
            }
        """)
        sleep(0.8)
        return bool(ok)
    except Exception:
        return False


def verify_prompt_sent(page, original_text, timeout=SEND_VERIFY_TIMEOUT):
    start = time.time()

    while time.time() - start < timeout:
        wait_if_cloudflare(page)

        if is_generating(page):
            return True

        current_text = get_prompt_text(page)
        if current_text == "":
            return True

        if original_text not in current_text:
            return True

        sleep(1)

    return False


def send_prompt(page, text, max_send_attempts=4):
    """
    Gửi prompt bản chống treo.

    Fix các lỗi thường gặp:
    - Đã gõ chữ nhưng Enter không gửi.
    - Nút gửi bị overlay/chưa active.
    - Ô prompt focus giả.
    - Playwright fill được nhưng React/ProseMirror chưa nhận input.
    - Gửi xong nhưng không bắt đầu phản hồi.
    """
    last_error = None

    for attempt in range(1, max_send_attempts + 1):
        print(f"→ Gửi prompt: {text} | lần {attempt}")
        wait_if_cloudflare(page)

        if not wait_prompt_ready(page, timeout=120):
            last_error = "Prompt chưa sẵn sàng sau 120 giây"
            print(f"⚠ {last_error}")
            sleep(3)
            continue

        try:
            safe_click_prompt(page, timeout=60)
            clear_prompt_box(page)
            fill_prompt_box(page, text)
            sleep(1)

            typed = get_prompt_text(page)
            if text not in typed:
                print("⚠ Nội dung prompt chưa vào đúng ô nhập → gõ lại bằng keyboard")
                clear_prompt_box(page)
                safe_click_prompt(page, timeout=20)
                page.keyboard.type(text, delay=30)
                sleep(1)

            action_done = False

            if click_send_button(page):
                print("  ↳ Đã bấm nút gửi")
                action_done = True
            else:
                print("  ↳ Không thấy nút gửi rõ ràng, thử Enter một lần")
                page.keyboard.press("Enter")
                action_done = True

            if action_done and verify_prompt_sent(page, text, timeout=SEND_VERIFY_TIMEOUT):
                print("✓ Prompt đã được gửi")
                sleep(2)
                return True

            if action_done:
                raise Exception("Đã thực hiện thao tác gửi nhưng không xác minh được kết quả; dừng để tránh gửi trùng prompt.")

            last_error = "Không thực hiện được thao tác gửi prompt"
            print(f"⚠ {last_error}")

        except Exception as e:
            last_error = e
            print(f"⚠ Lỗi gửi prompt lần {attempt}: {e}")
            if "tránh gửi trùng prompt" in str(e):
                raise

        sleep(3)

    raise Exception(f"Không gửi được prompt sau {max_send_attempts} lần: {last_error}")


def get_assistant_response_signature(page):
    try:
        return page.evaluate("""
            () => {
                let nodes = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));

                if (nodes.length === 0) {
                    nodes = Array.from(document.querySelectorAll('.markdown')).filter((node) => {
                        const text = (node.innerText || node.textContent || '').trim();
                        return text.length > 0 && !node.closest('#prompt-textarea');
                    });
                }

                const texts = nodes
                    .map((node) => (node.innerText || node.textContent || '').trim())
                    .filter((text) => text.length > 0);
                const last = texts.length ? texts[texts.length - 1] : '';

                return {
                    count: texts.length,
                    last_len: last.length,
                    last_tail: last.slice(-500)
                };
            }
        """)
    except Exception:
        return {"count": 0, "last_len": 0, "last_tail": ""}


def has_new_assistant_response(page, before_signature):
    if not before_signature:
        return False

    current = get_assistant_response_signature(page)
    before_count = int(before_signature.get("count") or 0)
    before_len = int(before_signature.get("last_len") or 0)
    before_tail = before_signature.get("last_tail") or ""
    current_count = int(current.get("count") or 0)
    current_len = int(current.get("last_len") or 0)
    current_tail = current.get("last_tail") or ""

    if current_count > before_count and current_len >= 20:
        return True

    if current_count >= before_count and current_len >= 20:
        if current_tail and current_tail != before_tail:
            return True
        if current_len > before_len + 20:
            return True

    return False


def wait_assistant_response_stable(page, before_signature, stable_seconds=6, timeout=900):
    start = time.time()
    last_signature = None
    stable_start = None

    while time.time() - start < timeout:
        wait_if_cloudflare(page)

        if is_generating(page):
            stable_start = None
            last_signature = None
            sleep(2)
            continue

        if not has_new_assistant_response(page, before_signature):
            sleep(2)
            continue

        current = get_assistant_response_signature(page)
        comparable = (
            int(current.get("count") or 0),
            int(current.get("last_len") or 0),
            current.get("last_tail") or ""
        )

        if comparable == last_signature:
            if stable_start and time.time() - stable_start >= stable_seconds:
                return True
        else:
            last_signature = comparable
            stable_start = time.time()

        sleep(1)

    return False


def wait_response_after_send(page, timeout_start=90, timeout_done=900, resend_text=None, before_signature=None):
    """
    Chờ phản hồi bản chống treo.

    Nếu sau một khoảng thời gian không thấy ChatGPT bắt đầu phản hồi,
    hàm sẽ tự resend prompt một lần nếu có resend_text.
    """
    print("⏳ Chờ ChatGPT bắt đầu phản hồi...")

    start = time.time()
    started = False

    while time.time() - start < timeout_start:
        wait_if_cloudflare(page)

        if is_generating(page) or has_new_assistant_response(page, before_signature):
            started = True
            break

        sleep(1)

    if not started:
        print("⚠ Không thấy ChatGPT bắt đầu phản hồi.")

        if resend_text:
            current_text = get_prompt_text(page)
            if resend_text in current_text:
                print("↻ Prompt vẫn còn trong ô nhập, thử gửi lại một lần")
                try:
                    before_signature = get_assistant_response_signature(page)
                    send_prompt(page, resend_text, max_send_attempts=2)
                except Exception as e:
                    print(f"⚠ Gửi lại prompt lỗi: {e}")

                start2 = time.time()
                while time.time() - start2 < timeout_start:
                    wait_if_cloudflare(page)
                    if is_generating(page) or has_new_assistant_response(page, before_signature):
                        started = True
                        break
                    sleep(1)

        if not started:
            print("⚠ Vẫn chưa thấy dấu hiệu bắt đầu, chờ thêm 10 giây...")
            sleep(10)

    print("⏳ Chờ ChatGPT xử lý xong...")

    start = time.time()
    last_log = 0

    while time.time() - start < timeout_done:
        wait_if_cloudflare(page)

        if before_signature and has_new_assistant_response(page, before_signature):
            print("  ✓ Phát hiện phản hồi mới, chờ ổn định...")
            return wait_assistant_response_stable(
                page,
                before_signature,
                stable_seconds=6,
                timeout=max(30, int(timeout_done - (time.time() - start)))
            )

        if not is_generating(page):
            sleep(5)
            if not is_generating(page):
                print("  ✓ ChatGPT đã dừng xử lý")
                return True

        elapsed = int(time.time() - start)
        if time.time() - last_log >= 30:
            gen = is_generating(page)
            has_new = has_new_assistant_response(page, before_signature) if before_signature else False
            print(f"  ⏳ Đang chờ... {elapsed}s | generating={gen} | new_response={has_new}")
            last_log = time.time()

        sleep(2)

    return False


def get_all_outputs(page):
    try:
        return page.evaluate("""
            () => {
                const prompt = document.querySelector('#prompt-textarea');
                const composer = prompt ? (prompt.closest('form') || prompt.parentElement) : null;
                const seen = new Set();
                const result = [];

                // 1. Raster images
                for (const img of Array.from(document.querySelectorAll('img'))) {
                    if (composer && composer.contains(img)) continue;

                    const src = img.currentSrc || img.getAttribute('src') || '';
                    if (!src) continue;

                    const low = src.toLowerCase();
                    const alt = (img.getAttribute('alt') || '').toLowerCase();
                    if (low.includes('avatar') || low.includes('emoji') || alt.includes('avatar')) continue;
                    if (src.startsWith('data:image/svg')) continue;

                    const box = img.getBoundingClientRect();
                    const naturalWidth = img.naturalWidth || 0;
                    const naturalHeight = img.naturalHeight || 0;
                    const visible = box.width >= 80 && box.height >= 80;
                    const realSize = naturalWidth >= 80 && naturalHeight >= 80;

                    if (!visible && !realSize) continue;
                    if (seen.has(src)) continue;

                    seen.add(src);
                    result.push({ kind: "raster", value: src });
                }

                // Helper to check if an element is inside composer, sidebar, nav, header, or generic UI we want to skip
                const shouldSkip = (el) => {
                    if (composer && composer.contains(el)) return true;

                    let cur = el;
                    while (cur) {
                        const tag = cur.tagName.toLowerCase();
                        const id = (cur.id || '').toLowerCase();
                        const cls = (cur.getAttribute('class') || '').toLowerCase();
                        const role = (cur.getAttribute('role') || '').toLowerCase();
                        const testid = (cur.getAttribute('data-testid') || '').toLowerCase();

                        if (
                            tag === 'nav' || tag === 'header' || role === 'navigation' ||
                            id.includes('sidebar') || cls.includes('sidebar') || testid.includes('sidebar') ||
                            testid.includes('profile') || testid.includes('user')
                        ) {
                            return true;
                        }
                        cur = cur.parentElement;
                    }
                    return false;
                };

                // 2. SVG links and buttons
                const candidates = Array.from(document.querySelectorAll('a, button, [role="link"], [role="button"], [download]'));
                let linkIdx = 0;
                for (const el of candidates) {
                    if (shouldSkip(el)) continue;

                    const rawHref = el.getAttribute('href') || '';
                    const rawText = (el.innerText || el.textContent || '').trim();
                    const rawDownload = el.getAttribute('download') || '';
                    const rawTitle = el.getAttribute('title') || '';
                    const ariaLabel = el.getAttribute('aria-label') || '';
                    const testid = el.getAttribute('data-testid') || '';
                    const role = el.getAttribute('role') || '';
                    const outerHTML = el.outerHTML ? el.outerHTML.slice(0, 300) : '';

                    const href = rawHref.toLowerCase();
                    const text = rawText.toLowerCase();
                    const downloadAttr = rawDownload.toLowerCase();
                    const titleAttr = rawTitle.toLowerCase();

                    // Keywords matching: svg, download, tải, tệp, vector, xml
                    const matchesKeyword = (
                        href.includes('svg') || href.includes('download') || href.startsWith('blob:') ||
                        text.includes('svg') || text.includes('.svg') || text.includes('download') || text.includes('tải') || text.includes('tài') || text.includes('tệp') || text.includes('vector') || text.includes('xml') ||
                        downloadAttr.includes('svg') || downloadAttr.includes('.svg') || downloadAttr.includes('download') ||
                        titleAttr.includes('svg') || titleAttr.includes('download')
                    );

                    const isGenerating = (
                        text.includes('generating') || text.includes('đang tạo') || 
                        outerHTML.toLowerCase().includes('loading-shimmer')
                    );

                    if (matchesKeyword && !isGenerating) {
                        let id = el.getAttribute('data-svg-id');
                        if (!id) {
                            linkIdx++;
                            id = `svg-lnk-${Date.now()}-${linkIdx}-${Math.random().toString(36).substr(2, 5)}`;
                            el.setAttribute('data-svg-id', id);
                        }
                        const tag = el.tagName.toLowerCase();
                        const selector = `${tag}[data-svg-id="${id}"]`;

                        const itemKey = `svg_download:${href}:${text}`;
                        if (!seen.has(itemKey)) {
                            seen.add(itemKey);
                            result.push({
                                kind: "svg_download",
                                value: rawHref || rawText,
                                href: rawHref,
                                selector: selector,
                                text: rawText,
                                download: rawDownload,
                                title: rawTitle,
                                ariaLabel: ariaLabel,
                                testid: testid,
                                role: role,
                                outerHTML: outerHTML
                            });
                        }
                    }
                }

                return result;
            }
        """)
    except Exception as e:
        print(f"⚠ Lỗi get_all_outputs: {e}")
        return []


def get_outcome_sig(item):
    if item.get("kind") == "raster":
        return ("raster", item.get("value"))
    else:
        return ("svg_download", item.get("value"), item.get("text"))


def get_latest_new_outcome(page, old_sigs):
    current = get_all_outputs(page)
    new_outcomes = []
    for item in current:
        sig = get_outcome_sig(item)
        if sig not in old_sigs:
            new_outcomes.append(item)
    return new_outcomes[-1] if new_outcomes else None


def run_dich_step(page):
    for attempt in range(1, MAX_RETRY_DICH + 1):
        print(f"→ Chép lại nguyên văn lần {attempt}")

        before_response = get_assistant_response_signature(page)
        send_prompt(page, PROMPT_CHEP_LAI)

        if not wait_response_after_send(
            page,
            timeout_start=90,
            timeout_done=900,
            resend_text=PROMPT_CHEP_LAI,
            before_signature=before_response
        ):
            print("⚠ Bước chép lại nguyên văn quá thời gian → thử lại")
            sleep(8)
            continue

        print(f"→ Dịch lần {attempt}")

        before_response = get_assistant_response_signature(page)
        send_prompt(page, PROMPT_DICH)

        if wait_response_after_send(
            page,
            timeout_start=90,
            timeout_done=900,
            resend_text=PROMPT_DICH,
            before_signature=before_response
        ):
            return True

        print("⚠ Bước Dịch quá thời gian → thử lại")
        sleep(8)

    return False


def wait_image_generation_finished_or_image_ready(page, old_sigs, timeout=IMAGE_WAIT_TIMEOUT):
    """
    Chờ riêng cho bước tạo ảnh/tệp theo kiểu KHÓA CỨNG.

    Nguyên tắc mới:
    - Sau khi đã gửi prompt tạo ảnh/tệp thì KHÔNG retry sớm.
    - Không dựa vào việc mất nút Stop để kết luận fail.
    - Không dựa vào idle tạm thời để retry.
    - Chỉ thoát khi:
        1. Có kết quả mới (ảnh/SVG);
        2. Có lỗi rõ ràng trên màn hình và đã chờ thêm đủ lâu;
        3. Hết timeout dài IMAGE_WAIT_TIMEOUT.
    """
    start = time.time()
    last_log = 0
    first_clear_error_time = None

    while time.time() - start < timeout:
        wait_if_cloudflare(page)

        outcome = get_latest_new_outcome(page, old_sigs)
        if outcome:
            print(f"✓ Có kết quả mới: {outcome.get('kind')}")
            return outcome

        elapsed = int(time.time() - start)

        if has_clear_generation_error(page):
            if first_clear_error_time is None:
                first_clear_error_time = time.time()
                print("⚠ Phát hiện thông báo lỗi tạo ảnh/tệp, chờ thêm để chắc chắn...")

            # Có lỗi rõ ràng thì vẫn chờ thêm 90 giây, vì đôi khi ảnh/SVG vẫn ra muộn.
            if time.time() - first_clear_error_time >= 90:
                outcome = get_latest_new_outcome(page, old_sigs)
                if outcome:
                    print(f"✓ Có kết quả mới: {outcome.get('kind')}")
                    return outcome
                print("⚠ Lỗi tạo ảnh/tệp rõ ràng và không có kết quả sau khi chờ thêm")
                return None
        else:
            first_clear_error_time = None

        # Log định kỳ, không kết luận fail khi idle.
        if time.time() - last_log >= 30:
            state = "đang xử lý" if is_generating(page) else "chưa có tín hiệu xử lý rõ, vẫn tiếp tục chờ"
            all_outs = get_all_outputs(page)
            print(f"  ⏳ Chờ kết quả mới... {elapsed}s | trạng thái: {state} | Quét được {len(all_outs)} outputs")
            for item in all_outs[:5]:
                print(f"    - Output: kind={item.get('kind')}, text='{item.get('text', '').strip()}', value='{item.get('value', '')[:100]}'")
            last_log = time.time()

        sleep(10)

    print("⚠ Hết timeout dài nhưng chưa thấy kết quả mới")
    return None


def try_create_image(page, old_sigs):
    for attempt in range(1, MAX_RETRY_IMAGE + 1):
        print(f"→ Tạo ảnh/tệp lần {attempt}")

        before_send_outputs = get_all_outputs(page)
        before_send_sigs = {get_outcome_sig(x) for x in before_send_outputs}
        merged_old_sigs = old_sigs.union(before_send_sigs)

        send_prompt(page, PROMPT_TAO_ANH, max_send_attempts=1)

        # Chỉ chờ phản hồi bắt đầu, không dùng hàm timeout ngắn 180 giây để kết luận fail.
        # Sau đó chuyển sang hàm chờ ảnh riêng bên dưới.
        started = False
        start = time.time()
        print("⏳ Chờ ChatGPT bắt đầu tạo...")
        while time.time() - start < 120:
            wait_if_cloudflare(page)
            if is_generating(page):
                started = True
                break
            outcome = get_latest_new_outcome(page, merged_old_sigs)
            if outcome:
                print(f"✓ Có kết quả mới: {outcome.get('kind')}")
                return outcome
            sleep(2)

        if not started:
            current_text = get_prompt_text(page)
            if PROMPT_TAO_ANH in current_text:
                raise Exception("Prompt tạo ảnh/tệp vẫn còn trong ô nhập sau khi gửi; dừng để tránh gửi trùng.")

        outcome = wait_image_generation_finished_or_image_ready(
            page,
            merged_old_sigs,
            timeout=IMAGE_WAIT_TIMEOUT
        )

        if outcome:
            return outcome

        # Trước khi retry lần sau, chờ chắc chắn ChatGPT đã thật sự dừng.
        print("⚠ Chưa lấy được kết quả → chuẩn bị retry, chờ ChatGPT idle chắc chắn")
        idle_start = time.time()
        while time.time() - idle_start < 120:
            wait_if_cloudflare(page)
            if not is_generating(page):
                sleep(10)
                if not is_generating(page):
                    break
            sleep(3)

        sleep(10)

    return None


def download_image(page, url, path):
    print("→ Tải ảnh")
    temp_path = f"{path}.part"

    if url.startswith("data:image"):
        data = base64.b64decode(url.split(",")[1])
        with open(temp_path, "wb") as f:
            f.write(data)
        if os.path.getsize(temp_path) <= 10000:
            raise Exception("File tải từ data URL quá nhỏ")
        os.replace(temp_path, path)
        return

    for attempt in range(1, 4):
        try:
            data = page.evaluate("""
                async (u) => {
                    const r = await fetch(u, {credentials:'include'});
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    const b = await r.blob();
                    const buf = await b.arrayBuffer();
                    return Array.from(new Uint8Array(buf));
                }
            """, url)

            with open(temp_path, "wb") as f:
                f.write(bytearray(data))

            if os.path.getsize(temp_path) > 10000:
                os.replace(temp_path, path)
                return

            raise Exception("File quá nhỏ")

        except Exception as e:
            print(f"⚠ Tải lỗi lần {attempt}: {e}")
            sleep(5)

    raise Exception("Không tải được ảnh")

def read_downloaded_svg_preview(path, limit=200):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(limit).replace("\n", " ").strip()
    except Exception:
        return ""


def ensure_downloaded_svg(path):
    if not os.path.exists(path):
        raise Exception("File SVG chưa được ghi ra ổ đĩa")

    size = os.path.getsize(path)
    if size <= 100:
        raise Exception(f"File SVG quá nhỏ ({size} bytes)")

    preview = read_downloaded_svg_preview(path)
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        raise Exception(f"Không đọc được SVG sau khi tải: {e}")

    if "<svg" not in content.lower():
        raise Exception(f"Nội dung tải về không phải SVG. Đoạn đầu: {preview}")


def write_data_url_to_file(data_url, path):
    header, payload = data_url.split(",", 1)
    if ";base64" in header.lower():
        data = base64.b64decode(payload)
    else:
        data = unquote_to_bytes(payload)
    with open(path, "wb") as f:
        f.write(data)


def normalize_download_href(page, href):
    if not href:
        return ""
    return page.evaluate(
        """(href) => new URL(href, window.location.origin).toString()""",
        href
    )


def is_fetchable_href(href):
    if not href:
        return False

    low = href.strip().lower()
    return (
        low.startswith("http://") or
        low.startswith("https://") or
        low.startswith("/backend-api/") or
        low.startswith("backend-api/") or
        low.startswith("blob:") or
        low.startswith("data:image")
    )


def fetch_svg_href(page, href, temp_path):
    url = normalize_download_href(page, href)
    if not url:
        raise Exception("Không có href để fetch")

    if url.startswith("data:image"):
        print("  ↳ Tải SVG từ data URL")
        write_data_url_to_file(url, temp_path)
        ensure_downloaded_svg(temp_path)
        return True

    print(f"  ↳ Tải SVG từ href: {url[:160]}")
    result = page.evaluate("""
        async (u) => {
            const r = await fetch(u, { credentials: 'include' });
            const text = await r.text();
            return {
                ok: r.ok,
                status: r.status,
                url: r.url,
                contentType: r.headers.get('content-type') || '',
                text
            };
        }
    """, url)

    text = result.get("text") or ""
    with open(temp_path, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    if not result.get("ok"):
        preview = text[:200].replace("\n", " ").strip()
        raise Exception(
            f"Fetch SVG HTTP {result.get('status')} | type={result.get('contentType')} | đoạn đầu: {preview}"
        )

    ensure_downloaded_svg(temp_path)
    return True


def find_svg_href_by_selector_or_text(page, selector):
    return page.evaluate("""
        (sel) => {
            const fromSelector = sel ? document.querySelector(sel) : null;
            const candidates = [
                fromSelector,
                ...Array.from(document.querySelectorAll('a, [role="link"], button, [role="button"], [download]'))
            ].filter(Boolean);

            for (const el of candidates) {
                const href = el.getAttribute('href') || '';
                const text = (el.innerText || el.textContent || '').trim();
                const download = el.getAttribute('download') || '';
                const haystack = `${href} ${text} ${download}`.toLowerCase();
                if (haystack.includes('.svg') || haystack.includes('svg') || haystack.includes('download svg') || haystack.includes('tải svg')) {
                    return href;
                }
            }
            return '';
        }
    """, selector or "")


def click_svg_download(page, outcome, temp_path):
    selector = outcome.get("selector") or ""
    locators_to_try = []
    if selector:
        locators_to_try.append(("selector", page.locator(selector)))
    locators_to_try.extend([
        ("text '.svg'", page.get_by_text(".svg", exact=False).last),
        ("text 'Download SVG'", page.get_by_text("Download SVG", exact=False).last),
        ("text 'Tải SVG'", page.get_by_text("Tải SVG", exact=False).last),
        ("text 'Tải SVG bản dịch'", page.get_by_text("Tải SVG bản dịch", exact=False).last)
    ])

    last_error = None
    for name, loc in locators_to_try:
        try:
            if loc.count() > 0:
                print(f"  ↳ Tải bằng click: {name}")
                with page.expect_download(timeout=15000) as download_info:
                    loc.click(timeout=8000)
                download = download_info.value
                download.save_as(temp_path)
                ensure_downloaded_svg(temp_path)
                return True
        except Exception as e:
            last_error = e
            print(f"  ↳ Click {name} chưa tải được, thử cách khác")

    raise Exception(f"Click không tải được SVG: {last_error}")


def get_download_dirs():
    dirs = [DOWNLOAD_FOLDER]
    try:
        user_downloads = os.path.join(os.environ['USERPROFILE'], 'Downloads')
        if os.path.exists(user_downloads):
            dirs.append(user_downloads)
    except Exception:
        pass
    return dirs


def get_download_dirs_files():
    files = {}
    for d in get_download_dirs():
        if not os.path.exists(d):
            continue
        try:
            for entry in os.scandir(d):
                if entry.is_file():
                    files[entry.path] = entry.stat().st_mtime
        except Exception:
            pass
    return files


def find_newly_downloaded_file(before_files):
    for _ in range(6):
        current_files = get_download_dirs_files()
        new_files = []
        for path, mtime in current_files.items():
            if path not in before_files:
                new_files.append((path, mtime))
            elif mtime > before_files[path]:
                new_files.append((path, mtime))

        if new_files:
            new_files.sort(key=lambda x: x[1], reverse=True)
            for path, _ in new_files:
                low = path.lower()
                if low.endswith(".crdownload") or low.endswith(".tmp") or low.endswith(".part"):
                    sleep(0.5)
                    continue
                if low.endswith(".svg"):
                    return path
                try:
                    if os.path.getsize(path) > 100:
                        with open(path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read(2048)
                        if "<svg" in content.lower():
                            return path
                except Exception:
                    pass
        sleep(0.5)
    return None


def get_last_assistant_text(page):
    try:
        return page.evaluate("""
            () => {
                let nodes = Array.from(
                    document.querySelectorAll('[data-message-author-role="assistant"]')
                );
                if (!nodes.length) {
                    nodes = Array.from(
                        document.querySelectorAll('.agent-turn, .markdown, div.result-streaming')
                    );
                }
                if (!nodes.length) return "";
                const last = nodes[nodes.length - 1];
                return last.innerText || last.textContent || "";
            }
        """)
    except Exception as e:
        print(f"⚠ Lỗi get_last_assistant_text: {e}")
        return ""


def extract_json_from_text(text: str) -> dict:
    import re
    if not text:
        raise ValueError("Nội dung text rỗng")
        
    # 1. Thử trích xuất từ markdown code blocks (```json ... ``` hoặc ``` ... ```)
    match = re.search(r"```(?:json)?(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        content = match.group(1).strip()
        first_brace = content.find("{")
        last_brace = content.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace >= first_brace:
            json_str = content[first_brace:last_brace + 1].strip()
            try:
                return json.loads(json_str)
            except Exception as e:
                raise ValueError(f"Lỗi parse JSON từ code block: {e}")
                
    # 2. Tìm cặp ngoặc { ... } bên ngoài cùng trong toàn bộ text
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace >= first_brace:
        json_str = text[first_brace:last_brace + 1].strip()
        try:
            return json.loads(json_str)
        except Exception as e:
            raise ValueError(f"Lỗi parse JSON từ văn bản: {e}")
            
    raise ValueError("Không tìm thấy cấu trúc JSON hợp lệ trong phản hồi")


def extract_svg_from_dom(page):
    try:
        svg_content = page.evaluate("""
            () => {
                const assistantNodes = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'));
                for (const node of assistantNodes) {
                    const svgEl = node.querySelector('svg');
                    if (svgEl) {
                        return svgEl.outerHTML;
                    }
                }

                const codeBlocks = Array.from(document.querySelectorAll('pre, code, div.markdown'));
                for (const block of codeBlocks) {
                    const text = (block.innerText || block.textContent || '').trim();
                    if (text.includes('<svg') && text.includes('</svg>')) {
                        const startIdx = text.indexOf('<svg');
                        const endIdx = text.indexOf('</svg>', startIdx);
                        if (startIdx !== -1 && endIdx !== -1) {
                            return text.slice(startIdx, endIdx + 6);
                        }
                    }
                }

                const svgEls = Array.from(document.querySelectorAll('svg'));
                for (const svgEl of svgEls) {
                    const prompt = document.querySelector('#prompt-textarea');
                    const composer = prompt ? (prompt.closest('form') || prompt.parentElement) : null;
                    if (composer && composer.contains(svgEl)) continue;

                    let cur = svgEl;
                    let skip = false;
                    while (cur) {
                        const tag = cur.tagName.toLowerCase();
                        const id = (cur.id || '').toLowerCase();
                        const cls = (cur.getAttribute('class') || '').toLowerCase();
                        if (tag === 'nav' || tag === 'header' || id.includes('sidebar') || cls.includes('sidebar')) {
                            skip = true;
                            break;
                        }
                        cur = cur.parentElement;
                    }
                    if (!skip) {
                        const box = svgEl.getBoundingClientRect();
                        if (box.width > 20 && box.height > 20) {
                            return svgEl.outerHTML;
                        }
                    }
                }
                return '';
            }
        """)
        return svg_content
    except Exception as e:
        print(f"  ⚠ Lỗi extract_svg_from_dom: {e}")
        return ""


def click_element_without_expect_download(page, outcome):
    selector = outcome.get("selector") or ""
    locators_to_try = []
    if selector:
        locators_to_try.append(("selector", page.locator(selector)))
    locators_to_try.extend([
        ("text '.svg'", page.get_by_text(".svg", exact=False).last),
        ("text 'Download SVG'", page.get_by_text("Download SVG", exact=False).last),
        ("text 'Tải SVG'", page.get_by_text("Tải SVG", exact=False).last),
        ("text 'Tải SVG bản dịch'", page.get_by_text("Tải SVG bản dịch", exact=False).last)
    ])

    for name, loc in locators_to_try:
        try:
            if loc.count() > 0:
                print(f"  ↳ Thử click không expect_download: {name}")
                loc.click(timeout=5000)
                return True
        except Exception as e:
            print(f"  ↳ Click {name} (không expect_download) lỗi: {e}")
    return False


def download_svg_output(page, outcome, temp_svg_path):
    print("→ Tải SVG")
    temp_path = temp_svg_path

    # 1. Thử fetch href trước nếu có href hợp lệ
    hrefs = [
        outcome.get("href") or "",
        find_svg_href_by_selector_or_text(page, outcome.get("selector") or "")
    ]

    valid_hrefs = []
    for h in hrefs:
        if h and is_fetchable_href(h) and h not in valid_hrefs:
            valid_hrefs.append(h)

    for href in valid_hrefs:
        try:
            print(f"  ↳ Thử fetch SVG từ: {href[:120]}")
            if fetch_svg_href(page, href, temp_path):
                return temp_path
        except Exception as e:
            print(f"  ↳ Fetch SVG thất bại: {e}")
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    # 2. Click không expect_download và quét file mới
    print("  ↳ Thử click không expect_download + quét file mới")
    before_files = get_download_dirs_files()
    if click_element_without_expect_download(page, outcome):
        new_file = find_newly_downloaded_file(before_files)
        if new_file:
            print(f"  ✓ Phát hiện file tải về mới: {new_file}")
            try:
                shutil.copy2(new_file, temp_path)
                ensure_downloaded_svg(temp_path)
                return temp_path
            except Exception as e:
                print(f"  ↳ Copy file mới tải thất bại: {e}")
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

    # 3. Click dùng expect_download (Playwright standard)
    print("  ↳ Thử click dùng expect_download")
    try:
        if click_svg_download(page, outcome, temp_path):
            return temp_path
    except Exception as e:
        print(f"  ↳ Click dùng expect_download thất bại: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

    # 4. Thử đọc trực tiếp từ DOM
    print("  ↳ Thử đọc SVG trực tiếp từ DOM")
    dom_svg = extract_svg_from_dom(page)
    if dom_svg:
        try:
            with open(temp_path, "w", encoding="utf-8", newline="") as f:
                f.write(dom_svg)
            ensure_downloaded_svg(temp_path)
            print("  ✓ Đã lấy SVG thành công trực tiếp từ DOM")
            return temp_path
        except Exception as e:
            print(f"  ↳ Đọc DOM SVG thất bại: {e}")
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    # In thông tin chi tiết khi thất bại hoàn toàn
    print(f"  ⚠ Chi tiết SVG outcome:")
    print(f"    - kind: {outcome.get('kind')}")
    print(f"    - value: {outcome.get('value')}")
    print(f"    - href: {outcome.get('href')}")
    print(f"    - selector: {outcome.get('selector')}")
    print(f"    - text: {outcome.get('text')}")
    print(f"    - aria-label: {outcome.get('ariaLabel')}")
    print(f"    - data-testid: {outcome.get('testid')}")
    print(f"    - role: {outcome.get('role')}")
    print(f"    - outerHTML: {outcome.get('outerHTML')}")

    raise Exception("Không tải được SVG qua bất kỳ phương pháp nào (fetch, click, quét file, DOM extraction)")


def validate_and_process_svg(temp_download_path, target_svg_path):
    if not os.path.exists(temp_download_path):
        raise Exception("Không tìm thấy file SVG đã tải")

    size = os.path.getsize(temp_download_path)
    if size < 100:
        raise Exception(f"File SVG quá nhỏ ({size} bytes)")

    try:
        with open(temp_download_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        raise Exception(f"Không đọc được nội dung SVG: {e}")

    if "<svg" not in content.lower():
        # Genuine bad file (not containing svg tag) - rename to bad.svg
        bad_svg_path = target_svg_path.replace(".svg", ".bad.svg")
        if os.path.exists(bad_svg_path):
            try:
                os.remove(bad_svg_path)
            except Exception:
                pass
        os.rename(temp_download_path, bad_svg_path)
        raise Exception("Nội dung file không chứa thẻ <svg>.")

    # Valid SVG format content-wise - save to final target path immediately
    if os.path.exists(target_svg_path):
        try:
            os.remove(target_svg_path)
        except Exception:
            pass
    os.rename(temp_download_path, target_svg_path)

    return True


def send_svg_instruction(page):
    if not PROMPT_SVG_INSTRUCTION.strip():
        return
    print("→ Gửi SVG instruction nền")
    before_response = get_assistant_response_signature(page)
    send_prompt(page, PROMPT_SVG_INSTRUCTION)
    wait_response_after_send(
        page,
        timeout_start=90,
        timeout_done=900,
        resend_text=PROMPT_SVG_INSTRUCTION,
        before_signature=before_response
    )





def process_one(page, all_images, img):
    index = all_images.index(img) + 1
    
    if OUTPUT_MODE == "image":
        save_name = get_output_name(img)
        save_path = os.path.join(DOWNLOAD_FOLDER, save_name)

        print(f"\n--- {index}: {img.name} → {save_name} ---")

        reset_chat(page)
        send_svg_instruction(page)
        upload_image(page, img)
        wait_upload_attached(page, timeout=90)

        if not run_dich_step(page):
            raise Exception("Bước Dịch quá thời gian chờ sau nhiều lần thử")

        sleep(5)

        old_outputs = get_all_outputs(page)
        old_sigs = {get_outcome_sig(x) for x in old_outputs}

        outcome = try_create_image(page, old_sigs)

        if not outcome:
            raise Exception("Không tạo được ảnh/tệp sau nhiều lần thử")

        if outcome.get("kind") == "raster":
            download_image(page, outcome["value"], save_path)
            if os.path.exists(save_path) and os.path.getsize(save_path) > 10000:
                print("✓ DONE")
                write_progress(index, img.name, save_name, "done", "OK")
            else:
                raise Exception("File tải lỗi hoặc quá nhỏ")
        elif outcome.get("kind") == "svg_download":
            svg_name = get_svg_name_from_png(save_name)
            svg_path = os.path.join(DOWNLOAD_FOLDER, svg_name)
            bad_svg_path = svg_path.replace(".svg", ".bad.svg")

            # Restore bad.svg to .svg if it exists from previous run but .svg is missing
            if os.path.exists(bad_svg_path) and not os.path.exists(svg_path):
                try:
                    os.rename(bad_svg_path, svg_path)
                except Exception:
                    pass

            temp_download_path = os.path.join(DOWNLOAD_FOLDER, f"{svg_name}.part")

            # Clean up old temp files
            for path_to_clean in [temp_download_path, temp_download_path + ".part"]:
                if os.path.exists(path_to_clean):
                    try:
                        os.remove(path_to_clean)
                    except Exception:
                        pass

            download_svg_output(page, outcome, temp_download_path)
            validate_and_process_svg(temp_download_path, svg_path)

            if os.path.exists(svg_path) and os.path.getsize(svg_path) > 100:
                print("✓ DONE (SVG)")
                write_progress(index, img.name, svg_name, "done", "OK (SVG)")
            else:
                raise Exception("File SVG lỗi hoặc quá nhỏ")
                
    elif OUTPUT_MODE == "svg_json":
        print(f"\n--- {index}: {img.name} (SVG JSON Mode) ---")
        
        # 1. Reset chat & upload ảnh như cũ
        reset_chat(page)
        upload_image(page, img)
        wait_upload_attached(page, timeout=90)
        
        # 2. Gửi prompt "chép lại nguyên văn" và "dịch bản chép lại"
        print("→ Bắt đầu bước dịch (chép lại + dịch)")
        if not run_dich_step(page):
            raise Exception("Bước Dịch quá thời gian chờ sau nhiều lần thử")
            
        sleep(5)
        
        # 3. Gửi PROMPT_SVG_JSON_LAYOUT
        print("→ Gửi prompt JSON Layout")
        before_response = get_assistant_response_signature(page)
        send_prompt(page, PROMPT_SVG_JSON_LAYOUT)
        
        # Chờ assistant trả lời xong
        print("⏳ Chờ ChatGPT phản hồi JSON Layout...")
        if not wait_response_after_send(
            page,
            timeout_start=90,
            timeout_done=900,
            resend_text=PROMPT_SVG_JSON_LAYOUT,
            before_signature=before_response
        ):
            raise Exception("Chờ phản hồi JSON Layout quá thời gian")
            
        # Lấy text assistant cuối cùng
        text = get_last_assistant_text(page)
        if not text:
            raise Exception("Không lấy được nội dung phản hồi của assistant")
            
        # Extract JSON
        print("→ Trích xuất JSON từ phản hồi")
        layout = extract_json_from_text(text)
        
        # Đảm bảo thư mục lưu output tồn tại
        output_dir = BASE_DIR / "output"
        json_layout_dir = output_dir / "json_layout"
        svg_dir = output_dir / "svg"
        failed_dir = output_dir / "failed"
        
        os.makedirs(json_layout_dir, exist_ok=True)
        os.makedirs(svg_dir, exist_ok=True)
        os.makedirs(failed_dir, exist_ok=True)
        
        img_stem = img.stem
        json_path = json_layout_dir / f"{img_stem}.json"
        svg_path = svg_dir / f"{img_stem}.svg"
        
        # Lưu JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        print(f"✓ Đã lưu JSON vào: {json_path}")
        
        # Validate layout
        print("→ Kiểm tra (validate) layout")
        severe_errors, warning_errors = validate_layout_classified(layout)
        
        # Render SVG (chỉ render nếu không có lỗi nghiêm trọng từ validation)
        render_warnings = []
        if not severe_errors:
            print("→ Render SVG")
            render_warnings = render_svg(layout, str(svg_path))
            print(f"✓ Đã lưu SVG vào: {svg_path}")
            
            # Phân loại warnings từ render_svg
            for warn in render_warnings:
                if warn.startswith("[SEVERE]"):
                    severe_errors.append(warn[len("[SEVERE]"):].strip())
                else:
                    clean_warn = warn[len("[WARNING]"):].strip() if warn.startswith("[WARNING]") else warn
                    warning_errors.append(clean_warn)
                    
        # Nếu có lỗi nghiêm trọng (Severe)
        if severe_errors:
            print(f"[FAILED] {img.name} thất bại do lỗi nghiêm trọng: {severe_errors}")
            # Ghi thông tin lỗi và copy ảnh gốc vào output/failed
            failed_img_path = failed_dir / img.name
            error_txt_path = failed_dir / f"{img_stem}_error.txt"
            
            try:
                shutil.copy2(img, failed_img_path)
                with open(error_txt_path, "w", encoding="utf-8") as f:
                    f.write(f"File: {img.name}\n")
                    f.write(f"Time: {datetime.now().isoformat()}\n")
                    f.write("Severe Layout/Rendering Errors:\n")
                    for err in severe_errors:
                        f.write(f"- {err}\n")
                    if warning_errors:
                        f.write("\nWarnings:\n")
                        for warn in warning_errors:
                            f.write(f"- {warn}\n")
                print(f"✓ Đã copy ảnh gốc và ghi log lỗi vào: {failed_dir}")
            except Exception as e_failed:
                print(f"⚠ Lỗi khi lưu log thất bại: {e_failed}")
                
            raise Exception(f"Severe errors: {'; '.join(severe_errors)}")
            
        # Nếu chỉ có warnings và không có severe errors
        elif warning_errors:
            print(f"[WARNING] {img.name} thành công nhưng có cảnh báo: {warning_errors}")
            
            # Vẫn xuất PNG preview và PDF từ SVG
            png_preview_path = output_dir / "png_preview" / f"{img_stem}.png"
            pdf_path = output_dir / "pdf" / f"{img_stem}.pdf"
            export_svg_to_formats(svg_path, png_preview_path, pdf_path, EXPORT_PNG_PREVIEW, EXPORT_PDF)
            
            # Ghi progress
            write_progress(index, img.name, f"{img_stem}.svg", "done", f"WARNING: {'; '.join(warning_errors)[:100]}")
            
        # Nếu hoàn toàn không có lỗi
        else:
            print(f"[OK] {img.name} hoàn thành xuất sắc!")
            
            # Xuất PNG preview và PDF từ SVG
            png_preview_path = output_dir / "png_preview" / f"{img_stem}.png"
            pdf_path = output_dir / "pdf" / f"{img_stem}.pdf"
            export_svg_to_formats(svg_path, png_preview_path, pdf_path, EXPORT_PNG_PREVIEW, EXPORT_PDF)
            
            # Ghi progress
            write_progress(index, img.name, f"{img_stem}.svg", "done", "OK (SVG JSON)")


def main():
    ensure_dirs()
    init_progress()

    images = get_images()
    images = apply_start_from(images)

    batch = get_next_batch(images)

    print(f"📁 Ảnh gốc: {IMAGE_FOLDER}")
    print(f"📁 Ảnh VN: {DOWNLOAD_FOLDER}")
    print(f"📄 Log: {PROGRESS_FILE}")
    print(f"🔢 Tổng ảnh sau điểm bắt đầu: {len(images)}")
    print(f"🚀 Mỗi lần xử lý: {BATCH_SIZE} ảnh")
    print(f"📌 Batch lần này: {len(batch)} ảnh")
    print(f"🔁 Chế độ chạy: {RUN_MODE}")
    print(f"📤 Chế độ đầu ra (OUTPUT_MODE): {OUTPUT_MODE}")
    print(f"🖼 Xuất PNG Preview (EXPORT_PNG_PREVIEW): {EXPORT_PNG_PREVIEW}")
    print(f"📄 Xuất PDF (EXPORT_PDF): {EXPORT_PDF}")
    print(f"📝 Prompt chép lại: {PROMPT_CHEP_LAI}")
    print(f"📝 Prompt dịch: {PROMPT_DICH}")
    print(f"📝 Instruction tạo SVG: {PROMPT_SVG_INSTRUCTION}")
    print(f"📝 Prompt tạo ảnh: {PROMPT_TAO_ANH}")
    print(f"📝 Prompt JSON Layout: {PROMPT_SVG_JSON_LAYOUT}")

    if START_FROM:
        print(f"▶ Bắt đầu từ: {START_FROM}")

    if not batch:
        print("✅ Không còn ảnh cần xử lý.")
        return

    with sync_playwright() as p:
        context = None
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=False,
                accept_downloads=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox"
                ],
                viewport={"width": 1400, "height": 900}
            )

            page = context.pages[0] if context.pages else context.new_page()

            minimize_own_browser(context)
            login_if_needed(page)

            for img in batch:
                try:
                    index = images.index(img) + 1
                    if OUTPUT_MODE == "svg_json":
                        save_name = img.stem + ".svg"
                    else:
                        save_name = get_output_name(img)
                    process_one(page, images, img)

                except Exception as e:
                    index = getattr(img, '_batch_index', 0) or (images.index(img) + 1 if img in images else 0)
                    try:
                        if OUTPUT_MODE == "svg_json":
                            save_name = img.stem + ".svg"
                        else:
                            save_name = get_output_name(img)
                    except Exception:
                        save_name = img.stem + "_VN.png"
                    print(f"✗ Lỗi: {e}")
                    write_progress(index, img.name, save_name, "fail", str(e))

                print(f"⏸ Nghỉ {WAIT_AFTER_EACH_IMAGE} giây")
                sleep(WAIT_AFTER_EACH_IMAGE)
        finally:
            if context is not None:
                context.close()


if __name__ == "__main__":
    main()
