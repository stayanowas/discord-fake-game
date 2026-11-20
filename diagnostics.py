# diagnostics.py
"""
Outils de diagnostic « terrain » pour Discord Fake Game.

Ce module répond à la question « est-ce que ça marche vraiment ? » sans avoir à
croire l'interface sur parole :

  * Discord est-il lancé ? quelle version ? quels canaux IPC ?
  * Combien de fois Discord a-t-il scanné les processus récemment ?
  * Quels jeux Discord a-t-il RÉELLEMENT détectés (lus directement dans ses
    journaux : %APPDATA%\\discord\\logs\\renderer_js.log) ?
  * Le faux processus est-il visible dans tasklist sous le bon nom ?

C'est grâce à ces journaux que le diagnostic du projet a pu être établi : quand
Discord détecte un jeu, il écrit une ligne
    [Clips] decider: handleRunningGamesChange visibleGame=<Jeu> newPrimaryKey=<chemin>:<Jeu>
Quand aucun jeu n'est détecté, la même ligne contient `visibleGame=null`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from process_simulator import image_is_running, list_running_images
from rpc_manager import list_ipc_pipes

# ─────────────────────────── Chemins ──────────────────────────────
APPDATA = Path(os.environ.get("APPDATA", "")) if os.environ.get("APPDATA") else None
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", "")) if os.environ.get("LOCALAPPDATA") else None

DISCORD_LOG = APPDATA / "discord" / "logs" / "renderer_js.log" if APPDATA else None

LOG_TAIL_BYTES = 2_000_000  # on ne lit que la fin du journal (il est gros)

# Ligne de détection réussie (ou `null` si aucun jeu).
_DETECT_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\].*?visibleGame=(?!null)(.+?) newPrimaryKey=(\S+)",
    re.MULTILINE,
)
_SCAN_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\].*?\[RunningGameStore\] Running Games Changed",
                      re.MULTILINE)


# ─────────────────────────── Structures ───────────────────────────
@dataclass
class Detection:
    """Un jeu réellement détecté par Discord, d'après ses journaux."""
    heure: datetime
    jeu: str
    chemin: str


# ─────────────────────────── Discord ──────────────────────────────
def discord_process_count() -> int:
    """Nombre de processus Discord (0 = client fermé)."""
    if os.name != "nt":
        return 0
    try:
        import subprocess
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Discord.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        return sum(1 for line in completed.stdout.splitlines()
                   if line.strip().startswith('"Discord.exe"'))
    except Exception:
        return 0


def discord_version() -> str | None:
    """Dernière version installée du client Discord (dossier app-x.y.z)."""
    if not LOCALAPPDATA:
        return None
    base = LOCALAPPDATA / "Discord"
    if not base.exists():
        return None
    versions = []
    for child in base.iterdir():
        if child.is_dir() and child.name.startswith("app-"):
            versions.append(child.name[4:])
    if not versions:
        return None

    def sort_key(value: str) -> tuple:
        return tuple(int(part) if part.isdigit() else 0 for part in value.split("."))

    return sorted(versions, key=sort_key)[-1]


def discord_settings_hint() -> str:
    """Rappel des réglages Discord à vérifier (non lisibles de façon fiable)."""
    return ("Paramètres Discord → Confidentialité et sécurité de l'activité → "
            "« Afficher l'activité de jeu actuelle » doit être ACTIVÉ.")


# ─────────────────────────── Journal ──────────────────────────────
def _read_log_tail() -> str:
    """Lit la fin du journal du renderer Discord (jamais d'exception)."""
    if not DISCORD_LOG or not DISCORD_LOG.exists():
        return ""
    try:
        size = DISCORD_LOG.stat().st_size
        with open(DISCORD_LOG, "rb") as handle:
            if size > LOG_TAIL_BYTES:
                handle.seek(size - LOG_TAIL_BYTES, os.SEEK_SET)
            raw = handle.read()
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def recent_detections(minutes: int = 15) -> list[Detection]:
    """Jeux détectés par Discord durant les N dernières minutes."""
    text = _read_log_tail()
    if not text:
        return []

    limit = datetime.now() - timedelta(minutes=minutes)
    seen: set[tuple[str, str]] = set()
    result: list[Detection] = []

    for match in _DETECT_RE.finditer(text):
        try:
            heure = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if heure < limit:
            continue
        jeu = match.group(2).strip()
        chemin = match.group(3).strip()
        key = (jeu, chemin)
        if key in seen:
            continue
        seen.add(key)
        result.append(Detection(heure=heure, jeu=jeu, chemin=chemin))

    result.sort(key=lambda d: d.heure)
    return result


