# paths.py
"""
Chemins de travail de l'application.

Deux situations :

* **Mode développement** (``python main.py``) : tout se passe dans le dossier du
  projet, comme avant (cache, réglages et ``fake_processes/`` à côté des
  sources).
* **Mode compilé** (``.exe`` PyInstaller) : le programme s'exécute depuis un
  dossier temporaire qui est supprimé à la fermeture. On utilise donc
  ``%LOCALAPPDATA%\\Orbs`` pour les données persistantes.

Ainsi l'utilisateur d'un ``.exe`` envoyé par un ami n'a besoin d'aucun droit
particulier, et ses données persistent entre deux lancements.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Orbs"
LEGACY_APP_NAME = "DiscordFakeGame"


def is_frozen() -> bool:
    """Vrai si l'on tourne depuis un exécutable PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Dossier de travail inscriptible (créé au besoin)."""
    if is_frozen():
        root = os.environ.get("LOCALAPPDATA")
        directory = (Path(root) if root else Path.home()) / APP_NAME
        legacy = (Path(root) if root else Path.home()) / LEGACY_APP_NAME
        # Reprise du cache de l'ancienne version, s'il existe.
        try:
            if legacy.exists() and not (directory / "discord_games_cache.json").exists():
                directory.mkdir(parents=True, exist_ok=True)
                old_cache = legacy / "discord_games_cache.json"
                if old_cache.exists():
                    shutil.copy2(old_cache, directory / "discord_games_cache.json")
        except Exception:
            pass
    else:
        directory = Path(__file__).resolve().parent

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return directory


def web_dir() -> Path:
    """Dossier des fichiers de l'interface (HTML / CSS / JS)."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        return base / "web"
    return Path(__file__).resolve().parent / "web"


def cache_file() -> Path:
    """Fichier de cache de la liste des jeux."""
    return app_dir() / "discord_games_cache.json"


def fake_dir() -> Path:
    """Dossier des faux exécutables."""
    return app_dir() / "fake_processes"


def data_file(name: str) -> Path:
    """Fichier de données persistant (réglages, favoris, historique…)."""
    return app_dir() / name
