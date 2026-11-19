# Discord Fake Game

Application Windows qui affiche un jeu comme « en cours » dans l'activité Discord,
sans avoir à installer le jeu. Deux méthodes : **Rich Presence** (déclaration directe
au client Discord) et **faux processus** (processus au nom de l'exe du jeu, avec une
vraie fenêtre — exigence de Discord).

## Téléchargement

👉 **[Dernière version](../../releases/latest)** → `DiscordFakeGame.exe`

Aucune installation : un seul fichier, Windows 10/11, Discord doit être ouvert.

## Activation

Une clé de licence personnelle est requise au premier lancement.

1. L'application affiche un **ID de machine** (16 caractères).
2. Envoie cet ID au propriétaire.
3. Colle la clé reçue (`DFG1....`) dans la fenêtre d'activation.

La clé est liée à l'ordinateur : elle ne fonctionne pas ailleurs.

## Mises à jour

Automatiques. L'application interroge `version.json` au démarrage et propose
l'installation si une version plus récente existe. Le téléchargement est vérifié
par empreinte **SHA-256** et **signature Ed25519** avant remplacement : un
manifeste falsifié ou un exécutable substitué est refusé.

## Fichiers techniques (racine du dépôt)

| Fichier | Rôle |
|---|---|
| `version.json` | manifeste de mise à jour signé (lu par l'application) |
| `revoked.json` | liste des licences révoquées (cache 24 h) |

## Avertissement

L'exécutable n'est pas signé par un certificat commercial : Windows SmartScreen
peut afficher un avertissement au premier lancement
(*Informations complémentaires* → *Exécuter quand même*).
