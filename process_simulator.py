# process_simulator.py
"""
Simulation d'un processus de jeu (méthode « faux processus »).

═══ CE QUI A ÉTÉ DÉCOUVERT PAR LES TESTS (Discord 1.0.9269, 19/11/2026) ═══

Discord ne se contente pas de lire le nom du processus : il lui faut DEUX
conditions. Les six essais contrôlés menés sur cette machine le montrent :

  nom d'image        | fenêtre              | détecté
  -------------------|----------------------|---------
  hotlinemiami.exe   | vraie fenêtre GUI    | OUI  (« Hotline Miami »)
  hotlinemiami.exe   | vraie fenêtre GUI    | OUI  (copié dans %TEMP% !)
  undertale.exe      | vraie fenêtre GUI    | OUI  (même binaire, renommé)
  undertale.exe      | console cachée       | non
  undertale.exe      | console visible      | non
  undertale.exe      | exe PyInstaller sans fenêtre | non

Autrement dit :
  1. le NOM DU FICHIER est bien ce qui associe le processus au jeu
     (le binaire de Hotline Miami renommé « undertale.exe » est annoncé comme
     UNDERTALE !) ;
  2. le processus doit posséder une VRAIE FENÊTRE GUI. Une fenêtre de console
     ne suffit pas, et un programme sans fenêtre non plus. Le chemin du fichier,
     lui, n'a aucune importance ;
  3. le titre de la fenêtre est indifférent (une fenêtre intitulée « SOUVENIR »
     est bien reconnue comme UNDERTALE).

D'où la technique utilisée ici : on copie un binaire système **GUI**
(mshta.exe, sinon wscript.exe) sous le nom exact de l'exécutable du jeu, et on
lui fait ouvrir une minuscule fenêtre sans bordure, placée HORS ÉCRAN. Le
processus est donc invisible pour toi, mais parfaitement réel pour Windows —
et donc pour Discord.

Le bug de la version précédente est expliqué plus bas (`timeout` + stdin).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import paths

# Dossier des faux exécutables : dossier du projet en développement, ou
# %LOCALAPPDATA%\DiscordFakeGame\fake_processes depuis un .exe (voir paths.py).
FAKE_DIR = paths.fake_dir()

# Caractères interdits dans un nom de fichier Windows.
_INVALID_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')

# Binaires système possédant une vraie fenêtre GUI (indispensable).
_GUI_HOSTS = ("mshta.exe", "wscript.exe")

# Position hors écran : la fenêtre existe, mais personne ne la voit.
_OFFSCREEN = (-4000, -4000)

# Gabarit de la fenêtre « pont » ouverte par mshta.
_HTA_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>Discord Fake Game</title>
<hta:application
    id="fakegame"
    border="none"
    caption="no"
    showintaskbar="no"
    scroll="no"
    contextmenu="no"
    selection="no" />
<script type="text/javascript">
    // Fenêtre minuscule, sans bordure, volontairement hors de l'écran :
    // invisible pour l'utilisateur, mais bien réelle pour Windows (Discord
    // exige une fenêtre GUI pour reconnaître le processus).
    window.resizeTo({width}, {height});
    window.moveTo({x}, {y});
</script>
</head>
<body style="background:#000000;margin:0;overflow:hidden"></body>
</html>
"""

# Solution de repli si mshta.exe est absent : une boîte de dialogue wscript.
_VBS_TEMPLATE = 'MsgBox "Discord Fake Game", 64, "Discord Fake Game"\n'

# Petit fichier de suivi, pour pouvoir tuer un processus laissé par une session
# précédente (utile maintenant que le processus n'a plus de limite de temps).
_PID_FILE = FAKE_DIR / ".running.json"
_PID_LOCK = threading.RLock()


# ─────────────────────────── Utilitaires ──────────────────────────
def sanitize_relative_path(raw_name: str) -> str:
    """
    Transforme un nom d'exécutable Discord (parfois un chemin relatif comme
    "among us/among us.exe" ou "win64/game.exe") en chemin relatif sûr.

    On conserve les sous-dossiers : Discord associe certains jeux à une
    arborescence précise, et cela ne coûte rien de la reproduire.
    """
    raw = str(raw_name or "").strip()
    parts = [p for p in re.split(r"[\\/]+", raw) if p not in ("", ".", "..")]

    cleaned: list[str] = []
    for part in parts:
        part = _INVALID_CHARS.sub("_", part).strip()
        part = part.rstrip(". ") or "_"
        cleaned.append(part)

    if not cleaned:
        cleaned = ["fake_game.exe"]

    if not cleaned[-1].lower().endswith(".exe"):
        cleaned[-1] += ".exe"

    return os.path.join(*cleaned)


