# game_fetcher.py
"""
Récupération de la liste officielle des jeux détectables par Discord.

Source : https://discord.com/api/v10/applications/detectable
(≈ 25 000 applications, ≈ 13 Mo de JSON)

Ce que ce module gère :
  * uniquement les exécutables Windows (os == "win32") ;
  * le CHEMIN RELATIF des exécutables (ex : "among us/among us.exe") ;
  * les entrées spéciales ">javaw.exe" (détection par arguments) sont ignorées ;
  * les launchers sont pénalisés au profit du vrai exécutable du jeu ;
  * les visuels officiels : `icon_hash` (icône Discord) et AppID Steam ;
  * un cache versionné, lu sans planter sur un BOM, avec progression ;
  * recherche insensible à la casse ET aux accents, alias compris.
"""

from __future__ import annotations

import json
import os
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

import paths

# ─────────────────────────── Constantes ───────────────────────────
DISCORD_API_URL = "https://discord.com/api/v10/applications/detectable"

CACHE_FILE = paths.cache_file()

CACHE_VERSION = 3                 # incrémenter si le format change
CACHE_MAX_AGE = 7 * 24 * 3600     # 7 jours
HTTP_TIMEOUT = 60                 # secondes (le JSON fait ~13 Mo)

# Préfixe des entrées « hook par arguments » : non simulables par nom.
_ARGS_PREFIX = ">"

# Dernière erreur rencontrée (utilisée par l'interface pour informer l'utilisateur).
LAST_ERROR: str | None = None

# Progression du téléchargement (0.0 → 1.0), lue par l'interface.
PROGRESS: float = 0.0


# ─────────────────────────── Structures ───────────────────────────
@dataclass
class GamesResult:
    """Résultat chargé de la liste des jeux."""
    games: list[dict[str, Any]] = field(default_factory=list)
    from_cache: bool = False
    error: str | None = None
    fetched_at: float | None = None

    @property
    def ok(self) -> bool:
        return bool(self.games)


# ─────────────────────────── Utilitaires ──────────────────────────
def normalize(text: str) -> str:
    """Minuscules + suppression des accents, pour une recherche tolérante."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()


def _win32_executables(app: dict[str, Any]) -> list[dict[str, Any]]:
    """Retourne les exécutables Windows exploitables d'une application Discord."""
    result: list[dict[str, Any]] = []
    for exe in app.get("executables") or []:
        if not isinstance(exe, dict):
            continue
        name = (exe.get("name") or "").strip()
        if not name or name.startswith(_ARGS_PREFIX):
            continue
        if exe.get("os") not in (None, "", "win32"):
            continue
        result.append(exe)
    return result


def _pick_preferred(executables: list[dict[str, Any]]) -> str | None:
    """
    Choisit le meilleur exécutable pour la simulation.

    Ordre de préférence :
      1. non-launcher, nom simple ("undertale.exe") ;
      2. non-launcher, avec sous-dossier ("among us/among us.exe") ;
      3. launcher, nom simple ;
      4. launcher, avec sous-dossier.
    """
    def score(exe: dict[str, Any]) -> tuple[int, int, int]:
        name = exe.get("name", "")
        has_path = 1 if ("/" in name or "\\" in name) else 0
        is_launcher = 1 if exe.get("is_launcher") else 0
        return (is_launcher, has_path, len(name))

    if not executables:
        return None
    return sorted(executables, key=score)[0].get("name")


def _steam_id(app: dict[str, Any]) -> str | None:
    """Récupère l'AppID Steam éventuel (visuel de secours, cover)."""
    for sku in app.get("third_party_skus") or []:
        if isinstance(sku, dict) and sku.get("distributor") == "steam":
            value = sku.get("id")
            if value:
                return str(value)
    return None


def _build_game(app: dict[str, Any]) -> dict[str, Any] | None:
    """Transforme une entrée brute de l'API en dictionnaire interne."""
    name = (app.get("name") or "").strip()
    if not name:
        return None

    executables = _win32_executables(app)
    preferred = _pick_preferred(executables)

    names: list[str] = []
    if preferred:
        names.append(preferred)
    for exe in executables:
        candidate = exe.get("name")
        if candidate and candidate not in names:
            names.append(candidate)

    aliases = [a for a in (app.get("aliases") or []) if isinstance(a, str) and a.strip()]
    app_id = str(app.get("id")) if app.get("id") else None

    return {
        "name": name,
        "id": app_id,
        "aliases": aliases,
        "hook": bool(app.get("hook")),
        "executables": names,
        "preferred_executable": preferred,
        "has_executable": bool(names),
        "steam_id": _steam_id(app),
        "icon": app.get("icon_hash") or None,
    }


# ─────────────────────────── Visuels ──────────────────────────────
def icon_url(game: dict[str, Any] | None, size: int = 256) -> str | None:
    """Icône officielle de l'application Discord (CDN public)."""
    if not game:
        return None
    app_id = game.get("id")
    icon = game.get("icon")
    if not app_id or not icon:
        return None
    return f"https://cdn.discordapp.com/app-icons/{app_id}/{icon}.png?size={size}"


def banner_url(game: dict[str, Any] | None) -> str | None:
    """Bannière large : visuel Steam si connu, sinon icône Discord."""
    if not game:
        return None
    steam = game.get("steam_id")
    if steam:
        return (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam}"
                f"/header.jpg")
    return icon_url(game, 512)


