import os
import sys
import subprocess
import ctypes
import time
import re
import uuid
from pathlib import Path


def select_launch_mode(argv=None, platform=None):
    """Select the process role before importing either desktop shell."""
    argv = list(sys.argv if argv is None else argv)
    platform = sys.platform if platform is None else platform
    if "--worker" in argv:
        return "worker"
    if "--self-test" in argv:
        return "self-test"
    if platform == "win32" and "--tk" not in argv:
        return "web"
    return "tk"


def try_web_shell(run_webview, startup_error, error_stream=None):
    """Run the web shell, returning False only for a startup-safe fallback."""
    try:
        run_webview()
    except startup_error as exc:
        stream = sys.stderr if error_stream is None else error_stream
        if stream is not None:
            print(f"Web shell failed to start; falling back to Tk shell: {exc}", file=stream)
        return False
    return True


_LAUNCH_MODE = select_launch_mode() if __name__ == "__main__" else None
if _LAUNCH_MODE == "self-test":
    from desktop.webview_app import run_self_test

    raise SystemExit(run_self_test())
if _LAUNCH_MODE == "web":
    from desktop.webview_app import WebShellStartupError, run_webview

    if try_web_shell(run_webview, WebShellStartupError):
        raise SystemExit(0)


import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog, messagebox
from tkinter import font as tkfont

from desktop_controller import (
    ACCOUNT_EVENT_PREFIX,
    BATCH_RESULT_PREFIX,
    DesktopController,
    Scheduler,
)
from desktop.runtime import (
    build_process_launch,
    get_active_chatgpt_account as get_active_account_from_settings,
    load_settings as load_settings_file,
    normalize_chatgpt_accounts as normalize_accounts,
    save_settings as save_settings_file,
)
from desktop.window_identity import set_windows_app_user_model_id

try:
    import winreg
except ImportError:
    winreg = None


def get_app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = get_app_dir()
SCRIPT_FILE = APP_DIR / "run_chatgpt_batch.py"
def get_resource_path(*parts):
    """Resolve bundled read-only assets in source and PyInstaller builds."""
    bundle_dir = Path(getattr(sys, "_MEIPASS", APP_DIR))
    return bundle_dir.joinpath(*parts)


APP_ICON_FILE = get_resource_path("assets", "app-icon.png")
APP_ICON_ICO_FILE = get_resource_path("assets", "app-icon.ico")


def get_data_dir():
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ChatGPT Batch Translator"
    return APP_DIR


DATA_DIR = get_data_dir()
SETTINGS_FILE = DATA_DIR / "app_settings.json"

DEFAULT_SETTINGS = {
    "image_folder": str(DATA_DIR / "images"),
    "download_folder": str(DATA_DIR / "images_vn"),
    "profile_dir": str(DATA_DIR / "chatgpt_auto_profile"),
    "gemini_profile_dir": str(DATA_DIR / "gemini_auto_profile"),
    "chatgpt_accounts": [
        {
            "id": "default",
            "name": "ChatGPT 1",
            "profile_dir": str(DATA_DIR / "chatgpt_auto_profile")
        }
    ],
    "active_chatgpt_account_id": "default",
    "auto_account_fallback_enabled": True,
    "batch_size": "10",
    "start_from": "",
    "auto_next_enabled": True,
    "auto_next_delay_minutes": "2",
    "theme": "system",
    "language": "vi",
    "service": "chatgpt"
}


def copy_default_settings():
    """Return settings with independent account metadata for each app instance."""
    return {
        **DEFAULT_SETTINGS,
        "chatgpt_accounts": [dict(account) for account in DEFAULT_SETTINGS["chatgpt_accounts"]],
    }


LANGUAGE_OPTIONS = {
    "vi": "Tiếng Việt",
    "en": "English"
}

THEME_OPTIONS = {
    "vi": {
        "system": "Theo hệ thống",
        "light": "Sáng",
        "dark": "Tối"
    },
    "en": {
        "system": "System",
        "light": "Light",
        "dark": "Dark"
    }
}