def sanitize_exe_name(raw_name: str) -> str:
    """Compatibilité : retourne uniquement le nom de fichier final, assaini."""
    return os.path.basename(sanitize_relative_path(raw_name))


def _system32() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


def find_gui_host() -> Path | None:
    """
    Retourne un binaire système GUI à copier (mshta.exe de préférence : sa
    fenêtre est déplaçable hors écran et sans bordure).
    """
    for name in _GUI_HOSTS:
        candidate = _system32() / name
        if candidate.exists():
            return candidate
    return None


def list_running_images() -> set[str]:
    """
    Noms d'images en cours d'exécution (minuscules), tels que les voit le
    Gestionnaire des tâches — et donc Discord.
    """
    if sys.platform != "win32":
        return set()

    try:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
    except Exception:
        return set()

    images: set[str] = set()
    for line in completed.stdout.splitlines():
        match = re.match(r'"([^"]+)"', line.strip())
        if match:
            images.add(match.group(1).lower())
    return images


def image_is_running(image_name: str) -> bool:
    """Indique si un processus portant ce nom d'image est en cours."""
    return (image_name or "").lower() in list_running_images()


def _read_running_records() -> list[dict[str, object]]:
    try:
        raw = json.loads(_PID_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(raw, dict):
        raw = [raw]  # Compatibilité avec le format historique (un seul PID).
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _write_running_records(records: list[dict[str, object]]) -> None:
    try:
        FAKE_DIR.mkdir(parents=True, exist_ok=True)
        if records:
            _PID_FILE.write_text(json.dumps(records), encoding="utf-8")
        else:
            _PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _save_running(pid: int, exe_name: str) -> None:
    """Mémorise chaque processus pour pouvoir tous les arrêter au prochain démarrage."""
    with _PID_LOCK:
        records = [record for record in _read_running_records()
                   if int(record.get("pid") or 0) != pid]
        records.append({"pid": pid, "exe": exe_name.lower()})
        _write_running_records(records)


def _remove_running(pid: int | None) -> None:
    if not pid:
        return
    with _PID_LOCK:
        records = [record for record in _read_running_records()
                   if int(record.get("pid") or 0) != pid]
        _write_running_records(records)


def _clear_running() -> None:
    with _PID_LOCK:
        _write_running_records([])


def _kill_previous() -> str | None:
    """Tue tous les processus résiduels laissés par une session précédente."""
    with _PID_LOCK:
        records = _read_running_records()
        _write_running_records([])
    killed: list[str] = []
    for record in records:
        try:
            pid = int(record.get("pid") or 0)
            exe = str(record.get("exe") or "").lower()
        except (TypeError, ValueError):
            continue
        if not pid or not exe:
            continue
        try:
            listing = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            ).stdout.lower()
            # Vérifie le nom d'image afin de ne pas tuer un PID recyclé.
            if exe in listing:
                subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                               capture_output=True, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
                killed.append(f"{exe} (PID {pid})")
        except Exception:
            continue
    if not killed:
        return None
    return "Processus résiduels arrêtés : " + ", ".join(killed) + "."


def cleanup_orphans() -> int:
    """
    Nettoie la session précédente : tue un éventuel processus résiduel puis
    supprime les fichiers restants. Windows interdit la suppression d'un
    exécutable en cours d'exécution : cette fonction est sans danger.
    """
    _kill_previous()

    if not FAKE_DIR.exists():
        return 0
    removed = 0
    for path in sorted(FAKE_DIR.rglob("*"), reverse=True):
        try:
            if path.is_file():
                path.unlink()
                removed += 1
            elif path.is_dir():
                path.rmdir()
        except Exception:
            continue
    return removed


