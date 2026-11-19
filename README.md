# Discord Fake Game

Application Windows (Python 3.13 + CustomTkinter) qui affiche un jeu comme « en cours »
dans l'activité Discord, en choisissant n'importe lequel des ~25 000 jeux de la liste
officielle <https://discord.com/api/v10/applications/detectable>.

Deux méthodes, toutes deux fonctionnelles :

| Méthode | Principe | Détecté par Discord |
|---|---|---|
| **Rich Presence** | déclare l'activité sur l'API locale de Discord | ✅ oui (vérifié) |
| **Faux processus** | un processus porte le nom de l'exe du jeu + une vraie fenêtre | ✅ oui (vérifié) |

---

## 1. La règle de détection (ce que les tests ont établi)

Discord ne se contente pas de lire un nom de fichier. Il lui faut **deux conditions** :

1. **le nom d'image du processus** doit correspondre à l'exécutable déclaré par le jeu
   (`undertale.exe`, `roblox.exe`, `among us.exe`…) ;
2. le processus doit posséder une **vraie fenêtre GUI**. Une **fenêtre de console ne
   compte pas**, et un programme sans fenêtre non plus.

Le **chemin du fichier n'a aucune importance**, et le **titre de la fenêtre non plus**.

### Les expériences qui ont mené à cette conclusion

| # | Ce qui a été lancé | Fenêtre | Résultat Discord |
|---|---|---|---|
| 1 | `cmd.exe` copié en `undertale.exe`, console cachée | aucune | ❌ |
| 2 | `cmd.exe` copié en `undertale.exe`, console visible | console | ❌ |
| 3 | exe **PyInstaller** (7,3 Mo) nommé `undertale.exe` | aucune | ❌ |
| 4 | vrai binaire de Hotline Miami, dans son dossier Steam | vraie fenêtre | ✅ « Hotline Miami » |
| 5 | **le même binaire copié dans `%TEMP%`** | vraie fenêtre | ✅ « Hotline Miami » |
| 6 | **ce binaire renommé `undertale.exe`** | vraie fenêtre | ✅ « **UNDERTALE** » |
| 7 | fenêtre Tkinter titrée « Hotline Miami » (processus `python.exe`) | vraie fenêtre | ❌ |
| 8 | `mshta.exe` copié en `undertale.exe`, fenêtre hors écran | vraie fenêtre | ✅ « UNDERTALE » |

Lecture : l'expérience 6 prouve que le **nom** fait l'association (un binaire de Hotline
Miami renommé est annoncé comme UNDERTALE) ; l'expérience 5 prouve que le **chemin** est
indifférent ; l'expérience 7 prouve que la fenêtre seule ne suffit pas (il faut aussi le bon
nom) ; les expériences 1-3 et 7-8 montrent que la **fenêtre GUI est indispensable**.

### Comment le projet l'implémente

On copie `mshta.exe` (binaire système **GUI**) sous le nom exact de l'exécutable du jeu, et
on lui fait ouvrir une minuscule fenêtre sans bordure, sans icône de barre des tâches,
placée **hors de l'écran** (`-4000, -4000`). Résultat : un processus bien réel, invisible
pour toi, reconnu par Discord. Repli automatique sur `wscript.exe` si `mshta.exe` manque.

Vérifié de bout en bout (journaux de Discord) :

```
undertale.exe            → « UNDERTALE »
among us/among us.exe    → « Among Us »
roblox.exe               → « ROBLOX »
```

### Pourquoi ça ne marchait pas avant

1. **Le processus mourait en moins d'une seconde.** L'ancien code lançait
   `cmd.exe /c timeout /t 900 /nobreak` avec `stdin=DEVNULL`. Or `timeout.exe` refuse une
   entrée redirigée : il quitte immédiatement, entraînant la fin du `cmd.exe` renommé. Le
   fichier `.exe` apparaissait dans `fake_processes/`, mais il n'y avait plus de processus
   au moment où Discord regardait.
2. **La copie de `cmd.exe` n'a pas de fenêtre GUI.** Même vivant, un `cmd.exe` renommé
   n'ouvre qu'une console — et Discord ignore les fenêtres de console.

Le code corrige les deux : binaire GUI (`mshta`) + vraie fenêtre, plus une vérification
post-lancement et un chien de garde qui prévient l'interface si le processus meurt.

### Limites à connaître

- Certains antivirus n'aiment pas les binaires système renommés (`mshta.exe`, `wscript.exe`) :
  si Defender bloque, utilise le Rich Presence.
- Les entrées de la liste préfixées par `>` (`>javaw.exe`) se détectent par **arguments de
  ligne de commande** : elles ne sont pas simulables par un nom de fichier (elles sont
  écartées automatiquement).
- Un jeu sans exécutable Windows (marqué `○`) ne peut pas être simulé par processus.
- Aucun rapport avec les anti-triche : on ne lance jamais le vrai jeu, seulement un binaire
  système renommé.

---

## 2. Le Rich Presence (méthode la plus discrète)

Aucun processus : on se connecte à l'API locale de Discord (IPC) et on envoie une activité.
Discord affiche « Joue à … » avec le nom et l'icône de l'application.

Le nom affiché est celui de **l'application Discord** associée à l'ID, pas un texte libre :
sélectionner un jeu remplit automatiquement son ID officiel, donc le vrai nom et la vraie
jaquette apparaissent. Pour un nom libre, crée ton application sur
<https://discord.com/developers/applications> et utilise son ID.

---

## 3. Installation

```bat
cd "C:\Users\yassi\Desktop\projet discord orbs"
"C:\Users\yassi\AppData\Local\Programs\Python\Python313\python.exe" -m pip install -r requirements.txt
```

Puis double-clic sur **`Lancer.bat`** (il installe les dépendances manquantes tout seul).

### Version `.exe` (à envoyer à un ami)

`build_exe.bat` compile le projet en **un seul fichier** : `dist\DiscordFakeGame.exe`
(≈ 14 Mo, aucun Python à installer chez la personne qui le reçoit). `dist\LISEZ-MOI.txt`
contient le mode d'emploi à joindre.

- Premier lancement : Windows peut afficher « Windows a protégé votre PC » (fichier non
  signé) → *Informations complémentaires* → *Exécuter quand même*.
- Les données (cache de la liste, faux exécutables) vont dans
  `%LOCALAPPDATA%\DiscordFakeGame` : un `.exe` PyInstaller s'exécute dans un dossier
  temporaire, on ne peut donc pas écrire à côté du fichier. C'est géré par `paths.py`.
- Certains antivirus signalent parfois les exécutables PyInstaller : c'est un faux positif
  classique, sans rapport avec le code.
- Windows uniquement, Discord doit être installé et ouvert.

### Licences et mises à jour

L'application demande une **clé de licence** au premier lancement : elle affiche
l'ID de la machine, l'utilisateur te l'envoie, et tu génères une clé liée à cet
ordinateur.

```bat
python keygen.py new --user "Prenom" --hwid 88CEAF40DF580D4D --days 365
```

Les clés sont **signées** (Ed25519) : l'application ne peut que les vérifier,
pas en fabriquer — la clé privée reste dans `keys/private.key`, jamais livrée.

Les **mises à jour** se publient en trois commandes (`config.py` → rebuild →
`keygen.py sign-release`). Les utilisateurs voient un bandeau « Installer la
mise à jour », l'exe est remplacé et relancé automatiquement, après vérification
de l'empreinte SHA-256 **et** de la signature du manifeste.

👉 Tout est détaillé dans **[GUIDE-PROPRIETAIRE.md](GUIDE-PROPRIETAIRE.md)**.

---

## 4. Utilisation

1. Ouvre Discord et connecte-toi.
2. Lance `Lancer.bat`.
3. Tape un nom dans la recherche (ex. `roblox`, `undertale`, `genshin`).
4. Clique sur le jeu : la ligne du bas affiche l'exécutable et l'ID Discord.
5. **▶ Lancer le faux processus** pour l'activité « jeu », ou **🔗 Activer Rich Presence**
   pour la version sans processus. Le processus n'a **aucune limite de temps** : il tourne
   jusqu'à ce que tu cliques sur **⏹ Arrêter** (ou que tu fermes l'application).
6. **🔍 Diagnostic** affiche ce que Discord voit réellement (lecture de ses journaux).

La case « Afficher la fenêtre du faux processus » fait apparaître la fenêtre-pont à l'écran
(utile pour comprendre ce qui se passe) ; décochée, elle reste hors écran.

