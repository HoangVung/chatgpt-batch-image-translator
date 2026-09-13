import os
import sys
import time
import csv
import json
import base64
import functools
import tempfile
from io import BytesIO
from pathlib import Path
from datetime import datetime
from PIL import Image
from playwright.sync_api import sync_playwright
from progress_utils import FAILED_STATUSES, read_latest_progress

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


def get_data_dir():
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ChatGPT Batch Translator"
    return BASE_DIR


DATA_DIR = get_data_dir()
SETTINGS_FILE = DATA_DIR / "app_settings.json"

DEFAULT_CONFIG = {
    "image_folder": str(DATA_DIR / "images"),
    "download_folder": str(DATA_DIR / "images_vn"),
    "profile_dir": str(DATA_DIR / "chatgpt_auto_profile"),
    "batch_size": "10",
    "start_from": ""
}


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
    cfg["profile_dir"] = os.getenv("PROFILE_DIR", cfg.get("profile_dir", "")).strip()
    cfg["batch_size"] = int(os.getenv("BATCH_SIZE", cfg.get("batch_size", "10")))
    cfg["run_mode"] = os.getenv("RUN_MODE", "main")
    cfg["start_from"] = os.getenv("START_FROM", cfg.get("start_from", "")).strip()
    cfg["service"] = os.getenv("SERVICE", cfg.get("service", "chatgpt")).strip().lower()

    if not cfg["profile_dir"]:
        if cfg["service"] == "gemini":
            cfg["profile_dir"] = str(DATA_DIR / "gemini_auto_profile")
        else:
            cfg["profile_dir"] = str(DATA_DIR / "chatgpt_auto_profile")

    return cfg


CFG = load_config()

IMAGE_FOLDER = CFG["image_folder"]
DOWNLOAD_FOLDER = CFG["download_folder"]
PROFILE_DIR = CFG["profile_dir"]
BATCH_SIZE = CFG["batch_size"]
RUN_MODE = CFG["run_mode"]
START_FROM = CFG["start_from"]
SERVICE = CFG.get("service", "chatgpt")
BATCH_RESULT_PREFIX = "__BATCH_RESULT__="

WAIT_AFTER_EACH_IMAGE = 30
MAX_RETRY_IMAGE = 3
MAX_RETRY_DICH = 3
IMAGE_WAIT_TIMEOUT = 1800
SEND_VERIFY_TIMEOUT = 45

PROMPT_CHEP_LAI = "chép lại nguyên văn"
PROMPT_DICH = "dịch bản chép lại"
PROMPT_TAO_ANH = "Tạo ảnh với bản dịch"

IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp"]
PROGRESS_FILE = os.path.join(DOWNLOAD_FOLDER, "progress.csv")


def sleep(s):
    time.sleep(s)