def portrait_url(game: dict[str, Any] | None) -> str | None:
    """Affiche verticale Steam (cartes de jeu)."""
    if not game:
        return None
    steam = game.get("steam_id")
    if steam:
        return (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam}"
                f"/library_600x900.jpg")
    return icon_url(game, 256)


# ─────────────────────────── Cache ────────────────────────────────
def _load_cache(allow_stale: bool = False) -> GamesResult | None:
    """Lit le cache disque. Retourne None si absent/illisible/trop ancien."""
    global PROGRESS
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)

        if isinstance(payload, list):        # très ancien format
            return None
        if not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION:
            return None

        games = payload.get("games") or []
        if not isinstance(games, list) or not games:
            return None

        fetched_at = payload.get("fetched_at")
        if (not allow_stale and fetched_at
                and (time.time() - float(fetched_at)) > CACHE_MAX_AGE):
            return None

        PROGRESS = 1.0
        return GamesResult(games=games, from_cache=True, fetched_at=fetched_at)
    except Exception:
        return None


def _write_cache(games: list[dict[str, Any]]) -> None:
    """Écrit le cache de façon atomique (fichier temporaire puis remplacement)."""
    payload = {
        "version": CACHE_VERSION,
        "fetched_at": time.time(),
        "count": len(games),
        "games": games,
    }
    tmp = CACHE_FILE.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, CACHE_FILE)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _download(progress: Callable[[float], None] | None = None) -> list[dict[str, Any]]:
    """Télécharge et convertit la liste officielle Discord (avec progression)."""
    global PROGRESS
    response = requests.get(
        DISCORD_API_URL,
        timeout=HTTP_TIMEOUT,
        stream=True,
        headers={
            "User-Agent": "Orbs/2.0 (+python-requests)",
            "Accept": "application/json",
        },
    )
    response.raise_for_status()

    total = int(response.headers.get("Content-Length") or 0)
    chunks: list[bytes] = []
    received = 0
    for chunk in response.iter_content(chunk_size=256 * 1024):
        if not chunk:
            continue
        chunks.append(chunk)
        received += len(chunk)
        if total:
            PROGRESS = min(0.95, received / total)
            if progress:
                progress(PROGRESS)
    raw = b"".join(chunks)
    PROGRESS = 0.97
    if progress:
        progress(PROGRESS)

    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("Réponse inattendue de l'API Discord (liste attendue).")

    games: list[dict[str, Any]] = []
    for app in data:
        if not isinstance(app, dict):
            continue
        game = _build_game(app)
        if game:
            games.append(game)
    PROGRESS = 1.0
    if progress:
        progress(1.0)
    return games


# ─────────────────────────── API publique ─────────────────────────
def load_games(force_refresh: bool = False,
               progress: Callable[[float], None] | None = None) -> GamesResult:
    """Charge la liste des jeux. Ne lève jamais d'exception."""
    global LAST_ERROR

    if not force_refresh:
        cached = _load_cache()
        if cached:
            LAST_ERROR = None
            return cached

    try:
        games = _download(progress)
        if not games:
            raise ValueError("La liste téléchargée est vide.")
        _write_cache(games)
        LAST_ERROR = None
        return GamesResult(games=games, from_cache=False, fetched_at=time.time())
    except Exception as exc:  # réseau, HTTP, JSON, parsing…
        LAST_ERROR = f"{type(exc).__name__} : {exc}"

    # Secours : un cache même périmé vaut mieux qu'une liste vide.
    stale = _load_cache(allow_stale=True)
    if stale:
        stale.error = f"Réseau indisponible ({LAST_ERROR}) — cache local utilisé."
        return stale

    return GamesResult(games=[], from_cache=False,
                       error=f"Réseau indisponible ({LAST_ERROR}) et aucun cache local.")


def fetch_games(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Compatibilité avec l'ancienne API : retourne directement la liste."""
    return load_games(force_refresh=force_refresh).games


def search_games(games: list[dict[str, Any]], query: str,
                 limit: int | None = None) -> list[dict[str, Any]]:
    """
    Filtre les jeux par nom, alias ou nom d'exécutable.

    Résultats classés par pertinence : nom exact, alias exact, préfixe, puis
    simple présence. « roblox » remonte ROBLOX avant NeuroBloxs.
    """
    q = normalize(query)

    def rank(game: dict[str, Any]) -> tuple[int, str]:
        name = normalize(game.get("name", ""))
        aliases = [normalize(a) for a in (game.get("aliases") or [])]

        if name == q:
            level = 0
        elif q in aliases:
            level = 1
        elif name.startswith(q):
            level = 2
        elif any(alias.startswith(q) for alias in aliases):
            level = 3
        elif q in name:
            level = 4
        else:
            level = 5
        return (level, name)

    if not q:
        result = sorted(games, key=lambda g: normalize(g.get("name", "")))
    else:
        matches = []
        for game in games:
            haystack = [game.get("name", "")]
            haystack.extend(game.get("aliases") or [])
            haystack.extend(game.get("executables") or [])
            if any(q in normalize(item) for item in haystack if item):
                matches.append(game)
        result = sorted(matches, key=rank)

    if limit is not None:
        return result[:limit]
    return result


def get_game_names(games: list[dict[str, Any]]) -> list[str]:
    """Compatibilité : liste triée des noms de jeux."""
    return sorted({g["name"] for g in games if g.get("name")})