TEXT = {
    "vi": {
        "language": "Ngôn ngữ",
        "theme": "Giao diện",
        "sidebar_title": "Dịch sách tự động",
        "sidebar_desc": "Upload ảnh, dịch nội dung, tạo ảnh Việt hóa và quản lý batch.",
        "status_label": "Trạng thái",
        "status_ready": "Sẵn sàng",
        "progress_label": "Tiến trình",
        "progress_zero": "Tiến trình: 0%",
        "quick_actions": "Thao tác nhanh",
        "actions": "Thao tác",
        "open_output": "Mở kết quả",
        "export_log": "Xuất log",
        "copy_log": "Copy log",
        "save_config": "Lưu cấu hình",
        "clear_log": "Xóa log",
        "dashboard": "Bảng điều khiển",
        "dashboard_desc": "Chạy batch ổn định, theo dõi tiến trình và can thiệp thủ công khi ChatGPT yêu cầu.",
        "data_config": "Cấu hình nguồn dữ liệu",
        "data_hint": "Giữ profile trình duyệt riêng để hạn chế đăng nhập lại và không đưa thư mục này lên GitHub.",
        "source_folder": "Thư mục ảnh gốc",
        "output_folder": "Thư mục lưu ảnh VN",
        "profile": "Profile trình duyệt",
        "chatgpt_account": "Tài khoản ChatGPT",
        "chatgpt_account_hint": "Mỗi tài khoản dùng profile riêng; phiên đăng nhập không bị chia sẻ.",
        "account_add": "Thêm",
        "account_rename": "Đổi tên",
        "account_remove": "Bỏ khỏi DS",
        "account_login": "Đăng nhập",
        "account_name_title": "Tài khoản ChatGPT",
        "account_name_prompt": "Tên gợi nhớ (ví dụ: Business 2):",
        "account_name_required": "Hãy nhập tên cho tài khoản.",
        "account_name_exists": "Tên tài khoản này đã có. Hãy chọn tên khác.",
        "account_added": "Đã chọn \"{name}\". Bấm \"Đăng nhập\" để mở phiên mới.",
        "account_selected": "Đã chuyển sang profile \"{name}\". Lần chạy sau sẽ dùng tài khoản này.",
        "account_renamed": "Đã đổi tên thành \"{name}\".",
        "account_remove_title": "Bỏ tài khoản",
        "account_remove_message": "Bỏ \"{name}\" khỏi danh sách? Thư mục profile và phiên đăng nhập sẽ không bị xóa.",
        "account_removed": "Đã bỏ \"{name}\" khỏi danh sách.",
        "account_last": "Cần giữ ít nhất một tài khoản ChatGPT trong danh sách.",
        "account_change_running": "Hãy dừng batch hiện tại trước khi đổi hoặc quản lý tài khoản.",
        "account_login_hint": "Mở trình duyệt để đăng nhập hoặc làm mới phiên của tài khoản đang chọn.",
        "account_fallback": "Tự chuyển tài khoản khi hết lượt tạo ảnh",
        "account_fallback_hint": "Chạy lại ảnh đang dở bằng profile ChatGPT kế tiếp đã đăng nhập.",
        "account_quota_log": "⚠ {name} đã hết lượt tạo ảnh. Đang tìm tài khoản tiếp theo...",
        "account_switched_log": "🔁 Đã chuyển sang {name}; đang chạy lại ảnh {image}.",
        "account_skipped_log": "↷ Bỏ qua {name}: {reason}.",
        "account_waiting_log": "⏸ Tạm dừng: {reason}. Ảnh đang dở: {image}.",
        "account_fallback_off_log": "⏸ Tạm dừng vì tự chuyển tài khoản đang tắt. Ảnh đang dở: {image}.",
        "account_waiting_status": "Đang chờ tài khoản ChatGPT khả dụng...",
        "login_ready": "Phiên ChatGPT đã sẵn sàng.",
        "login_ready_log": "=== PHIÊN CHATGPT ĐÃ SẴN SÀNG ===",
        "service": "Dịch vụ",
        "service_chatgpt": "ChatGPT",
        "service_gemini": "Google Gemini",
        "batch_size": "Số ảnh mỗi lần",
        "auto_next": "Tự chạy batch tiếp theo",
        "auto_next_delay": "Chờ (phút)",
        "auto_next_hint": "Chỉ tự chạy tiếp khi batch chính đủ ảnh và đều thành công.",
        "invalid_auto_next_delay": "Thời gian chờ tự chạy phải là số dương.",
        "auto_countdown": "Batch hoàn tất. Chạy batch tiếp theo sau {time}.",
        "auto_run_now": "Chạy ngay",
        "auto_cancel": "Hủy tự chạy",
        "auto_cancelled": "Đã hủy tự chạy batch tiếp theo.",
        "auto_scheduled_log": "=== Batch đủ {count} ảnh thành công. Tự chạy batch tiếp theo sau {seconds} giây. ===",
        "auto_running_log": "=== Đang tự chạy batch tiếp theo ===",
        "auto_skip_failed": "=== Không tự chạy: batch vừa xong có ảnh lỗi hoặc thiếu ảnh thành công. ===",
        "auto_skip_incomplete": "=== Không tự chạy: batch vừa xong chưa đủ {count} ảnh. ===",
        "auto_skip_intervened": "=== Không tự chạy: đã có can thiệp thủ công trong lần chạy này. ===",
        "auto_skip_process_error": "=== Không tự chạy: worker kết thúc với mã {code}. ===",
        "auto_recover_after_worker_exit": "=== Worker kết thúc với mã {code} sau khi đã báo batch thành công đầy đủ; vẫn tự chạy tiếp an toàn. ===",
        "auto_skip_no_more": "=== Không tự chạy: không còn ảnh đủ điều kiện để chạy tiếp. ===",
        "auto_skip_missing_result": "=== Không tự chạy: không nhận được kết quả batch đầy đủ từ worker. ===",
        "batch_result_log": "=== Kết quả batch: {success}/{selected} thành công, {failed} lỗi. ===",
        "start_from": "Bắt đầu từ ảnh",
        "start_hint": "Ví dụ: 66, 122, 66_122 hoặc 66_122.jpg",
        "new_batch": "Chạy batch mới",
        "retry_failed": "Chạy lại ảnh lỗi",
        "rerun_image": "Chạy lại ảnh này",
        "continue_manual": "Tiếp tục sau can thiệp",
        "stop": "Dừng",
        "process_log": "Nhật ký xử lý",
        "choose": "Chọn",
        "saved_config": "Đã lưu cấu hình.",
        "running_title": "Đang chạy",
        "running_message": "Batch đang chạy.",
        "missing_image_title": "Thiếu số ảnh",
        "missing_image_message": "Nhập số ảnh cần chạy lại vào ô 'Bắt đầu từ ảnh' trước.",
        "invalid_batch_size": "Số ảnh mỗi lần phải là số nguyên dương.",
        "error_title": "Lỗi",
        "file_missing": "Không thấy file:\n{path}",
        "log_start": "=== BẮT ĐẦU CHẠY: {mode} ===",
        "status_running": "Đang chạy...",
        "log_read_error": "[LỖI ĐỌC LOG] {error}",
        "process_done": "Đã dừng / hoàn tất",
        "manual_wait": "Đang chờ bạn can thiệp trong trình duyệt...",
        "progress_count": "Tiến trình: {done}/{total} ảnh",
        "progress_percent": "Tiến trình: {done}/{total} ảnh ({percent:.0f}%)",
        "continue_sent": "Đã gửi lệnh tiếp tục...",
        "log_continue_sent": "=== ĐÃ GỬI LỆNH TIẾP TỤC ===",
        "continue_error": "Không gửi được lệnh tiếp tục:\n{error}",
        "stopped": "Đã dừng",
        "log_stopped": "=== ĐÃ DỪNG VÀ KILL SẠCH PROCESS CON ===",
        "no_process": "Không có tiến trình đang chạy",
        "no_log": "Nhật ký đang trống.",
        "exported_log": "=== Đã xuất log: {path} ===",
        "exported_log_message": "Đã xuất log vào:\n{path}",
        "copy_log_message": "Đã copy log vào clipboard.",
        "log_action_error": "Không thể {action}:\n{error}"
    },
    "en": {
        "language": "Language",
        "theme": "Theme",
        "sidebar_title": "Automatic book translation",
        "sidebar_desc": "Upload images, translate content, generate localized images, and manage batches.",
        "status_label": "Status",
        "status_ready": "Ready",
        "progress_label": "Progress",
        "progress_zero": "Progress: 0%",
        "quick_actions": "Quick actions",
        "actions": "Actions",
        "open_output": "Open output",
        "export_log": "Export log",
        "copy_log": "Copy log",
        "save_config": "Save settings",
        "clear_log": "Clear log",
        "dashboard": "Dashboard",
        "dashboard_desc": "Run stable batches, monitor progress, and step in manually when ChatGPT asks.",
        "data_config": "Data source settings",
        "data_hint": "Keep a separate browser profile to reduce sign-ins, and do not commit this folder to GitHub.",
        "source_folder": "Source image folder",
        "output_folder": "VN output folder",
        "profile": "Browser profile",
        "chatgpt_account": "ChatGPT account",
        "chatgpt_account_hint": "Each account uses a separate profile; signed-in sessions are never shared.",
        "account_add": "Add",
        "account_rename": "Rename",
        "account_remove": "Remove",
        "account_login": "Sign in",
        "account_name_title": "ChatGPT account",
        "account_name_prompt": "A memorable name (for example: Business 2):",
        "account_name_required": "Enter a name for this account.",
        "account_name_exists": "That account name already exists. Choose another name.",
        "account_added": "Selected \"{name}\". Click \"Sign in\" to open its new session.",
        "account_selected": "Switched to the \"{name}\" profile. The next run will use this account.",
        "account_renamed": "Renamed the account to \"{name}\".",
        "account_remove_title": "Remove account",
        "account_remove_message": "Remove \"{name}\" from the list? Its profile folder and signed-in session will not be deleted.",
        "account_removed": "Removed \"{name}\" from the list.",
        "account_last": "Keep at least one ChatGPT account in the list.",
        "account_change_running": "Stop the current batch before switching or managing accounts.",
        "account_login_hint": "Open the browser to sign in or refresh the selected account session.",
        "account_fallback": "Automatically switch when image quota is exhausted",
        "account_fallback_hint": "Retry the unfinished image with the next signed-in ChatGPT profile.",
        "account_quota_log": "⚠ {name} has exhausted its image quota. Looking for the next account...",
        "account_switched_log": "🔁 Switched to {name}; retrying image {image}.",
        "account_skipped_log": "↷ Skipping {name}: {reason}.",
        "account_waiting_log": "⏸ Paused: {reason}. Unfinished image: {image}.",
        "account_fallback_off_log": "⏸ Paused because automatic account switching is off. Unfinished image: {image}.",
        "account_waiting_status": "Waiting for an available ChatGPT account...",
        "login_ready": "The ChatGPT session is ready.",
        "login_ready_log": "=== CHATGPT SESSION IS READY ===",
        "service": "Service",
        "service_chatgpt": "ChatGPT",
        "service_gemini": "Google Gemini",
        "batch_size": "Images per batch",
        "auto_next": "Automatically run next batch",
        "auto_next_delay": "Wait (minutes)",
        "auto_next_hint": "Continue only when a full main batch succeeds.",
        "invalid_auto_next_delay": "The automatic-run delay must be a positive number.",
        "auto_countdown": "Batch completed. The next batch starts in {time}.",
        "auto_run_now": "Run now",
        "auto_cancel": "Cancel auto-run",
        "auto_cancelled": "Automatic next batch cancelled.",
        "auto_scheduled_log": "=== A full batch of {count} images succeeded. The next batch starts in {seconds} seconds. ===",
        "auto_running_log": "=== Automatically starting the next batch ===",
        "auto_skip_failed": "=== Not auto-running: the completed batch has failed or incomplete images. ===",
        "auto_skip_incomplete": "=== Not auto-running: the completed batch has fewer than {count} images. ===",
        "auto_skip_intervened": "=== Not auto-running: this run had manual intervention. ===",
        "auto_skip_process_error": "=== Not auto-running: the worker exited with code {code}. ===",
        "auto_recover_after_worker_exit": "=== The worker exited with code {code} after reporting a complete successful batch; safely continuing automatically. ===",
        "auto_skip_no_more": "=== Not auto-running: no eligible images remain. ===",
        "auto_skip_missing_result": "=== Not auto-running: the worker did not return a complete batch result. ===",
        "batch_result_log": "=== Batch result: {success}/{selected} succeeded, {failed} failed. ===",
        "start_from": "Start from image",
        "start_hint": "Examples: 66, 122, 66_122, or 66_122.jpg",
        "new_batch": "Run new batch",
        "retry_failed": "Retry failed images",
        "rerun_image": "Rerun this image",
        "continue_manual": "Continue after manual step",
        "stop": "Stop",
        "process_log": "Process log",
        "choose": "Browse",
        "saved_config": "Settings saved.",
        "running_title": "Running",
        "running_message": "A batch is already running.",
        "missing_image_title": "Missing image number",
        "missing_image_message": "Enter the image number to rerun in the 'Start from image' field first.",
        "invalid_batch_size": "Images per batch must be a positive whole number.",
        "error_title": "Error",
        "file_missing": "File not found:\n{path}",
        "log_start": "=== STARTING RUN: {mode} ===",
        "status_running": "Running...",
        "log_read_error": "[LOG READ ERROR] {error}",
        "process_done": "Stopped / completed",
        "manual_wait": "Waiting for your manual action in the browser...",
        "progress_count": "Progress: {done}/{total} images",
        "progress_percent": "Progress: {done}/{total} images ({percent:.0f}%)",
        "continue_sent": "Continue command sent...",
        "log_continue_sent": "=== CONTINUE COMMAND SENT ===",
        "continue_error": "Could not send the continue command:\n{error}",
        "stopped": "Stopped",
        "log_stopped": "=== STOPPED AND KILLED CHILD PROCESSES ===",
        "no_process": "No process is running",
        "no_log": "The log is empty.",
        "exported_log": "=== Log exported: {path} ===",
        "exported_log_message": "Log exported to:\n{path}",
        "copy_log_message": "Log copied to the clipboard.",
        "log_action_error": "Could not {action}:\n{error}"
    }
}


def enable_windows_dpi_awareness():
    if os.name != "nt":
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def run_packaged_worker():
    import run_chatgpt_batch

    sys.exit(run_chatgpt_batch.main())


def copy_windows_clipboard_text(text):
    """Copy Unicode text with the native Windows clipboard API.

    Tk's clipboard ownership can be released before another application reads it,
    especially when this app is packaged. Windows owns this memory after
    SetClipboardData succeeds, so the copied log remains available reliably.
    """
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
    kernel32.GlobalFree.restype = wintypes.HANDLE

    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise ctypes.WinError(ctypes.get_last_error())

    memory = None
    try:
        if not user32.EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())

        encoded_text = (text + "\0").encode("utf-16-le")
        memory = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded_text))
        if not memory:
            raise ctypes.WinError(ctypes.get_last_error())

        pointer = kernel32.GlobalLock(memory)
        if not pointer:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.memmove(pointer, encoded_text, len(encoded_text))
        finally:
            kernel32.GlobalUnlock(memory)

        if not user32.SetClipboardData(CF_UNICODETEXT, memory):
            raise ctypes.WinError(ctypes.get_last_error())
        memory = None  # Windows now owns the global memory handle.
    finally:
        if memory:
            kernel32.GlobalFree(memory)
        user32.CloseClipboard()


def make_touch_scroll_handlers(
    scroll_target,
    *,
    prevent_drag_selection=False,
    prefer_pixel_scroll=False,
    on_drag_start=None,
):
    """Turn touch-emulated primary-button drags into vertical scrolling."""
    gesture = {
        "active": False,
        "last_y": 0,
        "remainder": 0,
        "distance": 0,
        "moved": False,
    }

    def touch_press(event):
        gesture["active"] = True
        gesture["last_y"] = event.y_root
        gesture["remainder"] = 0
        gesture["distance"] = 0
        gesture["moved"] = False
        if prevent_drag_selection:
            # A Text class binding starts its selection anchor on press. Stop
            # it here, before motion can turn a swipe into highlighted text.
            return "break"

    def touch_move(event):
        if not gesture["active"]:
            return "break" if prevent_drag_selection else None

        delta = event.y_root - gesture["last_y"]
        gesture["last_y"] = event.y_root
        gesture["distance"] += abs(delta)
        if gesture["distance"] >= 4 and not gesture["moved"]:
            gesture["moved"] = True
            if on_drag_start is not None:
                on_drag_start()

        if prefer_pixel_scroll:
            try:
                # Tk's Text widget supports pixel scrolling, which is smoother
                # than jumping one whole line at a time.
                scroll_target.yview_scroll(-delta, "pixels")
            except (tk.TclError, ValueError):
                prefer_units = True
            else:
                prefer_units = False
        else:
            prefer_units = True

        if prefer_units:
            # Canvas-style targets accept logical units only. Keep a remainder
            # so slow swipes still produce natural movement.
            gesture["remainder"] -= delta
            units = int(gesture["remainder"] / 24)
            if units:
                gesture["remainder"] -= units * 24
                scroll_target.yview_scroll(units, "units")

        if prevent_drag_selection or gesture["moved"]:
            return "break"

    def touch_release(event):
        was_drag = gesture["moved"]
        gesture["active"] = False
        gesture["remainder"] = 0
        gesture["distance"] = 0
        gesture["moved"] = False
        if prevent_drag_selection or was_drag:
            return "break"

    return touch_press, touch_move, touch_release


class TkScheduler(Scheduler):
    def __init__(self, root):
        self.root = root

    def call_later(self, delay_ms, callback):
        return self.root.after(delay_ms, callback)

    def cancel(self, handle):
        self.root.after_cancel(handle)


class ChatGPTBatchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ChatGPT Batch Translator PRO")
        self.root.geometry("1180x820")
        self.root.minsize(900, 620)
        self.set_window_icon()

        self.controller = DesktopController(TkScheduler(root))
        self._internal_account_update = False

        self.settings = self.load_settings()
        self.normalize_chatgpt_accounts()
        try:
            auto_next_delay = DesktopController.parse_auto_next_delay(
                str(self.settings.get("auto_next_delay_minutes", "2"))
            )
        except (TypeError, ValueError):
            auto_next_delay = None
        self.controller.configure_auto_next(
            bool(self.settings.get("auto_next_enabled", False)),
            auto_next_delay,
        )

        self.setup_style()
        self.build_ui()
        self.poll_controller_events()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _get_controller(self):
        """Return the controller, including for legacy __new__-based tests."""
        controller = self.__dict__.get("controller")
        if controller is None:
            controller = DesktopController(TkScheduler(getattr(self, "root", None)))
            self.__dict__["controller"] = controller
        return controller

    @property
    def proc(self):
        return self._get_controller().process

    @proc.setter
    def proc(self, value):
        self._get_controller().process = value

    @property
    def current_done(self):
        return self._get_controller().state.progress_done

    @current_done.setter
    def current_done(self, value):
        self._get_controller().state.progress_done = value

    @property
    def current_total(self):
        return self._get_controller().state.progress_total

    @current_total.setter
    def current_total(self, value):
        self._get_controller().state.progress_total = value

    @property
    def manual_action_required(self):
        return self._get_controller().state.manual_action_required

    @manual_action_required.setter
    def manual_action_required(self, value):
        self._get_controller().state.manual_action_required = value

    @property
    def log_history(self):
        return self._get_controller().log_history

    @log_history.setter
    def log_history(self, value):
        self._get_controller().log_history = value

    @property
    def current_run_mode(self):
        return self._get_controller().state.current_run_mode

    @current_run_mode.setter
    def current_run_mode(self, value):
        self._get_controller().state.current_run_mode = value

    @property
    def current_run_intervened(self):
        return self._get_controller().state.current_run_intervened

    @current_run_intervened.setter
    def current_run_intervened(self, value):
        self._get_controller().state.current_run_intervened = value

    @property
    def current_batch_result(self):
        return self._get_controller().state.current_batch_result

    @current_batch_result.setter
    def current_batch_result(self, value):
        self._get_controller().state.current_batch_result = value

    @property
    def auto_next_after_id(self):
        return self._get_controller()._auto_next_handle

    @auto_next_after_id.setter
    def auto_next_after_id(self, value):
        self._get_controller()._auto_next_handle = value

    @property
    def auto_next_deadline(self):
        return self._get_controller().state.auto_next_deadline

    @auto_next_deadline.setter
    def auto_next_deadline(self, value):
        state = self._get_controller().state
        state.auto_next_deadline = value
        state.auto_next_active = value is not None

    @property
    def auto_next_token(self):
        return self._get_controller().state.auto_next_token

    @auto_next_token.setter
    def auto_next_token(self, value):
        self._get_controller().state.auto_next_token = value

    def set_window_icon(self):
        """Apply the branded icon to the title bar, taskbar, and app switcher."""
        if sys.platform == "win32" and APP_ICON_ICO_FILE.is_file():
            try:
                self.root.iconbitmap(default=str(APP_ICON_ICO_FILE))
            except (OSError, tk.TclError):
                pass
        try:
            self.window_icon = tk.PhotoImage(file=str(APP_ICON_FILE))
            self.root.iconphoto(True, self.window_icon)
        except (OSError, tk.TclError):
            self.window_icon = None

    @staticmethod
    def get_scrollable_main_layout(natural_height, viewport_height):
        """Return the canvas-window height and whether the log card can grow."""
        natural_height = max(1, natural_height)
        viewport_height = max(1, viewport_height)
        return max(natural_height, viewport_height), natural_height <= viewport_height

    def normalize_chatgpt_accounts(self):
        """Validate account metadata and migrate the legacy single profile.

        Browser cookies remain only in each Playwright profile directory.  The
        settings file stores a friendly label and a directory path, never a
        password, cookie, or ChatGPT token.
        """
        return normalize_accounts(self.settings, DATA_DIR)

    def get_active_chatgpt_account(self):
        return get_active_account_from_settings(self.settings, DATA_DIR)

    def is_worker_running(self):
        proc = getattr(self, "proc", None)
        if not proc:
            return False
        try:
            return proc.poll() is None
        except AttributeError:
            return True

    def can_change_chatgpt_account(self):
        if self.is_worker_running():
            messagebox.showwarning(self.t("running_title"), self.t("account_change_running"))
            return False
        return True

    def refresh_chatgpt_account_controls(self):
        active = self.get_active_chatgpt_account()
        if hasattr(self, "account_var"):
            self.account_var.set(active["name"])
        combo = getattr(self, "account_combo", None)
        if combo is not None:
            combo.configure(values=[account["name"] for account in self.settings["chatgpt_accounts"]])

    def set_chatgpt_account_controls_visible(self, visible):
        field = getattr(self, "account_field", None)
        if field is None:
            return
        if visible:
            field.grid()
        else:
            field.grid_remove()

    def on_service_change(self, _=None):
        service = self.service_var.get()
        previous_service = getattr(self, "last_service_value", service)
        if previous_service == "Google Gemini":
            self.settings["gemini_profile_dir"] = self.profile_var.get().strip() or self.settings["gemini_profile_dir"]
        if service == "ChatGPT":
            active = self.get_active_chatgpt_account()
            self.profile_var.set(active["profile_dir"])
            self.set_chatgpt_account_controls_visible(True)
        else:
            self.profile_var.set(self.settings["gemini_profile_dir"])
            self.set_chatgpt_account_controls_visible(False)
        self.last_service_value = service

    def select_chatgpt_account(self, selected_name=None):
        if not self.can_change_chatgpt_account():
            self.refresh_chatgpt_account_controls()
            return

        selected_name = (selected_name or self.account_var.get()).strip()
        account = next(
            (item for item in self.normalize_chatgpt_accounts() if item["name"] == selected_name),
            None,
        )
        if account is None:
            self.refresh_chatgpt_account_controls()
            return

        self.settings["active_chatgpt_account_id"] = account["id"]
        self.profile_var.set(account["profile_dir"])
        self.refresh_chatgpt_account_controls()
        self.save_settings()
        self.status_var.set(self.t("account_selected", name=account["name"]))

    def set_worker_active_account(self, account_id):
        """Reflect a worker-side fallback without treating it as user input."""
        account_id = str(account_id or "").strip()
        account = next(
            (item for item in self.normalize_chatgpt_accounts() if item["id"] == account_id),
            None,
        )
        if account is None:
            return

        self._internal_account_update = True
        try:
            self.settings["active_chatgpt_account_id"] = account["id"]
            self.profile_var.set(account["profile_dir"])
            self.refresh_chatgpt_account_controls()
        finally:
            self._internal_account_update = False
        self.save_settings()

    def prompt_chatgpt_account_name(self, initialvalue=""):
        """Collect an account label in a dialog owned by CustomTkinter.

        ``tkinter.simpledialog`` can be hidden behind a CustomTkinter root on
        Windows.  CTkInputDialog is topmost and modal, so the Rename action
        remains visibly actionable at any DPI setting.
        """
        dialog = ctk.CTkInputDialog(
            title=self.t("account_name_title"),
            text=self.t("account_name_prompt"),
        )

        if initialvalue:
            def fill_initial_value():
                entry = getattr(dialog, "_entry", None)
                if entry is not None:
                    entry.insert(0, initialvalue)
                    entry.select_range(0, "end")

            # CTkInputDialog creates its entry shortly after construction.
            dialog.after(20, fill_initial_value)

        name = dialog.get_input()
        if name is None:
            return None
        name = name.strip()
        if not name:
            messagebox.showerror(self.t("error_title"), self.t("account_name_required"))
            return None
        return name

    def account_name_exists(self, name, except_id=None):
        normalized_name = name.casefold()
        return any(
            account["name"].casefold() == normalized_name and account["id"] != except_id
            # Account actions call normalize_chatgpt_accounts before they
            # select an account.  Calling it again here replaces the list
            # with copied dictionaries, so a subsequent rename would mutate
            # an orphaned copy rather than the saved account.
            for account in self.settings.get("chatgpt_accounts", [])
        )

    def new_chatgpt_profile_dir(self, name):
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("._-") or "account"
        base_dir = DATA_DIR / f"chatgpt_auto_profile_{safe_name[:48]}"
        existing_paths = {account["profile_dir"] for account in self.normalize_chatgpt_accounts()}
        candidate = base_dir
        suffix = 2
        while str(candidate) in existing_paths or candidate.exists():
            candidate = DATA_DIR / f"{base_dir.name}_{suffix}"
            suffix += 1
        return str(candidate)

    def add_chatgpt_account(self):
        if not self.can_change_chatgpt_account():
            return
        name = self.prompt_chatgpt_account_name()
        if name is None:
            return
        if self.account_name_exists(name):
            messagebox.showerror(self.t("error_title"), self.t("account_name_exists"))
            return

        account = {
            "id": f"account-{uuid.uuid4().hex}",
            "name": name,
            "profile_dir": self.new_chatgpt_profile_dir(name),
        }
        self.settings["chatgpt_accounts"].append(account)
        self.settings["active_chatgpt_account_id"] = account["id"]
        self.profile_var.set(account["profile_dir"])
        self.refresh_chatgpt_account_controls()
        self.save_settings()
        self.status_var.set(self.t("account_added", name=name))

    def rename_chatgpt_account(self):
        if not self.can_change_chatgpt_account():
            return
        account = self.get_active_chatgpt_account()
        name = self.prompt_chatgpt_account_name(account["name"])
        if name is None:
            return
        if self.account_name_exists(name, except_id=account["id"]):
            messagebox.showerror(self.t("error_title"), self.t("account_name_exists"))
            return

        account["name"] = name
        self.refresh_chatgpt_account_controls()
        self.save_settings()
        self.status_var.set(self.t("account_renamed", name=name))

    def remove_chatgpt_account(self):
        if not self.can_change_chatgpt_account():
            return
        accounts = self.normalize_chatgpt_accounts()
        if len(accounts) == 1:
            messagebox.showwarning(self.t("account_remove_title"), self.t("account_last"))
            return

        account = self.get_active_chatgpt_account()
        if not messagebox.askyesno(
            self.t("account_remove_title"),
            self.t("account_remove_message", name=account["name"]),
            parent=self.root,
        ):
            return

        accounts.remove(account)
        next_account = accounts[0]
        self.settings["active_chatgpt_account_id"] = next_account["id"]
        self.profile_var.set(next_account["profile_dir"])
        self.refresh_chatgpt_account_controls()
        self.save_settings()
        self.status_var.set(self.t("account_removed", name=account["name"]))

    def login_chatgpt_account(self):
        if not self.can_change_chatgpt_account():
            return
        self.start("login")

    def language_code(self):
        code = self.settings.get("language", DEFAULT_SETTINGS["language"])
        return code if code in TEXT else DEFAULT_SETTINGS["language"]

    def t(self, key, **kwargs):
        value = TEXT[self.language_code()].get(key, TEXT["vi"].get(key, key))
        return value.format(**kwargs) if kwargs else value

    def current_language_label(self):
        return LANGUAGE_OPTIONS[self.language_code()]

    def theme_code(self):
        code = self.settings.get("theme", DEFAULT_SETTINGS["theme"])
        return code if code in THEME_OPTIONS["en"] else DEFAULT_SETTINGS["theme"]

    def effective_theme_code(self):
        code = self.theme_code()
        if code != "system":
            return code
        return "dark" if self.system_uses_dark_apps() else "light"

    def system_uses_dark_apps(self):
        if os.name != "nt" or winreg is None:
            return False

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return int(value) == 0
        except Exception:
            return False

    def current_theme_label(self):
        return THEME_OPTIONS[self.language_code()][self.theme_code()]

    def set_language(self, code):
        if code == self.language_code():
            return

        self.cancel_auto_next()
        self.settings["language"] = code
        self.save_settings()
        for child in self.root.winfo_children():
            child.destroy()
        self.build_ui()

    def set_theme(self, code):
        if code == self.theme_code():
            return

        self.cancel_auto_next()
        self.settings["theme"] = code
        self.save_settings()
        self.setup_style()
        for child in self.root.winfo_children():
            child.destroy()
        self.build_ui()

    def add_header_menu(self, parent, label, current_text, choices, command, width):
        c = self.colors
        box = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        box.pack(side="right", padx=(12, 0))

        ctk.CTkLabel(
            box,
            text=label,
            text_color=c["muted"],
            font=(self.ui_font, 13)
        ).pack(side="left", padx=(0, 8))

        value = tk.StringVar(value=current_text)
        labels = [choice_text for _, choice_text in choices]
        choice_codes = {choice_text: code for code, choice_text in choices}
        button = ctk.CTkOptionMenu(
            box,
            variable=value,
            values=labels,
            command=lambda selected: command(choice_codes[selected]),
            width=width * 10,
            height=34,
            corner_radius=6,
            fg_color=c["input_bg"],
            button_color=c["gray_btn_active"],
            button_hover_color=c["border"],
            dropdown_fg_color=c["card_bg"],
            dropdown_hover_color=c["gray_btn_active"],
            text_color=c["text"],
            dropdown_text_color=c["text"],
            font=(self.ui_font, 13),
            dropdown_font=(self.ui_font, 13),
            anchor="w"
        )
        button.pack(side="left")
        return button

    def get_palette(self):
        if self.effective_theme_code() == "dark":
            return {
                "app_bg": "#202020",
                "chrome_bg": "#202020",
                "sidebar_bg": "#202020",
                "card_bg": "#2b2b2b",
                "input_bg": "#333333",
                "log_bg": "#252525",
                "text": "#f3f3f3",
                "muted": "#b6b6b6",
                "field": "#dedede",
                "border": "#454545",
                "gray_btn": "#353535",
                "gray_btn_active": "#404040",
                "gray_btn_pressed": "#303030",
                "scroll_track": "#252525",
                "scroll_thumb": "#858585",
                "scroll_arrow": "#b6b6b6",
                "selection": "#34566f",
                "accent": "#60cdff",
                "accent_hover": "#78d5ff",
                "accent_pressed": "#4ab7e8",
                "accent_text": "#17232b",
                "danger": "#ffb4ab",
                "danger_hover": "#49312f",
                "danger_pressed": "#573532",
                "disabled_bg": "#303030",
                "disabled_text": "#858585"
            }

        return {
            "app_bg": "#f3f3f3",
            "chrome_bg": "#f3f3f3",
            "sidebar_bg": "#f3f3f3",
            "card_bg": "#fbfbfb",
            "input_bg": "#ffffff",
            "log_bg": "#f7f7f7",
            "text": "#1b1b1b",
            "muted": "#606060",
            "field": "#3b3b3b",
            "border": "#d6d6d6",
            "gray_btn": "#ffffff",
            "gray_btn_active": "#f0f0f0",
            "gray_btn_pressed": "#e8e8e8",
            "scroll_track": "#f7f7f7",
            "scroll_thumb": "#8a8a8a",
            "scroll_arrow": "#606060",
            "selection": "#cce8ff",
            "accent": "#0067c0",
            "accent_hover": "#1975c5",
            "accent_pressed": "#005a9e",
            "accent_text": "#ffffff",
            "danger": "#b42318",
            "danger_hover": "#fce9e7",
            "danger_pressed": "#f8d9d5",
            "disabled_bg": "#eeeeee",
            "disabled_text": "#888888"
        }

    def setup_style(self):
        self.colors = self.get_palette()
        c = self.colors

        ctk.set_appearance_mode("Dark" if self.effective_theme_code() == "dark" else "Light")

        # Use installed desktop fonts, with Tk's native fonts as the fallback.
        families = set(tkfont.families(self.root))
        self.ui_font = next(
            (name for name in ("Segoe UI", "SF Pro Text", "Helvetica") if name in families),
            tkfont.nametofont("TkDefaultFont").actual("family")
        )
        self.log_font = next(
            (name for name in ("Cascadia Mono", "Consolas", "Menlo") if name in families),
            tkfont.nametofont("TkFixedFont").actual("family")
        )

        self.root.configure(fg_color=c["app_bg"])
        self.apply_window_theme()

    def apply_window_theme(self):
        if os.name != "nt":
            return

        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            enabled = ctypes.c_int(1 if self.effective_theme_code() == "dark" else 0)
            for attribute in (20, 19):
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd),
                    ctypes.c_uint(attribute),
                    ctypes.byref(enabled),
                    ctypes.sizeof(enabled)
                )
                if result == 0:
                    break
        except Exception:
            pass

    def load_settings(self):
        return load_settings_file(SETTINGS_FILE, DEFAULT_SETTINGS)

    def save_settings(self):
        service_map = {"ChatGPT": "chatgpt", "Google Gemini": "gemini", "chatgpt": "chatgpt", "gemini": "gemini"}
        auto_next_var = getattr(self, "auto_next_var", None)
        auto_next_delay_var = getattr(self, "auto_next_delay_var", None)
        auto_account_fallback_var = getattr(self, "auto_account_fallback_var", None)
        service = service_map.get(self.service_var.get(), "chatgpt")
        profile_dir = self.profile_var.get().strip()
        accounts = self.normalize_chatgpt_accounts()
        if service == "chatgpt":
            active_account = self.get_active_chatgpt_account()
            if profile_dir:
                active_account["profile_dir"] = profile_dir
            else:
                profile_dir = active_account["profile_dir"]
        elif profile_dir:
            self.settings["gemini_profile_dir"] = profile_dir

        data = {
            **self.settings,
            "image_folder": self.image_var.get(),
            "download_folder": self.output_var.get(),
            "profile_dir": profile_dir,
            "gemini_profile_dir": self.settings["gemini_profile_dir"],
            "chatgpt_accounts": accounts,
            "active_chatgpt_account_id": self.settings["active_chatgpt_account_id"],
            "auto_account_fallback_enabled": bool(auto_account_fallback_var.get()) if auto_account_fallback_var else True,
            "batch_size": self.batch_var.get(),
            "start_from": self.start_from_var.get(),
            "auto_next_enabled": bool(auto_next_var.get()) if auto_next_var else False,
            "auto_next_delay_minutes": auto_next_delay_var.get() if auto_next_delay_var else "2",
            "theme": self.theme_code(),
            "language": self.language_code(),
            "service": service,
        }

        save_settings_file(SETTINGS_FILE, data)
        self.settings = data

    def build_ui(self):
        c = self.colors
        outer = ctk.CTkFrame(self.root, fg_color=c["app_bg"], corner_radius=0)
        outer.pack(fill="both", expand=True)

        chrome = ctk.CTkFrame(outer, fg_color=c["chrome_bg"], corner_radius=0)
        chrome.pack(fill="x", padx=20, pady=(12, 8))
        ctk.CTkLabel(
            chrome,
            text="ChatGPT Batch Image Translator",
            text_color=c["text"],
            font=(self.ui_font, 18, "bold")
        ).pack(side="left")

        header_controls = ctk.CTkFrame(chrome, fg_color="transparent", corner_radius=0)
        header_controls.pack(side="right")
        theme_button = self.add_header_menu(
            header_controls,
            self.t("theme"),
            self.current_theme_label(),
            list(THEME_OPTIONS[self.language_code()].items()),
            self.set_theme,
            16
        )
        language_button = self.add_header_menu(
            header_controls,
            self.t("language"),
            self.current_language_label(),
            list(LANGUAGE_OPTIONS.items()),
            self.set_language,
            12
        )

        header_boxes = (theme_button.master, language_button.master)

        def layout_header(event):
            stacked = event.width < 980
            for box in header_boxes:
                box.pack_forget()
            if stacked:
                language_button.master.pack(side="top", anchor="e", padx=(0, 0), pady=(0, 2))
                theme_button.master.pack(side="top", anchor="e", padx=(0, 0))
            else:
                theme_button.master.pack(side="right", padx=(12, 0))
                language_button.master.pack(side="right", padx=(12, 0))

        chrome.bind("<Configure>", layout_header)

        self.status_var = tk.StringVar(value=self.t("status_ready"))
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_label = tk.StringVar(value=self.t("progress_zero"))

        status_bar = ctk.CTkFrame(outer, fg_color=c["app_bg"], corner_radius=0, height=34)
        status_bar.pack(side="bottom", fill="x", padx=20, pady=(4, 8))
        ctk.CTkLabel(
            status_bar,
            text=self.t("status_label"),
            text_color=c["muted"],
            font=(self.ui_font, 13, "bold")
        ).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(
            status_bar,
            textvariable=self.status_var,
            text_color=c["muted"],
            font=(self.ui_font, 13)
        ).pack(side="left")

        workspace = ctk.CTkFrame(outer, fg_color=c["app_bg"], corner_radius=0)
        workspace.pack(fill="both", expand=True, padx=(20, 10))
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(0, weight=1)

        self.main_canvas = tk.Canvas(
            workspace,
            bg=c["app_bg"],
            highlightthickness=0,
            borderwidth=0,
            yscrollincrement=24
        )
        self.main_canvas.grid(row=0, column=0, sticky="nsew")
        self.main_scrollbar = ctk.CTkScrollbar(
            workspace,
            command=self.main_canvas.yview,
            orientation="vertical",
            width=14,
            corner_radius=7,
            fg_color=c["app_bg"],
            button_color=c["scroll_thumb"],
            button_hover_color=c["muted"]
        )
        self.main_scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.main_canvas.configure(yscrollcommand=self.main_scrollbar.set)

        main = ctk.CTkFrame(self.main_canvas, fg_color=c["app_bg"], corner_radius=0)
        main.columnconfigure(0, weight=1)
        main_window = self.main_canvas.create_window((0, 0), window=main, anchor="nw")

        layout_state = {"scheduled": False, "restore_position": None}

        def sync_main_layout():
            """Size the canvas window after all child widgets have settled.

            Changing the visual style rebuilds the widget tree asynchronously.
            Measuring it during the first canvas resize can lock the embedded
            frame to the viewport height before the log card is laid out,
            leaving its lower content unreachable.  Reflowing after idle keeps
            short screens filled and makes taller screens genuinely scrollable.
            """
            layout_state["scheduled"] = False
            viewport_width = max(1, self.main_canvas.winfo_width())
            viewport_height = max(1, self.main_canvas.winfo_height())

            main.update_idletasks()
            natural_height = main.winfo_reqheight()
            _, log_can_expand = self.get_scrollable_main_layout(
                natural_height,
                viewport_height,
            )
            main.rowconfigure(3, weight=1 if log_can_expand else 0)
            main.update_idletasks()
            content_height, _ = self.get_scrollable_main_layout(
                main.winfo_reqheight(),
                viewport_height,
            )

            self.main_canvas.itemconfigure(
                main_window,
                width=viewport_width,
                height=content_height,
            )
            self.main_canvas.configure(
                scrollregion=(0, 0, viewport_width, content_height)
            )

            restore_position = layout_state["restore_position"]
            layout_state["restore_position"] = None
            if restore_position is not None:
                self.main_canvas.yview_moveto(max(0.0, min(1.0, restore_position)))

        def schedule_main_layout(event=None, restore_position=None):
            if restore_position is not None:
                layout_state["restore_position"] = restore_position
            if layout_state["scheduled"]:
                return
            layout_state["scheduled"] = True
            self.root.after_idle(sync_main_layout)

        self.schedule_main_layout = schedule_main_layout
        main.bind("<Configure>", schedule_main_layout)
        self.main_canvas.bind("<Configure>", schedule_main_layout)

        self.image_var = tk.StringVar(value=self.settings["image_folder"])
        self.output_var = tk.StringVar(value=self.settings["download_folder"])
        self.profile_var = tk.StringVar(value=self.settings["profile_dir"])
        self.batch_var = tk.StringVar(value=self.settings["batch_size"])
        self.start_from_var = tk.StringVar(value=self.settings.get("start_from", ""))
        self.auto_next_var = tk.BooleanVar(value=bool(self.settings.get("auto_next_enabled", False)))
        self.auto_next_delay_var = tk.StringVar(
            value=str(self.settings.get("auto_next_delay_minutes", "2"))
        )
        self.auto_account_fallback_var = tk.BooleanVar(
            value=bool(self.settings.get("auto_account_fallback_enabled", True))
        )
        
        current_service = self.settings.get("service", "chatgpt")
        display_service = "Google Gemini" if current_service == "gemini" else "ChatGPT"
        self.service_var = tk.StringVar(value=display_service)
        self.last_service_value = display_service
        active_chatgpt_account = self.get_active_chatgpt_account()
        self.account_var = tk.StringVar(value=active_chatgpt_account["name"])

        for variable in (
            self.image_var,
            self.output_var,
            self.profile_var,
            self.batch_var,
            self.start_from_var,
            self.service_var,
            self.auto_next_delay_var,
        ):
            variable.trace_add("write", self.on_run_configuration_changed)

        config_card = ctk.CTkFrame(
            main,
            fg_color=c["card_bg"],
            border_width=1,
            border_color=c["border"],
            corner_radius=7
        )
        config_card.grid(row=0, column=0, sticky="ew")
        config_card.columnconfigure(1, weight=1)

        config_header = ctk.CTkFrame(config_card, fg_color="transparent", corner_radius=0)
        config_header.grid(row=0, column=0, columnspan=3, sticky="ew", padx=18, pady=(16, 0))
        ctk.CTkLabel(
            config_header,
            text=self.t("data_config"),
            text_color=c["text"],
            font=(self.ui_font, 16, "bold")
        ).pack(side="left")
        ctk.CTkButton(
            config_header,
            text=self.t("save_config"),
            command=self.save_and_notify,
            height=34,
            corner_radius=6,
            fg_color="transparent",
            hover_color=c["gray_btn_active"],
            text_color=c["field"],
            font=(self.ui_font, 13)
        ).pack(side="right")
        ctk.CTkLabel(
            config_card,
            text=self.t("data_hint"),
            text_color=c["muted"],
            font=(self.ui_font, 13),
            anchor="w"
        ).grid(row=1, column=0, columnspan=3, sticky="ew", padx=18, pady=(5, 14))

        options = ctk.CTkFrame(config_card, fg_color="transparent", corner_radius=0)
        options.grid(row=2, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 14))
        options.columnconfigure(2, weight=1)
        service_field = ctk.CTkFrame(options, fg_color="transparent", corner_radius=0)
        service_field.grid(row=0, column=0, sticky="nw", padx=(0, 24))
        batch_field = ctk.CTkFrame(options, fg_color="transparent", corner_radius=0)
        batch_field.grid(row=0, column=1, sticky="nw", padx=(0, 24))
        start_field = ctk.CTkFrame(options, fg_color="transparent", corner_radius=0)
        start_field.grid(row=0, column=2, sticky="new")
        start_field.columnconfigure(1, weight=1)

        ctk.CTkLabel(
            service_field,
            text=self.t("service"),
            text_color=c["field"],
            font=(self.ui_font, 13)
        ).pack(anchor="w", pady=(0, 6))

        self.service_combo = ctk.CTkComboBox(
            service_field,
            variable=self.service_var,
            values=["ChatGPT", "Google Gemini"],
            state="readonly",
            command=self.on_service_change,
            width=210,
            height=38,
            corner_radius=6,
            fg_color=c["input_bg"],
            border_color=c["border"],
            button_color=c["gray_btn_active"],
            button_hover_color=c["border"],
            dropdown_fg_color=c["card_bg"],
            dropdown_hover_color=c["gray_btn_active"],
            text_color=c["text"],
            dropdown_text_color=c["text"],
            font=(self.ui_font, 14),
            dropdown_font=(self.ui_font, 14)
        )
        self.service_combo.pack(anchor="w")

        self.account_field = ctk.CTkFrame(options, fg_color="transparent", corner_radius=0)
        self.account_field.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        account_top = ctk.CTkFrame(self.account_field, fg_color="transparent", corner_radius=0)
        account_top.pack(fill="x")
        ctk.CTkLabel(
            account_top,
            text=self.t("chatgpt_account"),
            text_color=c["field"],
            font=(self.ui_font, 13)
        ).pack(side="left", padx=(0, 12))
        self.account_combo = ctk.CTkComboBox(
            account_top,
            variable=self.account_var,
            values=[account["name"] for account in self.settings["chatgpt_accounts"]],
            state="readonly",
            command=self.select_chatgpt_account,
            width=210,
            height=36,
            corner_radius=6,
            fg_color=c["input_bg"],
            border_color=c["border"],
            button_color=c["gray_btn_active"],
            button_hover_color=c["border"],
            dropdown_fg_color=c["card_bg"],
            dropdown_hover_color=c["gray_btn_active"],
            text_color=c["text"],
            dropdown_text_color=c["text"],
            font=(self.ui_font, 13),
            dropdown_font=(self.ui_font, 13)
        )
        self.account_combo.pack(side="left")
        for text, command, width in (
            (self.t("account_add"), self.add_chatgpt_account, 70),
            (self.t("account_rename"), self.rename_chatgpt_account, 82),
            (self.t("account_remove"), self.remove_chatgpt_account, 94),
            (self.t("account_login"), self.login_chatgpt_account, 96),
        ):
            ctk.CTkButton(
                account_top,
                text=text,
                command=command,
                width=width,
                height=34,
                corner_radius=6,
                fg_color=c["gray_btn"],
                hover_color=c["gray_btn_active"],
                border_width=1,
                border_color=c["border"],
                text_color=c["text"],
                font=(self.ui_font, 12)
            ).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(
            self.account_field,
            text=self.t("chatgpt_account_hint"),
            text_color=c["muted"],
            font=(self.ui_font, 12)
        ).pack(anchor="w", pady=(5, 0))
        self.account_fallback_check = ctk.CTkCheckBox(
            self.account_field,
            text=self.t("account_fallback"),
            variable=self.auto_account_fallback_var,
            command=self.on_account_fallback_toggle,
            text_color=c["field"],
            fg_color=c["accent"],
            hover_color=c["accent_hover"],
            border_color=c["border"],
            font=(self.ui_font, 12)
        )
        self.account_fallback_check.pack(anchor="w", pady=(9, 0))
        ctk.CTkLabel(
            self.account_field,
            text=self.t("account_fallback_hint"),
            text_color=c["muted"],
            font=(self.ui_font, 11)
        ).pack(anchor="w", padx=(28, 0), pady=(2, 0))
        self.set_chatgpt_account_controls_visible(display_service == "ChatGPT")

        ctk.CTkLabel(
            batch_field,
            text=self.t("batch_size"),
            text_color=c["field"],
            font=(self.ui_font, 13)
        ).pack(anchor="w", pady=(0, 6))
        ctk.CTkEntry(
            batch_field,
            textvariable=self.batch_var,
            width=120,
            height=38,
            corner_radius=6,
            fg_color=c["input_bg"],
            border_color=c["border"],
            text_color=c["text"],
            font=(self.ui_font, 14)
        ).pack(anchor="w")
        ctk.CTkLabel(
            start_field,
            text=self.t("start_from"),
            text_color=c["field"],
            font=(self.ui_font, 13)
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ctk.CTkEntry(
            start_field,
            textvariable=self.start_from_var,
            width=220,
            height=38,
            corner_radius=6,
            fg_color=c["input_bg"],
            border_color=c["border"],
            text_color=c["text"],
            font=(self.ui_font, 14)
        ).grid(row=1, column=0, sticky="w")
        start_hint = ctk.CTkLabel(
            start_field,
            text=self.t("start_hint"),
            text_color=c["muted"],
            font=(self.ui_font, 12)
        )
        start_hint.grid(row=1, column=1, sticky="w", padx=(12, 0))

        # Wrap only the visual hint when larger desktop fonts need more room.
        def layout_start_hint(event):
            entry_width = start_field.grid_slaves(row=1, column=0)[0].winfo_reqwidth()
            if event.width < entry_width + start_hint.winfo_reqwidth() + 12:
                start_hint.grid(row=2, column=0, columnspan=2, padx=0, pady=(4, 0))
            else:
                start_hint.grid(row=1, column=1, columnspan=1, padx=(12, 0), pady=0)

        start_field.bind("<Configure>", layout_start_hint)

        auto_field = ctk.CTkFrame(options, fg_color="transparent", corner_radius=0)
        auto_field.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        ctk.CTkSwitch(
            auto_field,
            text=self.t("auto_next"),
            variable=self.auto_next_var,
            command=self.on_auto_next_toggle,
            onvalue=True,
            offvalue=False,
            fg_color=c["gray_btn_active"],
            progress_color=c["accent"],
            button_color=c["field"],
            button_hover_color=c["text"],
            text_color=c["field"],
            font=(self.ui_font, 13)
        ).pack(side="left")
        ctk.CTkLabel(
            auto_field,
            text=self.t("auto_next_delay"),
            text_color=c["muted"],
            font=(self.ui_font, 13)
        ).pack(side="left", padx=(22, 8))
        ctk.CTkEntry(
            auto_field,
            textvariable=self.auto_next_delay_var,
            width=72,
            height=34,
            corner_radius=6,
            fg_color=c["input_bg"],
            border_color=c["border"],
            text_color=c["text"],
            font=(self.ui_font, 13)
        ).pack(side="left")
        ctk.CTkLabel(
            auto_field,
            text=self.t("auto_next_hint"),
            text_color=c["muted"],
            font=(self.ui_font, 12)
        ).pack(side="left", padx=(16, 0))

        self.add_folder_row(config_card, self.t("source_folder"), self.image_var, 3)
        self.add_folder_row(config_card, self.t("output_folder"), self.output_var, 4)
        self.add_folder_row(config_card, self.t("profile"), self.profile_var, 5, choose_command=self.choose_profile_folder)

        action_card = ctk.CTkFrame(
            main,
            fg_color=c["card_bg"],
            border_width=1,
            border_color=c["border"],
            corner_radius=7
        )
        action_card.grid(row=1, column=0, sticky="ew", pady=14)
        ctk.CTkLabel(
            action_card,
            text=self.t("actions"),
            text_color=c["text"],
            font=(self.ui_font, 16, "bold")
        ).grid(
            row=0, column=0, columnspan=6, sticky="w", padx=18, pady=(14, 10)
        )

        self.start_btn = ctk.CTkButton(
            action_card,
            text=self.t("new_batch"),
            command=lambda: self.start("main"),
            width=180,
            height=42,
            corner_radius=6,
            fg_color=c["accent"],
            hover_color=c["accent_hover"],
            text_color=c["accent_text"],
            text_color_disabled=c["disabled_text"],
            font=(self.ui_font, 14, "bold")
        )
        self.retry_btn = ctk.CTkButton(
            action_card,
            text=self.t("retry_failed"),
            command=lambda: self.start("retry"),
            width=190,
            height=42,
            corner_radius=6,
            fg_color=c["gray_btn"],
            hover_color=c["gray_btn_active"],
            border_width=1,
            border_color=c["border"],
            text_color=c["text"],
            text_color_disabled=c["disabled_text"],
            font=(self.ui_font, 14)
        )
        self.force_btn = ctk.CTkButton(
            action_card,
            text=self.t("rerun_image"),
            command=lambda: self.start("force"),
            width=180,
            height=42,
            corner_radius=6,
            fg_color=c["gray_btn"],
            hover_color=c["gray_btn_active"],
            border_width=1,
            border_color=c["border"],
            text_color=c["text"],
            text_color_disabled=c["disabled_text"],
            font=(self.ui_font, 14)
        )
        self.continue_btn = ctk.CTkButton(
            action_card,
            text=self.t("continue_manual"),
            command=self.send_continue,
            state="disabled",
            width=240,
            height=42,
            corner_radius=6,
            fg_color=c["gray_btn"],
            hover_color=c["gray_btn_active"],
            border_width=1,
            border_color=c["border"],
            text_color=c["text"],
            text_color_disabled=c["disabled_text"],
            font=(self.ui_font, 14)
        )

        self.stop_btn = ctk.CTkButton(
            action_card,
            text=self.t("stop"),
            command=self.stop,
            width=120,
            height=42,
            corner_radius=6,
            fg_color=c["gray_btn"],
            hover_color=c["danger_hover"],
            border_width=1,
            border_color=c["border"],
            text_color=c["danger"],
            text_color_disabled=c["disabled_text"],
            font=(self.ui_font, 14)
        )
        self.auto_next_frame = ctk.CTkFrame(
            action_card,
            fg_color=c["input_bg"],
            border_width=1,
            border_color=c["border"],
            corner_radius=6
        )
        self.auto_next_frame.grid(row=3, column=0, columnspan=6, sticky="ew", padx=18, pady=(0, 16))
        self.auto_next_countdown_var = tk.StringVar(value="")
        ctk.CTkLabel(
            self.auto_next_frame,
            textvariable=self.auto_next_countdown_var,
            text_color=c["field"],
            font=(self.ui_font, 13)
        ).pack(side="left", padx=(14, 10), pady=8)
        self.auto_next_cancel_btn = ctk.CTkButton(
            self.auto_next_frame,
            text=self.t("auto_cancel"),
            command=lambda: self.cancel_auto_next(announce=True),
            width=120,
            height=30,
            corner_radius=6,
            fg_color="transparent",
            hover_color=c["gray_btn_active"],
            text_color=c["field"],
            font=(self.ui_font, 12)
        )
        self.auto_next_cancel_btn.pack(side="right", padx=(4, 10), pady=6)
        self.auto_next_now_btn = ctk.CTkButton(
            self.auto_next_frame,
            text=self.t("auto_run_now"),
            command=self.run_auto_next_now,
            width=100,
            height=30,
            corner_radius=6,
            fg_color=c["accent"],
            hover_color=c["accent_hover"],
            text_color=c["accent_text"],
            font=(self.ui_font, 12, "bold")
        )
        self.auto_next_now_btn.pack(side="right", padx=4, pady=6)
        self.auto_next_frame.grid_remove()
        action_card.columnconfigure(4, weight=1)
        action_buttons = (self.start_btn, self.retry_btn, self.force_btn, self.continue_btn, self.stop_btn)
        for button in action_buttons:
            button.config = button.configure
        if self.manual_action_required:
            self.continue_btn.config(state="normal")

        action_layout = {"single_row": None}

        def layout_actions(event):
            required_width = sum(button.winfo_reqwidth() for button in action_buttons) + 96
            single_row = event.width >= required_width
            if action_layout["single_row"] == single_row:
                return

            action_layout["single_row"] = single_row
            for button in action_buttons:
                button.grid_forget()

            self.start_btn.grid(row=1, column=0, sticky="w", padx=(18, 12), pady=(0, 16) if single_row else 0)
            self.retry_btn.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=(0, 16) if single_row else 0)
            self.force_btn.grid(row=1, column=2, sticky="w", padx=(0, 12), pady=(0, 16) if single_row else 0)
            if single_row:
                self.continue_btn.grid(row=1, column=3, sticky="w", padx=(0, 12), pady=(0, 16))
                self.stop_btn.grid(row=1, column=5, sticky="e", padx=(12, 18), pady=(0, 16))
            else:
                self.continue_btn.grid(row=2, column=0, sticky="w", padx=(18, 12), pady=(12, 16))
                self.stop_btn.grid(row=2, column=5, sticky="e", padx=(12, 18), pady=(12, 16))
            schedule_main_layout()

        action_card.bind("<Configure>", layout_actions)

        progress_box = ctk.CTkFrame(
            main,
            fg_color=c["card_bg"],
            border_width=1,
            border_color=c["border"],
            corner_radius=7
        )
        progress_box.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        progress_box.columnconfigure(1, weight=1)
        ctk.CTkLabel(
            progress_box,
            text=self.t("progress_label"),
            text_color=c["text"],
            font=(self.ui_font, 16, "bold")
        ).grid(row=0, column=0, sticky="w", padx=(18, 16), pady=(14, 0))
        ctk.CTkLabel(
            progress_box,
            textvariable=self.status_var,
            text_color=c["muted"],
            font=(self.ui_font, 13)
        ).grid(row=0, column=1, sticky="w", pady=(14, 0))
        ctk.CTkLabel(
            progress_box,
            textvariable=self.progress_label,
            text_color=c["muted"],
            font=(self.ui_font, 13)
        ).grid(row=0, column=2, sticky="e", padx=(16, 18), pady=(14, 0))
        self.progress_bar = ctk.CTkProgressBar(
            progress_box,
            height=8,
            corner_radius=4,
            fg_color=c["gray_btn_active"],
            progress_color=c["accent"]
        )
        self.progress_bar.grid(row=1, column=0, columnspan=3, sticky="ew", padx=18, pady=(14, 16))

        def sync_progress_bar(*_):
            self.progress_bar.set(max(0.0, min(1.0, self.progress_var.get() / 100)))

        self.progress_var.trace_add("write", sync_progress_bar)
        sync_progress_bar()

        log_card = ctk.CTkFrame(
            main,
            fg_color=c["card_bg"],
            border_width=1,
            border_color=c["border"],
            corner_radius=7
        )
        log_card.grid(row=3, column=0, sticky="nsew")
        log_toolbar = ctk.CTkFrame(log_card, fg_color="transparent", corner_radius=0)
        log_toolbar.pack(fill="x", padx=14, pady=(12, 8))
        ctk.CTkLabel(
            log_toolbar,
            text=self.t("process_log"),
            text_color=c["text"],
            font=(self.ui_font, 16, "bold")
        ).pack(side="left", padx=(4, 0))

        for text, command in (
            (self.t("clear_log"), self.clear_log),
            (self.t("copy_log"), self.copy_log),
            (self.t("export_log"), self.export_log),
            (self.t("open_output"), self.open_output),
        ):
            ctk.CTkButton(
                log_toolbar,
                text=text,
                command=command,
                width=120,
                height=32,
                corner_radius=6,
                fg_color="transparent",
                hover_color=c["gray_btn_active"],
                text_color=c["field"],
                font=(self.ui_font, 12)
            ).pack(side="right", padx=(4, 0))

        self.log_text = ctk.CTkTextbox(
            log_card,
            wrap="word",
            font=(self.log_font, 13),
            fg_color=c["log_bg"],
            text_color=c["text"],
            border_width=1,
            border_color=c["border"],
            corner_radius=6,
            scrollbar_button_color=c["scroll_thumb"],
            scrollbar_button_hover_color=c["muted"],
            width=1,
            height=220
        )
        self.log_text.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        def scroll_main(event):
            direction = -1 if event.delta > 0 else 1
            self.main_canvas.yview_scroll(direction * 3, "units")
            return "break"

        def scroll_main_linux(event):
            self.main_canvas.yview_scroll(-3 if event.num == 4 else 3, "units")
            return "break"

        def scroll_log(event):
            direction = -1 if event.delta > 0 else 1
            self.log_text.yview_scroll(direction * 3, "units")
            return "break"

        def scroll_log_linux(event):
            self.log_text.yview_scroll(-3 if event.num == 4 else 3, "units")
            return "break"

        def bind_main_wheel(widget):
            if widget == self.log_text:
                return
            widget.bind("<MouseWheel>", scroll_main)
            widget.bind("<Button-4>", scroll_main_linux)
            widget.bind("<Button-5>", scroll_main_linux)
            for child in widget.winfo_children():
                bind_main_wheel(child)

        bind_main_wheel(workspace)

        touch_press, touch_move, touch_release = make_touch_scroll_handlers(self.main_canvas)

        def bind_main_touch(widget):
            if widget == self.log_text:
                return
            widget.bind("<ButtonPress-1>", touch_press, add="+")
            widget.bind("<B1-Motion>", touch_move, add="+")
            widget.bind("<ButtonRelease-1>", touch_release, add="+")
            for child in widget.winfo_children():
                bind_main_touch(child)

        bind_main_touch(workspace)

        def clear_log_selection():
            try:
                self.log_text.tag_remove("sel", "1.0", "end")
            except (AttributeError, tk.TclError):
                pass

        log_touch_press, log_touch_move, log_touch_release = make_touch_scroll_handlers(
            self.log_text,
            prevent_drag_selection=True,
            prefer_pixel_scroll=True,
            on_drag_start=clear_log_selection,
        )
        self.log_text.bind("<ButtonPress-1>", log_touch_press, add="+")
        self.log_text.bind("<B1-Motion>", log_touch_move, add="+")
        self.log_text.bind("<ButtonRelease-1>", log_touch_release, add="+")
        self.log_text.bind("<MouseWheel>", scroll_log)
        self.log_text.bind("<Button-4>", scroll_log_linux)
        self.log_text.bind("<Button-5>", scroll_log_linux)

        schedule_main_layout()

        if self.log_history:
            self.log_text.insert("end", "".join(self.log_history))
            self.log_text.see("end")

        if self.proc and self.proc.poll() is None:
            self.status_var.set(self.t("manual_wait") if self.manual_action_required else self.t("status_running"))
            self.start_btn.config(state="disabled")
            self.retry_btn.config(state="disabled")
            self.force_btn.config(state="disabled")

    def add_folder_row(self, parent, label, var, row, choose_command=None):
        c = self.colors
        row_pady = (6, 16) if row == 5 else 6
        ctk.CTkLabel(
            parent,
            text=label,
            text_color=c["field"],
            font=(self.ui_font, 13)
        ).grid(row=row, column=0, sticky="w", padx=(18, 14), pady=row_pady)
        ctk.CTkEntry(
            parent,
            textvariable=var,
            height=38,
            corner_radius=6,
            fg_color=c["input_bg"],
            border_color=c["border"],
            text_color=c["text"],
            font=(self.ui_font, 14)
        ).grid(row=row, column=1, sticky="ew", pady=row_pady)
        ctk.CTkButton(
            parent,
            text=self.t("choose"),
            command=choose_command or (lambda: self.choose_folder(var)),
            width=110,
            height=38,
            corner_radius=6,
            fg_color=c["gray_btn"],
            hover_color=c["gray_btn_active"],
            border_width=1,
            border_color=c["border"],
            text_color=c["text"],
            font=(self.ui_font, 13)
        ).grid(row=row, column=2, padx=(12, 18), pady=row_pady)

    def choose_folder(self, var):
        folder = filedialog.askdirectory()
        if folder:
            var.set(folder)

    def choose_profile_folder(self):
        if self.service_var.get() == "ChatGPT" and not self.can_change_chatgpt_account():
            return

        folder = filedialog.askdirectory()
        if not folder:
            return

        if self.service_var.get() == "Google Gemini":
            self.settings["gemini_profile_dir"] = folder
            self.profile_var.set(folder)
            return

        account = self.get_active_chatgpt_account()
        matching_account = next(
            (item for item in self.settings["chatgpt_accounts"] if item["profile_dir"] == folder),
            None,
        )
        if matching_account is not None:
            self.settings["active_chatgpt_account_id"] = matching_account["id"]
        else:
            account["profile_dir"] = folder
        self.profile_var.set(folder)
        self.refresh_chatgpt_account_controls()
        self.save_settings()

    def save_and_notify(self):
        # Saving settings is an explicit user action.  Do not let a pending
        # automatic restart race it, even if none of the fields changed.
        self.on_run_configuration_changed()
        self.save_settings()
        messagebox.showinfo("OK", self.t("saved_config"))

    def auto_next_is_enabled(self):
        auto_next_var = getattr(self, "auto_next_var", None)
        return bool(auto_next_var.get()) if auto_next_var is not None else False

    def get_auto_next_delay_seconds(self):
        return DesktopController.parse_auto_next_delay(self.auto_next_delay_var.get())

    def sync_auto_next_configuration(self):
        try:
            delay_seconds = self.get_auto_next_delay_seconds()
        except (AttributeError, TypeError, ValueError):
            delay_seconds = None
        self.controller.configure_auto_next(self.auto_next_is_enabled(), delay_seconds)

    def on_run_configuration_changed(self, *_):
        if getattr(self, "_internal_account_update", False):
            return
        self.sync_auto_next_configuration()
        self.controller.mark_run_configuration_changed()
        self.render_controller_events()

    def on_auto_next_toggle(self):
        self.on_run_configuration_changed()
        self.save_settings()

    def on_account_fallback_toggle(self):
        self.on_run_configuration_changed()
        self.save_settings()

    def set_auto_next_controls_visible(self, visible):
        frame = getattr(self, "auto_next_frame", None)
        if frame is None:
            return
        if visible:
            frame.grid()
        else:
            frame.grid_remove()

    def cancel_auto_next(self, announce=False):
        active = self.controller.cancel_auto_next(announce=announce)
        self.render_controller_events()
        return active

    def schedule_auto_next(self):
        self.sync_auto_next_configuration()
        scheduled = self.controller.schedule_auto_next()
        self.render_controller_events()
        return scheduled

    def update_auto_next_countdown(self, token):
        self.controller.update_auto_next_countdown(token)
        self.render_controller_events()

    def run_auto_next_now(self):
        self.controller.run_auto_next_now()
        self.render_controller_events()

    def handle_worker_output(self, text):
        self.controller.handle_worker_output(text)
        self.render_controller_events()

    def get_auto_next_skip_reason(self, exit_code):
        self.sync_auto_next_configuration()
        return self.controller.get_auto_next_skip_reason(exit_code)

    def handle_process_done(self, exit_code):
        self.controller.handle_process_done(exit_code)
        self.render_controller_events()

    def start(self, mode, auto_started=False):
        if self.proc and self.proc.poll() is None:
            messagebox.showwarning(self.t("running_title"), self.t("running_message"))
            return

        if not auto_started:
            self.cancel_auto_next()

        if mode == "force" and not self.start_from_var.get().strip():
            messagebox.showwarning(
                self.t("missing_image_title"),
                self.t("missing_image_message")
            )
            return

        if mode != "login":
            try:
                batch_size = int(self.batch_var.get().strip())
                if batch_size < 1:
                    raise ValueError
            except ValueError:
                messagebox.showerror(self.t("error_title"), self.t("invalid_batch_size"))
                return

        if mode == "main" and self.auto_next_is_enabled():
            try:
                self.get_auto_next_delay_seconds()
            except (TypeError, ValueError):
                messagebox.showerror(self.t("error_title"), self.t("invalid_auto_next_delay"))
                return

        if not getattr(sys, "frozen", False) and not SCRIPT_FILE.exists():
            messagebox.showerror(self.t("error_title"), self.t("file_missing", path=SCRIPT_FILE))
            return

        service_map = {"ChatGPT": "chatgpt", "Google Gemini": "gemini", "chatgpt": "chatgpt", "gemini": "gemini"}
        service_val = service_map.get(self.service_var.get(), "chatgpt")
        if mode == "login" and service_val != "chatgpt":
            messagebox.showerror(self.t("error_title"), self.t("chatgpt_account"))
            return
        profile_dir = self.profile_var.get().strip()
        if not profile_dir:
            if service_val == "gemini":
                profile_dir = str(DATA_DIR / "gemini_auto_profile")
            else:
                profile_dir = str(DATA_DIR / "chatgpt_auto_profile")
            self.profile_var.set(profile_dir)

        self.save_settings()

        try:
            auto_next_delay = self.get_auto_next_delay_seconds() if self.auto_next_is_enabled() else None
        except (TypeError, ValueError):
            # Only main mode validates this field. Other modes keep their old
            # behavior and simply cannot schedule an automatic main run.
            auto_next_delay = None
        self.controller.configure_auto_next(self.auto_next_is_enabled(), auto_next_delay)
        launch = build_process_launch(
            self.settings,
            mode,
            app_dir=APP_DIR,
            executable=sys.executable,
            frozen=bool(getattr(sys, "frozen", False)),
        )
        if not self.controller.start(mode, launch, auto_started=auto_started):
            messagebox.showwarning(self.t("running_title"), self.t("running_message"))
            return
        self.render_controller_events()

    def poll_controller_events(self):
        self.render_controller_events()
        self.root.after(200, self.poll_controller_events)

    def render_controller_events(self):
        if getattr(self, "_rendering_controller_events", False):
            return
        self._rendering_controller_events = True
        try:
            while True:
                events = self.controller.drain_events()
                if not events:
                    break
                for event in events:
                    self.handle_controller_event(event)
        finally:
            self._rendering_controller_events = False

    def handle_controller_event(self, event):
        event_type = event.type
        data = event.data

        if event_type == "log_appended":
            self.log_text.insert("end", data["text"])
            self.log_text.see("end")
        elif event_type == "log_cleared":
            self.log_text.delete("1.0", "end")
        elif event_type == "progress_changed":
            done = data["done"]
            total = data["total"]
            percent = done / max(total, 1) * 100 if total else 0
            self.progress_var.set(percent)
            if data.get("reset"):
                self.progress_label.set(self.t("progress_count", done=done, total=total))
            elif total:
                self.progress_label.set(self.t("progress_percent", done=done, total=total, percent=percent))
            else:
                self.progress_label.set(self.t("progress_zero"))
        elif event_type == "manual_action_required":
            self.status_var.set(self.t("manual_wait"))
            self.continue_btn.config(state="normal")
        elif event_type == "process_started":
            self.log(f"\n{self.t('log_start', mode=data['mode'].upper())}\n")
            self.status_var.set(self.t("status_running"))
            self.start_btn.config(state="disabled")
            self.retry_btn.config(state="disabled")
            self.force_btn.config(state="disabled")
            self.continue_btn.config(state="disabled")
        elif event_type == "process_completed":
            self.start_btn.config(state="normal")
            self.retry_btn.config(state="normal")
            self.force_btn.config(state="normal")
            self.continue_btn.config(state="disabled")
        elif event_type == "batch_result":
            result = data["result"]
            self.log("\n" + self.t(
                "batch_result_log",
                success=result.get("success_count", 0),
                selected=result.get("selected_count", 0),
                failed=result.get("failure_count", 0),
            ) + "\n")
        elif event_type == "account_event":
            self.render_account_event(data["event"])
        elif event_type == "reader_error":
            self.log(f"\n{self.t('log_read_error', error=data['error'])}\n")
        elif event_type == "continue_sent":
            self.continue_btn.config(state="disabled")
            self.status_var.set(self.t("continue_sent"))
            self.log(f"\n{self.t('log_continue_sent')}\n")
        elif event_type == "continue_error":
            messagebox.showerror(self.t("error_title"), self.t("continue_error", error=data["error"]))
        elif event_type == "stopped":
            self.status_var.set(self.t("stopped"))
            self.log(f"\n{self.t('log_stopped')}\n")
        elif event_type == "no_process":
            self.status_var.set(self.t("no_process"))
        elif event_type == "auto_next_cancelled":
            countdown_var = getattr(self, "auto_next_countdown_var", None)
            if countdown_var is not None:
                countdown_var.set("")
            self.set_auto_next_controls_visible(False)
            if data["active"] and data["announce"]:
                self.status_var.set(self.t("auto_cancelled"))
                self.log(f"\n=== {self.t('auto_cancelled')} ===\n")
        elif event_type == "auto_next_scheduled":
            self.set_auto_next_controls_visible(True)
            self.log(f"\n{self.t('auto_scheduled_log', count=data['count'], seconds=data['seconds'])}\n")
        elif event_type == "auto_next_tick":
            remaining = data["remaining"]
            formatted = f"{remaining // 60:02d}:{remaining % 60:02d}"
            message = self.t("auto_countdown", time=formatted)
            self.status_var.set(message)
            self.auto_next_countdown_var.set(message)
            if remaining == 0:
                self.set_auto_next_controls_visible(False)
        elif event_type == "auto_next_running":
            self.log(f"\n{self.t('auto_running_log')}\n")
        elif event_type == "auto_next_start_requested":
            # Rebuild the launch environment from the current presentation
            # state so a worker-side account switch carries into the next run.
            self.start("main", auto_started=True)
        elif event_type == "auto_next_recovered":
            self.log("\n" + self.t("auto_recover_after_worker_exit", code=data["code"]) + "\n")
        elif event_type == "auto_next_skipped":
            self.log(f"\n{self.t(data['reason'], **data['values'])}\n")
        elif event_type == "invalid_auto_next_delay":
            self.status_var.set(self.t("process_done"))
            messagebox.showerror(self.t("error_title"), self.t("invalid_auto_next_delay"))
        elif event_type == "process_outcome":
            self.render_process_outcome(data)

    def render_account_event(self, event):
        event_name = event.get("event")
        if event_name == "account_quota_exhausted":
            self.log("\n" + self.t("account_quota_log", name=event.get("account_name", "ChatGPT")) + "\n")
        elif event_name == "account_switched":
            self.set_worker_active_account(event.get("account_id"))
            self.log("\n" + self.t(
                "account_switched_log",
                name=event.get("account_name", "ChatGPT"),
                image=event.get("image", ""),
            ) + "\n")
        elif event_name == "account_skipped":
            self.log("\n" + self.t(
                "account_skipped_log",
                name=event.get("account_name", "ChatGPT"),
                reason=event.get("reason", ""),
            ) + "\n")
        elif event_name == "job_waiting":
            self.status_var.set(self.t("account_waiting_status"))
            self.log("\n" + self.t(
                "account_waiting_log",
                reason=event.get("reason", ""),
                image=event.get("image", ""),
            ) + "\n")

    def render_process_outcome(self, data):
        outcome = data["outcome"]
        exit_code = data["exit_code"]
        job = data.get("job", {})
        if outcome == "login":
            if exit_code == 0:
                self.status_var.set(self.t("login_ready"))
                self.log(f"\n{self.t('login_ready_log')}\n")
            else:
                self.status_var.set(self.t("process_done"))
        elif outcome == "complete":
            message = f"Job hoàn tất: {job['done']}/{job['total']} ảnh. Exit code: 0."
            self.status_var.set(message)
            self.log(f"\n=== {message} ===\n")
        elif outcome == "waiting_quota":
            message = f"Batch tạm dừng: {job.get('waiting_reason', '')}. Ảnh đang dở: {job.get('waiting_image', '')}."
            self.status_var.set(self.t("account_waiting_status"))
            self.log(f"\n=== {message} ===\n")
        elif outcome == "needs_retry":
            message = f"Job đã dừng: còn {job['failed']} ảnh cần chạy lại. Exit code: 2."
            self.status_var.set(message)
            self.log(f"\n=== {message} ===\n")
        else:
            self.status_var.set(self.t("process_done"))

    def log(self, text):
        self.controller.append_log(text)
        if not getattr(self, "_rendering_controller_events", False):
            self.render_controller_events()

    def update_manual_button_from_log(self, text):
        self.controller._update_manual_state_from_log(text)
        self.render_controller_events()

    def update_progress_from_log(self, text):
        self.controller._update_progress_from_log(text)
        self.render_controller_events()

    def send_continue(self):
        self.controller.send_continue()
        self.render_controller_events()

    def stop(self):
        self.controller.stop()
        self.render_controller_events()

    def open_output(self):
        folder = self.output_var.get()
        os.makedirs(folder, exist_ok=True)
        if os.name == "nt":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    def get_log_contents(self):
        log_widget = getattr(self, "log_text", None)
        if log_widget is not None:
            return log_widget.get("1.0", "end-1c")
        return "".join(getattr(self, "log_history", []))

    def copy_text_to_clipboard(self, text):
        if os.name == "nt":
            copy_windows_clipboard_text(text)
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()

    def export_log(self):
        log_contents = self.get_log_contents()
        if not log_contents.strip():
            messagebox.showinfo("OK", self.t("no_log"))
            return

        log_file = Path(self.output_var.get()) / "process_log.txt"
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(log_contents)
        except OSError as e:
            messagebox.showerror(
                self.t("error_title"),
                self.t("log_action_error", action=self.t("export_log"), error=e),
            )
            return

        self.log(f"\n{self.t('exported_log', path=log_file)}\n")
        messagebox.showinfo("OK", self.t("exported_log_message", path=log_file))

    def copy_log(self):
        log_contents = self.get_log_contents()
        if not log_contents.strip():
            messagebox.showinfo("OK", self.t("no_log"))
            return

        try:
            self.copy_text_to_clipboard(log_contents)
        except (OSError, tk.TclError) as e:
            messagebox.showerror(
                self.t("error_title"),
                self.t("log_action_error", action=self.t("copy_log"), error=e),
            )
            return

        messagebox.showinfo("OK", self.t("copy_log_message"))

    def clear_log(self):
        self.controller.clear_log()
        self.render_controller_events()

    def on_close(self):
        self.controller.shutdown()
        self.root.destroy()


def run_tk_app():
    enable_windows_dpi_awareness()
    set_windows_app_user_model_id()
    root = ctk.CTk()
    app = ChatGPTBatchApp(root)
    root.mainloop()


if __name__ == "__main__":
    if _LAUNCH_MODE == "worker":
        run_packaged_worker()
    else:
        run_tk_app()
