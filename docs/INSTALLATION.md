# Installer l'outil chez le cabinet (Google Cloud, Belgique)

## 1. Projet Google Cloud
Compte Google du cabinet (validation en deux étapes activée) → console.cloud.google.com →
nouveau projet `outil-cabinet` → facturation associée → budget mensuel avec alerte.

## 2. Ouvrir Cloud Shell et récupérer le code
Dans la console, bouton **>_** (Activer Cloud Shell) en haut à droite, puis coller :

```bash
gcloud config set project ID-DU-PROJET
command -v gh >/dev/null || { curl -sL https://github.com/cli/cli/releases/download/v2.63.2/gh_2.63.2_linux_amd64.tar.gz | tar xz -C ~ && export PATH="$HOME/gh_2.63.2_linux_amd64/bin:$PATH"; }
gh auth login --hostname github.com --git-protocol https --web
gh repo clone jeremydewaelheyns1-creator/Outil-cabinet- outil && cd outil
```

## 3. Lancer l'installateur
```bash
PREMIER_COMPTE=oui bash deploy/installer.sh
```
20 à 30 minutes la première fois. À la fin, le script demande l'adresse, le nom et le mot de
passe du premier compte (le mot de passe ne s'affiche pas, n'est écrit nulle part) et donne
l'adresse de l'outil.

## Mettre à jour plus tard
```bash
cd ~/outil && git pull && bash deploy/installer.sh
```

## Ce qui est créé (tout en europe-west1)
Service Cloud Run `outil`, base Cloud SQL PostgreSQL 16 `outil-db` (sauvegardes chaque nuit +
retour dans le temps 7 jours, protection contre la suppression), espace de stockage privé
`ID-documents` (accès public interdit, versions conservées), secrets dans Secret Manager
(`DJANGO_SECRET_KEY`, `DATABASE_URL`, `MAILBOX_TOKEN_KEY`), tâche `outil-travaux` toutes les
5 minutes, comptes techniques `outil-app` et `outil-planificateur` aux droits limités.
