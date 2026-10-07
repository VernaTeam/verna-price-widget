"""Windows pieces pywebview does not offer: tray icon, window opacity, no taskbar button,
docking beside the clock, and waking the running copy from a second launch.

Window calls take the raw HWND and go through user32, so they work from any thread. The
tray icon is WinForms (already loaded by pywebview) and must be built on the GUI thread.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, wt.LONG]
user32.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.COLORREF, wt.BYTE, wt.DWORD]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wt.UINT]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
kernel32.CreateEventW.restype = wt.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
kernel32.OpenEventW.restype = wt.HANDLE
kernel32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
kernel32.SetEvent.argtypes = [wt.HANDLE]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
gdi32.CreateRoundRectRgn.restype = wt.HANDLE
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
user32.SetWindowRgn.argtypes = [wt.HWND, wt.HANDLE, wt.BOOL]

KEY_RGB = (1, 2, 3)  # the form's background, cut out of the window while it is keyed
KEY_HEX = "#%02x%02x%02x" % KEY_RGB
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_LAYERED = 0x80, 0x40000, 0x80000
LWA_COLORKEY, LWA_ALPHA = 1, 2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
DOCK_MARGIN = 12


def prepare_window(hwnd: int) -> None:
    """No taskbar button (the tray icon stands in for it) and ready for set_layer().

    Form.ShowInTaskbar and Form.Opacity are avoided on purpose: the first recreates the
    window handle under WebView2, the second rewrites the extended style and would undo
    the tool-window bit. Call before the window is first shown.
    """
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style = (style | WS_EX_TOOLWINDOW | WS_EX_LAYERED) & ~WS_EX_APPWINDOW
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def make_see_through(form) -> None:
    """GUI thread, before the first show: let the page decide where the window is solid.

    WebView2 draws with a transparent background over the form, and the form is painted in
    KEY_COLOR, which set_layer(keyed=True) turns into a hole. Keying only works this way
    round: a colour key never cuts through pixels WebView2 itself drew (tried 2026-10-01).
    """
    from System.Drawing import Color

    form.BackColor = Color.FromArgb(255, *KEY_RGB)
    form.browser.webview.DefaultBackgroundColor = Color.Transparent


def set_layer(hwnd: int, opacity: float, keyed: bool = False) -> None:
    """Whole-window opacity, and whether everything the page leaves unpainted is a hole.

    A keyed window is click-through over its WHOLE area, painted parts included, because
    hit-testing looks at the form's own surface, which is all key colour. So key it only
    while nothing on it needs the mouse, and find the cursor with cursor_inside().
    """
    alpha = max(0, min(255, round(opacity * 255)))
    red, green, blue = KEY_RGB
    user32.SetLayeredWindowAttributes(hwnd, red | green << 8 | blue << 16, alpha,
                                      LWA_ALPHA | (LWA_COLORKEY if keyed else 0))


def dpi_scale(hwnd: int) -> float:
    try:
        return user32.GetDpiForWindow(wt.HWND(hwnd)) / 96 or 1.0
    except (AttributeError, OSError):
        return 1.0


def window_rect(hwnd: int) -> wt.RECT:
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect


def anchored_top(anchor: str, edge: int, height: int) -> int:
    """Where the top of a window `height` tall goes when its `anchor` edge sits at `edge`.

    anchor "top": the top edge stays put, so the widget opens downward and collapses upward.
    anchor "bottom": the bottom edge stays put, so it opens upward and collapses downward.
    Either way it is pushed back inside the work area while it is too tall to fit there.
    """
    area = work_area()
    top = edge if anchor == "top" else edge - height
    return max(area.top, min(top, area.bottom - height))


def anchor_for(hwnd: int) -> tuple[str, int]:
    """Which edge a window left here by hand should keep: the one nearer its screen edge."""
    rect, area = window_rect(hwnd), work_area()
    if rect.top + rect.bottom < area.top + area.bottom:  # centre in the upper half
        return "top", rect.top
    return "bottom", rect.bottom


def place(hwnd: int, left: int, anchor: str, edge: int) -> None:
    """Move the window so its anchored edge is at `edge` and its left side at `left`."""
    rect = window_rect(hwnd)
    top = anchored_top(anchor, edge, rect.bottom - rect.top)
    user32.SetWindowPos(hwnd, None, left, top, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def resize(hwnd: int, dw: int, dh: int, radius: int, anchor: str = "dock",
           edge: int | None = None, keep_right: bool = False) -> None:
    """Grow the window by (dw, dh) logical pixels in one step and round its corners.

    anchor: "dock" keeps it above the clock; "top" / "bottom" keep that edge at `edge`
    (see anchored_top), which is where the user's last drag left it, so a widget pushed
    aside while open goes back when it collapses. keep_right holds the right side still
    instead of the left. Size and position change in a single SetWindowPos so the window
    never shows up in a half-moved state.
    """
    rect, scale = window_rect(hwnd), dpi_scale(hwnd)
    width = max(40, rect.right - rect.left + round(dw * scale))
    height = max(24, rect.bottom - rect.top + round(dh * scale))
    if anchor == "dock":
        x, y = corner(width, height)
    else:
        x = rect.right - width if keep_right else rect.left
        if edge is None:
            edge = rect.top if anchor == "top" else rect.bottom
        y = anchored_top(anchor, edge, height)
    user32.SetWindowPos(hwnd, None, x, y, width, height, SWP_NOZORDER | SWP_NOACTIVATE)
    r = round(radius * scale) * 2
    # The region belongs to the system once set; it must not be deleted here.
    user32.SetWindowRgn(hwnd, gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, r, r), True)


def set_topmost(hwnd: int, on: bool) -> None:
    """Always-on-top, without going through Form.TopMost.

    pythonnet keeps the GIL while it sets a .NET property, and this one sends a message to
    the GUI thread. If that thread is waiting for the GIL to deliver a page call, both wait
    forever: the widget froze this way in testing on 2026-10-01.
    """
    after = wt.HWND(-1 if on else -2)  # HWND_TOPMOST / HWND_NOTOPMOST
    user32.SetWindowPos(hwnd, after, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)


def work_area() -> wt.RECT:
    """The primary screen minus the taskbar, in physical pixels."""
    rect = wt.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
    return rect


def corner(width: int, height: int) -> tuple[int, int]:
    """Top-left corner that puts a window of this size just above the clock."""
    area = work_area()
    return (max(area.left, area.right - width - DOCK_MARGIN),
            max(area.top, area.bottom - height - DOCK_MARGIN))


def dock(hwnd: int) -> None:
    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return
    x, y = corner(rect.right - rect.left, rect.bottom - rect.top)
    user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def cursor_inside(hwnd: int) -> bool:
    point, rect = wt.POINT(), wt.RECT()
    if not (user32.GetCursorPos(ctypes.byref(point)) and user32.GetWindowRect(hwnd, ctypes.byref(rect))):
        return False
    return rect.left <= point.x < rect.right and rect.top <= point.y < rect.bottom


def signal_running_copy(name: str) -> None:
    """Second launch: ask the copy that owns the event to show itself."""
    handle = kernel32.OpenEventW(0x0002, False, name)  # EVENT_MODIFY_STATE
    if handle:
        kernel32.SetEvent(handle)
        kernel32.CloseHandle(handle)


def watch_show_requests(name: str, callback) -> None:
    """Call `callback` every time a later launch signals this copy."""
    handle = kernel32.CreateEventW(None, False, False, name)
    if not handle:
        return

    def wait() -> None:
        while kernel32.WaitForSingleObject(handle, 0xFFFFFFFF) == 0:
            callback()

    threading.Thread(target=wait, daemon=True).start()


class Tray:
    """Icon beside the clock. Left click calls `on_click`; right click opens the menu.

    entries: (label, callback, checked) tuples, `checked` being None or a function that
    says whether the entry shows a tick; None in place of a tuple is a separator.
    Build it on the GUI thread. Callbacks run on their own threads, never on the GUI one.
    """

    def __init__(self, icon_path: Path, tooltip: str, on_click, entries) -> None:
        import clr

        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        import System.Windows.Forms as WinForms
        from System.Drawing import Icon, SystemIcons

        def later(fn):
            return lambda *_: threading.Thread(target=fn, daemon=True).start()

        self._menu = WinForms.ContextMenuStrip()
        self._menu.RightToLeft = WinForms.RightToLeft.Yes
        self._checks = []
        for entry in entries:
            if entry is None:
                self._menu.Items.Add(WinForms.ToolStripSeparator())
                continue
            label, fn, checked = entry
            item = WinForms.ToolStripMenuItem(label)
            item.Click += later(fn)
            if checked is not None:
                self._checks.append((item, checked))
            self._menu.Items.Add(item)
        self._menu.Opening += self._refresh_checks

        self._left = WinForms.MouseButtons.Left
        self._info = WinForms.ToolTipIcon.Info
        self._on_click = later(on_click)
        self._icon = WinForms.NotifyIcon()
        if icon_path.is_file():
            self._icon.Icon = Icon(str(icon_path), WinForms.SystemInformation.SmallIconSize)
        else:
            self._icon.Icon = SystemIcons.Application
        self._icon.Text = tooltip[:63]
        self._icon.ContextMenuStrip = self._menu
        self._icon.MouseClick += self._clicked
        self._icon.Visible = True

    def _refresh_checks(self, *_) -> None:
        for item, checked in self._checks:
            item.Checked = bool(checked())

    def _clicked(self, _sender, event) -> None:
        if event.Button == self._left:
            self._on_click()

    def notify(self, title: str, text: str) -> None:
        """A Windows notification from the tray icon. GUI thread."""
        self._icon.ShowBalloonTip(10000, title, text, self._info)

    def remove(self) -> None:
        """Take the icon out now; otherwise it lingers until the mouse passes over it."""
        self._icon.Visible = False
        self._icon.Dispose()
