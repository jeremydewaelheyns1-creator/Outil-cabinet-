# Conventions

## Langue
- Code (noms de variables, fonctions, modèles) en anglais.
- Interface, messages, commentaires, docstrings, documentation : en français.
- Libellés des champs de modèle en français, en minuscules (`"numéro d'entreprise"`).

## Style et qualité
- `ruff format` + `ruff check` (règles dans `pyproject.toml`), lignes de 100 caractères.
- `mypy` strict avec django-stubs sur le code applicatif ; les tests sont vérifiés en les
  exécutant (`ignore_errors` pour `*.tests.*` et `apps.core.testing`).
- Pas d'`assert` dans le code applicatif (sauf invariant documenté avec `noqa: S101`).

## Organisation d'une application
- `models.py` : données et règles de cohérence (`clean`), sans logique d'écran.
- `services/` ou `services.py` : logique métier réutilisable (calculs, synchronisations).
- `views.py` : vues fonctions, typées `AppRequest` ; droits par `@require_capability`.
- `handlers.py` : automatismes `@events.on(...)`, importés dans `AppConfig.ready()`.
- Gabarits dans `templates/<app>/` ; fragments HTMX préfixés `_`.

## Sécurité et données
- Données clients : toujours via `visible_to(user)`.
- Chaque consultation de fiche, export, affichage de donnée sensible : `log_access()`.
- Ne jamais écrire de numéro national dans un journal, un rapport, un message d'erreur.
- Aucun appel réseau dans les tests : clients HTTP simulés (`httpx.MockTransport`).
- Données de test fictives : `apps/core/testing/factories.py` et `numbers.py`.

## Événements
- Nom : `objet.fait_au_passé` (`client.created`, `bce.enterprise_changed`).
- Un traitement est idempotent et court ; s'il appelle un service externe lent, il programme
  un travail de fond au lieu de l'appeler directement.
- Ajouter le libellé lisible dans `apps/core/event_labels.py`.

## Migrations
- Une migration par changement, nommée explicitement quand elle est écrite à la main.
- `makemigrations --check` doit passer avant de terminer une session.
