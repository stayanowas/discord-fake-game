# bridge.py
"""
Passerelle entre l'interface web (HTML/CSS/JS) et Python.

Chaque méthode publique de ``Bridge`` est exposée à JavaScript via
``window.pywebview.api.<méthode>(...)`` et doit renvoyer un objet
sérialisable en JSON.

Le pont gère :
  * le catalogue Discord (25 000 jeux, cache local, recherche, pagination) ;
  * les favoris, l'historique et les presets (fichiers JSON) ;
  * la Rich Presence (pypresence) et le faux processus expérimental ;
  * les diagnostics (canaux IPC, journaux Discord) ;
  * les réglages et le démarrage automatique avec Windows.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
import uuid
import webbrowser
from typing import Any

import requests

import diagnostics as diag
import discord_quests
import game_fetcher
import paths
import store
from process_simulator import FakeProcess, cleanup_orphans
from rpc_manager import RPCManager, list_ipc_pipes

VERSION = "2.0.0"

_ACCENTS = {"blurple", "violet", "emerald", "rose", "amber"}


def _now() -> int:
    return int(time.time())


class Bridge:
    """API appelée par l'interface."""

    def __init__(self) -> None:
        self.settings = store.load_settings()
        self.favorites: list[str] = store.load_favorites()
        self.recents: list[dict[str, Any]] = store.load_recents()
        self.presets: list[dict[str, Any]] = store.load_presets()

        self.rpc = RPCManager()
        self.fakes: dict[str, tuple[FakeProcess, dict[str, Any]]] = {}
        self.running: dict[str, Any] | None = None

        self.games: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        self._hay: dict[str, str] = {}
        self.library_state = "loading"
        self.library_error: str | None = None
        self.library_source: str | None = None
        self.library_progress = 0.0
        self.library_loaded_at: float | None = None

        self.events: list[dict[str, str]] = []
        self._lock = threading.RLock()
        self._window = None
        self._app_cache: dict[str, dict[str, Any]] = {}

        self._start_library_load()
        threading.Thread(target=self._cleanup_startup, daemon=True).start()

    # ═══════════════════════════ Cycle de vie ════════════════════════
    def attach_window(self, window) -> None:
        """Reçoit la fenêtre pywebview (pour réduire / fermer / dimensions)."""
        self._window = window
        try:
            window.events.closing += self._on_window_closing
        except Exception:
            pass

    def _on_window_closing(self) -> None:
        self.shutdown()

    def _cleanup_startup(self) -> None:
        try:
            cleanup_orphans()
        except Exception:
            pass

    def _log(self, message: str) -> None:
        entry = {"at": time.strftime("%H:%M:%S"), "msg": str(message)}
        with self._lock:
            self.events.append(entry)
            self.events = self.events[-200:]

    # ═══════════════════════════ Catalogue ═══════════════════════════
    def _start_library_load(self, force: bool = False) -> None:
        def work() -> None:
            self.library_state = "loading"
            self.library_progress = 0.0
            try:
                result = game_fetcher.load_games(force_refresh=force)
            except Exception as exc:
                self.library_state = "error"
                self.library_error = f"{type(exc).__name__} : {exc}"
                self._log(f"Erreur catalogue : {self.library_error}")
                return

            with self._lock:
                self.games = result.games
                self.by_id = {g["id"]: g for g in self.games if g.get("id")}
                self._hay = {}
                for game in self.games:
                    parts = [game.get("name", "")]
                    parts.extend(game.get("aliases") or [])
                    parts.extend(game.get("executables") or [])
                    self._hay[game["id"]] = game_fetcher.normalize(" ".join(parts))

                self.library_state = "ready" if self.games else "error"
                self.library_error = result.error
                self.library_source = "cache" if result.from_cache else "api"
                self.library_loaded_at = result.fetched_at or time.time()
                self.library_progress = 1.0

            self._log(f"Catalogue prêt : {len(self.games)} jeux ({self.library_source}).")

        threading.Thread(target=work, daemon=True, name="library").start()

    def _item(self, game: dict[str, Any]) -> dict[str, Any]:
        exe = game.get("preferred_executable")
        return {
            "id": game.get("id"),
            "name": game.get("name") or "?",
            "exe": exe,
            "hasExe": bool(exe),
            "steam": game.get("steam_id"),
            "icon": game_fetcher.icon_url(game, 128),
            "portrait": game_fetcher.portrait_url(game),
            "banner": game_fetcher.banner_url(game),
            "fav": game.get("id") in self.favorites,
        }

    def _snapshot(self, game: dict[str, Any]) -> dict[str, Any]:
        """Version allégée conservée dans l'historique."""
        return {
            "id": game.get("id"),
            "name": game.get("name") or "?",
            "icon": game_fetcher.icon_url(game, 128),
            "steam": game.get("steam_id"),
            "exe": game.get("preferred_executable"),
            "banner": game_fetcher.banner_url(game),
        }

    # ═══════════════════════════ API : démarrage ═════════════════════
    def bootstrap(self) -> dict[str, Any]:
        """État initial complet, appelé une fois par l'interface."""
        return {
            "ok": True,
            "version": VERSION,
            "settings": self.settings,
            "startup": store.startup_enabled(),
            "dataDir": str(paths.app_dir()),
            "counts": {
                "games": len(self.games),
                "favorites": len(self.favorites),
                "recents": len(self.recents),
                "presets": len(self.presets),
            },
            "favorites": list(self.favorites),
            "recents": self.recents,
            "presets": self.presets,
            "discord": self._discord_state(),
            "library": self._library_state(),
            "running": self._running_state(),
            "runningGames": self._running_games(),
        }

    def status(self) -> dict[str, Any]:
        """État rafraîchi (appelé chaque seconde par l'interface)."""
        return {
            "discord": self._discord_state(),
            "library": self._library_state(),
            "running": self._running_state(),
            "runningGames": self._running_games(),
            "counts": {
                "favorites": len(self.favorites),
                "recents": len(self.recents),
                "presets": len(self.presets),
            },
        }

    def _discord_state(self) -> dict[str, Any]:
        pipes = list_ipc_pipes()
        return {
            "running": diag.discord_process_count() > 0,
            "pipes": pipes,
            "ipc": bool(pipes),
            "version": diag.discord_version(),
        }

    def _library_state(self) -> dict[str, Any]:
        return {
            "state": self.library_state,
            "count": len(self.games),
            "error": self.library_error,
            "source": self.library_source,
            "progress": round(game_fetcher.PROGRESS, 3),
        }

    def _running_games(self) -> list[dict[str, Any]]:
        """Renvoie l'état de tous les faux jeux actifs."""
        games = []
        for game_id, (fake, info) in self.fakes.items():
            if not fake.running:
                continue
            games.append({**info, "gameId": game_id, "kind": "process",
                          "elapsed": fake.elapsed_seconds})
        return sorted(games, key=lambda item: item.get("started") or 0)

    def _running_state(self) -> dict[str, Any] | None:
        if self.running and self.running.get("kind") == "rpc":
            running = self.running
            elapsed = max(0, _now() - int(running.get("started") or _now()))
            return {**running, "elapsed": elapsed}
        games = self._running_games()
        return games[-1] if games else None

    # ═══════════════════════════ API : recherche ═════════════════════
    def search_games(self, query: str = "", tab: str = "all",
                     offset: int = 0, limit: int = 60) -> dict[str, Any]:
        offset = max(0, int(offset or 0))
        limit = max(1, min(120, int(limit or 60)))
        query = (query or "").strip()
        tab = tab or "all"

        if tab == "recents":
            games: list[dict[str, Any]] = []
            for snap in self.recents:
                game = self.by_id.get(snap.get("id"))
                games.append(self._item(game) if game else {
                    "id": snap.get("id"), "name": snap.get("name") or "?",
                    "exe": snap.get("exe"), "hasExe": bool(snap.get("exe")),
                    "steam": snap.get("steam"), "icon": snap.get("icon"),
                    "portrait": snap.get("portrait"), "banner": snap.get("banner"),
                    "fav": snap.get("id") in self.favorites,
                })
            if query:
                q = game_fetcher.normalize(query)
                games = [g for g in games if q in game_fetcher.normalize(g["name"])]
            total = len(games)
            return {"items": games[offset:offset + limit], "total": total,
                    "hasMore": offset + limit < total}

        if tab == "favorites":
            base = [self.by_id[i] for i in self.favorites if i in self.by_id]
            base.sort(key=lambda g: game_fetcher.normalize(g.get("name", "")))
        else:
            base = self.games

        if query:
            q = game_fetcher.normalize(query)
            hay = self._hay
            matches = [g for g in base if q in hay.get(g.get("id"), "")]
            # classement : nom exact, préfixe, puis alphabétique
            def rank(game: dict[str, Any]) -> tuple[int, str]:
                name = game_fetcher.normalize(game.get("name", ""))
                if name == q:
                    level = 0
                elif name.startswith(q):
                    level = 1
                elif q in name:
                    level = 2
                else:
                    level = 3
                return (level, name)
            base = sorted(matches, key=rank)

        total = len(base)
        page = base[offset:offset + limit]
        return {
            "items": [self._item(g) for g in page],
            "total": total,
            "hasMore": offset + limit < total,
        }

    def get_game(self, game_id: str) -> dict[str, Any]:
        game = self.by_id.get(str(game_id))
        if not game:
            return {"ok": False, "code": "not_found"}
        item = self._item(game)
        item["executables"] = game.get("executables") or []
        item["aliases"] = game.get("aliases") or []
        item["ok"] = True
        return item

    def refresh_library(self) -> dict[str, Any]:
        if self.library_state == "loading":
            return {"ok": True, "already": True}
        self._log("Rafraîchissement manuel du catalogue.")
        self._start_library_load(force=True)
        return {"ok": True}

    def resolve_app(self, app_id: str) -> dict[str, Any]:
        """Retrouve le nom et l'icône d'une application Discord à partir de son ID."""
        app_id = str(app_id or "").strip()
        if not app_id.isdigit() or len(app_id) < 10:
            return {"ok": True, "found": False}

        game = self.by_id.get(app_id)
        if game:
            return {
                "ok": True, "found": True,
                "name": game.get("name"),
                "icon": game_fetcher.icon_url(game, 256),
                "banner": game_fetcher.banner_url(game),
            }

        if app_id in self._app_cache:
            return self._app_cache[app_id]

        result: dict[str, Any] = {"ok": True, "found": False}
        try:
            response = requests.get(
                f"https://discord.com/api/v10/applications/{app_id}/public",
                timeout=6,
                headers={"User-Agent": "Orbs/2.0"},
            )
            if response.ok:
                data = response.json()
                name = data.get("name")
                icon = data.get("icon")
                url = (f"https://cdn.discordapp.com/app-icons/{app_id}/{icon}.png?size=256"
                       if icon else None)
                result = {"ok": True, "found": bool(name), "name": name,
                          "icon": url, "banner": url}
        except Exception:
            pass

        self._app_cache[app_id] = result
        return result

    def clear_history(self) -> dict[str, Any]:
        with self._lock:
            self.recents = []
        store.save_recents([])
        return {"ok": True}

    # ═══════════════════════════ API : présence ══════════════════════
    def launch(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Lance une présence (Rich Presence) ou un faux processus."""
        payload = payload or {}
        method = payload.get("method") or "rpc"
        app_id = str(payload.get("appId") or "").strip()
        name = str(payload.get("name") or "").strip() or "Jeu"
        details = (payload.get("details") or "").strip()
        state = (payload.get("state") or "").strip()
        large_image = (payload.get("largeImage") or "").strip()
        large_text = (payload.get("largeText") or "").strip()
        playtime_hours = max(0, min(87600, int(self.settings.get("playtime_hours") or 0)))
        started = _now() - playtime_hours * 3600

        if method == "process":
            return self._launch_process(payload)

        if not app_id.isdigit() or len(app_id) < 10:
            return {"ok": False, "code": "invalid_id",
                    "message": "ID d'application Discord invalide (chiffres uniquement)."}

        if app_id and self.running and self.running.get("kind") == "rpc" \
                and self.running.get("appId") == app_id and self.rpc.is_connected:
            ok, message = self.rpc.set_presence(
                details=details or "En jeu", state=state or None,
                large_image=large_image or None, large_text=large_text or None,
                start_time=started,
            )
            if ok:
                self._update_running(details=details, state=state, started=started)
                return {"ok": True, "code": "updated", "running": self._running_state()}
            return {"ok": False, "code": "rpc_error", "message": message}

        self.stop_presence()

        ok, message = self.rpc.connect(app_id)
        if not ok:
            self._log(f"Échec connexion RPC : {message}")
            return {"ok": False, "code": "connect_failed", "message": message}

        ok, message = self.rpc.set_presence(
            details=details or "En jeu",
            state=state or None,
            large_image=large_image or None,
            large_text=large_text or None,
            start_time=started,
        )
        if not ok:
            self.rpc.disconnect()
            self._log(f"Échec présence : {message}")
            return {"ok": False, "code": "presence_failed", "message": message}

        game = self.by_id.get(str(payload.get("gameId") or ""))
        cover = payload.get("icon") or (self._snapshot(game)["icon"] if game else None)
        banner = payload.get("banner") or (self._snapshot(game)["banner"] if game else None)

        self.running = {
            "kind": "rpc",
            "appId": app_id,
            "name": name,
            "gameId": payload.get("gameId"),
            "details": details,
            "state": state,
            "icon": cover,
            "banner": banner,
            "started": started,
        }
        self._remember(game, name, payload)
        self._log(f"Rich Presence lancée : {name} (ID {app_id}).")
        return {"ok": True, "code": "started", "running": self._running_state()}

    def _launch_process(self, payload: dict[str, Any]) -> dict[str, Any]:
        exe = str(payload.get("exe") or "").strip()
        if not exe:
            return {"ok": False, "code": "no_exe",
                    "message": "Ce jeu n'a pas d'exécutable Windows connu."}
        game_id = str(payload.get("gameId") or exe.lower())
        existing = self.fakes.get(game_id)
        if existing and existing[0].running:
            existing[0].stop()
            self.fakes.pop(game_id, None)
            self._log(f"Faux processus arrêté : {existing[1].get('name') or exe}.")
            return {"ok": True, "code": "stopped", "message": "Jeu arrêté.",
                    "running": self._running_state(), "runningGames": self._running_games()}

        visible = bool(self.settings.get("show_fake_window"))
        fake = FakeProcess(
            exe, duration_minutes=None,
            on_exit=lambda reason, gid=game_id, instance=None:
                self._on_fake_exit(gid, instance or fake, reason),
            visible_window=visible,
        )
        ok, message = fake.start()
        if not ok:
            self._log(f"Échec faux processus : {message}")
            return {"ok": False, "code": "process_failed", "message": message}

        game = self.by_id.get(str(payload.get("gameId") or ""))
        snap = self._snapshot(game) if game else {}
        info = {
            "kind": "process",
            "gameId": game_id,
            "name": payload.get("name") or fake.exe_name,
            "exe": fake.exe_name,
            "icon": payload.get("icon") or snap.get("icon"),
            "banner": payload.get("banner") or snap.get("banner"),
            "started": _now(),
        }
        self.fakes[game_id] = (fake, info)
        self._remember(game, info["name"], payload)
        self._log(f"Faux processus lancé : {fake.exe_name}.")
        return {"ok": True, "code": "process_started",
                "running": self._running_state(),
                "runningGames": self._running_games(), "message": message}

    def _on_fake_exit(self, game_id: str, fake: FakeProcess, reason: str) -> None:
        with self._lock:
            current = self.fakes.get(game_id)
            if current and current[0] is fake:
                self.fakes.pop(game_id, None)
        self._log(f"Faux processus terminé : {reason}")

    def stop_game(self, game_id: str) -> dict[str, Any]:
        """Arrête un seul faux jeu, sans toucher aux autres activités."""
        key = str(game_id or "")
        current = self.fakes.get(key)
        if not current:
            return {"ok": False, "code": "not_running",
                    "running": self._running_state(), "runningGames": self._running_games()}
        fake, info = current
        fake.stop()
        self.fakes.pop(key, None)
        self._log(f"Faux processus arrêté : {info.get('name') or key}.")
        return {"ok": True, "code": "stopped", "message": "Jeu arrêté.",
                "running": self._running_state(), "runningGames": self._running_games()}

    def _update_running(self, **patch: Any) -> None:
        if not self.running:
            return
        for key, value in patch.items():
            if value is not None:
                self.running[key] = value

    def stop_presence(self) -> dict[str, Any]:
        message = ""
        if self.rpc.is_connected:
            self.rpc.clear_presence()
            self.rpc.disconnect()
            message = "Présence désactivée."
        if self.running and self.running.get("kind") == "rpc":
            self.running = None
        if message:
            self._log(message)
        return {"ok": True, "code": "stopped", "message": message,
                "running": self._running_state(), "runningGames": self._running_games()}

    def _remember(self, game: dict[str, Any] | None,
                  name: str, payload: dict[str, Any]) -> None:
        snapshot = self._snapshot(game) if game else {
            "id": str(payload.get("gameId") or payload.get("appId") or uuid.uuid4()),
            "name": name,
            "icon": payload.get("icon"),
            "banner": payload.get("banner"),
            "steam": None,
            "exe": payload.get("exe"),
        }
        snapshot["at"] = _now()
        with self._lock:
            self.recents = [r for r in self.recents if r.get("id") != snapshot.get("id")]
            self.recents.insert(0, snapshot)
            self.recents = self.recents[:store.MAX_RECENTS]
        store.save_recents(self.recents)

    # ═══════════════════════════ API : favoris ═══════════════════════
    def toggle_favorite(self, game_id: str) -> dict[str, Any]:
        game_id = str(game_id or "")
        if not game_id:
            return {"ok": False}
        with self._lock:
            if game_id in self.favorites:
                self.favorites.remove(game_id)
                active = False
            else:
                self.favorites.insert(0, game_id)
                active = True
            store.save_favorites(self.favorites)
        return {"ok": True, "fav": active, "count": len(self.favorites)}

    # ═══════════════════════════ API : presets ═══════════════════════
    def save_preset(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        name = str(payload.get("name") or "").strip()
        app_id = str(payload.get("appId") or "").strip()
        if not name:
            return {"ok": False, "code": "name_required"}
        if not app_id.isdigit():
            return {"ok": False, "code": "invalid_id"}

        preset = {
            "id": str(payload.get("id") or uuid.uuid4().hex[:10]),
            "name": name,
            "appId": app_id,
            "details": str(payload.get("details") or ""),
            "state": str(payload.get("state") or ""),
            "largeImage": str(payload.get("largeImage") or ""),
            "largeText": str(payload.get("largeText") or ""),
            "icon": payload.get("icon"),
            "createdAt": _now(),
        }
        with self._lock:
            self.presets = [p for p in self.presets if p.get("id") != preset["id"]]
            self.presets.insert(0, preset)
            store.save_presets(self.presets)
        self._log(f"Preset enregistré : {name}.")
        return {"ok": True, "preset": preset, "presets": self.presets}

    def delete_preset(self, preset_id: str) -> dict[str, Any]:
        with self._lock:
            self.presets = [p for p in self.presets if p.get("id") != str(preset_id)]
            store.save_presets(self.presets)
        return {"ok": True, "presets": self.presets}

    # ═══════════════════════════ API : réglages ══════════════════════
    def save_settings(self, patch: dict[str, Any] | None = None) -> dict[str, Any]:
        patch = patch or {}
        merged = dict(self.settings)
        merged.update({k: v for k, v in patch.items() if k in store.DEFAULTS})

        if merged.get("lang") not in ("fr", "en"):
            merged["lang"] = "fr"
        if merged.get("accent") not in _ACCENTS:
            merged["accent"] = "blurple"

        try:
            merged["playtime_hours"] = max(0, min(87600, int(merged.get("playtime_hours") or 0)))
        except (TypeError, ValueError, OverflowError):
            merged["playtime_hours"] = 0

        startup = bool(merged.get("start_with_windows"))
        if startup != store.startup_enabled():
            store.set_startup(startup)

        self.settings = store.save_settings(merged)
        return {"ok": True, "settings": self.settings,
                "startup": store.startup_enabled()}

    def save_window_size(self, width: int, height: int) -> dict[str, Any]:
        with self._lock:
            self.settings["window"] = {
                "width": max(960, int(width)),
                "height": max(640, int(height)),
            }
        store.save_settings(self.settings)
        return {"ok": True}

    # ═══════════════════════════ API : diagnostics ═══════════════════
    def discord_quest_snapshot(self) -> dict[str, Any]:
        """Read visible Quest Home text from Discord via Windows UI Automation."""
        try:
            return discord_quests.read_quest_home()
        except Exception as exc:
            return {"ok": False, "code": "uia_error", "message": type(exc).__name__}

    def diagnostics(self) -> dict[str, Any]:
        fake_status = None
        active_fake = next((fake for fake, _ in self.fakes.values() if fake.running), None)
        if active_fake:
            fake_status = {
                "actif": True,
                "image": active_fake.exe_name,
                "depuis": active_fake.elapsed_seconds,
                "limite": not active_fake.unlimited,
                "restant": active_fake.remaining_seconds,
                "detail": active_fake.verify()[1],
                "nombre": len(self._running_games()),
            }
        selected = self.by_id.get(str((self.running or {}).get("gameId") or ""))
        try:
            report = diag.build_report(
                games_count=len(self.games),
                from_cache=self.library_source == "cache",
                games_error=self.library_error,
                selected=selected,
                fake_status=fake_status,
                rpc_status=self.rpc.diagnostics(),
            )
        except Exception as exc:
            report = f"Erreur pendant le diagnostic : {type(exc).__name__} : {exc}"

        detections = []
        try:
            for detection in diag.recent_detections(30)[-10:]:
                detections.append({
                    "time": detection.heure.strftime("%H:%M:%S"),
                    "game": detection.jeu,
                })
        except Exception:
            pass

        return {
            "ok": True,
            "text": report,
            "discord": self._discord_state(),
            "pipes": list_ipc_pipes(),
            "detections": detections,
            "events": int(diag.game_change_events(30)),
            "log": self.events[-40:],
            "rpc": self.rpc.diagnostics(),
            "library": self._library_state(),
        }

    # ═══════════════════════════ API : divers ════════════════════════
    def open_url(self, url: str) -> dict[str, Any]:
        url = str(url or "")
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "code": "invalid_url"}
        try:
            webbrowser.open(url)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def open_data_folder(self) -> dict[str, Any]:
        try:
            os.startfile(str(paths.app_dir()))  # type: ignore[attr-defined]
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def debug_log(self, message: str) -> None:
        """Journal JS → fichier, utile en développement (jamais bloquant)."""
        try:
            with open(paths.data_file("debug.log"), "a", encoding="utf-8") as handle:
                handle.write(f"[{time.strftime('%H:%M:%S')}] {message}\n")
        except Exception:
            pass

    # ═══════════════════════════ Fenêtre ═════════════════════════════
    def fit_window(self, width: int, height: int) -> dict[str, Any]:
        """Adapte la fenêtre à l'écran (utile en mise à l'échelle 125 %)."""
        window = self._window
        if window is None:
            return {"ok": False}
        try:
            window.resize(max(980, int(width)), max(600, int(height)))
            window.move(24, 24)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True}

    def window_action(self, action: str) -> dict[str, Any]:
        window = self._window
        if window is None:
            return {"ok": False}
        try:
            if action == "minimize":
                window.minimize()
            elif action == "maximize":
                if getattr(window, "maximized", False):
                    window.restore()
                else:
                    window.maximize()
                return {"ok": True, "maximized": getattr(window, "maximized", False)}
            elif action == "close":
                self.shutdown()
                window.destroy()
            elif action == "hide":
                window.hide()
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "maximized": getattr(window, "maximized", False)}

    def window_state(self) -> dict[str, Any]:
        window = self._window
        return {
            "width": getattr(window, "width", 1280),
            "height": getattr(window, "height", 820),
            "maximized": getattr(window, "maximized", False),
        }

    def quit(self) -> dict[str, Any]:
        self.shutdown()
        window = self._window
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass
        return {"ok": True}

    # ═══════════════════════════ Arrêt ═══════════════════════════════
    def shutdown(self) -> None:
        try:
            if self.rpc.is_connected:
                self.rpc.clear_presence()
                self.rpc.disconnect()
        except Exception:
            pass
        for fake, _ in list(self.fakes.values()):
            try:
                if fake.running:
                    fake.stop()
            except Exception:
                pass
        self.fakes.clear()
        self.running = None
        try:
            window = self._window
            if window is not None:
                self.save_window_size(getattr(window, "width", 1280),
                                      getattr(window, "height", 820))
        except Exception:
            pass


def safe_call(func):
    """Décorateur de secours (facultatif) pour tracer les erreurs du pont."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            return {"ok": False, "message": traceback.format_exc(limit=3)}
    return wrapper
