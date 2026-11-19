# Discord Fake Game

![logo](assets/logo.png)

Application Windows qui affiche un jeu comme « en cours » dans l'activité Discord,
sans avoir à installer le jeu.

> ⚠️ **Accès sur autorisation.** Une clé de licence personnelle, liée à ta machine,
> est nécessaire. Elle s'obtient uniquement auprès du propriétaire du projet.

---

## 🇫🇷 Français

### Deux méthodes

| Méthode | Principe | Résultat |
|---|---|---|
| **Rich Presence** | déclare l'activité sur l'API locale de Discord | « Joue à <jeu> » — recommandé |
| **Faux processus** | processus au nom de l'exe du jeu + vraie fenêtre (hors écran) | détecté par Discord |

### Installation

1. Télécharge `DiscordFakeGame.exe` dans [Releases](../../releases/latest).
2. Double-clique. Windows peut afficher un avertissement SmartScreen
   (*Informations complémentaires* → *Exécuter quand même*) : l'exécutable n'est pas
   signé par un certificat commercial.
3. Au premier lancement, une fenêtre d'activation affiche ton **ID machine**.
   Envoie-le au propriétaire : il te renverra une clé `DFG1…` à coller.
4. Discord doit être ouvert, et **Paramètres → Confidentialité et sécurité de
   l'activité → « Afficher l'activité de jeu actuelle »** activé.

### Fonctionnalités

- Recherche parmi ~25 000 jeux officiels (casse et accents ignorés, alias compris).
- Remplissage automatique de l'ID officiel du jeu sélectionné.
- Faux processus **sans limite de temps**, arrêt manuel.
- **Interface bilingue** français / anglais (bouton FR/EN, mémorisé).
- Écran de lancement animé et logo.
- Diagnostic intégré : lit les journaux de Discord et affiche ce qu'il a réellement
  détecté.
- **Mises à jour automatiques** signées (SHA-256 + Ed25519).

### Mises à jour

L'application interroge `version.json` au démarrage. Si une version plus récente existe,
un bandeau apparaît ; le téléchargement est vérifié puis l'exe est remplacé et relancé.
Un manifeste falsifié ou un exécutable substitué est **refusé**.

---

## 🇬🇧 English

Windows app that shows a game as “currently playing” in your Discord activity,
without installing the game.

> ⚠️ **Access by permission only.** A personal licence key, bound to your machine, is
> required. It is issued solely by the project owner.

### Two methods

| Method | How it works | Result |
|---|---|---|
| **Rich Presence** | declares the activity through Discord's local API | “Playing <game>” — recommended |
| **Fake process** | a process named after the game's exe, with a real off-screen window | detected by Discord |

### Install

1. Download `DiscordFakeGame.exe` from [Releases](../../releases/latest).
2. Double-click it. Windows may show a SmartScreen warning
   (*More info* → *Run anyway*) — the executable is not commercially signed.
3. On first launch, an activation window shows your **machine ID**. Send it to the
   owner; you will receive a `DFG1…` key to paste.
4. Discord must be running, and **Settings → Activity Privacy → “Display current
   activity as a status message”** must be enabled.

### Features

- Search across ~25,000 official games (case- and accent-insensitive, aliases included).
- The selected game's official application ID is filled in automatically.
- Fake process with **no time limit**, stopped manually.
- **Bilingual interface** French / English (FR/EN switch, remembered).
- Animated splash screen and app logo.
- Built-in diagnostics: reads Discord's logs and shows what it actually detected.
- **Signed automatic updates** (SHA-256 + Ed25519).

### Updates

The app checks `version.json` at startup. If a newer version exists, a banner appears;
the download is verified, the exe is replaced and the app restarts. A tampered manifest
or a substituted executable is **refused**.

---

## Files in this repository / Fichiers de ce dépôt

| File | Purpose / Rôle |
|---|---|
| `version.json` | signed update manifest / manifeste de mise à jour signé |
| `revoked.json` | revoked licence IDs / licences révoquées |

The application source code is **not** published here.

Le code source de l'application n'est **pas** publié ici.
