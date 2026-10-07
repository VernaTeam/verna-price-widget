"""Start with Windows: one value under the current user's Run key, nothing else.

Only the built exe can be registered; a source checkout has no stable command to run.
The value is written when the user ticks the box in the settings view and removed when
they untick it.
"""

from __future__ import annotations

import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def command() -> str | None:
    """What the Run value should hold, or None when this is not the built exe."""
    return f'"{sys.executable}"' if getattr(sys, "frozen", False) else None


def read(name: str, key_path: str = RUN_KEY) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, kind = winreg.QueryValueEx(key, name)
            return value if kind == winreg.REG_SZ else None
    except OSError:
        return None


def is_enabled(name: str, key_path: str = RUN_KEY) -> bool:
    """True only if the value points at this exe (a moved exe counts as not enabled)."""
    wanted = command()
    return wanted is not None and read(name, key_path) == wanted


def set_enabled(name: str, on: bool, key_path: str = RUN_KEY, value: str | None = None) -> bool:
    """Write or remove the value. Returns whether it is set afterwards."""
    value = value if value is not None else command()
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if on and value:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            else:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
    except OSError:
        pass
    return read(name, key_path) is not None
