import os
import sys
import json
import math
import queue
import threading
import subprocess
import ctypes
import time
import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog, messagebox
from tkinter import font as tkfont
from pathlib import Path

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
BATCH_RESULT_PREFIX = "__BATCH_RESULT__="


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
    "batch_size": "10",
    "start_from": "",
    "auto_next_enabled": False,
    "auto_next_delay_minutes": "2",
    "theme": "system",
    "language": "vi",
    "service": "chatgpt"
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


class ChatGPTBatchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ChatGPT Batch Translator PRO")
        self.root.geometry("1180x820")
        self.root.minsize(900, 620)

        self.proc = None
        self.log_queue = queue.Queue()
        self.current_done = 0
        self.current_total = 0
        self.manual_action_required = False
        self.log_history = []
        self.current_run_mode = None
        self.current_run_intervened = False
        self.current_batch_result = None
        self.auto_next_after_id = None
        self.auto_next_deadline = None
        self.auto_next_token = 0

        self.settings = self.load_settings()

        self.setup_style()
        self.build_ui()
        self.poll_log_queue()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

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
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    return {**DEFAULT_SETTINGS, **json.load(f)}
            except Exception:
                pass

        return DEFAULT_SETTINGS.copy()

    def save_settings(self):
        service_map = {"ChatGPT": "chatgpt", "Google Gemini": "gemini", "chatgpt": "chatgpt", "gemini": "gemini"}
        auto_next_var = getattr(self, "auto_next_var", None)
        auto_next_delay_var = getattr(self, "auto_next_delay_var", None)
        data = {
            **self.settings,
            "image_folder": self.image_var.get(),
            "download_folder": self.output_var.get(),
            "profile_dir": self.profile_var.get(),
            "batch_size": self.batch_var.get(),
            "start_from": self.start_from_var.get(),
            "auto_next_enabled": bool(auto_next_var.get()) if auto_next_var else False,
            "auto_next_delay_minutes": auto_next_delay_var.get() if auto_next_delay_var else "2",
            "theme": self.theme_code(),
            "language": self.language_code(),
            "service": service_map.get(self.service_var.get(), "chatgpt")
        }

        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
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

        def update_main_scrollregion(event=None):
            self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

        def resize_main_content(event=None):
            viewport_width = event.width if event is not None else self.main_canvas.winfo_width()
            viewport_height = event.height if event is not None else self.main_canvas.winfo_height()
            self.main_canvas.itemconfigure(main_window, width=viewport_width)
            main.update_idletasks()
            natural_height = main.winfo_reqheight()
            fill_height = max(natural_height, viewport_height)
            self.main_canvas.itemconfigure(main_window, height=fill_height)
            main.rowconfigure(3, weight=1 if natural_height < viewport_height else 0)
            update_main_scrollregion()

        main.bind("<Configure>", update_main_scrollregion)
        self.main_canvas.bind("<Configure>", resize_main_content)

        self.image_var = tk.StringVar(value=self.settings["image_folder"])
        self.output_var = tk.StringVar(value=self.settings["download_folder"])
        self.profile_var = tk.StringVar(value=self.settings["profile_dir"])
        self.batch_var = tk.StringVar(value=self.settings["batch_size"])
        self.start_from_var = tk.StringVar(value=self.settings.get("start_from", ""))
        self.auto_next_var = tk.BooleanVar(value=bool(self.settings.get("auto_next_enabled", False)))
        self.auto_next_delay_var = tk.StringVar(
            value=str(self.settings.get("auto_next_delay_minutes", "2"))
        )
        
        current_service = self.settings.get("service", "chatgpt")
        display_service = "Google Gemini" if current_service == "gemini" else "ChatGPT"
        self.service_var = tk.StringVar(value=display_service)

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

        def on_service_change(event=None):
            val = self.service_var.get()
            current_profile = self.profile_var.get()
            if val == "Google Gemini" and "chatgpt_auto_profile" in current_profile:
                new_profile = current_profile.replace("chatgpt_auto_profile", "gemini_auto_profile")
                self.profile_var.set(new_profile)
            elif val == "ChatGPT" and "gemini_auto_profile" in current_profile:
                new_profile = current_profile.replace("gemini_auto_profile", "chatgpt_auto_profile")
                self.profile_var.set(new_profile)

        self.service_combo = ctk.CTkComboBox(
            service_field,
            variable=self.service_var,
            values=["ChatGPT", "Google Gemini"],
            state="readonly",
            command=on_service_change,
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
        auto_field.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(16, 0))
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
        self.add_folder_row(config_card, self.t("profile"), self.profile_var, 5)

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
            self.root.after_idle(resize_main_content)

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

        def make_touch_scroll_handlers(scroll_target):
            """Turn the touch screen's mouse-emulated drag into vertical scrolling."""
            gesture = {"active": False, "last_y": 0, "remainder": 0, "moved": False}

            def touch_press(event):
                gesture["active"] = True
                gesture["last_y"] = event.y_root
                gesture["remainder"] = 0
                gesture["moved"] = False

            def touch_move(event):
                if not gesture["active"]:
                    return

                delta = event.y_root - gesture["last_y"]
                gesture["last_y"] = event.y_root
                gesture["remainder"] -= delta
                if abs(gesture["remainder"]) >= 10:
                    gesture["moved"] = True

                # One canvas unit is 24 px. Keep the fractional remainder so
                # slow swipes still move naturally instead of being ignored.
                units = int(gesture["remainder"] / 24)
                if units:
                    gesture["remainder"] -= units * 24
                    scroll_target.yview_scroll(units, "units")

                if gesture["moved"]:
                    return "break"

            def touch_release(event):
                was_drag = gesture["moved"]
                gesture["active"] = False
                gesture["remainder"] = 0
                gesture["moved"] = False
                if was_drag:
                    return "break"

            return touch_press, touch_move, touch_release

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

        log_touch_press, log_touch_move, log_touch_release = make_touch_scroll_handlers(self.log_text)
        self.log_text.bind("<ButtonPress-1>", log_touch_press, add="+")
        self.log_text.bind("<B1-Motion>", log_touch_move, add="+")
        self.log_text.bind("<ButtonRelease-1>", log_touch_release, add="+")
        self.log_text.bind("<MouseWheel>", scroll_log)
        self.log_text.bind("<Button-4>", scroll_log_linux)
        self.log_text.bind("<Button-5>", scroll_log_linux)

        if self.log_history:
            self.log_text.insert("end", "".join(self.log_history))
            self.log_text.see("end")

        if self.proc and self.proc.poll() is None:
            self.status_var.set(self.t("manual_wait") if self.manual_action_required else self.t("status_running"))
            self.start_btn.config(state="disabled")
            self.retry_btn.config(state="disabled")
            self.force_btn.config(state="disabled")

    def add_folder_row(self, parent, label, var, row):
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
            command=lambda: self.choose_folder(var),
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
        minutes = float(self.auto_next_delay_var.get().strip())
        if not math.isfinite(minutes) or minutes <= 0:
            raise ValueError
        return max(1, round(minutes * 60))

    def on_run_configuration_changed(self, *_):
        if self.proc and self.proc.poll() is None:
            self.current_run_intervened = True
        self.cancel_auto_next()

    def on_auto_next_toggle(self):
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
        active = self.auto_next_deadline is not None or self.auto_next_after_id is not None
        self.auto_next_token += 1
        if self.auto_next_after_id is not None:
            try:
                self.root.after_cancel(self.auto_next_after_id)
            except Exception:
                pass
        self.auto_next_after_id = None
        self.auto_next_deadline = None

        countdown_var = getattr(self, "auto_next_countdown_var", None)
        if countdown_var is not None:
            countdown_var.set("")
        self.set_auto_next_controls_visible(False)

        if active and announce:
            self.status_var.set(self.t("auto_cancelled"))
            self.log(f"\n=== {self.t('auto_cancelled')} ===\n")
        return active

    def schedule_auto_next(self):
        try:
            delay_seconds = self.get_auto_next_delay_seconds()
        except (TypeError, ValueError):
            self.status_var.set(self.t("process_done"))
            messagebox.showerror(self.t("error_title"), self.t("invalid_auto_next_delay"))
            return False

        self.cancel_auto_next()
        self.auto_next_token += 1
        token = self.auto_next_token
        self.auto_next_deadline = time.monotonic() + delay_seconds
        self.set_auto_next_controls_visible(True)
        batch_size = self.current_batch_result.get("requested_batch_size", "?")
        self.log(f"\n{self.t('auto_scheduled_log', count=batch_size, seconds=delay_seconds)}\n")
        self.update_auto_next_countdown(token)
        return True

    def update_auto_next_countdown(self, token):
        if token != self.auto_next_token or self.auto_next_deadline is None:
            return

        remaining = max(0, int(self.auto_next_deadline - time.monotonic() + 0.999))
        formatted = f"{remaining // 60:02d}:{remaining % 60:02d}"
        message = self.t("auto_countdown", time=formatted)
        self.status_var.set(message)
        self.auto_next_countdown_var.set(message)

        if remaining > 0:
            self.auto_next_after_id = self.root.after(
                1000,
                lambda: self.update_auto_next_countdown(token),
            )
            return

        self.auto_next_after_id = None
        self.auto_next_deadline = None
        self.set_auto_next_controls_visible(False)
        if self.auto_next_is_enabled() and not (self.proc and self.proc.poll() is None):
            self.log(f"\n{self.t('auto_running_log')}\n")
            self.start("main", auto_started=True)

    def run_auto_next_now(self):
        if self.auto_next_deadline is None:
            return
        self.cancel_auto_next()
        self.log(f"\n{self.t('auto_running_log')}\n")
        self.start("main", auto_started=True)

    def handle_worker_output(self, text):
        if text.startswith(BATCH_RESULT_PREFIX):
            try:
                result = json.loads(text[len(BATCH_RESULT_PREFIX):].strip())
                if not isinstance(result, dict):
                    raise ValueError("Batch result is not an object")
                self.current_batch_result = result
                self.log("\n" + self.t(
                    "batch_result_log",
                    success=result.get("success_count", 0),
                    selected=result.get("selected_count", 0),
                    failed=result.get("failure_count", 0),
                ) + "\n")
                return
            except (json.JSONDecodeError, ValueError):
                pass
        self.log(text)

    def get_auto_next_skip_reason(self, exit_code):
        if not self.auto_next_is_enabled() or self.current_run_mode != "main":
            return None
        if self.current_run_intervened:
            return "auto_skip_intervened", {}
        if exit_code != 0:
            return "auto_skip_process_error", {"code": exit_code}

        result = self.current_batch_result
        if not result:
            return "auto_skip_missing_result", {}
        if result.get("job", {}).get("state") in ("complete", "needs_retry"):
            return "auto_skip_no_more", {}

        try:
            selected = int(result.get("selected_count", 0))
            requested = int(result.get("requested_batch_size", 0))
            completed = int(result.get("completed_count", 0))
            succeeded = int(result.get("success_count", 0))
            failed = int(result.get("failure_count", 0))
            next_pending = int(result.get("next_pending_count", 0))
        except (TypeError, ValueError):
            return "auto_skip_missing_result", {}

        if requested < 1 or selected != requested:
            return "auto_skip_incomplete", {"count": requested}
        if completed != selected or succeeded != selected or failed:
            return "auto_skip_failed", {}
        if next_pending < 1:
            return "auto_skip_no_more", {}
        return "", {}

    def handle_process_done(self, exit_code):
        self.proc = None
        self.manual_action_required = False
        self.start_btn.config(state="normal")
        self.retry_btn.config(state="normal")
        self.force_btn.config(state="normal")
        self.continue_btn.config(state="disabled")

        job = (self.current_batch_result or {}).get("job", {})
        if exit_code == 0 and job.get("state") == "complete":
            self.cancel_auto_next()
            message = f"Job hoàn tất: {job['done']}/{job['total']} ảnh. Exit code: 0."
            self.status_var.set(message)
            self.log(f"\n=== {message} ===\n")
            return
        if exit_code == 2 and job.get("state") == "needs_retry":
            self.cancel_auto_next()
            message = f"Job đã dừng: còn {job['failed']} ảnh cần chạy lại. Exit code: 2."
            self.status_var.set(message)
            self.log(f"\n=== {message} ===\n")
            return

        reason, values = self.get_auto_next_skip_reason(exit_code) or (None, {})
        if reason == "":
            if self.schedule_auto_next():
                return
        elif reason is not None:
            self.log(f"\n{self.t(reason, **values)}\n")

        self.status_var.set(self.t("process_done"))

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
        profile_dir = self.profile_var.get().strip()
        if not profile_dir:
            if service_val == "gemini":
                profile_dir = str(DATA_DIR / "gemini_auto_profile")
            else:
                profile_dir = str(DATA_DIR / "chatgpt_auto_profile")
            self.profile_var.set(profile_dir)

        self.save_settings()

        env = os.environ.copy()
        env["IMAGE_FOLDER"] = self.image_var.get()
        env["DOWNLOAD_FOLDER"] = self.output_var.get()
        env["PROFILE_DIR"] = self.profile_var.get()
        env["BATCH_SIZE"] = self.batch_var.get()
        env["START_FROM"] = self.start_from_var.get()
        env["RUN_MODE"] = mode
        env["SERVICE"] = service_val
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        browser_path = APP_DIR / "ms-playwright"
        if getattr(sys, "frozen", False) or browser_path.exists():
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_path)

        # Some Python installations keep sqlite3.dll in DLLs rather than next
        # to python.exe. The worker is a fresh process, so make both locations
        # visible to Windows' DLL loader before starting it.
        if os.name == "nt":
            python_dir = Path(sys.executable).resolve().parent
            dll_dirs = [APP_DIR, python_dir, python_dir / "DLLs"]
            existing_path = env.get("PATH", "")
            env["PATH"] = os.pathsep.join(
                [str(path) for path in dll_dirs if path.exists()] + [existing_path]
            )

        self.current_done = 0
        self.current_total = 0
        self.manual_action_required = False
        self.current_run_mode = mode
        self.current_run_intervened = False
        self.current_batch_result = None
        self.progress_var.set(0)
        self.progress_label.set(self.t("progress_zero"))

        self.log(f"\n{self.t('log_start', mode=mode.upper())}\n")
        self.status_var.set(self.t("status_running"))
        self.start_btn.config(state="disabled")
        self.retry_btn.config(state="disabled")
        self.force_btn.config(state="disabled")
        self.continue_btn.config(state="disabled")

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        if getattr(sys, "frozen", False):
            command = [sys.executable, "--worker"]
        else:
            command = [sys.executable, "-u", str(SCRIPT_FILE)]

        self.proc = subprocess.Popen(
            command,
            cwd=str(APP_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            bufsize=1,
            creationflags=creationflags
        )

        threading.Thread(
            target=self.read_process_output,
            args=(self.proc,),
            daemon=True,
        ).start()

    def read_process_output(self, proc):
        try:
            for line in proc.stdout:
                self.log_queue.put(("line", line))
        except Exception as e:
            self.log_queue.put(("line", f"\n{self.t('log_read_error', error=e)}\n"))
        finally:
            code = proc.wait()
            self.log_queue.put(("line", f"\n=== KẾT THÚC, EXIT CODE: {code} ===\n"))
            self.log_queue.put(("done", code))

    def poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()

                if isinstance(msg, tuple) and msg[0] == "done":
                    self.handle_process_done(msg[1])
                elif isinstance(msg, tuple) and msg[0] == "line":
                    self.handle_worker_output(msg[1])
                else:
                    self.handle_worker_output(msg)

        except queue.Empty:
            pass

        self.root.after(200, self.poll_log_queue)

    def log(self, text):
        self.log_history.append(text)
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.update_progress_from_log(text)
        self.update_manual_button_from_log(text)

    def update_manual_button_from_log(self, text):
        if "MANUAL_ACTION_REQUIRED" in text:
            self.manual_action_required = True
            self.status_var.set(self.t("manual_wait"))
            self.continue_btn.config(state="normal")

    def update_progress_from_log(self, text):
        if "📌 Batch lần này:" in text:
            try:
                self.current_total = int(text.split(":")[-1].strip().split()[0])
                self.current_done = 0
                self.progress_var.set(0)
                self.progress_label.set(self.t("progress_count", done=0, total=self.current_total))
            except Exception:
                pass

        if "✓ DONE" in text or "✗ Lỗi:" in text:
            self.current_done += 1
            total = max(self.current_total, 1)
            percent = self.current_done / total * 100
            self.progress_var.set(percent)
            self.progress_label.set(self.t("progress_percent", done=self.current_done, total=total, percent=percent))

    def send_continue(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write("\n")
                self.proc.stdin.flush()
                self.current_run_intervened = True
                self.manual_action_required = False
                self.continue_btn.config(state="disabled")
                self.status_var.set(self.t("continue_sent"))
                self.log(f"\n{self.t('log_continue_sent')}\n")
            except Exception as e:
                messagebox.showerror(self.t("error_title"), self.t("continue_error", error=e))

    def stop(self):
        cancelled_auto_run = self.cancel_auto_next(announce=True)
        if self.proc and self.proc.poll() is None:
            pid = self.proc.pid
            self.current_run_intervened = True

            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                self.proc.terminate()

            self.status_var.set(self.t("stopped"))
            self.manual_action_required = False
            self.log(f"\n{self.t('log_stopped')}\n")
        elif not cancelled_auto_run:
            self.status_var.set(self.t("no_process"))

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
        self.log_history.clear()
        self.log_text.delete("1.0", "end")

    def on_close(self):
        self.cancel_auto_next()
        if self.proc and self.proc.poll() is None:
            self.stop()
        self.root.destroy()


if __name__ == "__main__":
    enable_windows_dpi_awareness()
    if "--worker" in sys.argv:
        run_packaged_worker()
        raise SystemExit(0)

    root = ctk.CTk()
    app = ChatGPTBatchApp(root)
    root.mainloop()
