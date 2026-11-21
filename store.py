# store.py
"""
Petit magasin JSON persistant (réglages, favoris, historique, presets).

Toutes les écritures sont atomiques (fichier temporaire + remplacement) et ne
lèvent jamais d'exception : une donnée corrompue ne doit pas empêcher
l'application de démarrer.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import paths

DEFAULTS: dict[str, Any] = {
    "lang": "fr",
    "accent": "blurple",
    "start_with_windows": False,
    "auto_refresh": True,
    "reduced_motion": False,
    "show_fake_window": False,
    "default_method": "rpc",
    "playtime_hours": 0,
    "window": {"width": 1280, "height": 820},
    "onboarded": False,
}

FAVORITES_FILE = "favorites.json"
RECENTS_FILE = "recents.json"
PRESETS_FILE = "presets.json"
SETTINGS_FILE = "settings.json"

MAX_RECENTS = 24


def _read_json(name: str, default: Any) -> Any:
    try:
        path = paths.data_file(name)
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except Exception:
        return default


def _write_json(name: str, payload: Any) -> bool:
    tmp = None
    try:
        path = paths.data_file(name)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            if tmp:
                tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


# ─────────────────────────── Réglages ─────────────────────────────
def load_settings() -> dict[str, Any]:
    stored = _read_json(SETTINGS_FILE, {})
    settings = dict(DEFAULTS)
    if isinstance(stored, dict):
        for key, value in stored.items():
            if key in DEFAULTS and isinstance(value, type(DEFAULTS[key])):
                settings[key] = value
            elif key in DEFAULTS and isinstance(DEFAULTS[key], dict) and isinstance(value, dict):
                merged = dict(DEFAULTS[key])
                merged.update({k: v for k, v in value.items() if k in merged})
                settings[key] = merged
            elif key not in DEFAULTS:
                continue
    return settings


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    safe = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in settings:
            safe[key] = settings[key]
    _write_json(SETTINGS_FILE, safe)
    return safe


# ─────────────────────────── Favoris ──────────────────────────────
def load_favorites() -> list[str]:
    data = _read_json(FAVORITES_FILE, [])
    if isinstance(data, list):
        return [str(item) for item in data if isinstance(item, (str, int))]
    return []


def save_favorites(ids: list[str]) -> None:
    _write_json(FAVORITES_FILE, list(dict.fromkeys(ids)))


# ─────────────────────────── Historique ───────────────────────────
def load_recents() -> list[dict[str, Any]]:
    data = _read_json(RECENTS_FILE, [])
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and item.get("id")]
    return []


def save_recents(items: list[dict[str, Any]]) -> None:
    _write_json(RECENTS_FILE, items[:MAX_RECENTS])


# ─────────────────────────── Presets ──────────────────────────────
def load_presets() -> list[dict[str, Any]]:
    data = _read_json(PRESETS_FILE, [])
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and item.get("id")]
    return []


def save_presets(items: list[dict[str, Any]]) -> None:
    _write_json(PRESETS_FILE, items)


# ─────────────────────────── Démarrage Windows ────────────────────
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Orbs"


def _startup_command() -> str:
    if paths.is_frozen():
        return f'"{sys.executable}"'
    launcher = Path(sys.executable)
    pythonw = launcher.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else launcher
    entry = Path(__file__).resolve().parent / "main.py"
    return f'"{interpreter}" "{entry}"'


def startup_enabled() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            try:
                winreg.QueryValueEx(key, RUN_VALUE)
                return True
            except FileNotFoundError:
                return False
    except Exception:
        return False


def set_startup(enabled: bool) -> bool:
    """Active / désactive le lancement automatique au démarrage de Windows."""
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, _startup_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False
