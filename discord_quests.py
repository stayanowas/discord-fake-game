"""Read visible, accessible Quest Home text from the Discord desktop UI.

This is a best-effort, read-only UI Automation adapter. It never clicks, types,
or reads Discord profile files, cookies, or credentials.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any


_PS = r'''
$ErrorActionPreference = 'Stop'
$a = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\WPF\UIAutomationTypes.dll'
$b = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\WPF\UIAutomationClient.dll'
Add-Type -Path $a; Add-Type -Path $b
$root = [System.Windows.Automation.AutomationElement]::RootElement
$windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children,
  [System.Windows.Automation.Condition]::TrueCondition)
$discord = @()
foreach ($w in $windows) {
  try {
    $p = Get-Process -Id $w.Current.ProcessId -ErrorAction Stop
    if ($p.ProcessName -match '^Discord') { $discord += $w }
  } catch {}
}
if ($discord.Count -eq 0) { @{ ok=$false; code='discord_window_not_found' } | ConvertTo-Json -Compress; exit }
$all = [System.Collections.Generic.List[string]]::new()
foreach ($w in $discord) {
  try {
    $nodes = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants,
      [System.Windows.Automation.Condition]::TrueCondition)
    $limit = [Math]::Min($nodes.Count, 3000)
    for ($i=0; $i -lt $limit; $i++) {
      try {
        $n = [string]$nodes.Item($i).Current.Name
        if ($n -and $n.Trim()) { $all.Add(($n -replace '\s+', ' ').Trim()) }
      } catch {}
    }
  } catch {}
}
$lines = @($all | Select-Object -Unique)
$q = -1
for ($i=0; $i -lt $lines.Count; $i++) {
  if ($lines[$i] -match '^(Quests|Quêtes)$|Quest Home|Quêtes Discord') { $q=$i; break }
}
if ($q -lt 0) { @{ ok=$false; code='quest_home_not_visible' } | ConvertTo-Json -Compress; exit }
# Return only text within the Quest Home content region, never the full window tree.
$end = [Math]::Min($lines.Count, $q + 180)
for ($i=$q+1; $i -lt $end; $i++) {
  if ($lines[$i] -match '^(Shop|Boutique|Nitro|Messages|Amis|Friends)$') { $end=$i; break }
}
$content = @($lines[$q..($end-1)])
@{ ok=$true; lines=$content } | ConvertTo-Json -Compress -Depth 3
'''


def read_quest_home() -> dict[str, Any]:
    """Read Quest Home accessible labels, returning only parsed quest data."""
    if os.name != "nt":
        return {"ok": False, "code": "windows_only"}
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-STA", "-Command", _PS],
            capture_output=True, text=True, timeout=12, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            encoding="utf-8", errors="replace",
        )
        raw = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": "uia_timeout"}
    except Exception:
        return {"ok": False, "code": "uia_unavailable"}
    if not raw.get("ok"):
        return {"ok": False, "code": raw.get("code", "uia_unavailable")}

    lines = [re.sub(r"\s+", " ", str(x)).strip() for x in raw.get("lines", []) if str(x).strip()]
    joined = "\n".join(lines)
    balance = None
    for pattern in (r"(?i)([\d][\d\s,.]*)\s+Orbs?\b", r"(?i)Orbs?\s*[:：]?\s*([\d][\d\s,.]*)"):
        match = re.search(pattern, joined)
        if match:
            balance = re.sub(r"\s", "", match.group(1))
            break

    quests: list[dict[str, str]] = []
    completed = re.compile(r"(?i)\b(completed|complete|terminée?s?|réussi[es]?)\b")
    pending = re.compile(r"(?i)\b(in progress|available|start quest|en cours|disponible|commencer|réclamer|claim reward)\b")
    for i, line in enumerate(lines):
        match = completed.search(line) or pending.search(line)
        if not match:
            continue
        status = "completed" if completed.search(line) else "pending"
        # Some Discord UIA providers expose each card as a single text node;
        # extract a title only when it shares that node with the status.
        title = re.sub(r"(?i)\b(completed|complete|terminée?s?|réussi[es]?|in progress|available|start quest|en cours|disponible|commencer|réclamer|claim reward)\b", "", line).strip(" -:·")
        if not title and i > 0 and len(lines[i-1]) < 140:
            title = lines[i-1]
        if title and not any(q["title"] == title for q in quests):
            quests.append({"title": title, "status": status, "detail": line})

    return {"ok": True, "balance": balance, "quests": quests,
            "completed": sum(q["status"] == "completed" for q in quests),
            "pending": sum(q["status"] == "pending" for q in quests)}
