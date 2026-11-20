# main.py
"""
Orbs — Discord Activity Studio.

Interface moderne (HTML/CSS/JS) affichée dans une fenêtre native Windows via
WebView2 (pywebview). Le backend Python gère la Rich Presence Discord, le
catalogue officiel des jeux, le faux processus expérimental et les diagnostics.

Lancement en développement :  python main.py  (ou Lancer.bat)
Mode debug (DevTools)     :  python main.py --debug
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time

import webview

import paths
from bridge import Bridge

WINDOW_TITLE = "Orbs"


# ─────────────────────────── Finitions Windows ───────────────────────────
def _apply_windows_style() -> None:
    """Coins arrondis + barre sombre + icône, sans dépendance externe."""
    if os.name != "nt":
        return
    try:
        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi
    except Exception:
        return

    def find_window() -> int:
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def callback(hwnd, _lparam):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != os.getpid():
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value == WINDOW_TITLE:
                found.append(hwnd)
            return True

        user32.EnumWindows(callback, None)
        return found[0] if found else 0

    hwnd = 0
    for _ in range(50):                     # la fenêtre apparaît en ~1 s
        hwnd = find_window()
        if hwnd:
            break
        time.sleep(0.1)
    if not hwnd:
        return

    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    DWMWCP_ROUND = 2
    try:
        value = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE,
                                     ctypes.byref(value), ctypes.sizeof(value))
        value = ctypes.c_int(DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
                                     ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass

    # Icône de la fenêtre / barre des tâches.
    try:
        ico = paths.web_dir() / "assets" / "orbs.ico"
        if ico.exists():
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            LR_DEFAULTSIZE = 0x0040
            handle = user32.LoadImageW(None, str(ico), IMAGE_ICON, 0, 0,
                                       LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if handle:
                WM_SETICON = 0x0080
                user32.SendMessageW(hwnd, WM_SETICON, 1, handle)
                user32.SendMessageW(hwnd, WM_SETICON, 0, handle)
    except Exception:
        pass


# ─────────────────────────── Point d'entrée ──────────────────────────────
def main() -> None:
    settings = __import__("store").load_settings()
    width = int(settings.get("window", {}).get("width") or 1280)
    height = int(settings.get("window", {}).get("height") or 820)

    bridge = Bridge()
    index = paths.web_dir() / "index.html"
    if not index.exists():
        raise SystemExit(f"Interface introuvable : {index}")

    window = webview.create_window(
        WINDOW_TITLE,
        url=index.as_uri(),
        js_api=bridge,
        width=width,
        height=height,
        min_size=(1000, 600),
        frameless=True,
        easy_drag=False,
        background_color="#08080c",
        text_select=True,
    )
    bridge.attach_window(window)

    debug = "--debug" in sys.argv or os.environ.get("ORBS_DEBUG") == "1"
    threading.Thread(target=_apply_windows_style, daemon=True).start()

    if "--probe" in sys.argv:
        def probe():
            time.sleep(7)
            try:
                info = window.evaluate_js(
                    "JSON.stringify({w:innerWidth,h:innerHeight,dpr:devicePixelRatio,"
                    "vw:document.documentElement.clientWidth,"
                    "view:(typeof state!=='undefined'?state.view:null),"
                    "scroll:document.getElementById('main').scrollTop,"
                    "shell:!!document.getElementById('shell')&&!document.getElementById('shell').classList.contains('hidden')})")
                print("PROBE", info, flush=True)
            except Exception as exc:
                print("PROBE_ERR", exc, flush=True)
        threading.Thread(target=probe, daemon=True).start()

    webview.start(debug=debug, gui="edgechromium")


if __name__ == "__main__":
    main()
