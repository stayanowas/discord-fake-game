# Orbs — Discord Activity Studio

[Français](#français) · [English](#english)

> **Release note:** the pre-existing v1.x GitHub releases still point to the old app. Download the current packaged build from [Orbs-Windows-x64.zip](https://github.com/stayanowas/discord-fake-game-for-orbs/blob/main/release/Orbs-Windows-x64.zip). Extract the folder before launching `Orbs.exe`.
>
> **License:** this current source and package use PolyForm Noncommercial 1.0.0. Earlier v1.x releases and commits were published under The Unlicense; these new terms do not retroactively change permissions already granted for those copies.

## Français

> **Note de publication :** les anciennes releases GitHub v1.x correspondent encore à l’ancienne application. Télécharge le paquet actuel [Orbs-Windows-x64.zip](https://github.com/stayanowas/discord-fake-game-for-orbs/blob/main/release/Orbs-Windows-x64.zip) et extrais le dossier avant de lancer `Orbs.exe`.
>
> **Licence :** le code et le paquet actuels utilisent PolyForm Noncommercial 1.0.0. Les anciennes releases et commits v1.x ont été publiés sous The Unlicense ; ces nouvelles conditions ne modifient pas rétroactivement les permissions déjà accordées pour ces copies.

Orbs est une application de bureau Windows qui permet de parcourir un catalogue de jeux et d’afficher une activité Rich Presence dans Discord. L’interface est construite avec HTML, CSS et JavaScript, reliée à une passerelle Python via pywebview.

### Fonctions

- Catalogue de jeux, recherche, favoris, historique récent et presets personnalisés.
- Présence Discord via l’IPC local de Discord.
- Outils de diagnostic pour l’IPC, la Rich Presence et le catalogue.
- Mode expérimental de détection par processus. Il lance un exécutable système renommé et peut être bloqué par un antivirus ; la Rich Presence est le mode conseillé.
- Lecteur expérimental de Quest Home en lecture seule avec l’accessibilité Windows. Il n’ouvre pas Discord, ne navigue pas et ne lit aucun jeton. Les résultats dépendent des textes que Discord expose à Windows et peuvent être incomplets. Quest Home doit être déjà visible dans Discord.

### Lancer depuis les sources

1. Installer Python 3.10 ou plus récent et Discord pour Windows.
2. Lancer `Installer.bat` pour installer les dépendances dans un environnement virtuel local.
3. Lancer `Lancer.bat`.

Le script `build_exe.bat` compile une version PyInstaller. Le dossier de sortie complet `dist-quests/Orbs` est nécessaire au lancement ; `Orbs.exe` seul n’est pas autonome. Au démarrage, l’application retire le marqueur Windows « fichier téléchargé depuis Internet » des DLL embarquées avant de charger pywebview, afin d’éviter l’erreur .NET `Python.Runtime.Loader.Initialize` qui peut arriver après l’extraction d’un ZIP téléchargé. Si Windows bloque encore les fichiers, débloque le ZIP dans ses propriétés puis extrais-le à nouveau.

### Données et confidentialité

En mode source, les réglages, favoris, presets, historique et cache du catalogue sont enregistrés à côté des fichiers du projet. En version compilée, ils sont stockés dans `%LOCALAPPDATA%\Orbs`. Ces fichiers peuvent contenir des préférences et l’historique d’utilisation ; ils sont ignorés par Git et ne font pas partie du dépôt public. L’application ne demande pas de mot de passe Discord et ne lit pas les jetons d’authentification.

La connexion Rich Presence utilise le canal IPC local de Discord. Elle ne fournit pas à Orbs l’identité du compte, les Orbs ou les quêtes. Le lecteur Quest Home est une lecture d’interface Windows distincte et expérimentale.

### Dépendances principales

Python, pywebview, Requests, Pillow et pypresence. Voir `requirements.txt` pour les dépendances Python.

## English

Orbs is a Windows desktop application for browsing a game catalogue and displaying a Discord Rich Presence activity. Its interface uses HTML, CSS, and JavaScript, connected to a Python bridge through pywebview.

### Features

- Game catalogue, search, favourites, recent activity, and custom presets.
- Discord Rich Presence through Discord’s local IPC interface.
- Diagnostics for IPC, Rich Presence, and the game catalogue.
- Experimental process-detection mode. It starts a renamed Windows system executable and may be blocked by antivirus software; Rich Presence is the recommended mode.
- Experimental, read-only Quest Home reader using Windows UI Automation. It does not open or navigate Discord and does not read authentication tokens. Results depend on the text Discord exposes to Windows and may be incomplete. Quest Home must already be visible in Discord.

### Run from source

1. Install Python 3.10 or newer and Discord for Windows.
2. Run `Installer.bat` to install dependencies into a local virtual environment.
3. Run `Lancer.bat`.

Run `build_exe.bat` to build with PyInstaller. The complete output folder `dist-quests/Orbs` is required; `Orbs.exe` is not a standalone executable by itself. On startup, the app removes Windows' downloaded-file marker from bundled DLLs before loading pywebview, avoiding the .NET `Python.Runtime.Loader.Initialize` error that can occur after extracting a downloaded ZIP. If Windows still blocks the files, unblock the ZIP in its Properties dialog and extract it again.

### Data and privacy

In source mode, settings, favourites, presets, recent activity, and the game catalogue cache are stored next to the project files. In the packaged application, they are stored under `%LOCALAPPDATA%\Orbs`. These files can contain preferences and usage history; Git ignores them and they are not part of this public repository. The app does not ask for a Discord password or read authentication tokens.

Rich Presence uses Discord’s local IPC channel. It does not provide Orbs with the account identity, Orb balance, or quest data. The Quest Home reader is a separate, experimental Windows UI read.

### Main dependencies

Python, pywebview, Requests, Pillow, and pypresence. See `requirements.txt` for Python dependencies.

## License / Licence

The current project source is released under [PolyForm Noncommercial 1.0.0](LICENSE). Commercial use is not permitted by this license; personal and other noncommercial uses, including modification and redistribution, are subject to its terms. This is source-available software, not OSI-defined open source. Earlier v1.x releases and commits used The Unlicense, and this license change does not retroactively revoke permissions already granted for those copies. Orbs is not affiliated with Discord. Users are responsible for complying with Discord's Terms of Service and applicable laws. Third-party dependencies remain under their own licenses.

Le code actuel est publié sous [PolyForm Noncommercial 1.0.0](LICENSE). L’usage commercial n’est pas permis par cette licence ; les usages personnels et autres usages non commerciaux, y compris les modifications et redistributions, restent soumis à ses conditions. Il s’agit d’un logiciel à code source disponible, pas d’un logiciel open source au sens de l’OSI. Les anciennes releases et commits v1.x utilisaient The Unlicense ; ce changement ne révoque pas rétroactivement les permissions déjà accordées pour ces copies. Orbs n’est pas affilié à Discord. Chacun reste responsable du respect des Conditions d’utilisation de Discord et des lois applicables. Les dépendances tierces gardent leurs propres licences.