def game_change_events(minutes: int = 15) -> int:
    """
    Nombre de changements enregistrés par le détecteur de jeux de Discord.

    Discord n'écrit une ligne que lorsque l'ENSEMBLE des jeux détectés change :
    un processus qu'il ne reconnaît pas ne produit donc aucune ligne. C'est
    exactement ce qui permet de dire « Discord n'a rien vu », et non
    « Discord n'a pas regardé ».
    """
    text = _read_log_tail()
    if not text:
        return 0
    limit = datetime.now() - timedelta(minutes=minutes)
    count = 0
    for match in _SCAN_RE.finditer(text):
        try:
            if datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S") >= limit:
                count += 1
        except ValueError:
            continue
    return count


# ─────────────────────────── Rapport ──────────────────────────────
def build_report(games_count: int = 0, from_cache: bool = False,
                 games_error: str | None = None,
                 selected: dict[str, Any] | None = None,
                 fake_status: dict[str, Any] | None = None,
                 rpc_status: dict[str, Any] | None = None,
                 minutes: int = 15) -> str:
    """Construit un rapport texte lisible dans l'interface."""
    lines: list[str] = []

    # ── Discord ──
    lines.append("═══ DISCORD ═══")
    processes = discord_process_count()
    version = discord_version()
    lines.append(f"Client lancé      : {'OUI' if processes else 'NON'} "
                 f"({processes} processus)")
    lines.append(f"Version installée : {version or 'inconnue'}")
    pipes = list_ipc_pipes()
    lines.append(f"Canaux IPC        : {', '.join(pipes) if pipes else 'AUCUN (API locale inaccessible)'}")
    lines.append(f"Détection de jeu  : {discord_settings_hint()}")
    lines.append(f"Changements jeux  : {game_change_events(minutes)} événement(s) "
                 f"sur {minutes} min (Discord ne journalise que les changements)")

    # ── Liste des jeux ──
    lines.append("")
    lines.append("═══ LISTE DES JEUX ═══")
    source = "cache local" if from_cache else "téléchargée depuis l'API"
    lines.append(f"Jeux chargés      : {games_count} ({source})")
    if games_error:
        lines.append(f"Avertissement     : {games_error}")

    if selected:
        lines.append(f"Jeu sélectionné   : {selected.get('name')}")
        lines.append(f"Exécutable choisi : {selected.get('preferred_executable') or 'AUCUN'}")
        lines.append(f"ID Discord du jeu : {selected.get('id') or 'inconnu'}")
        if selected.get("steam_id"):
            lines.append(f"AppID Steam       : {selected.get('steam_id')}")

    # ── Faux processus ──
    lines.append("")
    lines.append("═══ FAUX PROCESSUS (expérimental) ═══")
    if not fake_status or not fake_status.get("actif"):
        lines.append("État              : aucun processus simulé")
    else:
        name = fake_status.get("image") or "?"
        lines.append(f"État              : ACTIF — image « {name} »")
        lines.append(f"Vivant (tasklist) : {'OUI' if image_is_running(name) else 'NON'}")
        if fake_status.get("limite"):
            lines.append(f"Reste             : {fake_status.get('restant', 0)} s")
        else:
            lines.append(f"En cours depuis   : {fake_status.get('depuis', 0)} s "
                         f"(sans limite de temps)")
        lines.append(f"Détail            : {fake_status.get('detail', '')}")

    # ── RPC ──
    lines.append("")
    lines.append("═══ RICH PRESENCE ═══")
    if rpc_status and rpc_status.get("connecte"):
        lines.append(f"État              : CONNECTÉ (ID {rpc_status.get('client_id')})")
    else:
        lines.append("État              : déconnecté")

    # ── Détections réelles ──
    lines.append("")
    lines.append(f"═══ JEUX DÉTECTÉS PAR DISCORD ({minutes} dernières minutes) ═══")
    detections = recent_detections(minutes)
    if detections:
        for detection in detections[-12:]:
            lines.append(f"  {detection.heure.strftime('%H:%M:%S')}  {detection.jeu}")
        lines.append("")
        lines.append("→ Discord a bien détecté un jeu : le journal parle de lui-même.")
    else:
        lines.append("  Aucune détection enregistrée.")
        lines.append("")
        lines.append("→ Si tu viens de lancer un faux processus et que rien n'apparaît ici,")
        lines.append("   c'est la preuve que Discord ne le voit pas : utilise le Rich Presence.")

    lines.append("")
    lines.append("Note : ce rapport lit les journaux de Discord, il ne modifie rien.")
    return "\n".join(lines)


def quick_summary() -> str:
    """Résumé d'une ligne pour la barre de statut."""
    if not discord_process_count():
        return "Discord n'est pas lancé."
    if not list_ipc_pipes():
        return "Discord est lancé mais l'API locale (IPC) est indisponible."
    return "Discord est prêt (IPC disponible)."
