"""Native desktop identity helpers shared by the Tk and webview shells."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
from typing import Any


WINDOWS_APP_USER_MODEL_ID = "ChatGPT.BatchImageTranslator"

GWL_STYLE = -16
WS_MINIMIZEBOX = 0x00020000
WS_SYSMENU = 0x00080000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020


def set_windows_app_user_model_id() -> bool:
    """Give source and packaged launches their own Windows taskbar identity."""
    if sys.platform != "win32":
        return False

    try:
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_USER_MODEL_ID
        )
    except (AttributeError, OSError):
        return False
    return result == 0


def _extract_hwnd(target: Any) -> int | None:
    """Extract a native Win32 HWND from an integer or pywebview Window."""
    if isinstance(target, int):
        return target if target > 0 else None

    native = getattr(target, "native", target)
    handle = getattr(native, "Handle", None)
    if handle is not None:
        try:
            if hasattr(handle, "ToInt64"):
                hwnd = int(handle.ToInt64())
            elif hasattr(handle, "ToInt32"):
                hwnd = int(handle.ToInt32())
            else:
                hwnd = int(handle)
            return hwnd if hwnd > 0 else None
        except (ValueError, TypeError, OverflowError):
            pass
    return None


def enable_windows_taskbar_minimize(target: Any) -> bool:
    """Ensure a frameless pywebview window can be minimized/restored via the taskbar icon.

    Frameless windows on Windows (such as WinForms FormBorderStyle.None in pywebview)
    have WS_MINIMIZEBOX and WS_SYSMENU stripped by default. Without WS_MINIMIZEBOX,
    clicking the active window's taskbar icon does not minimize it to the taskbar.
    Adding WS_MINIMIZEBOX and WS_SYSMENU restores the native click-to-minimize behavior
    without introducing unwanted OS titlebars.
    """
    if sys.platform != "win32":
        return False

    hwnd = _extract_hwnd(target)
    if not hwnd:
        return False

    try:
        user32 = ctypes.windll.user32
        get_window_long = getattr(user32, "GetWindowLongPtrW", getattr(user32, "GetWindowLongW", None))
        set_window_long = getattr(user32, "SetWindowLongPtrW", getattr(user32, "SetWindowLongW", None))
        if get_window_long is None or set_window_long is None:
            return False

        get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_window_long.restype = ctypes.c_ssize_t
        set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_window_long.restype = ctypes.c_ssize_t

        current_style = get_window_long(hwnd, GWL_STYLE)
        target_flags = WS_MINIMIZEBOX | WS_SYSMENU
        if (current_style & target_flags) == target_flags:
            return True

        new_style = current_style | target_flags
        set_window_long(hwnd, GWL_STYLE, new_style)

        set_window_pos = getattr(user32, "SetWindowPos", None)
        if set_window_pos is not None:
            set_window_pos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
            )
        return True
    except Exception:
        return False
