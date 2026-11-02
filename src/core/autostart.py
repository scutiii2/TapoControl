"""Start with Windows: a per-user Run key, no admin needed."""
import sys
import winreg
from pathlib import Path

KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "TapoControl"


def command() -> str:
    """Launch line for the registry; `--minimized` keeps the window hidden in the tray."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    return f'"{sys.executable}" "{Path(__file__).resolve().parents[2] / "run.py"}" --minimized'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            winreg.QueryValueEx(key, NAME)
        return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass
