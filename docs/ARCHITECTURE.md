# Architecture

## Vue d'ensemble

```
Navigateur ──HTTPS──> Cloud Run (Django + gunicorn) ──> Cloud SQL PostgreSQL 16
                          │                                 (source unique de vérité)
                          ├──> Cloud Storage (documents, verrou de conservation AML)
                          ├──> Vertex AI Gemini, région Belgique (à venir)
                          └──> API publiques : VIES ; fichiers BCE Open Data
Cloud Scheduler ──> Cloud Run Job `run_jobs` (toutes les 5 min) : retraitements, file de fond
```

Tout est en région `europe-west1` (Belgique), dans le projet Google Cloud du cabinet.

## Code

| Dossier | Contenu |
| --- | --- |
| `config/` | Réglages (`base`, `dev`, `test`, `prod`), URLs, WSGI, paramétrage de reprise (YAML) |
| `apps/core/` | Utilisateurs, profils de sécurité, portefeuilles, journal des consultations, journal d'événements, accueil |
| `apps/clients/` | Fiche client, coordonnées, relations, équipe, calcul UBO (`services/ubo.py`) |
| `apps/bce/` | Copie BCE Open Data (`opendata.py` : import ; `services.py` : recherche, comparaison) |
| `apps/integrations/` | Services externes : VIES (`vies.py`) |
| `apps/reprise/` | Reprise FID-Manager (`importer.py`, mapping `config/reprise/clients.yaml`) |
| `templates/`, `static/` | Gabarits HTML (HTMX pour l'interactivité), une feuille CSS |

## Mécanismes transverses

**Accès.** `LoginRequiredMiddleware` (tout écran exige une connexion) puis
`RequireMFAMiddleware` (sans second facteur configuré, seul l'écran de configuration est
accessible). Comptes créés par un administrateur (pas d'inscription). Droits = capacités
(`apps/core/capabilities.py`) regroupées en profils de sécurité ; visibilité par portefeuille.

**Journal des consultations** (`AccessLog`). Écrit par `log_access()`. Inaltérable : refus côté
Django et déclencheur PostgreSQL (`core_accesslog_readonly`). Seule la purge légale passe, avec
`SET LOCAL app.allow_audit_purge = 'on'`. Un compte présent au journal ne peut être supprimé
(seulement désactivé).

**Journal d'événements** (`Event`, `EventHandling`). `events.emit()` enregistre un fait dans la
transaction en cours ; après validation, chaque traitement abonné (`@events.on`) s'exécute dans
son propre point de sauvegarde. Un traitement réussi n'est jamais relancé ; un échec est
retenté (5 fois au plus) par `run_jobs`. Clé d'idempotence pour les faits externes (e-mail
reçu, mise à jour BCE). Mode `eager` (juste après la requête) ou `queue` (procrastinate).

**Historique.** `django-simple-history` sur les modèles métier : qui a changé quoi, quand.

**Données BCE.** Import par COPY en flux d'une archive complète (mensuelle) ou de mise à jour
(quotidienne). Seules les entreprises (pas les établissements), leurs dénominations, adresses,
activités principales et coordonnées sont gardées. Après une mise à jour, un événement
`bce.enterprise_changed` par client concerné réaligne statut, situation juridique et activités ;
nom et adresse restent des propositions à valider sur la fiche.

**Reprise FID-Manager.** Analyse dans une transaction annulée (rapport exact sans écriture),
puis import confirmé. Les fiches existantes ne sont jamais écrasées.

## Hébergement (à mettre en place avec le cabinet)

- Cloud Run service `outil` (min 0 instance) + Cloud Run Job `run_jobs` (Cloud Scheduler).
- Cloud SQL PostgreSQL 16 (plus petite instance), sauvegardes automatiques + PITR, export
  hebdomadaire vers un autre projet, test de restauration mensuel.
- Secret Manager pour `DJANGO_SECRET_KEY`, `DATABASE_URL`, identifiants SMTP/Graph.
- Deux environnements : essai et production. Migrations lancées par un Cloud Run Job
  `python manage.py migrate` avant chaque déploiement.
- Deux rôles PostgreSQL : le propriétaire des tables (migrations uniquement) et le rôle de
  l'application, sans droit de propriété (il ne peut ni supprimer les déclencheurs ni vider le
  journal des consultations), avec seulement SELECT/INSERT sur `core_accesslog`.
- Sonde de santé : `/sante/` (répond avant tout contrôle d'hôte ou de HTTPS).