def ensure_dirs():
    if not Path(IMAGE_FOLDER).is_dir():
        raise ValueError(f"Không tìm thấy thư mục ảnh gốc: {IMAGE_FOLDER}. Hãy chọn lại thư mục ảnh gốc.")
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
        # Fail before uploading or generating if the chosen destination is unwritable.
        with tempfile.TemporaryFile(dir=DOWNLOAD_FOLDER) as probe:
            probe.write(b"write-check")
            probe.flush()
    except OSError as exc:
        raise OSError(f"Không ghi được vào thư mục ảnh VN: {DOWNLOAD_FOLDER}: {exc}") from exc
    os.makedirs(PROFILE_DIR, exist_ok=True)


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
    73_129.jpg -> 00073_00129VN.png
    """
    left, right = parse_source_numbers(img)

    if left == 999999999 or right == 999999999:
        raise Exception(f"Tên file nguồn không đúng dạng số_trang_sốthứtự: {img.name}")

    return f"{left:05d}_{right:05d}VN.png"


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


def find_start_matches(images, start_value):
    value = start_value.lower().strip()
    exact = [img for img in images if value in {img.name.lower(), img.stem.lower()}]
    if exact:
        return exact
    return [img for img in images if match_start_file(img, start_value)]


def apply_start_from(images, require_single_match=False):
    if not START_FROM:
        return images

    matches = find_start_matches(images, START_FROM)
    if not matches:
        raise ValueError(f"Không tìm thấy ảnh bắt đầu: {START_FROM}")
    if require_single_match and len(matches) != 1:
        raise ValueError(
            f"'{START_FROM}' khớp với {len(matches)} ảnh. "
            "Hãy nhập đầy đủ tên file để chạy lại đúng một ảnh."
        )

    first_match = matches[0]
    index = images.index(first_match)
    print(f"▶ Bắt đầu từ ảnh: {first_match.name}")
    return images[index:]


def read_latest_status():
    init_progress()
    return {
        file_name: {
            "status": (row.get("status") or "").strip().lower(),
            "note": row.get("note", ""),
        }
        for file_name, row in read_latest_progress(PROGRESS_FILE).items()
    }


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


def output_file_exists(img):
    try:
        output_name = get_output_name(img)
        output_path = os.path.join(DOWNLOAD_FOLDER, output_name)

        return is_valid_image_file(output_path)
    except Exception:
        return False


def legacy_output_file_exists(img, images):
    """Recognize a pre-unique-name output only when it cannot be ambiguous."""
    try:
        left, _ = parse_source_numbers(img)
        if left == 999999999:
            return False
        if sum(parse_source_numbers(candidate)[0] == left for candidate in images) != 1:
            return False
        legacy_path = os.path.join(DOWNLOAD_FOLDER, f"{left:05d}VN.png")
        return is_valid_image_file(legacy_path)
    except Exception:
        return False


def get_job_state(images):
    """Reconcile source files with valid outputs; CSV status alone is insufficient."""
    latest = read_latest_status()
    pending, failed, done = [], [], []
    for img in images:
        status = latest.get(img.name, {}).get("status", "")
        valid = output_file_exists(img)
        if status == "done" and not valid:
            valid = legacy_output_file_exists(img, images)
        if valid:
            done.append(img)
        elif status in FAILED_STATUSES:
            failed.append(img)
        else:
            pending.append(img)
    return {
        "total": len(images), "done": len(done), "failed": len(failed),
        "pending": len(pending), "pending_files": pending,
        "state": "complete" if len(done) == len(images) else
                 "needs_retry" if not pending else "pending",
    }


def get_next_batch(images):
    latest = read_latest_status()
    pending = []

    if RUN_MODE == "retry":
        for img in images:
            st = latest.get(img.name, {}).get("status", "")
            if st in FAILED_STATUSES:
                pending.append(img)
        return pending[:BATCH_SIZE]

    if RUN_MODE == "force":
        return images[:1]

    return get_job_state(images)["pending_files"][:BATCH_SIZE]


def finish_batch_result(result, images):
    job = get_job_state(images)
    result["job"] = {key: value for key, value in job.items() if key != "pending_files"}
    result["next_pending_count"] = job["pending"]
    code = 0
    if result.get("failure_count") or job["state"] == "needs_retry":
        code = 2
    elif (result["mode"] == "main" and result["selected_count"] and
          job["pending"] >= result["pending_before"]):
        code = 3
    result["exit_code"] = code
    print(f"Job: {job['done']}/{job['total']} ảnh hợp lệ; "
          f"{job['pending']} chờ xử lý; {job['failed']} cần chạy lại; {job['state']}")
    emit_batch_result(result)
    return code


def emit_batch_result(result):
    """Send a machine-readable, single-line summary to the desktop app."""
    print(BATCH_RESULT_PREFIX + json.dumps(result, ensure_ascii=False, sort_keys=True))


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


def get_prompt_locator(page):
    if page.locator("#prompt-textarea").count() > 0:
        return page.locator("#prompt-textarea")
    elif page.locator('.ql-editor[contenteditable="true"]').count() > 0:
        return page.locator('.ql-editor[contenteditable="true"]').first
    elif page.locator('rich-textarea div[contenteditable="true"]').count() > 0:
        return page.locator('rich-textarea div[contenteditable="true"]').first
    elif page.locator('div[contenteditable="true"]').count() > 0:
        return page.locator('div[contenteditable="true"]').first
    else:
        return page.locator("#prompt-textarea")


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
            or "Enter a prompt" in text
            or "Nhập câu lệnh" in text
            or "Trò chuyện để cùng lên ý tưởng" in text
            or page.locator("#prompt-textarea").count() > 0
            or page.locator('.ql-editor[contenteditable="true"]').count() > 0
            or page.locator('rich-textarea').count() > 0
            or page.locator('div[contenteditable="true"]').count() > 0
        ):
            return True

        sleep(2)

    return False


def login_if_needed(page, service=SERVICE):
    url = "https://gemini.google.com/app" if service == "gemini" else "https://chatgpt.com/"
    page.goto(url, wait_until="domcontentloaded")
    wait_if_cloudflare(page)

    signin_selectors = (
        [
            '.sign-in-button',
            'a:has-text("Sign in")',
            'button:has-text("Sign in")',
            'a:has-text("Đăng nhập")',
            'button:has-text("Đăng nhập")',
            'a:has-text("Get started")',
            'button:has-text("Get started")',
            'a:has-text("Bắt đầu")',
            'button:has-text("Bắt đầu")',
        ]
        if service == "gemini"
        else [
            'a:has-text("Log in")',
            'button:has-text("Log in")',
            'a:has-text("Đăng nhập")',
            'button:has-text("Đăng nhập")',
        ]
    )
    has_signin = False
    for selector in signin_selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible():
                has_signin = True
                break
        except Exception:
            continue

    if wait_page_ready(page, 90) and not has_signin:
        print(f"✅ Đã vào được {service.upper()}.")
        return

    print("\nMANUAL_ACTION_REQUIRED")
    print(f"⚠️ Chưa đăng nhập {service.upper()}.")
    print("👉 Login thủ công trong cửa sổ trình duyệt.")
    print("👉 Khi thấy ô chat, quay lại app bấm 'Tiếp tục sau can thiệp'.")
    input("Chờ app gửi ENTER sau khi login xong... ")

    wait_if_cloudflare(page)
    if not wait_page_ready(page, 90):
        raise Exception(f"{service.upper()} chưa sẵn sàng sau khi đăng nhập.")


def reset_chat(page, service=SERVICE):
    print("→ Reset New chat")

    url = "https://gemini.google.com/app" if service == "gemini" else "https://chatgpt.com/"
    page.goto(url, wait_until="domcontentloaded")
    wait_if_cloudflare(page)

    if not wait_page_ready(page, 120):
        raise Exception(f"{service.upper()} chưa sẵn sàng.")

    try:
        if service == "gemini":
            page.locator('button[aria-label*="New chat" i], button[aria-label*="Trò chuyện mới" i], a[aria-label*="New chat" i], a[aria-label*="Trò chuyện mới" i]').first.click(timeout=4000)
        else:
            page.locator("text=New chat").first.click(timeout=4000)
    except Exception:
        pass

    sleep(4)
    wait_if_cloudflare(page)


def upload_image(page, img, service=SERVICE):
    if service == "gemini":
        try:
            input_el = page.locator('input[type="file"]').first
            if input_el.count() > 0:
                input_el.set_input_files(str(img), timeout=5000)
                print("✓ Upload bằng input[type=file] trực tiếp")
                sleep(6)
                return
        except Exception:
            pass

        plus_selectors = [
            'button[aria-label*="Nội dung tải lên" i]',
            'button[aria-label*="Uploads" i]',
            'button[aria-label*="Add files" i]',
            'button[aria-label*="Thêm" i]',
            'button:has(svg)'
        ]

        plus_clicked = False
        for sel in plus_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=3000, force=True)
                    plus_clicked = True
                    sleep(2)
                    break
            except Exception:
                continue

        if not plus_clicked:
            raise Exception("Không tìm thấy nút Plus (+) để mở menu tải lên của Gemini")

        sub_selectors = [
            'button:has-text("Lựa chọn tải lên khác")',
            'button:has-text("Other upload options")',
            'button[aria-label*="tải lên khác" i]',
            'button[aria-label*="upload options" i]'
        ]
        for sel in sub_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=3000, force=True)
                    sleep(2)
                    break
            except Exception:
                continue

        upload_btn_selectors = [
            'button[aria-label*="Tải tệp lên" i]',
            'button:has-text("Tải tệp lên")',
            'button[aria-label*="Upload file" i]',
            'button:has-text("Upload file")',
            'button:has-text("Upload files")',
            'button[aria-label*="Attach file" i]'
        ]

        for sel in upload_btn_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    with page.expect_file_chooser(timeout=8000) as fc_info:
                        btn.click(timeout=3000, force=True)
                    file_chooser = fc_info.value
                    file_chooser.set_files(str(img))
                    print(f"✓ Upload thành công qua {sel}")
                    sleep(6)
                    return
            except Exception:
                continue

        raise Exception("Không tìm thấy nút 'Tải tệp lên' để gửi ảnh lên Gemini")
    else:
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
                    const prompt = document.querySelector('#prompt-textarea') || 
                                   document.querySelector('.ql-editor[contenteditable="true"]') ||
                                   document.querySelector('rich-textarea div[contenteditable="true"]') ||
                                   document.querySelector('div[contenteditable="true"]');
                    if (!prompt) return false;

                    const roots = [];
                    const addRoot = (root) => {
                        if (root && !roots.includes(root)) roots.push(root);
                    };
                    let root = prompt.closest('form') || prompt.closest('.input-area-container') || prompt.parentElement;
                    addRoot(root);

                    for (let i = 0; i < 6 && root && root.parentElement; i++) {
                        root = root.parentElement;
                        const descriptor = [root.className, root.getAttribute('data-testid'), root.getAttribute('role')]
                            .filter(Boolean)
                            .join(' ')
                            .toLowerCase();
                        if (/(composer|input|prompt|upload|rich-textarea)/.test(descriptor)) {
                            addRoot(root);
                        }
                    }

                    return roots.some((candidateRoot) => Array.from(candidateRoot.querySelectorAll('img')).some(img => {
                        const src = img.getAttribute('src') || '';
                        const box = img.getBoundingClientRect();
                        const low = src.toLowerCase();
                        return box.width > 40 && box.height > 40 &&
                            !low.includes('avatar') &&
                            !low.includes('emoji') &&
                            !src.startsWith('data:image/svg');
                    }));
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
                    const el = document.querySelector('#prompt-textarea') || 
                               document.querySelector('.ql-editor[contenteditable="true"]') ||
                               document.querySelector('rich-textarea div[contenteditable="true"]') ||
                               document.querySelector('div[contenteditable="true"]');
                    if (!el) return false;

                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    const stopVisible = Array.from(document.querySelectorAll(
                        'button[data-testid="stop-button"], button[aria-label*="Stop" i], ' +
                        'button[aria-label*="Cancel" i], button[aria-label*="Dừng" i], ' +
                        'button[aria-label*="Hủy" i]'
                    )).some((button) => {
                        const buttonRect = button.getBoundingClientRect();
                        const buttonStyle = window.getComputedStyle(button);
                        return buttonRect.width > 0 && buttonRect.height > 0 &&
                            buttonStyle.visibility !== 'hidden' && buttonStyle.display !== 'none';
                    });

                    const disabled =
                        el.getAttribute('aria-disabled') === 'true' ||
                        el.getAttribute('disabled') !== null ||
                        style.pointerEvents === 'none' ||
                        style.visibility === 'hidden' ||
                        style.display === 'none';

                    return (
                        rect.width > 0 &&
                        rect.height > 0 &&
                        !stopVisible &&
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
    last_error = None
    start = time.time()

    while time.time() - start < timeout:
        wait_if_cloudflare(page)

        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass

        box = get_prompt_locator(page)

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
                    const el = document.querySelector('#prompt-textarea') || 
                               document.querySelector('.ql-editor[contenteditable="true"]') ||
                               document.querySelector('rich-textarea div[contenteditable="true"]') ||
                               document.querySelector('div[contenteditable="true"]');
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

    raise Exception(f"Không click/focus được prompt box: {last_error}")


def clear_prompt_box(page):
    box = get_prompt_locator(page)

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
                const el = document.querySelector('#prompt-textarea') || 
                           document.querySelector('.ql-editor[contenteditable="true"]') ||
                           document.querySelector('rich-textarea div[contenteditable="true"]') ||
                           document.querySelector('div[contenteditable="true"]');
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
    box = get_prompt_locator(page)

    try:
        box.fill(text, timeout=8000)
        sleep(0.5)
        return
    except Exception:
        pass

    try:
        page.evaluate("""
            (value) => {
                const el = document.querySelector('#prompt-textarea') || 
                           document.querySelector('.ql-editor[contenteditable="true"]') ||
                           document.querySelector('rich-textarea div[contenteditable="true"]') ||
                           document.querySelector('div[contenteditable="true"]');
                if (!el) throw new Error('Không thấy prompt box');

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
                const el = document.querySelector('#prompt-textarea') || 
                           document.querySelector('.ql-editor[contenteditable="true"]') ||
                           document.querySelector('rich-textarea div[contenteditable="true"]') ||
                           document.querySelector('div[contenteditable="true"]');
                if (!el) return '';
                return (el.innerText || el.textContent || '').trim();
            }
        """)
    except Exception:
        return ""


def is_generating(page):
    """
    Nhận diện ChatGPT hoặc Gemini đang xử lý.
    """
    try:
        stop_buttons = page.locator('button[data-testid="stop-button"], button[aria-label*="Stop" i], button[aria-label*="Cancel" i], button[aria-label*="Dừng" i], button[aria-label*="Hủy" i]')
        if stop_buttons.count() > 0:
            for i in range(stop_buttons.count()):
                btn = stop_buttons.nth(i)
                if btn.is_visible():
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
                        label.includes('dừng phản hồi') ||
                        label.includes('stop') ||
                        label.includes('cancel') ||
                        label.includes('hủy')
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
        'button[aria-label="Submit message"]',
        'button[aria-label*="Send" i]',
        'button[aria-label*="Gửi" i]',
        'button[aria-label*="Submit" i]',
        'button.send-button'
    ]

    for sel in selectors:
        try:
            btn = page.locator(sel).last
            if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
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
                    'button[aria-label="Submit message"]',
                    'button[aria-label*="Send" i]',
                    'button[aria-label*="Gửi" i]',
                    'button[aria-label*="Submit" i]',
                    'button.send-button'
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
                const isUserNode = (node) => Boolean(node.closest(
                    '[data-message-author-role="user"], [data-testid*="user" i], ' +
                    'user-query, .user-query, .user-message'
                ));
                let nodes = Array.from(document.querySelectorAll(
                    '[data-message-author-role="assistant"], [data-testid*="assistant" i], ' +
                    'message-content, .message-content, .model-response-text'
                )).filter((node) => !isUserNode(node));

                if (nodes.length === 0) {
                    nodes = Array.from(document.querySelectorAll('.markdown, .message-content')).filter((node) => {
                        const text = (node.innerText || node.textContent || '').trim();
                        return text.length > 0 && !isUserNode(node) &&
                            !node.closest('#prompt-textarea') &&
                            !node.closest('.input-area-container') &&
                            !node.closest('rich-textarea');
                    });
                }

                // A response wrapper and its message-content child can both match.
                // Keep the deepest matching node so one response is counted once.
                nodes = nodes.filter((node) => !nodes.some(
                    (other) => other !== node && node.contains(other)
                ));

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
        print("⚠ Không nhận được phản hồi mới; không coi bước này là thành công.")
        return False

    print("⏳ Chờ ChatGPT xử lý xong...")
    if not before_signature:
        print("⚠ Không có mốc phản hồi trước khi gửi prompt.")
        return False

    return wait_assistant_response_stable(
        page,
        before_signature,
        stable_seconds=6,
        timeout=timeout_done,
    )


def get_image_snapshot(page):
    """Inspect image results, including tool cards outside the assistant text node."""
    try:
        return page.evaluate("""
            () => {
                const prompt = document.querySelector('#prompt-textarea') || 
                               document.querySelector('.ql-editor[contenteditable="true"]') ||
                               document.querySelector('rich-textarea div[contenteditable="true"]') ||
                               document.querySelector('div[contenteditable="true"]');
                const composer = prompt ? (prompt.closest('form') || prompt.closest('.input-area-container') || prompt.parentElement) : null;
                const seen = new Set();
                const result = [];
                const ignored = {};
                const skip = (reason) => { ignored[reason] = (ignored[reason] || 0) + 1; };
                const userSelector = '[data-message-author-role="user"], [data-turn="user"], ' +
                    '[data-testid*="user" i], user-query, .user-query, .user-message';
                const assistantSelector = '[data-message-author-role="assistant"], [data-turn="assistant"], ' +
                    '[data-testid*="assistant" i], model-response, message-content, ' +
                    '.message-content, .model-response-text';

                for (const img of Array.from(document.querySelectorAll('img'))) {
                    if (composer && composer.contains(img)) { skip('composer'); continue; }
                    if (img.closest(userSelector)) { skip('user'); continue; }

                    // ChatGPT can render the image tool as a sibling of the assistant
                    // message. Scope the fallback to its conversation turn, never the
                    // whole page (which also contains uploads, avatars and history).
                    const turn = img.closest('[data-testid^="conversation-turn-"]');
                    if (turn && turn.querySelector(userSelector)) { skip('user'); continue; }
                    const message = img.closest(assistantSelector) || turn;
                    if (!message) { skip('outside_response'); continue; }

                    const src = img.currentSrc || img.getAttribute('src') || '';
                    if (!src) continue;

                    const low = src.toLowerCase();
                    const alt = (img.getAttribute('alt') || '').toLowerCase();
                    if (low.includes('avatar') || low.includes('emoji') || alt.includes('avatar')) { skip('icon'); continue; }
                    if (src.startsWith('data:image/svg')) { skip('icon'); continue; }

                    const box = img.getBoundingClientRect();
                    const naturalWidth = img.naturalWidth || 0;
                    const naturalHeight = img.naturalHeight || 0;
                    const style = window.getComputedStyle(img);
                    const visible = box.width >= 80 && box.height >= 80 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                    const fullyLoaded = img.complete && naturalWidth >= 80 && naturalHeight >= 80;

                    if (seen.has(src)) continue;

                    seen.add(src);
                    result.push({src, ready: visible && fullyLoaded});
                    if (!visible || !fullyLoaded) skip('not_ready');
                }

                return {images: result, ignored};
            }
        """)
    except Exception as exc:
        return {"images": [], "ignored": {}, "error": str(exc).splitlines()[0]}


def get_all_image_srcs(page, include_pending=False):
    return [
        image["src"] for image in get_image_snapshot(page)["images"]
        if include_pending or image["ready"]
    ]


def log_image_detection(page):
    snapshot = get_image_snapshot(page)
    ready = sum(image["ready"] for image in snapshot["images"])
    print(f"  ↳ Nhận diện ảnh: {ready} đã tải xong / {len(snapshot['images'])} trong phản hồi; "
          f"bỏ qua: {snapshot['ignored']}")
    if snapshot.get("error"):
        print(f"  ↳ Lỗi đọc ảnh trên trang: {snapshot['error']}")


def get_latest_new_image(page, old_list):
    current = get_all_image_srcs(page)
    new_imgs = [x for x in current if x not in old_list]
    return new_imgs[-1] if new_imgs else None


def find_image_locator(page, expected_src):
    images = page.locator("img")
    for index in range(images.count()):
        candidate = images.nth(index)
        try:
            src = candidate.evaluate("img => img.currentSrc || img.getAttribute('src') || ''")
            if src == expected_src:
                return candidate
        except Exception:
            continue
    return None


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


def wait_image_generation_finished_or_image_ready(page, old_imgs, timeout=IMAGE_WAIT_TIMEOUT):
    """
    Chờ riêng cho bước tạo ảnh theo kiểu KHÓA CỨNG.

    Nguyên tắc mới:
    - Sau khi đã gửi prompt tạo ảnh thì KHÔNG retry sớm.
    - Không dựa vào việc mất nút Stop để kết luận fail.
    - Không dựa vào idle tạm thời để retry.
    - Chỉ thoát khi:
        1. Có ảnh mới;
        2. Có lỗi rõ ràng trên màn hình và đã chờ thêm đủ lâu;
        3. Hết timeout dài IMAGE_WAIT_TIMEOUT.
    """
    start = time.time()
    last_log = 0
    first_clear_error_time = None
    candidate_url = None
    candidate_idle_since = None

    while time.time() - start < timeout:
        wait_if_cloudflare(page)

        img_url = get_latest_new_image(page, old_imgs)
        generating = is_generating(page)
        if img_url != candidate_url:
            candidate_url = img_url
            candidate_idle_since = None

        if candidate_url and not generating:
            if candidate_idle_since is None:
                candidate_idle_since = time.time()
                print("✓ Có ảnh mới, chờ xác nhận ảnh hoàn tất...")
            elif time.time() - candidate_idle_since >= 5:
                print("✓ Ảnh mới đã ổn định")
                return candidate_url
        elif generating:
            candidate_idle_since = None

        elapsed = int(time.time() - start)

        if has_clear_generation_error(page):
            if first_clear_error_time is None:
                first_clear_error_time = time.time()
                print("⚠ Phát hiện thông báo lỗi tạo ảnh, chờ thêm để chắc chắn...")

            # Có lỗi rõ ràng thì vẫn chờ thêm 90 giây, vì đôi khi ảnh vẫn ra muộn.
            if time.time() - first_clear_error_time >= 90:
                if candidate_url and not is_generating(page):
                    print("✓ Ảnh mới đã hoàn tất sau cảnh báo lỗi")
                    return candidate_url
                print("⚠ Lỗi tạo ảnh rõ ràng và không có ảnh sau khi chờ thêm")
                return None
        else:
            first_clear_error_time = None

        # Log định kỳ, không kết luận fail khi idle.
        if time.time() - last_log >= 30:
            state = "đang xử lý" if generating else "chưa có tín hiệu xử lý rõ, vẫn tiếp tục chờ"
            print(f"  ⏳ Chờ ảnh mới... {elapsed}s | trạng thái: {state}")
            if not generating and not candidate_url:
                log_image_detection(page)
            last_log = time.time()

        sleep(10)

    print("⚠ Hết timeout dài nhưng chưa thấy ảnh mới")
    return None


def try_create_image(page, old_imgs):
    for attempt in range(1, MAX_RETRY_IMAGE + 1):
        print(f"→ Tạo ảnh lần {attempt}")

        before_send_imgs = get_all_image_srcs(page, include_pending=True)
        merged_old_imgs = list(dict.fromkeys(old_imgs + before_send_imgs))

        send_prompt(page, PROMPT_TAO_ANH, max_send_attempts=1)

        # Chỉ chờ phản hồi bắt đầu, không dùng hàm timeout ngắn 180 giây để kết luận fail.
        # Sau đó chuyển sang hàm chờ ảnh riêng bên dưới.
        started = False
        start = time.time()
        print("⏳ Chờ ChatGPT bắt đầu tạo ảnh...")
        while time.time() - start < 120:
            wait_if_cloudflare(page)
            if is_generating(page):
                started = True
                break
            if get_latest_new_image(page, merged_old_imgs):
                started = True
                break
            sleep(2)

        if not started:
            current_text = get_prompt_text(page)
            if PROMPT_TAO_ANH in current_text:
                raise Exception("Prompt tạo ảnh vẫn còn trong ô nhập sau khi gửi; dừng để tránh gửi trùng.")

        img_url = wait_image_generation_finished_or_image_ready(
            page,
            merged_old_imgs,
            timeout=IMAGE_WAIT_TIMEOUT
        )

        if img_url:
            return img_url

        # Trước khi retry lần sau, chờ chắc chắn ChatGPT đã thật sự dừng.
        print("⚠ Chưa lấy được ảnh → chuẩn bị retry, chờ ChatGPT idle chắc chắn")
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


def find_gemini_viewer_download_button(page):
    overlay = page.locator(".cdk-overlay-container, [role='dialog']").last
    overlay.wait_for(state="visible", timeout=10000)
    print("✓ Viewer Gemini đã mở")
    print("→ Tìm nút download trong overlay viewer")

    # 1. Try direct selectors
    selectors = [
        'button[aria-label*="Tải ảnh có kích thước đầy đủ xuống" i]',
        'button[aria-label*="Tải xuống" i]',
        'button[aria-label*="Download" i]',
        'button[title*="Tải ảnh có kích thước đầy đủ xuống" i]',
        'button[title*="Download" i]',
    ]

    print("→ Thử selector aria-label/title download")
    for sel in selectors:
        btn = overlay.locator(sel)
        if btn.count() > 0:
            for idx in range(btn.count()):
                candidate = btn.nth(idx)
                if candidate.is_visible() and candidate.is_enabled():
                    return candidate

    # 2. Try tooltip verification by hovering
    print("→ Thử tooltip “Tải ảnh có kích thước đầy đủ xuống”")
    buttons = overlay.locator('button')
    btn_count = buttons.count()
    for idx in range(btn_count):
        btn = buttons.nth(idx)
        if btn.is_visible() and btn.is_enabled():
            try:
                btn.hover()
                sleep(0.5)
                tooltip_loc = page.locator('.mat-tooltip, .tooltip, [role="tooltip"], .cdk-overlay-container')
                tooltip_text = ""
                for t_idx in range(tooltip_loc.count()):
                    t_el = tooltip_loc.nth(t_idx)
                    if t_el.is_visible():
                        tooltip_text += (t_el.inner_text() or "") + " "
                
                low_text = tooltip_text.lower()
                if any(w in low_text for w in ["tải ảnh có kích thước đầy đủ xuống", "tải xuống", "download full-size", "download"]):
                    if not any(w in low_text for w in ["chia sẻ", "share", "sao chép", "copy", "đóng", "close"]):
                        return btn
            except Exception:
                pass

    # 3. Fallback by position (excluding other buttons)
    print("→ Thử fallback theo vị trí toolbar")
    candidates = []
    for idx in range(btn_count):
        btn = buttons.nth(idx)
        if btn.is_visible() and btn.is_enabled():
            lbl = (btn.get_attribute("aria-label") or "").lower()
            title = (btn.get_attribute("title") or "").lower()
            
            exclude_keywords = [
                "share", "chia sẻ",
                "copy", "sao chép",
                "undo", "hoàn tác",
                "redo", "làm lại",
                "save", "lưu",
                "close", "đóng", "x"
            ]
            
            is_excluded = False
            for kw in exclude_keywords:
                if kw in lbl or kw in title:
                    is_excluded = True
                    break
                    
            if not is_excluded:
                candidates.append(btn)

    if candidates:
        return candidates[-1]

    return None


def download_gemini_fullsize_image(page, output_path, expected_image_src):
    print("→ Tải ảnh full-size từ Gemini")
    
    for attempt in range(1, 4):
        print(f"→ Thử tải ảnh full-size lần {attempt}")
        try:
            viewer_open = False
            try:
                overlay = page.locator(".cdk-overlay-container, [role='dialog']").last
                if overlay.count() > 0 and overlay.is_visible():
                    viewer_open = True
            except Exception:
                pass

            if not viewer_open:
                print("→ Mở đúng ảnh kết quả để tải")
                image = find_image_locator(page, expected_image_src)
                if image:
                    image.scroll_into_view_if_needed()
                    image.hover()
                    sleep(1)
                    image.click(force=True)
                    sleep(2)
                else:
                    raise Exception("Không tìm thấy đúng ảnh kết quả cần tải trên trang")

            btn = find_gemini_viewer_download_button(page)
            
            if btn:
                print("→ Bấm nút download full-size trong toolbar")
                with page.expect_download(timeout=60000) as download_info:
                    btn.click(force=True)
                
                download = download_info.value
                download.save_as(output_path)
                
                sleep(1.5)
                try:
                    toast_visible = page.locator('text="Đang tải hình ảnh có kích thước đầy đủ xuống", text="Downloading full-size image", text*="kích thước đầy đủ", text*="full-size image"').count() > 0
                    if toast_visible:
                        print("✓ Gemini xác nhận đang tải ảnh full-size")
                except Exception:
                    pass
                    
                if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                    print(f"✓ Đã lưu ảnh full-size: {output_path}")
                    try:
                        page.keyboard.press("Escape")
                        sleep(1)
                    except Exception:
                        pass
                    return True
            else:
                print(f"⚠ Viewer đã mở nhưng chưa tìm thấy nút download trong overlay lần {attempt}")
                sleep(2)
        except Exception as e:
            print(f"⚠ Lỗi ở lần thử {attempt}: {e}")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            sleep(2)
            
    print("⚠ Không tải được ảnh full-size, fallback screenshot preview chất lượng thấp")
    try:
        image = find_image_locator(page, expected_image_src)
        if image:
            image.scroll_into_view_if_needed()
            image.wait_for(state="visible", timeout=15000)
            image.screenshot(path=output_path)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                print(f"✓ Đã lưu ảnh: {output_path}")
                return True
    except Exception as e:
        print(f"  ↳ Fallback screenshot thất bại: {e}")
        
    raise Exception("Không tải được ảnh sau tất cả các phương thức kể cả fallback screenshot")


def download_gemini_image(page, path, expected_image_src):
    return download_gemini_fullsize_image(page, path, expected_image_src)


def is_valid_image_file(path):
    try:
        with Image.open(path) as img:
            if min(img.size) < 80:
                return False
            img.verify()
        return True
    except (OSError, ValueError, SyntaxError):
        return False


def normalize_image_bytes(data):
    """Reject HTML/error responses and encode the actual PNG promised by the filename."""
    try:
        with Image.open(BytesIO(data)) as img:
            img.load()
            if min(img.size) < 80:
                raise ValueError("Ảnh tải về nhỏ hơn 80 × 80 pixel")
            output = BytesIO()
            img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB").save(output, format="PNG")
            return output.getvalue()
    except (OSError, ValueError, SyntaxError) as exc:
        raise ValueError(f"Dữ liệu tải về không phải ảnh kết quả hợp lệ: {exc}") from exc


def fetch_image_in_browser(page, url):
    encoded = page.evaluate("""
        async (u) => {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 45000);
            try {
                const response = await fetch(u, {credentials: 'include', signal: controller.signal});
                if (!response.ok) throw new Error('HTTP ' + response.status);
                const blob = await response.blob();
                return await new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onload = () => resolve(reader.result.split(',')[1]);
                    reader.onerror = () => reject(new Error('Không đọc được dữ liệu ảnh'));
                    reader.readAsDataURL(blob);
                });
            } finally { clearTimeout(timer); }
        }
    """, url)
    return base64.b64decode(encoded, validate=True)


def fetch_image_with_session(page, url):
    # The request context shares browser cookies and is not restricted by page CORS.
    response = page.context.request.get(url, headers={"Referer": page.url}, timeout=45000)
    try:
        if not response.ok:
            raise ValueError(f"HTTP {response.status}")
        return response.body()
    finally:
        response.dispose()


def read_loaded_image(page, url):
    image = find_image_locator(page, url)
    if image is None:
        raise ValueError("Ảnh kết quả không còn trên trang")
    encoded = image.evaluate("""
        (img) => {
            if (!img.complete || img.naturalWidth < 80 || img.naturalHeight < 80)
                throw new Error('Ảnh chưa tải xong');
            const canvas = document.createElement('canvas');
            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;
            canvas.getContext('2d').drawImage(img, 0, 0);
            return canvas.toDataURL('image/png').split(',')[1];
        }
    """)
    return base64.b64decode(encoded, validate=True)


def download_image(page, url, path):
    print(f"→ Tải ảnh vào: {path}")
    methods = [("trình duyệt", lambda: fetch_image_in_browser(page, url))]
    if url.startswith(("https://", "http://")):
        methods.append(("phiên đăng nhập", lambda: fetch_image_with_session(page, url)))
    methods.append(("ảnh đã tải trên trang", lambda: read_loaded_image(page, url)))
    errors = []

    for label, fetch in methods:
        try:
            data = normalize_image_bytes(fetch())
        except Exception as exc:
            # Do not print signed image URLs or entire browser/network error stacks.
            errors.append(f"{label}: {type(exc).__name__}")
            print(f"⚠ Không lấy được ảnh qua {label} ({type(exc).__name__}), thử cách tiếp theo")
            continue

        destination = Path(path)
        temp_path = destination.with_name(destination.name + ".part")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_bytes(data)
            os.replace(temp_path, destination)
        except OSError as exc:
            raise OSError(f"Không lưu được ảnh vào {destination}: {exc}") from exc
        finally:
            temp_path.unlink(missing_ok=True)
        print(f"✓ Đã lưu ảnh: {destination.resolve()} ({len(data):,} byte)")
        return

    raise RuntimeError("Không tải được ảnh kết quả qua các cách: " + "; ".join(errors))


def process_one(page, image_indices, img):
    index = image_indices[img]
    save_name = get_output_name(img)
    save_path = os.path.join(DOWNLOAD_FOLDER, save_name)

    print(f"\n--- {index}: {img.name} → {save_name} ---")

    reset_chat(page)
    upload_image(page, img)
    wait_upload_attached(page, timeout=90)

    if not run_dich_step(page):
        raise Exception("Bước Dịch quá thời gian chờ sau nhiều lần thử")

    sleep(5)

    old_imgs = get_all_image_srcs(page)

    img_url = try_create_image(page, old_imgs)

    if not img_url:
        raise Exception("Không tạo được ảnh sau nhiều lần thử")

    if SERVICE == "gemini":
        download_gemini_image(page, save_path, img_url)
    else:
        download_image(page, img_url, save_path)

    if is_valid_image_file(save_path):
        print("✓ DONE")
        write_progress(index, img.name, save_name, "done", "OK")
    else:
        raise Exception(f"File ảnh tải về không hợp lệ: {save_path}")


def main():
    ensure_dirs()
    init_progress()

    all_images = get_images()
    if RUN_MODE == "force" and not START_FROM:
        raise ValueError("Chế độ chạy lại một ảnh yêu cầu giá trị 'Bắt đầu từ ảnh'.")

    images = apply_start_from(all_images, require_single_match=(RUN_MODE == "force"))
    image_indices = {img: index + 1 for index, img in enumerate(all_images)}

    batch = get_next_batch(images)
    batch_result = {
        "mode": RUN_MODE,
        "requested_batch_size": BATCH_SIZE,
        "selected_count": len(batch),
        "completed_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "next_pending_count": 0,
        "files": [img.name for img in batch],
        "pending_before": get_job_state(images)["pending"],
    }

    print(f"📁 Ảnh gốc: {IMAGE_FOLDER}")
    print(f"📁 Ảnh VN: {DOWNLOAD_FOLDER}")
    print(f"📄 Log: {PROGRESS_FILE}")
    print(f"🔢 Tổng ảnh sau điểm bắt đầu: {len(images)}")
    print(f"🚀 Mỗi lần xử lý: {BATCH_SIZE} ảnh")
    print(f"📌 Batch lần này: {len(batch)} ảnh")
    print(f"🔁 Chế độ chạy: {RUN_MODE}")

    if START_FROM:
        print(f"▶ Bắt đầu từ: {START_FROM}")

    if not batch:
        return finish_batch_result(batch_result, images)

    try:
        with sync_playwright() as p:
            context = None
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=PROFILE_DIR,
                    headless=False,
                    accept_downloads=True,
                    args=[
                        "--disable-blink-features=AutomationControlled"
                    ],
                    viewport={"width": 1400, "height": 900}
                )

                page = context.pages[0] if context.pages else context.new_page()

                minimize_own_browser(context)
                login_if_needed(page)

                for position, img in enumerate(batch):
                    try:
                        index = image_indices[img]
                        save_name = get_output_name(img)
                        process_one(page, image_indices, img)
                        batch_result["success_count"] += 1

                    except Exception as e:
                        index = image_indices.get(img, 0)
                        try:
                            save_name = get_output_name(img)
                        except Exception:
                            save_name = img.stem + "_VN.png"
                        print(f"✗ Lỗi: {e}")
                        write_progress(index, img.name, save_name, "fail", str(e))
                        batch_result["failure_count"] += 1
                    finally:
                        batch_result["completed_count"] += 1

                    # The final image does not need a cooldown before the app
                    # evaluates whether to schedule the next batch.
                    if position < len(batch) - 1:
                        print(f"⏸ Nghỉ {WAIT_AFTER_EACH_IMAGE} giây")
                        sleep(WAIT_AFTER_EACH_IMAGE)
            finally:
                if context is not None:
                    context.close()
    except Exception as e:
        batch_result["fatal_error"] = str(e)
        raise
    return finish_batch_result(batch_result, images)


if __name__ == "__main__":
    sys.exit(main())
