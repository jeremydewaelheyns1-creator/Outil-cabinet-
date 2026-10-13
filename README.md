# Outil cabinet

Outil interne de gestion du cabinet : fiches clients, relations et bénéficiaires effectifs,
copie de la Banque-Carrefour des Entreprises, vérification TVA (VIES), reprise des données
FID-Manager. Viendront ensuite les échéances, les documents, l'anti-blanchiment, la
facturation… (voir `docs/ROADMAP.md`).

## Démarrer sur un poste de développement

Prérequis : Python 3.13, [uv](https://docs.astral.sh/uv/), PostgreSQL 16.

```bash
cp .env.example .env
uv sync
uv run python manage.py migrate
uv run python manage.py demo          # données fictives + compte demo@cabinet.test
uv run python manage.py runserver
```

À la première connexion, l'outil impose la configuration de la double authentification
(application d'authentification ou clé d'accès).

## Commandes utiles

| Commande | Rôle |
| --- | --- |
| `python manage.py import_bce archive.zip` | Importe un export BCE (complet ou mise à jour) |
| `python manage.py import_fid_clients export.xlsx` | Analyse un export clients FID-Manager |
| `python manage.py import_fid_clients export.xlsx --appliquer` | L'importe réellement |
| `python manage.py run_jobs` | Traite le travail de fond en attente (planifié en ligne) |

## Documentation technique

- `docs/ARCHITECTURE.md` — comment l'outil est construit et hébergé
- `docs/DECISIONS.md` — les choix et leurs raisons
- `docs/CONVENTIONS.md` — règles d'écriture du code
- `docs/ROADMAP.md` — plan des épiques
- `docs/SESSIONS.md` — journal des sessions de travail
