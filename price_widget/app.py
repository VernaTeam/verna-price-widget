"""Desktop price widget: a small frameless, draggable WebView2 window with a tray icon.

Nobitex prices refresh every 5 s, tgju every 60 s (tgju itself caches for 5 min).
Settings and the window position live in %APPDATA%\\VernaPriceWidget\\settings.json.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

import webview

from . import catalog, derived, history, native, startup
from .sources import SourceError, fetch_nobitex, fetch_tgju

APP_NAME = "VernaPriceWidget"
CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
SETTINGS = CONFIG_DIR / "settings.json"
SHOW_EVENT = f"Local\\{APP_NAME}.show"
NOBITEX_EVERY = 5
TGJU_EVERY = 60
WIDTH = 300
COLLAPSED_HEIGHT = 64  # the window's first height; the page then asks for its real size
LEAVE_DELAY = 0.4  # seconds the mouse must stay away before the widget counts as left
OPTIONS = ("compact", "background", "locked")
# (family, Persian name). Each is ui/fonts/<family>-Regular.woff2 and -Bold.woff2, all OFL.
FONT_FAMILIES = [("Vazirmatn", "وزیرمتن"), ("Shabnam", "شبنم"), ("Sahel", "ساحل"),
                 ("Samim", "صمیم"), ("Estedad", "استعداد"), ("Parastoo", "پرستو")]
STORY_SECONDS = (2, 15, 4)  # min, max, default


def fa_number(value: float) -> str:
    """2585000 -> '۲٬۵۸۵٬۰۰۰' (decimals only for small numbers), for notifications."""
    text = f"{value:,.0f}" if abs(value) >= 1000 else f"{value:,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", "٬").replace(".", "٫").translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def resource(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)


def log(text: str) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_DIR / "widget.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text.rstrip()}\n")
    except OSError:
        pass


def clean_settings(stored) -> dict:
    """Whatever is in settings.json turned into values the widget can trust."""
    stored = stored if isinstance(stored, dict) else {}
    is_int = lambda v: isinstance(v, int) and not isinstance(v, bool)  # noqa: E731
    x, anchor, edge = stored.get("x"), stored.get("anchor"), stored.get("edge")
    if not is_int(edge):  # older files: "bottom" (1 Oct 2026), before that "y", the top edge
        for anchor, key in (("bottom", "bottom"), ("top", "y")):
            edge = stored.get(key)
            if is_int(edge):
                break
    placed = is_int(x) and is_int(edge) and anchor in ("top", "bottom")
    return {
        "items": catalog.clean_items(stored.get("items")),
        "on_top": stored.get("on_top") is not False,
        # Where an undocked widget sits: its left side, and the edge that stays put while it
        # opens and collapses (top edge near the top of the screen, bottom edge otherwise).
        "x": x if placed else None,
        "anchor": anchor if placed else None,
        "edge": edge if placed else None,
        "scale": catalog.clamp(stored.get("scale"), *catalog.SCALE),
        "opacity": catalog.clamp(stored.get("opacity"), *catalog.OPACITY),
        # Locked = cannot be moved or resized with the mouse.
        "locked": stored.get("locked") is True,
        "font": stored.get("font") if stored.get("font") in dict(FONT_FAMILIES) else "Vazirmatn",
        "story_seconds": round(catalog.clamp(stored.get("story_seconds"), *STORY_SECONDS)),
        # {"source:key": {"above": price, "below": price}}: one-shot, removed once it fires.
        "alerts": clean_alerts(stored.get("alerts")),
        # Docked = sitting above the clock and kept there when its size changes.
        "docked": stored.get("docked") is not False,
        # Compact = one row at a time while the mouse is away, all rows under the mouse.
        "compact": stored.get("compact") is not False,
        # Background off = only the text is drawn while the mouse is away.
        "background": stored.get("background") is not False,
    }


def clean_alerts(raw) -> dict:
    out = {}
    if not isinstance(raw, dict):
        return out
    for rid, rule in raw.items():
        if not (isinstance(rid, str) and isinstance(rule, dict)):
            continue
        levels = {side: float(rule[side]) for side in ("above", "below")
                  if isinstance(rule.get(side), (int, float)) and not isinstance(rule.get(side), bool)
                  and rule[side] > 0}
        if levels:
            out[rid] = levels
    return out


def load_settings() -> dict:
    try:
        return clean_settings(json.loads(SETTINGS.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return clean_settings(None)


def save_settings(data: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def available_fonts() -> list[str]:
    return [f for f, _ in FONT_FAMILIES if resource("ui", "fonts", f"{f}-Regular.woff2").is_file()]


def build_html() -> str:
    ui = resource("ui")
    faces = "".join(
        "@font-face{font-family:'%s';font-weight:%d;font-display:block;"
        "src:url(data:font/woff2;base64,%s) format('woff2')}"
        % (family, weight, base64.b64encode((ui / "fonts" / f"{family}-{style}.woff2").read_bytes()).decode("ascii"))
        for family in available_fonts() for weight, style in ((400, "Regular"), (700, "Bold"))
        if (ui / "fonts" / f"{family}-{style}.woff2").is_file())
    html = (ui / "index.html").read_text(encoding="utf-8")
    html = html.replace("/*__STYLE__*/", faces + (ui / "style.css").read_text(encoding="utf-8"))
    return html.replace("/*__APP__*/", (ui / "app.js").read_text(encoding="utf-8"))


class Api:
    """Called from the page. Fetching runs in a background thread; the page just reads."""

    def __init__(self, settings: dict) -> None:
        self._settings = settings
        self._window = None
        self._hwnd = 0
        self._tray = None
        self._visible = True
        self._revealed = False
        self._view = "list"  # what the page shows: list, settings or detail
        self._hover = False
        self._held = False  # the page is in the middle of a mouse drag
        self._layer = None  # (opacity, keyed) last applied
        self._auto_until = float("inf")  # window moves before this moment are ours, not a drag
        self._moved_at = 0.0  # when the user last dragged the window, until that is saved
        self._quotes: dict[str, dict] = {}
        self._alert_state: dict[tuple, bool] = {}  # (row, side) -> was the level reached
        self._alerted: dict[str, float] = {}  # row -> when an alert last fired
        self._status = {"nobitex": {"t": 0, "error": ""}, "tgju": {"t": 0, "error": ""}}
        self._stop = threading.Event()
        self._wake = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._hover_loop, daemon=True).start()

    def _items(self, source: str) -> list[str]:
        """Keys to fetch from `source`: its rows, and what the derived rows are worked out from."""
        keys = [key for src, key, _, _ in self._settings["items"] if src == source]
        for src, key, _, _ in self._settings["items"]:
            for dep_source, dep_key in derived.DEPENDS.get(key, []) if src == "calc" else []:
                if dep_source == source and dep_key not in keys:
                    keys.append(dep_key)
        return keys

    def _quote(self, rid: str) -> dict | None:
        source, _, key = rid.partition(":")
        if source == "calc":
            return derived.compute(key, self._quotes)
        return self._quotes.get(rid)

    def _check_alerts(self) -> None:
        """Fire an alert when its row's price reaches the level, then forget the alert.

        Only a crossing fires: a level that is already reached when it is set (or when the
        widget starts) waits until the price has gone back and reached it again.
        """
        rows = {f"{src}:{key}": (label, unit) for src, key, label, unit in self._settings["items"]}
        changed = False
        for rid, rule in list(self._settings["alerts"].items()):
            quote = self._quote(rid) if rid in rows else None
            if not (quote and quote.get("ok") and quote.get("price") is not None):
                continue
            price = quote["price"]
            for side in ("above", "below"):
                level = rule.get(side)
                if level is None:
                    continue
                reached = price >= level if side == "above" else price <= level
                was = self._alert_state.get((rid, side))
                self._alert_state[(rid, side)] = reached
                if reached and was is False:
                    label, unit = rows[rid]
                    verb = "بالاتر رفت" if side == "above" else "پایین‌تر آمد"
                    self._notify(f"هشدار {label}",
                                 f"از {fa_number(level)} {verb}. الان {fa_number(price)} {unit}")
                    del rule[side]
                    self._alerted[rid] = time.time()
                    changed = True
            if not rule:
                del self._settings["alerts"][rid]
        if changed:
            save_settings(self._settings)

    def _notify(self, title: str, text: str) -> None:
        if self._tray is None or self._window is None:
            return
        from System import Func, Type  # loaded by pywebview by now

        # A method call through Invoke: pythonnet lets go of the GIL for it (see HANDOFF).
        self._window.native.Invoke(Func[Type](lambda: self._tray.notify(title, text)))

    def _refresh(self, source: str) -> None:
        fetch = fetch_nobitex if source == "nobitex" else fetch_tgju
        keys = self._items(source)
        if not keys:
            return
        try:
            for q in fetch(keys):
                self._quotes[f"{source}:{q.key}"] = q.to_dict()
            self._status[source] = {"t": time.time(), "error": ""}
        except SourceError as exc:
            self._status[source]["error"] = str(exc)
            log(f"{source}: {exc}")

    def _loop(self) -> None:
        last = {"nobitex": 0.0, "tgju": 0.0}
        every = {"nobitex": NOBITEX_EVERY, "tgju": TGJU_EVERY}
        while not self._stop.is_set():
            forced = self._wake.is_set()
            self._wake.clear()
            for source in last:
                if forced or time.time() - last[source] >= every[source]:
                    last[source] = time.time()
                    try:
                        self._refresh(source)
                        self._check_alerts()
                    except Exception:  # never let the fetch thread die
                        log(traceback.format_exc())
            # A new place is written a second after the drag ends, not only on exit: a
            # shutdown kills the process without the closing event.
            if self._moved_at and time.time() - self._moved_at > 1:
                self._moved_at = 0.0
                save_settings(self._settings)
            self._wake.wait(1)

    # ---------------------------------------------------------- native window

    def _before_show(self) -> None:
        """GUI thread, window built but not yet visible."""
        try:
            form = self._window.native
            self._hwnd = form.Handle.ToInt64()
            native.prepare_window(self._hwnd)
            native.make_see_through(form)
            # Invisible until the page has fitted the window (see ready), so the first
            # thing on screen is the right size in the right place.
            native.set_layer(self._hwnd, 0)
            self._tray = native.Tray(resource("app.ico"), "قیمت لحظه‌ای", self.toggle, [
                ("نمایش یا پنهان کردن", self.toggle, None),
                ("تنظیمات", self._open_settings, None),
                ("همیشه روی پنجره‌های دیگر", self._flip_on_top, lambda: self._settings["on_top"]),
                ("قفل (با ماوس جابه‌جا نشود)", self._flip_lock, lambda: self._settings["locked"]),
                ("بردن کنار ساعت", self.dock, None),
                None,
                ("خروج", self.quit, None),
            ])
            native.watch_show_requests(SHOW_EVENT, self.show)
        except Exception:
            log(traceback.format_exc())
        threading.Timer(5, self.ready).start()  # if the page never reports in, show anyway

    def _apply_layer(self) -> None:
        if not (self._hwnd and self._revealed):
            return
        dimmed = self._settings["opacity"]
        # A dimmed widget turns solid under the mouse so it can be read. While the settings
        # are open it stays dimmed, so the slider shows what it does.
        solid = dimmed >= 1 or (self._hover and self._view != "settings")
        # Text only, no panel, while the mouse is away. A keyed window takes no clicks at
        # all, which is why this is limited to the moments nobody is pointing at it.
        keyed = not self._settings["background"] and self._view == "list" and not self._hover
        layer = (1.0 if solid else dimmed, keyed)
        if layer != self._layer:
            self._layer = layer
            native.set_layer(self._hwnd, *layer)

    def _hover_loop(self) -> None:
        """Tell the page when the mouse arrives and leaves.

        Polled from here instead of mouseenter/mouseleave in the page: the window changes
        size under the cursor and is click-through while keyed, and the page sees neither.
        """
        away_since = None
        while not self._stop.wait(0.1):
            if not (self._revealed and self._visible):
                continue
            try:
                if self._held or native.cursor_inside(self._hwnd):
                    away_since, hover = None, True
                else:
                    away_since = away_since or time.time()
                    hover = self._hover and time.time() - away_since < LEAVE_DELAY
                if hover != self._hover:
                    self._hover = hover
                    self._apply_layer()
                    self._window.evaluate_js(f"setHover({'true' if hover else 'false'})")
            except Exception:
                log(traceback.format_exc())

    def _dock(self) -> None:
        self._auto_until = time.time() + 1
        native.dock(self._hwnd)

    def _moved(self, x: int, y: int) -> None:
        self._settings["x"] = x
        if time.time() > self._auto_until and self._hwnd:
            # Dragged by hand: stop following the clock, and remember the edge that stays
            # put when the widget opens and collapses. Our own moves (open, collapse, pushed
            # back inside the screen) leave it alone.
            self._settings["docked"] = False
            self._settings["anchor"], self._settings["edge"] = native.anchor_for(self._hwnd)
            self._moved_at = time.time()  # saved by _loop once the drag has stopped

    def _closing(self) -> None:
        self._stop.set()
        save_settings(self._settings)
        if self._tray is not None:
            self._tray.remove()

    def _open_settings(self) -> None:
        self.show()
        self._window.evaluate_js("openSettings()")

    def _flip_on_top(self) -> None:
        self.set_on_top(not self._settings["on_top"])

    def _flip_lock(self) -> None:
        self.set_option("locked", not self._settings["locked"])
        self._window.evaluate_js("tick()")  # the page is what stops the dragging

    def _set_items(self, items: list) -> dict:
        if items is not self._settings["items"]:
            self._settings["items"] = items
            kept = {f"{src}:{key}" for src, key, _, _ in items}
            self._settings["alerts"] = {rid: rule for rid, rule in self._settings["alerts"].items()
                                        if rid in kept}
            save_settings(self._settings)
            self._wake.set()
        return self.state()

    # ------------------------------------------------------------- page calls

    def config(self) -> dict:
        return {
            "catalog": [{"source": s, "key": k, "label": label, "unit": u, "group": g}
                        for s, k, label, u, g in catalog.CATALOG],
            "max_items": catalog.MAX_ITEMS,
            "scale": catalog.SCALE[:2],
            "opacity": catalog.OPACITY[:2],
            "can_autostart": startup.command() is not None,
            "fonts": [[f, name] for f, name in FONT_FAMILIES if f in available_fonts()],
            "story_seconds": STORY_SECONDS[:2],
        }

    def state(self) -> dict:
        rows = []
        for src, key, label, unit in self._settings["items"]:
            q = self._quote(f"{src}:{key}")
            rows.append({"id": f"{src}:{key}", "source": src, "key": key, "label": label,
                         "unit": unit, "quote": q,
                         "ranges": [[rid, name] for rid, name, _, _ in history.ranges_for(src, key)]})
        s = self._settings
        return {"rows": rows, "status": self._status, "now": time.time(),
                "on_top": s["on_top"], "scale": s["scale"], "opacity": s["opacity"],
                "docked": s["docked"], "compact": s["compact"], "background": s["background"],
                "locked": s["locked"], "font": s["font"], "story_seconds": s["story_seconds"],
                "alerts": s["alerts"],
                "alerted": {rid: time.time() - t for rid, t in self._alerted.items()
                            if time.time() - t < 120},
                "autostart": startup.is_enabled(APP_NAME)}

    def history(self, source: str, key: str, range_id: str) -> dict:
        """Points for the chart: {"points": [[unix time, price], ...]} or {"error": text}."""
        quote = self._quotes.get(f"{source}:{key}") or {}
        try:
            points = history.fetch(source, key, range_id, quote.get("price"))
        except SourceError as exc:
            log(f"history {source}:{key} {range_id}: {exc}")
            return {"error": "connection"}
        except Exception:
            log(traceback.format_exc())
            return {"error": "connection"}
        return {"points": points} if len(points) >= 2 else {"error": "empty"}

    def spark(self, source: str, key: str) -> dict:
        """A small series for the line behind a row: the last 24 hours where there is one."""
        ranges = [rid for rid, _, _, _ in history.ranges_for(source, key)]
        if not ranges:
            return {}
        quote = self._quotes.get(f"{source}:{key}") or {}
        try:
            points = history.fetch(source, key, "1d" if "1d" in ranges else ranges[0], quote.get("price"))
        except Exception as exc:  # the row simply goes without its line
            log(f"spark {source}:{key}: {exc}")
            return {}
        step = max(1, len(points) // 48)
        values = [p[1] for p in points[::step]]
        if points and values[-1] != points[-1][1]:
            values.append(points[-1][1])
        return {"values": values} if len(values) >= 2 else {}

    def set_alert(self, rid: str, above, below) -> dict:
        """Set or clear (None) the two levels of one row; returns what is now set."""
        rule = {side: float(v) for side, v in (("above", above), ("below", below))
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0}
        alerts = self._settings["alerts"]
        if rule:
            alerts[rid] = rule
        else:
            alerts.pop(rid, None)
        for side in ("above", "below"):  # the next check only takes note of where it is
            self._alert_state.pop((rid, side), None)
        self._check_alerts()
        save_settings(self._settings)
        return alerts.get(rid, {})

    def set_font(self, family: str) -> str:
        if family in dict(FONT_FAMILIES):
            self._settings["font"] = family
            save_settings(self._settings)
        return self._settings["font"]

    def set_story_seconds(self, value: float) -> int:
        self._settings["story_seconds"] = round(catalog.clamp(value, *STORY_SECONDS))
        save_settings(self._settings)
        return self._settings["story_seconds"]

    def refresh(self) -> None:
        self._wake.set()

    def set_on_top(self, on: bool) -> bool:
        self._settings["on_top"] = bool(on)
        if self._hwnd:
            native.set_topmost(self._hwnd, bool(on))
        save_settings(self._settings)
        return bool(on)

    def set_scale(self, value: float) -> float:
        self._settings["scale"] = catalog.clamp(value, *catalog.SCALE)
        save_settings(self._settings)
        return self._settings["scale"]

    def set_opacity(self, value: float, save: bool = True) -> float:
        self._settings["opacity"] = catalog.clamp(value, *catalog.OPACITY)
        self._apply_layer()
        if save:
            save_settings(self._settings)
        return self._settings["opacity"]

    def set_option(self, name: str, on: bool) -> bool:
        if name in OPTIONS:
            self._settings[name] = bool(on)
            self._apply_layer()
            save_settings(self._settings)
        return bool(self._settings.get(name))

    def set_autostart(self, on: bool) -> bool:
        """Add or remove this exe under the user's Run key. The box in settings calls this."""
        return startup.set_enabled(APP_NAME, bool(on)) and startup.is_enabled(APP_NAME)

    def set_view(self, view: str) -> None:
        self._view = str(view)
        self._apply_layer()

    def hold(self, on: bool) -> None:
        """The page is dragging something: keep treating the mouse as over the widget."""
        self._held = bool(on)

    def add_item(self, source: str, key: str) -> dict:
        return self._set_items(catalog.add_item(self._settings["items"], source, key))

    def remove_item(self, index: int) -> dict:
        return self._set_items(catalog.remove_item(self._settings["items"], int(index)))

    def move_item(self, index: int, target: int) -> dict:
        return self._set_items(catalog.move_item(self._settings["items"], int(index), int(target)))

    def fit(self, dw: int, dh: int, radius: int = 0, keep_right: bool = False) -> None:
        """Grow or shrink the window by the page's measured shortfall and round its corners.

        Windows sizes a frameless window smaller than requested (16 x 39 px here: the
        border the frame would have had), which cut off the last row. The page measures
        its real content and asks for exactly the difference.
        """
        if not self._hwnd:
            return
        self._auto_until = time.time() + 1
        s = self._settings
        anchor = "dock" if s["docked"] else s["anchor"] or "bottom"
        native.resize(self._hwnd, int(dw), int(dh), int(radius), anchor, s["edge"], bool(keep_right))

    def ready(self) -> None:
        """The page has fitted the window for the first time: reveal it."""
        if self._revealed or not self._hwnd:
            return
        self._revealed = True
        self._auto_until = time.time() + 1
        if self._settings["docked"]:
            self._dock()
        elif self._settings["edge"] is not None:
            # Windows made the window a different size than asked, so its anchored edge is
            # not where it was left yet.
            s = self._settings
            native.place(self._hwnd, s["x"], s["anchor"], s["edge"])
        self._apply_layer()

    def dock(self) -> bool:
        self._settings["docked"] = True
        self._dock()
        save_settings(self._settings)
        return True

    def show(self) -> None:
        if self._window is None:
            return
        self._auto_until = time.time() + 1
        self._window.show()
        self._visible = True
        if self._settings["docked"]:
            self._dock()

    def hide(self) -> None:
        """The close button: off the screen, still running in the tray."""
        if self._window is None:
            return
        self._visible = False
        save_settings(self._settings)
        self._window.hide()

    def toggle(self) -> None:
        self.hide() if self._visible else self.show()

    def quit(self) -> None:
        if self._window is not None:
            self._window.destroy()


