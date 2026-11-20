# rpc_manager.py
"""
Gestion du Rich Presence Discord (méthode FIABLE).

Pourquoi c'est la méthode recommandée ?
    Les tests menés sur Discord 1.0.9269 (novembre 2026) montrent que la
    détection par nom de processus ne fonctionne plus : un binaire renommé
    (cmd.exe, ou même un vrai exécutable compilé avec PyInstaller) n'apparaît
    jamais dans l'activité. En revanche, l'API locale de Discord accepte
    parfaitement une présence envoyée via pypresence : le statut « Joue à … »
    s'affiche alors avec le nom et l'icône de l'application Discord utilisée.

Fonctionnement :
    1. On se connecte au canal IPC local de Discord (\\\\.\\pipe\\discord-ipc-0).
    2. On envoie une activité (details / state / timestamp) pour un ID
       d'application Discord.
    3. Discord affiche « Joue à <nom de l'application> ».

Important : le NOM affiché est celui de l'application Discord associée à l'ID.
    * Pour afficher un vrai jeu : utilise l'ID officiel du jeu (récupéré depuis
      la liste detectable — l'interface le remplit automatiquement).
    * Pour un nom libre : crée ton application sur
      https://discord.com/developers/applications et utilise son ID.

Améliorations par rapport à la version précédente :
  * détection claire de l'absence de Discord (message explicite au lieu d'une
    exception brute) ;
  * reconnexion automatique si le canal IPC tombe (redémarrage de Discord) ;
  * renvoi périodique de la présence (keepalive) pour qu'elle ne disparaisse pas ;
  * verrou de thread : appels sûrs depuis l'interface ;
  * messages d'erreur en français et explicites.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from pypresence import Presence
from pypresence import exceptions as rpc_exceptions

# Les noms d'exceptions varient selon les versions de pypresence : on les
# récupère de façon défensive pour éviter un ImportError au démarrage.
_PYPRESENCE_ERROR = getattr(rpc_exceptions, "PyPresenceException", Exception)

PIPE_PREFIX = "discord-ipc"


def list_ipc_pipes() -> list[str]:
    """Liste les canaux IPC Discord disponibles (vide si Discord est fermé)."""
    if os.name != "nt":
        return []
    try:
        names = os.listdir(r"\\.\pipe\\")
    except Exception:
        return []
    return sorted(name for name in names if name.startswith(PIPE_PREFIX))


def discord_ipc_available() -> bool:
    """Indique si le client Discord expose au moins un canal IPC."""
    return bool(list_ipc_pipes())


class RPCManager:
    """Encapsule une connexion Rich Presence à Discord."""

    def __init__(self) -> None:
        self.rpc: Presence | None = None
        self.connected = False
        self.client_id: str | None = None

        self._last_payload: dict[str, Any] | None = None
        self._lock = threading.RLock()
        self._keepalive_stop = threading.Event()
        self._keepalive_thread: threading.Thread | None = None

    # ─────────────────── connexion ──────────────────────────────
    def connect(self, client_id: str) -> tuple[bool, str]:
        """Se connecte au client Discord avec l'ID d'application fourni."""
        client_id = str(client_id or "").strip()

        if not client_id.isdigit():
            return False, "L'ID d'application doit être composé uniquement de chiffres."

        if not discord_ipc_available():
            return False, ("Discord ne semble pas ouvert (aucun canal IPC trouvé). "
                           "Lance le client Discord, connecte-toi, puis réessaie.")

        with self._lock:
            self._disconnect_locked()

            try:
                rpc = Presence(client_id)
                rpc.connect()
            except _PYPRESENCE_ERROR as exc:
                return False, f"Discord a refusé la connexion : {_explain(exc)}"
            except Exception as exc:  # OSError, BrokenPipeError, timeout…
                return False, f"Connexion impossible : {type(exc).__name__} : {exc}"

            self.rpc = rpc
            self.client_id = client_id
            self.connected = True

        self._start_keepalive()
        return True, "Connecté à Discord."

    # ─────────────────── présence ──────────────────────────────
    def set_presence(self, details: str | None = None, state: str | None = None,
                     large_image: str | None = None, large_text: str | None = None,
                     small_image: str | None = None, small_text: str | None = None,
                     start_time: int | None = None, party_size: list[int] | None = None,
                     buttons: list[dict[str, str]] | None = None) -> tuple[bool, str]:
        """
        Envoie une activité à Discord.

        Les paramètres vides sont ignorés (Discord n'aime pas les chaînes vides).
        `large_image` doit être une clé d'asset existante sur l'application ;
        pour un ID de jeu officiel on ne l'envoie pas (l'icône vient du jeu).
        """
        with self._lock:
            if not self.connected or not self.rpc:
                return False, "Non connecté à Discord."

            payload: dict[str, Any] = {}
            if details:
                payload["details"] = str(details)[:128]
            if state:
                payload["state"] = str(state)[:128]
            if large_image:
                payload["large_image"] = large_image
            if large_text:
                payload["large_text"] = str(large_text)[:128]
            if small_image:
                payload["small_image"] = small_image
            if small_text:
                payload["small_text"] = str(small_text)[:128]
            if start_time:
                payload["start"] = int(start_time)
            if party_size:
                payload["party_size"] = list(party_size)
            if buttons:
                payload["buttons"] = buttons

            ok, message = self._send(payload)
            if ok:
                self._last_payload = payload
            return ok, message

    def set_game_presence(self, game_name: str, details: str | None = None,
                          state: str | None = None,
                          start_time: int | None = None) -> tuple[bool, str]:
        """
        Raccourci : présence « jeu » avec un timestamp de début.
        C'est le nom de l'application Discord qui détermine le « Joue à … ».
        """
        return self.set_presence(
            details=details or game_name,
            state=state,
            start_time=start_time or int(time.time()),
        )

    def _send(self, payload: dict[str, Any]) -> tuple[bool, str]:
        """Envoie le payload, avec une tentative de reconnexion en cas de pipe cassé."""
        if not self.rpc:
            return False, "Non connecté à Discord."

        try:
            self.rpc.update(**payload)
            return True, "Présence mise à jour."
        except Exception as exc:
            if not _is_pipe_error(exc):
                return False, f"Erreur RPC : {_explain(exc)}"

            # Le canal IPC est mort (Discord redémarré ?) : on retente une fois.
            if not self._reconnect_locked():
                return False, ("La connexion à Discord a été perdue et la reconnexion "
                               "a échoué. Vérifie que Discord est bien ouvert.")
            try:
                self.rpc.update(**payload)
                return True, "Présence mise à jour (reconnexion automatique)."
            except Exception as exc2:
                return False, f"Erreur RPC après reconnexion : {_explain(exc2)}"

    # ─────────────────── keepalive ─────────────────────────────
    def _start_keepalive(self, interval: int = 20) -> None:
        """Renvoie régulièrement la présence pour qu'elle ne disparaisse pas."""
        self._stop_keepalive()
        self._keepalive_stop.clear()

        def loop() -> None:
            while not self._keepalive_stop.wait(interval):
                payload = self._last_payload
                if not payload or not self.connected:
                    continue
                with self._lock:
                    if self.connected and self.rpc:
                        try:
                            self.rpc.update(**payload)
                        except Exception:
                            # Échec silencieux : la prochaine boucle retentera,
                            # la reconnexion est gérée par _send lors d'un envoi.
                            pass

        self._keepalive_thread = threading.Thread(target=loop, daemon=True,
                                                  name="rpc-keepalive")
        self._keepalive_thread.start()

    def _stop_keepalive(self) -> None:
        self._keepalive_stop.set()
        thread = self._keepalive_thread
        if thread and thread.is_alive():
            thread.join(timeout=1)
        self._keepalive_thread = None

    # ─────────────────── reconnexion / arrêt ───────────────────
    def _reconnect_locked(self) -> bool:
        """Recrée la connexion (utilisé après une perte du canal IPC)."""
        if not self.client_id:
            return False
        try:
            self._disconnect_locked()
            rpc = Presence(self.client_id)
            rpc.connect()
            self.rpc = rpc
            self.connected = True
            return True
        except Exception:
            self.connected = False
            self.rpc = None
            return False

    def clear_presence(self) -> tuple[bool, str]:
        """Efface l'activité affichée (le compte redevient « en ligne »)."""
        with self._lock:
            if not self.connected or not self.rpc:
                return False, "Non connecté."
            try:
                self.rpc.clear()
                self._last_payload = None
                return True, "Présence effacée."
            except Exception as exc:
                return False, f"Erreur : {_explain(exc)}"

    def _disconnect_locked(self) -> None:
        if self.rpc:
            try:
                self.rpc.close()
            except Exception:
                pass
        self.rpc = None
        self.connected = False

    def disconnect(self) -> tuple[bool, str]:
        """Déconnecte proprement et arrête le keepalive."""
        self._stop_keepalive()
        with self._lock:
            was_connected = self.connected
            self._disconnect_locked()
            self._last_payload = None
        if was_connected:
            return True, "RPC déconnecté."
        return False, "Déjà déconnecté."

    # ─────────────────── divers ───────────────────────────────
    @property
    def is_connected(self) -> bool:
        return self.connected

    def diagnostics(self) -> dict[str, Any]:
        """Petit dictionnaire d'état, utile pour la fenêtre de diagnostic."""
        return {
            "connecte": self.connected,
            "client_id": self.client_id,
            "canaux_ipc": list_ipc_pipes(),
        }


# ─────────────────────────── Aides ───────────────────────────────
def _is_pipe_error(exc: Exception) -> bool:
    """Reconnaît une erreur de canal IPC (donc récupérable par reconnexion)."""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return ("pipe" in name or "pipe" in text or "broken" in text
            or isinstance(exc, (BrokenPipeError, ConnectionError, OSError)))


def _explain(exc: Exception) -> str:
    """Traduit les erreurs pypresence les plus courantes en message lisible."""
    name = type(exc).__name__
    text = str(exc)

    if name == "InvalidID" or "invalid client id" in text.lower():
        return "ID d'application invalide (vérifie les 18-19 chiffres)."
    if name == "InvalidPipe" or "could not find discord" in text.lower():
        return "Discord n'est pas lancé ou l'API locale est inaccessible."
    if name == "PipeClosed" or "pipe" in text.lower():
        return "Le canal de communication avec Discord a été fermé."
    if "response timed out" in text.lower():
        return "Discord n'a pas répondu (client figé ?)."
    return f"{name} : {text}"