# ─────────────────────────── Classe principale ────────────────────
class FakeProcess:
    """
    Gère le cycle de vie d'un faux processus de jeu.

    Utilisation :
        fp = FakeProcess("undertale.exe")                  # sans limite de temps
        fp = FakeProcess("undertale.exe", duration_minutes=15)  # limité à 15 min
        ok, msg = fp.start()
        ...
        fp.stop()
    """

    def __init__(self, exe_name: str, duration_minutes: float | None = None,
                 on_exit: Callable[[str], None] | None = None,
                 visible_window: bool = False):
        self.relative_path = sanitize_relative_path(exe_name)
        self.exe_name = os.path.basename(self.relative_path)
        self.instance_id = uuid.uuid4().hex

        # duration_minutes = None (ou 0) → aucune limite : le processus tourne
        # jusqu'à ce que l'utilisateur clique sur « Arrêter ».
        self.unlimited = not duration_minutes
        self.duration = None if self.unlimited else max(1, int(duration_minutes * 60))

        self.visible_window = visible_window
        self.on_exit = on_exit

        self.process: subprocess.Popen | None = None
        self.running = False
        self.started_at: float | None = None
        self.exit_reason: str | None = None
        self.method: str | None = None

        self._target_path: Path | None = None
        self._bridge_path: Path | None = None
        self._timer: threading.Timer | None = None
        self._watchdog: threading.Thread | None = None
        self._lock = threading.RLock()

    # ─────────────────── propriétés pratiques ───────────────────
    @property
    def remaining_seconds(self) -> int | None:
        """Temps restant, ou None si le processus n'a pas de limite."""
        if self.unlimited:
            return None
        if not self.running or not self.started_at:
            return 0
        return max(0, int(self.duration - (time.time() - self.started_at)))

    @property
    def elapsed_seconds(self) -> int:
        if not self.started_at:
            return 0
        return int(time.time() - self.started_at)

    def verify(self) -> tuple[bool, str]:
        """Vérifie que le processus est vivant et bien nommé pour Windows."""
        if not self.process:
            return False, "Aucun processus lancé."

        if self.process.poll() is not None:
            return False, f"Le processus est terminé (code {self.process.returncode})."

        if sys.platform == "win32":
            if image_is_running(self.exe_name):
                return True, f"Vivant sous « {self.exe_name} » dans le Gestionnaire des tâches."
            return False, (f"Le processus tourne mais « {self.exe_name} » n'apparaît pas "
                           f"dans tasklist (nom d'image inattendu).")

        return True, "Vivant."

    # ─────────────────── fenêtre « pont » ───────────────────────
    def _offset(self) -> tuple[int, int]:
        return (220, 220) if self.visible_window else _OFFSCREEN

    def _write_bridge(self, host: Path) -> list[str]:
        """
        Crée le fichier qui fait ouvrir une vraie fenêtre au processus copié,
        et retourne la ligne de commande à utiliser.
        """
        x, y = self._offset()
        bridge_dir = FAKE_DIR / ".bridge"
        bridge_dir.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex[:8]

        if host.name.lower() == "mshta.exe":
            bridge = bridge_dir / f"{token}.hta"
            bridge.write_text(
                _HTA_TEMPLATE.format(width=260 if self.visible_window else 160,
                                     height=140 if self.visible_window else 100,
                                     x=x, y=y),
                encoding="utf-8",
            )
        else:
            # Repli : wscript affiche une petite boîte de dialogue.
            bridge = bridge_dir / f"{token}.vbs"
            bridge.write_text(_VBS_TEMPLATE, encoding="utf-8")

        self._bridge_path = bridge
        return [str(self._target_path), str(bridge)]

    # ─────────────────── lancement ──────────────────────────────
    def start(self) -> tuple[bool, str]:
        """Copie un binaire GUI au nom du jeu puis le lance avec une fenêtre."""
        with self._lock:
            if self.running:
                return False, "Un faux processus est déjà en cours."

            if sys.platform != "win32":
                return False, "Cette fonctionnalité est réservée à Windows."

            host = find_gui_host()
            if host is None:
                return False, ("Aucun binaire GUI système disponible "
                               "(mshta.exe / wscript.exe introuvables).")

            try:
                FAKE_DIR.mkdir(parents=True, exist_ok=True)
                # Chaque instance utilise son propre dossier, même si deux jeux
                # partagent le même nom d’exécutable.
                self._target_path = FAKE_DIR / self.instance_id / self.relative_path
                self._target_path.parent.mkdir(parents=True, exist_ok=True)

                if self._target_path.exists():
                    try:
                        self._target_path.unlink()
                    except Exception:
                        return False, (f"Le fichier {self._target_path.name} est verrouillé "
                                       f"(un ancien processus tourne encore ?).")

                shutil.copy2(str(host), str(self._target_path))
                command = self._write_bridge(host)
                self.method = host.name

                # Pas de CREATE_NO_WINDOW : la fenêtre est le point clé.
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
            except Exception as exc:
                self._cleanup_files()
                return False, f"Erreur au lancement : {type(exc).__name__} : {exc}"

            # Contrôle immédiat : sans cela, un processus mort au bout de
            # 200 ms était annoncé comme « lancé 15 minutes ».
            time.sleep(0.8)
            if self.process.poll() is not None:
                code = self.process.returncode
                self._cleanup_files()
                return False, (f"Le processus s'est arrêté immédiatement (code {code}). "
                               f"Le nom « {self.exe_name} » est peut-être refusé par le système.")

            self.running = True
            self.started_at = time.time()
            self.exit_reason = None
            _save_running(self.process.pid, self.exe_name)

            # Minuterie seulement si une durée a été demandée ; sinon le
            # processus tourne jusqu'à un arrêt manuel.
            if not self.unlimited:
                self._timer = threading.Timer(self.duration, self.stop)
                self._timer.daemon = True
                self._timer.start()

            self._watchdog = threading.Thread(target=self._watch, daemon=True)
            self._watchdog.start()

            if self.unlimited:
                duree = "sans limite de temps (arrête-le avec le bouton)"
            else:
                duree = f"pour {self.duration // 60} min"
            return True, (f"Faux processus « {self.exe_name} » lancé {duree} "
                          f"(PID {self.process.pid}, via {self.method}).")

    # ─────────────────── surveillance ───────────────────────────
    def _watch(self) -> None:
        """Détecte la mort prématurée du processus et prévient l'interface."""
        while self.running:
            time.sleep(2)
            process = self.process
            if not self.running or process is None:
                return
            if process.poll() is not None:
                code = process.returncode
                with self._lock:
                    if not self.running:
                        return
                    self.running = False
                    self.exit_reason = (f"Le processus « {self.exe_name} » s'est arrêté "
                                        f"tout seul (code {code}).")
                    self._cancel_timer()
                    _remove_running(process.pid)
                    self._cleanup_files()
                if callable(self.on_exit):
                    try:
                        self.on_exit(self.exit_reason)
                    except Exception:
                        pass
                return

    def _cancel_timer(self) -> None:
        if self._timer:
            try:
                self._timer.cancel()
            except Exception:
                pass
            self._timer = None

    # ─────────────────── arrêt / nettoyage ──────────────────────
    def stop(self, reason: str | None = None) -> tuple[bool, str]:
        """Arrête le processus et supprime les fichiers temporaires."""
        with self._lock:
            was_running = self.running
            self.running = False
            self._cancel_timer()
            process_pid = self.process.pid if self.process else None

            if self.process:
                try:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except Exception:
                        try:
                            self.process.kill()
                            self.process.wait(timeout=2)
                        except Exception:
                            pass
                except Exception:
                    pass
                self.process = None

            _remove_running(process_pid)
            self._cleanup_files()
            self.started_at = None

            if was_running:
                return True, (reason or f"Faux processus « {self.exe_name} » arrêté.")
            return False, "Aucun faux processus en cours."

    def _cleanup_files(self) -> None:
        """Supprime l'exécutable, le fichier « pont » et les dossiers vides."""
        for path in (self._target_path, self._bridge_path):
            if not path:
                continue
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass

        # Supprime tous les sous-dossiers devenus vides (y compris « .bridge »
        # et les arborescences du type « among us/ »), du plus profond au moins
        # profond. Les dossiers encore occupés sont simplement ignorés.
        try:
            if FAKE_DIR.exists():
                directories = [p for p in FAKE_DIR.rglob("*") if p.is_dir()]
                for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
                    try:
                        directory.rmdir()
                    except Exception:
                        continue
        except Exception:
            pass

        self._target_path = None
        self._bridge_path = None