def single_instance() -> bool:
    """False if another copy is already running (named mutex, per user session)."""
    ctypes.windll.kernel32.CreateMutexW(None, False, f"Local\\{APP_NAME}")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def on_screen(x: int, y: int) -> bool:
    user32 = ctypes.windll.user32
    left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    return left <= x <= left + width - 60 and top <= y <= top + height - 40


def run() -> int:
    if not single_instance():
        native.signal_running_copy(SHOW_EVENT)  # it may be hidden in the tray
        return 0
    settings = load_settings()
    width = round(WIDTH * settings["scale"])
    height = round(COLLAPSED_HEIGHT * settings["scale"])  # one row; the page asks for the rest
    x = settings["x"]
    y = None if x is None else native.anchored_top(settings["anchor"], settings["edge"], height)
    if settings["docked"] or x is None or not on_screen(x, y):
        settings["docked"] = True
        x, y = native.corner(width, height)
    api = Api(settings)
    window = webview.create_window(
        "قیمت‌ها", html=build_html(), js_api=api, width=width, height=height, x=x, y=y,
        # shadow=False: the DWM frame it adds shows as a white line around a see-through window
        min_size=(60, 30), frameless=True, easy_drag=False, shadow=False, on_top=settings["on_top"],
        resizable=False, background_color=native.KEY_HEX)
    api._window = window
    window.events.before_show += api._before_show
    window.events.moved += api._moved
    window.events.closing += api._closing
    webview.start(gui="edgechromium")
    return 0