**Durée :** par défaut **illimitée** — le processus tourne jusqu'à un arrêt manuel. Pour
remettre une limite, ouvre `main.py` et mets `DURATION_MINUTES = 15`. Si l'application est
fermée brutalement (plantage, gestionnaire des tâches), le processus résiduel est arrêté
automatiquement au démarrage suivant grâce au fichier de suivi `.running.json`.

---

## 5. Comment tester chaque scénario

### a) Faux processus pour un jeu avec exécutable connu (ex. Genshin Impact)

- Sélectionne `Genshin Impact`, clique **▶ Faux processus**.
- Le statut confirme le PID et le nom d'image vu par Windows.
- Au bout de quelques secondes, ton profil Discord affiche « Joue à Genshin Impact ».
- **🔍 Diagnostic** → section « JEUX DÉTECTÉS PAR DISCORD » : la ligne doit apparaître.

### b) Jeu sans exécutable Windows

- Sélectionne un jeu marqué `○` (ex. `UNDERTALE YELLOW`).
- Un message explique que le faux processus est impossible et que l'ID est prêt pour le
  Rich Presence. Aucun fichier n'est créé, rien ne casse.

### c) Rich Presence avec un ID valide

- Sélectionne `ROBLOX` (ID `363445589247131668` rempli automatiquement).
- **🔗 Activer Rich Presence** → « ✓ Rich Presence activé ».
- Ton profil affiche « Joue à ROBLOX ». **🔌 Désactiver** efface l'activité.

### d) Recherche « roblox »

- `ROBLOX` en premier, puis `NeuroBloxs` ; compteur « 2 / 25349 jeux ».
- La recherche ignore casse et accents (`pokemon` trouve `Pokémon Legends: Arceus`) et
  couvre les alias.

---

## 6. Réglages Discord à vérifier

- **Paramètres → Confidentialité et sécurité de l'activité → « Afficher l'activité de jeu
  actuelle » doit être ACTIVÉ** (sinon aucun statut de jeu n'est publié, même pour un vrai jeu).
- Le statut n'apparaît pas en « Ne pas déranger » : passe en « En ligne ».
- L'activité est visible sur ton profil, pas forcément dans la liste des membres.

Le bouton **🔍 Diagnostic** indique si l'IPC est disponible, combien de changements Discord a
enregistrés et quels jeux il a réellement détectés.

---

## 7. Fichiers du projet

| Fichier | Rôle |
|---|---|
| `main.py` | interface graphique (CustomTkinter), orchestration |
| `game_fetcher.py` | liste officielle Discord, cache, recherche |
| `paths.py` | chemins de travail (projet en dev, `%LOCALAPPDATA%` en `.exe`) |
| `process_simulator.py` | faux processus (binaire GUI renommé + fenêtre hors écran) |
| `rpc_manager.py` | Rich Presence (connexion, keepalive, reconnexion) |
| `diagnostics.py` | lecture des journaux Discord, rapport de diagnostic |
| `config.py` | version de l'app, adresses de mise à jour et de révocation |
| `licensing.py` | vérification des clés signées, ID machine, révocation |
| `licensing_ui.py` | fenêtre d'activation au premier lancement |
| `updater.py` | mises à jour signées + remplacement de l'exe |
| `keygen.py` | **outil privé** : générer/révoquer des licences, signer une version |
| `gestionnaire.py` | **outil privé** : interface graphique de gestion (licences, vérification, publication) |
| `build_version_info.py` | métadonnées Windows du `.exe` |
| `Lancer.bat` | lancement + installation automatique des dépendances |
| `Gestionnaire.bat` | lancement du gestionnaire de licences |
| `Console-licences.bat` | console ouverte dans le projet, pour les commandes |
| `build_exe.bat` | compilation en `dist\DiscordFakeGame.exe` |
| `GUIDE-PROPRIETAIRE.md` | procédures de licence et de publication |
| `requirements.txt` | dépendances Python |

---

## 8. Note d'usage

Afficher un jeu que l'on ne possède pas est une **plaisanterie visuelle** : cela ne donne
accès à aucun contenu, mais cela peut tromper tes contacts. Utiliser l'ID d'application d'un
éditeur tiers pour apparaître sous son nom est une zone grise vis-à-vis des conditions
d'utilisation de Discord ; la méthode propre consiste à créer ta propre application sur le
portail développeur et à l'utiliser comme identité.
