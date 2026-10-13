# Journal des sessions

## Session 1 — 13 octobre 2026 : socle et module clients

**Fait**
- Projet Django 6.1 / Python 3.13 / PostgreSQL 16, réglages par environnement, CI GitHub
  Actions (format, lint, mypy strict, migrations, tests, contrôles de déploiement), Dockerfile
  Cloud Run.
- Comptes sans inscription, double authentification obligatoire, connexion exigée partout,
  administration derrière la même connexion.
- Profils de sécurité (capacités) et portefeuilles privés ; trois profils et le portefeuille
  « Cabinet » créés par migration.
- Journal des consultations inaltérable (déclencheur PostgreSQL), connexions/échecs journalisés,
  IP fiable derrière le répartiteur Google.
- Journal d'événements avec exécution unique et reprise des échecs ; commande `run_jobs`.
- Clients : fiche complète, recherche en direct (accents, numéros, nom + prénom), filtres,
  export Excel journalisé, numéro national masqué (affichage journalisé), coordonnées,
  relations (dirigeants, actionnaires, mandats, proches), équipe, historique des changements.
- Calcul des bénéficiaires effectifs (direct, indirect, contrôle, repli sur les dirigeants,
  ASBL) avec comparaison aux bénéficiaires déclarés.
- BCE Open Data : import complet et mises à jour, recherche, préremplissage d'une nouvelle
  fiche, complétion automatique, différences à valider, alertes faillite/radiation à l'accueil.
- VIES : vérification TVA avec preuve conservée.
- Reprise FID-Manager : analyse à blanc puis import de l'export clients Excel (mapping YAML).
- Commande `demo` (données fictives). 99 tests.

**Reste à faire / en attente**
- Dépôt GitHub privé (action de Jeremy), puis pousser le code.
- Structure réelle de l'export clients FID-Manager (en-têtes uniquement + lignes inventées).
- Déploiement de l'environnement d'essai sur le Google Cloud du cabinet.
- Suite : épique 4 (moteur de tâches et d'échéances).
