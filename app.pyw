import os
import sys
import csv
import json
import queue
import shutil
import threading
import subprocess
import ctypes
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
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
SETTINGS_FILE = APP_DIR / "app_settings.json"

DEFAULT_SETTINGS = {
    "image_folder": str(APP_DIR / "images"),
    "download_folder": str(APP_DIR / "images_vn"),
    "profile_dir": str(APP_DIR / "chatgpt_auto_profile"),
    "batch_size": "5",
    "start_from": "",
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
        "open_output": "Mở kết quả",
        "export_failed": "Xuất lỗi",
        "copy_failed": "Copy lỗi",
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
        "no_failed": "Không có ảnh lỗi.",
        "exported_failed_log": "=== Đã xuất lỗi: {path} ===",
        "exported_failed": "Đã xuất {count} dòng lỗi.",
        "copy_retry_log": "=== Copy lỗi retry ===\nĐã copy: {count}\nThư mục: {path}",
        "missing_count": "Không tìm thấy: {count} file",
        "copied_failed": "Đã copy {count} ảnh lỗi sang:\n{path}"
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
        "open_output": "Open output",
        "export_failed": "Export failures",
        "copy_failed": "Copy failures",
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
        "no_failed": "No failed images.",
        "exported_failed_log": "=== Exported failures: {path} ===",
        "exported_failed": "Exported {count} failed rows.",
        "copy_retry_log": "=== Copy failures for retry ===\nCopied: {count}\nFolder: {path}",
        "missing_count": "Missing: {count} files",
        "copied_failed": "Copied {count} failed images to:\n{path}"
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

    run_chatgpt_batch.main()


class ChatGPTBatchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ChatGPT Batch Translator PRO")
        self.root.geometry("1280x840")
        self.root.minsize(1120, 720)

        self.proc = None
        self.log_queue = queue.Queue()
        self.current_done = 0
        self.current_total = 0

        self.settings = self.load_settings()

        self.setup_style()
        self.build_ui()
        self.poll_log_queue()

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

        self.settings["language"] = code
        self.save_settings()
        for child in self.root.winfo_children():
            child.destroy()
        self.build_ui()

    def set_theme(self, code):
        if code == self.theme_code():
            return

        self.settings["theme"] = code
        self.save_settings()
        self.setup_style()
        for child in self.root.winfo_children():
            child.destroy()
        self.build_ui()

    def add_header_menu(self, parent, label, current_text, choices, command, width):
        c = self.colors
        box = tk.Frame(parent, bg=c["chrome_bg"])
        box.pack(side="right", padx=(14, 0))

        tk.Label(
            box,
            text=label,
            bg=c["chrome_bg"],
            fg=c["text"],
            font=("Segoe UI", 10, "bold")
        ).pack(side="left", padx=(0, 8))

        value = tk.StringVar(value=current_text)
        button = tk.Menubutton(
            box,
            textvariable=value,
            bg=c["input_bg"],
            fg=c["text"],
            activebackground=c["gray_btn"],
            activeforeground=c["text"],
            relief="solid",
            bd=1,
            padx=12,
            pady=6,
            width=width,
            anchor="w",
            font=("Segoe UI", 10),
            cursor="hand2"
        )
        button.pack(side="left")

        menu = tk.Menu(
            button,
            tearoff=False,
            bg=c["card_bg"],
            fg=c["text"],
            activebackground=c["selection"],
            activeforeground=c["text"],
            relief="flat",
            bd=0,
            font=("Segoe UI", 10)
        )
        for code, text in choices:
            menu.add_command(label=text, command=lambda item_code=code: command(item_code))

        button.configure(menu=menu)
        return button

    def get_palette(self):
        if self.effective_theme_code() == "dark":
            return {
                "app_bg": "#111827",
                "chrome_bg": "#1f2937",
                "sidebar_bg": "#182230",
                "card_bg": "#243041",
                "input_bg": "#111827",
                "log_bg": "#0b1220",
                "text": "#f9fafb",
                "muted": "#cbd5e1",
                "field": "#e5e7eb",
                "border": "#475467",
                "gray_btn": "#344054",
                "gray_btn_active": "#475467",
                "scroll_track": "#1f2937",
                "scroll_thumb": "#9aa4b2",
                "scroll_arrow": "#d0d5dd",
                "selection": "#355f9f"
            }

        return {
            "app_bg": "#eef0f4",
            "chrome_bg": "#f7f7fa",
            "sidebar_bg": "#e8ebf0",
            "card_bg": "#ffffff",
            "input_bg": "#fbfcfe",
            "log_bg": "#f8fafc",
            "text": "#111827",
            "muted": "#667085",
            "field": "#344054",
            "border": "#d0d5dd",
            "gray_btn": "#f2f4f7",
            "gray_btn_active": "#e4e7ec",
            "scroll_track": "#e4e7ec",
            "scroll_thumb": "#98a2b3",
            "scroll_arrow": "#344054",
            "selection": "#c7ddff"
        }

    def setup_style(self):
        self.colors = self.get_palette()
        c = self.colors

        self.root.configure(bg=c["app_bg"])
        self.apply_window_theme()

        self.style = ttk.Style()
        self.style.theme_use("clam")

        self.style.configure("TFrame", background=c["app_bg"])
        self.style.configure("App.TFrame", background=c["app_bg"])
        self.style.configure("Chrome.TFrame", background=c["chrome_bg"])
        self.style.configure("Sidebar.TFrame", background=c["sidebar_bg"])
        self.style.configure("Main.TFrame", background=c["app_bg"])
        self.style.configure("Card.TFrame", background=c["card_bg"], relief="flat")
        self.style.configure("Toolbar.TFrame", background=c["card_bg"], relief="flat")

        self.style.configure(
            "Title.TLabel",
            background=c["app_bg"],
            foreground=c["text"],
            font=("Segoe UI", 17, "bold")
        )

        self.style.configure(
            "Sub.TLabel",
            background=c["app_bg"],
            foreground=c["muted"],
            font=("Segoe UI", 9)
        )

        self.style.configure(
            "ChromeTitle.TLabel",
            background=c["chrome_bg"],
            foreground=c["text"],
            font=("Segoe UI", 10, "bold")
        )

        self.style.configure(
            "SidebarTitle.TLabel",
            background=c["sidebar_bg"],
            foreground=c["text"],
            font=("Segoe UI", 13, "bold")
        )

        self.style.configure(
            "SidebarSub.TLabel",
            background=c["sidebar_bg"],
            foreground=c["muted"],
            font=("Segoe UI", 9)
        )

        self.style.configure(
            "SectionTitle.TLabel",
            background=c["card_bg"],
            foreground=c["text"],
            font=("Segoe UI", 10, "bold")
        )

        self.style.configure(
            "SectionHint.TLabel",
            background=c["card_bg"],
            foreground=c["muted"],
            font=("Segoe UI", 9)
        )

        self.style.configure(
            "Field.TLabel",
            background=c["card_bg"],
            foreground=c["field"],
            font=("Segoe UI", 9)
        )

        self.style.configure(
            "TLabel",
            background=c["card_bg"],
            foreground=c["text"],
            font=("Segoe UI", 10)
        )

        self.style.configure(
            "TEntry",
            fieldbackground=c["input_bg"],
            background=c["input_bg"],
            foreground=c["text"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            font=("Segoe UI", 10),
            padding=8
        )

        self.style.configure(
            "TCombobox",
            fieldbackground=c["input_bg"],
            background=c["input_bg"],
            foreground=c["text"],
            bordercolor=c["border"],
            arrowcolor=c["text"],
            selectbackground=c["selection"],
            selectforeground=c["text"]
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", c["input_bg"]), ("!disabled", c["input_bg"])],
            background=[("readonly", c["input_bg"]), ("!disabled", c["input_bg"])],
            foreground=[("readonly", c["text"]), ("!disabled", c["text"])],
            selectbackground=[("readonly", c["selection"])],
            selectforeground=[("readonly", c["text"])]
        )

        self.style.configure(
            "Blue.TButton",
            background="#0a84ff",
            foreground="white",
            font=("Segoe UI", 10, "bold"),
            padding=(14, 8),
            borderwidth=0
        )

        self.style.map("Blue.TButton", background=[("active", "#006edb"), ("disabled", "#93c5fd")])

        self.style.configure(
            "Purple.TButton",
            background="#5856d6",
            foreground="white",
            font=("Segoe UI", 10, "bold"),
            padding=(14, 8),
            borderwidth=0
        )

        self.style.map("Purple.TButton", background=[("active", "#4745b8"), ("disabled", "#c4b5fd")])

        self.style.configure(
            "Green.TButton",
            background="#34c759",
            foreground="white",
            font=("Segoe UI", 10, "bold"),
            padding=(14, 8),
            borderwidth=0
        )

        self.style.map("Green.TButton", background=[("active", "#248a3d"), ("disabled", "#a6e7b7")])

        self.style.configure(
            "Red.TButton",
            background="#ff3b30",
            foreground="white",
            font=("Segoe UI", 10, "bold"),
            padding=(14, 8),
            borderwidth=0
        )

        self.style.map("Red.TButton", background=[("active", "#d92d20")])

        self.style.configure(
            "Gray.TButton",
            background=c["gray_btn"],
            foreground=c["text"],
            font=("Segoe UI", 10),
            padding=(12, 8),
            borderwidth=0
        )

        self.style.map("Gray.TButton", background=[("active", c["gray_btn_active"])])

        self.style.configure(
            "Ghost.TButton",
            background=c["card_bg"],
            foreground=c["field"],
            font=("Segoe UI", 10),
            padding=(12, 7),
            borderwidth=0
        )

        self.style.map("Ghost.TButton", background=[("active", c["gray_btn"])])

        self.style.configure(
            "Horizontal.TProgressbar",
            troughcolor=c["gray_btn_active"],
            background="#0a84ff",
            thickness=10,
            bordercolor=c["gray_btn_active"],
            lightcolor="#0a84ff",
            darkcolor="#0a84ff"
        )

        self.style.configure(
            "Dark.Vertical.TScrollbar",
            troughcolor=c["log_bg"],
            background=c["gray_btn_active"],
            bordercolor=c["log_bg"],
            arrowcolor=c["muted"],
            lightcolor=c["gray_btn_active"],
            darkcolor=c["gray_btn_active"],
            relief="flat",
            width=14
        )
        self.style.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", c["border"]), ("pressed", c["border"])],
            arrowcolor=[("active", c["text"])]
        )

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
        data = {
            **self.settings,
            "image_folder": self.image_var.get(),
            "download_folder": self.output_var.get(),
            "profile_dir": self.profile_var.get(),
            "batch_size": self.batch_var.get(),
            "start_from": self.start_from_var.get(),
            "theme": self.theme_code(),
            "language": self.language_code(),
            "service": service_map.get(self.service_var.get(), "chatgpt")
        }

        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def build_ui(self):
        c = self.colors
        outer = ttk.Frame(self.root, style="App.TFrame")
        outer.pack(fill="both", expand=True)

        chrome = ttk.Frame(outer, style="Chrome.TFrame", padding=(18, 9))
        chrome.pack(fill="x")

        dots = tk.Frame(chrome, bg=c["chrome_bg"])
        dots.pack(side="left", padx=(0, 14))
        for color in ("#ff5f57", "#febc2e", "#28c840"):
            tk.Label(dots, text="●", fg=color, bg=c["chrome_bg"], font=("Segoe UI", 11)).pack(side="left", padx=2)

        ttk.Label(
            chrome,
            text="ChatGPT Batch Translator PRO",
            style="ChromeTitle.TLabel"
        ).pack(side="left")

        self.add_header_menu(
            chrome,
            self.t("theme"),
            self.current_theme_label(),
            list(THEME_OPTIONS[self.language_code()].items()),
            self.set_theme,
            15
        )
        self.add_header_menu(
            chrome,
            self.t("language"),
            self.current_language_label(),
            list(LANGUAGE_OPTIONS.items()),
            self.set_language,
            12
        )

        body = ttk.Frame(outer, style="App.TFrame", padding=(14, 14, 14, 14))
        body.pack(fill="both", expand=True)

        sidebar = ttk.Frame(body, style="Sidebar.TFrame", padding=(16, 16))
        sidebar.pack(side="left", fill="y", padx=(0, 14))
        sidebar.pack_propagate(False)
        sidebar.configure(width=280)

        ttk.Label(
            sidebar,
            text=self.t("sidebar_title"),
            style="SidebarTitle.TLabel",
            wraplength=230,
            justify="left"
        ).pack(anchor="w")
        ttk.Label(
            sidebar,
            text=self.t("sidebar_desc"),
            style="SidebarSub.TLabel",
            wraplength=235,
            justify="left"
        ).pack(anchor="w", pady=(4, 12))

        self.status_var = tk.StringVar(value=self.t("status_ready"))
        status_box = tk.Frame(sidebar, bg=c["card_bg"], padx=12, pady=10)
        status_box.pack(fill="x", pady=(0, 10))
        tk.Label(
            status_box,
            text=self.t("status_label"),
            bg=c["card_bg"],
            fg=c["muted"],
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w")
        tk.Label(
            status_box,
            textvariable=self.status_var,
            bg=c["card_bg"],
            fg=c["text"],
            font=("Segoe UI", 10, "bold"),
            wraplength=220,
            justify="left"
        ).pack(anchor="w", pady=(6, 0))

        self.progress_var = tk.DoubleVar(value=0)
        progress_box = tk.Frame(sidebar, bg=c["card_bg"], padx=12, pady=10)
        progress_box.pack(fill="x", pady=(0, 10))
        tk.Label(
            progress_box,
            text=self.t("progress_label"),
            bg=c["card_bg"],
            fg=c["muted"],
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w")
        ttk.Progressbar(
            progress_box,
            variable=self.progress_var,
            maximum=100,
            style="Horizontal.TProgressbar"
        ).pack(fill="x", pady=(8, 5))

        self.progress_label = tk.StringVar(value=self.t("progress_zero"))
        tk.Label(
            progress_box,
            textvariable=self.progress_label,
            bg=c["card_bg"],
            fg=c["muted"],
            font=("Segoe UI", 9),
            wraplength=220,
            justify="left"
        ).pack(anchor="w")

        ttk.Label(sidebar, text=self.t("quick_actions"), style="SidebarSub.TLabel").pack(anchor="w", pady=(6, 6))
        ttk.Button(sidebar, text=self.t("open_output"), command=self.open_output, style="Ghost.TButton").pack(fill="x", pady=2)
        ttk.Button(sidebar, text=self.t("export_failed"), command=self.export_failed, style="Ghost.TButton").pack(fill="x", pady=2)
        ttk.Button(sidebar, text=self.t("copy_failed"), command=self.copy_failed_retry, style="Ghost.TButton").pack(fill="x", pady=2)
        ttk.Button(sidebar, text=self.t("save_config"), command=self.save_and_notify, style="Ghost.TButton").pack(fill="x", pady=2)
        ttk.Button(sidebar, text=self.t("clear_log"), command=self.clear_log, style="Ghost.TButton").pack(fill="x", pady=2)

        main = ttk.Frame(body, style="Main.TFrame")
        main.pack(side="left", fill="both", expand=True)

        header = ttk.Frame(main, style="Main.TFrame")
        header.pack(fill="x", pady=(0, 8))

        ttk.Label(header, text=self.t("dashboard"), style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text=self.t("dashboard_desc"),
            style="Sub.TLabel"
        ).pack(anchor="w", pady=(2, 0))

        self.image_var = tk.StringVar(value=self.settings["image_folder"])
        self.output_var = tk.StringVar(value=self.settings["download_folder"])
        self.profile_var = tk.StringVar(value=self.settings["profile_dir"])
        self.batch_var = tk.StringVar(value=self.settings["batch_size"])
        self.start_from_var = tk.StringVar(value=self.settings.get("start_from", ""))
        
        current_service = self.settings.get("service", "chatgpt")
        display_service = "Google Gemini" if current_service == "gemini" else "ChatGPT"
        self.service_var = tk.StringVar(value=display_service)

        config_card = ttk.Frame(main, style="Card.TFrame", padding=(14, 10))
        config_card.pack(fill="x", pady=(0, 8))

        ttk.Label(config_card, text=self.t("data_config"), style="SectionTitle.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 2)
        )
        ttk.Label(
            config_card,
            text=self.t("data_hint"),
            style="SectionHint.TLabel"
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 6))

        ttk.Label(config_card, text=self.t("service"), style="Field.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 12), pady=3
        )
        self.service_combo = ttk.Combobox(
            config_card,
            textvariable=self.service_var,
            values=["ChatGPT", "Google Gemini"],
            state="readonly",
            width=22
        )
        self.service_combo.grid(row=2, column=1, sticky="w", pady=3)

        def on_service_change(event=None):
            val = self.service_var.get()
            current_profile = self.profile_var.get()
            if val == "Google Gemini" and "chatgpt_auto_profile" in current_profile:
                new_profile = current_profile.replace("chatgpt_auto_profile", "gemini_auto_profile")
                self.profile_var.set(new_profile)
            elif val == "ChatGPT" and "gemini_auto_profile" in current_profile:
                new_profile = current_profile.replace("gemini_auto_profile", "chatgpt_auto_profile")
                self.profile_var.set(new_profile)

        self.service_combo.bind("<<ComboboxSelected>>", on_service_change)

        self.add_folder_row(config_card, self.t("source_folder"), self.image_var, 3)
        self.add_folder_row(config_card, self.t("output_folder"), self.output_var, 4)
        self.add_folder_row(config_card, self.t("profile"), self.profile_var, 5)

        ttk.Label(config_card, text=self.t("batch_size"), style="Field.TLabel").grid(
            row=6, column=0, sticky="w", padx=(0, 12), pady=(5, 3)
        )
        ttk.Entry(config_card, textvariable=self.batch_var, width=12).grid(row=6, column=1, sticky="w", pady=(5, 3))

        ttk.Label(config_card, text=self.t("start_from"), style="Field.TLabel").grid(
            row=7, column=0, sticky="w", padx=(0, 12), pady=3
        )
        ttk.Entry(config_card, textvariable=self.start_from_var, width=24).grid(row=7, column=1, sticky="w", pady=3)

        ttk.Label(
            config_card,
            text=self.t("start_hint"),
            style="SectionHint.TLabel"
        ).grid(row=8, column=1, sticky="w", pady=(0, 3))

        config_card.columnconfigure(1, weight=1)

        action_card = ttk.Frame(main, style="Toolbar.TFrame", padding=(14, 8))
        action_card.pack(fill="x", pady=(0, 8))

        self.start_btn = ttk.Button(
            action_card,
            text=self.t("new_batch"),
            command=lambda: self.start("main"),
            style="Blue.TButton"
        )
        self.start_btn.pack(side="left", padx=(0, 8))

        self.retry_btn = ttk.Button(
            action_card,
            text=self.t("retry_failed"),
            command=lambda: self.start("retry"),
            style="Purple.TButton"
        )
        self.retry_btn.pack(side="left", padx=8)

        self.force_btn = ttk.Button(
            action_card,
            text=self.t("rerun_image"),
            command=lambda: self.start("force"),
            style="Gray.TButton"
        )
        self.force_btn.pack(side="left", padx=8)

        self.continue_btn = ttk.Button(
            action_card,
            text=self.t("continue_manual"),
            command=self.send_continue,
            style="Green.TButton",
            state="disabled"
        )
        self.continue_btn.pack(side="left", padx=8)

        self.stop_btn = ttk.Button(
            action_card,
            text=self.t("stop"),
            command=self.stop,
            style="Red.TButton"
        )
        self.stop_btn.pack(side="left", padx=8)

        log_card = ttk.Frame(main, style="Card.TFrame", padding=(14, 10))
        log_card.pack(fill="both", expand=True)

        ttk.Label(
            log_card,
            text=self.t("process_log"),
            style="SectionTitle.TLabel"
        ).pack(anchor="w", pady=(0, 6))

        log_body = tk.Frame(log_card, bg=c["log_bg"])
        log_body.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_body,
            wrap="word",
            font=("Cascadia Mono", 10),
            bg=c["log_bg"],
            fg=c["text"],
            insertbackground=c["text"],
            selectbackground=c["selection"],
            selectforeground=c["text"],
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=12,
            height=16
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_scroll_canvas = tk.Canvas(
            log_body,
            width=18,
            bg=c["scroll_track"],
            highlightthickness=0,
            bd=0,
            cursor="hand2"
        )
        self.log_scroll_canvas.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=self.update_log_scrollbar)
        self.log_scroll_canvas.bind("<Button-1>", self.on_log_scrollbar_click)
        self.log_scroll_canvas.bind("<B1-Motion>", self.on_log_scrollbar_drag)
        self.log_scroll_canvas.bind("<Configure>", lambda event: self.update_log_scrollbar(*self.log_text.yview()))
        self.root.after(50, lambda: self.update_log_scrollbar(*self.log_text.yview()))

        if self.proc and self.proc.poll() is None:
            self.status_var.set(self.t("status_running"))
            self.start_btn.config(state="disabled")
            self.retry_btn.config(state="disabled")
            self.force_btn.config(state="disabled")

    def update_log_scrollbar(self, first, last):
        if not hasattr(self, "log_scroll_canvas"):
            return

        c = self.colors
        canvas = self.log_scroll_canvas
        first = float(first)
        last = float(last)
        width = int(canvas.winfo_width() or 18)
        height = int(canvas.winfo_height() or 1)
        arrow_h = 18
        track_top = arrow_h
        track_bottom = max(track_top + 1, height - arrow_h)
        track_height = track_bottom - track_top
        thumb_top = track_top + int(track_height * first)
        thumb_bottom = track_top + int(track_height * last)
        if thumb_bottom - thumb_top < 22:
            thumb_bottom = min(track_bottom, thumb_top + 22)

        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill=c["scroll_track"], outline="")
        canvas.create_polygon(
            width // 2, 5,
            width // 2 - 5, 12,
            width // 2 + 5, 12,
            fill=c["scroll_arrow"],
            outline=""
        )
        canvas.create_rectangle(
            width // 2 - 4,
            thumb_top,
            width // 2 + 4,
            thumb_bottom,
            fill=c["scroll_thumb"],
            outline=""
        )
        canvas.create_polygon(
            width // 2 - 5, height - 12,
            width // 2 + 5, height - 12,
            width // 2, height - 5,
            fill=c["scroll_arrow"],
            outline=""
        )

    def on_log_scrollbar_click(self, event):
        height = int(self.log_scroll_canvas.winfo_height() or 1)
        arrow_h = 18
        if event.y < arrow_h:
            self.log_text.yview_scroll(-1, "units")
            return
        if event.y > height - arrow_h:
            self.log_text.yview_scroll(1, "units")
            return
        self.on_log_scrollbar_drag(event)

    def on_log_scrollbar_drag(self, event):
        height = int(self.log_scroll_canvas.winfo_height() or 1)
        arrow_h = 18
        track_height = max(1, height - arrow_h * 2)
        fraction = (event.y - arrow_h) / track_height
        self.log_text.yview_moveto(min(max(fraction, 0), 1))

    def add_folder_row(self, parent, label, var, row):
        ttk.Label(parent, text=label, style="Field.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(
            parent,
            text=self.t("choose"),
            command=lambda: self.choose_folder(var),
            style="Gray.TButton"
        ).grid(row=row, column=2, padx=(10, 0), pady=3)

    def choose_folder(self, var):
        folder = filedialog.askdirectory()
        if folder:
            var.set(folder)

    def save_and_notify(self):
        self.save_settings()
        messagebox.showinfo("OK", self.t("saved_config"))

    def start(self, mode):
        if self.proc and self.proc.poll() is None:
            messagebox.showwarning(self.t("running_title"), self.t("running_message"))
            return

        if mode == "force" and not self.start_from_var.get().strip():
            messagebox.showwarning(
                self.t("missing_image_title"),
                self.t("missing_image_message")
            )
            return

        if not getattr(sys, "frozen", False) and not SCRIPT_FILE.exists():
            messagebox.showerror(self.t("error_title"), self.t("file_missing", path=SCRIPT_FILE))
            return

        service_map = {"ChatGPT": "chatgpt", "Google Gemini": "gemini", "chatgpt": "chatgpt", "gemini": "gemini"}
        service_val = service_map.get(self.service_var.get(), "chatgpt")
        profile_dir = self.profile_var.get().strip()
        if not profile_dir:
            if service_val == "gemini":
                profile_dir = str(APP_DIR / "gemini_auto_profile")
            else:
                profile_dir = str(APP_DIR / "chatgpt_auto_profile")
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

        self.current_done = 0
        self.current_total = 0
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

        threading.Thread(target=self.read_process_output, daemon=True).start()

    def read_process_output(self):
        try:
            for line in self.proc.stdout:
                self.log_queue.put(line)
        except Exception as e:
            self.log_queue.put(f"\n{self.t('log_read_error', error=e)}\n")
        finally:
            code = self.proc.wait()
            self.log_queue.put(f"\n=== KẾT THÚC, EXIT CODE: {code} ===\n")
            self.log_queue.put("__PROCESS_DONE__")

    def poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()

                if msg == "__PROCESS_DONE__":
                    self.status_var.set(self.t("process_done"))
                    self.start_btn.config(state="normal")
                    self.retry_btn.config(state="normal")
                    self.force_btn.config(state="normal")
                    self.continue_btn.config(state="disabled")
                else:
                    self.log(msg)

        except queue.Empty:
            pass

        self.root.after(200, self.poll_log_queue)

    def log(self, text):
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.update_progress_from_log(text)
        self.update_manual_button_from_log(text)

    def update_manual_button_from_log(self, text):
        if "MANUAL_ACTION_REQUIRED" in text:
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
                self.continue_btn.config(state="disabled")
                self.status_var.set(self.t("continue_sent"))
                self.log(f"\n{self.t('log_continue_sent')}\n")
            except Exception as e:
                messagebox.showerror(self.t("error_title"), self.t("continue_error", error=e))

    def stop(self):
        if self.proc and self.proc.poll() is None:
            pid = self.proc.pid

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
            self.log(f"\n{self.t('log_stopped')}\n")
        else:
            self.status_var.set(self.t("no_process"))

    def open_output(self):
        folder = self.output_var.get()
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)

    def export_failed(self):
        progress_file = Path(self.output_var.get()) / "progress.csv"
        failed_file = Path(self.output_var.get()) / "failed_list.csv"

        if not progress_file.exists():
            messagebox.showerror(self.t("error_title"), self.t("file_missing", path=progress_file))
            return

        rows = []

        with open(progress_file, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("status") or "").lower() in ["fail", "failed", "manual", "error"]:
                    rows.append(row)

        if not rows:
            messagebox.showinfo("OK", self.t("no_failed"))
            return

        with open(failed_file, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["index", "file", "output", "status", "time", "note"])
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "index": row.get("index", ""),
                    "file": row.get("file", ""),
                    "output": row.get("output", ""),
                    "status": row.get("status", ""),
                    "time": row.get("time", ""),
                    "note": row.get("note", "")
                })

        self.log(f"\n{self.t('exported_failed_log', path=failed_file)}\n")
        messagebox.showinfo("OK", self.t("exported_failed", count=len(rows)))

    def copy_failed_retry(self):
        image_folder = Path(self.image_var.get())
        output_folder = Path(self.output_var.get())
        progress_file = output_folder / "progress.csv"
        retry_folder = output_folder / "failed_retry"

        if not progress_file.exists():
            messagebox.showerror(self.t("error_title"), self.t("file_missing", path=progress_file))
            return

        retry_folder.mkdir(parents=True, exist_ok=True)

        latest = {}

        with open(progress_file, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                file_name = row.get("file", "")
                if file_name:
                    latest[file_name] = row

        failed_files = [
            name for name, row in latest.items()
            if (row.get("status") or "").lower() in ["fail", "failed", "manual", "error"]
        ]

        copied = 0
        missing = []

        for name in failed_files:
            src = image_folder / name
            dst = retry_folder / name

            if src.exists():
                shutil.copy2(src, dst)
                copied += 1
            else:
                missing.append(name)

        self.log(f"\n{self.t('copy_retry_log', count=copied, path=retry_folder)}\n")

        if missing:
            missing_file = retry_folder / "missing_files.txt"
            with open(missing_file, "w", encoding="utf-8") as f:
                for name in missing:
                    f.write(name + "\n")
            self.log(f"{self.t('missing_count', count=len(missing))}\n")

        messagebox.showinfo("OK", self.t("copied_failed", count=copied, path=retry_folder))

    def clear_log(self):
        self.log_text.delete("1.0", "end")


if __name__ == "__main__":
    enable_windows_dpi_awareness()
    if "--worker" in sys.argv:
        run_packaged_worker()
        raise SystemExit(0)

    root = tk.Tk()
    app = ChatGPTBatchApp(root)
    root.mainloop()
