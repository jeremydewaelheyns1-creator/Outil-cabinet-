# Outil cabinet — instructions pour Claude

Outil interne de gestion d'**un seul** cabinet comptable belge (Wallonie), destiné à remplacer
FID-Manager (au moins à parité), avec des automatismes en plus. Pas un SaaS.
Le porteur du projet (Jeremy) ne code pas : Claude écrit tout le code, les tests et la doc
technique. Parler en français, simplement, sans jargon.

## À lire au début de chaque session

1. `docs/SESSIONS.md` — où on en est, ce qui reste.
2. `docs/ROADMAP.md` — l'ordre des épiques et leur critère de fin.
3. `docs/DECISIONS.md` avant de changer un choix structurant (ajouter une décision, ne pas
   en réécrire une ancienne).
4. `docs/CONVENTIONS.md` avant d'écrire du code.

## Règles non négociables

- **Aucune donnée réelle de client** dans le dépôt, les tests, les exemples ou la
  conversation. Données fictives uniquement (`apps/core/testing`, commande `demo`). Les vraies
  données sont importées par le cabinet directement dans l'outil hébergé chez lui.
- Ne jamais manipuler les mots de passe ou identifiants de Jeremy ou du cabinet.
- Toute requête sur des données clients passe par `Client.objects.visible_to(user)` /
  `Portfolio.objects.visible_to(user)`.
- Consultation, modification, export ou affichage d'une donnée sensible → `log_access(...)`.
- Le numéro national n'apparaît jamais en clair sans action explicite journalisée
  (`reveal`), jamais dans un journal, un rapport ou un message d'erreur.
- L'IA propose, l'humain décide : un automatisme qui modifie une donnée saisie par le
  cabinet passe par une proposition validée (voir BCE : différences à cocher), SAUF dans les
  cas listés par D-032 où toutes les vérifications sont vertes (alors : appliqué, listé dans
  « Classé automatiquement », annulable, tracé).
- Un fait métier = `events.emit(...)` ; un automatisme = `@events.on(...)`, idempotent.
- Interface centrée sur le dossier client (D-019, D-026) : tout écran propre à un client est
  une entrée de `TOP` (onglets du haut, travail fréquent) ou de `SIDE` (panneau de gauche,
  paperasse) dans `apps/clients/dossier.py`, rendue via `render_section()`
  (apps/clients/views.py). Ne jamais ajouter d'onglet du haut sans l'accord de Jeremy ; deux
  clics maximum pour toute information (D-023).
- Ne prendre aucune initiative : faire ce que Jeremy demande, et proposer (sans le faire) ce qui
  pourrait être utile en plus. Attendre son accord.

## Commandes

```bash
export UV_SYSTEM_CERTS=1; unset UV_NATIVE_TLS   # dans ce conteneur
service postgresql start                        # si la base locale est arrêtée
uv run ruff format . && uv run ruff check .     # style
uv run mypy .                                   # typage strict
uv run pytest                                   # tests (base PostgreSQL locale)
uv run python manage.py makemigrations --check --dry-run --settings=config.settings.test
uv run python manage.py runserver               # poste de développement
uv run python manage.py demo                    # données fictives
```

Après chaque étape livrée : ajouter une entrée en langage simple en tête de
`docs/NOUVEAUTES.md` (page « Nouveautés » de la démo en ligne, publiée automatiquement sur
GitHub Pages par `.github/workflows/demo.yml`).

Une session n'est terminée que si format, ruff, mypy, migrations et pytest sont au vert.
