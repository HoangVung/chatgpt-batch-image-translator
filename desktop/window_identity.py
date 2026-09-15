"""Native desktop identity helpers shared by the Tk and webview shells."""

from __future__ import annotations

import ctypes
import sys


WINDOWS_APP_USER_MODEL_ID = "ChatGPT.BatchImageTranslator"


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
