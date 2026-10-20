#!/usr/bin/env bash
# Installation (ou mise à jour) de l'outil dans le projet Google Cloud du cabinet.
#
# À lancer depuis Google Cloud Shell, dans le dossier du code :   bash deploy/installer.sh
#
# Tout est créé en Belgique (europe-west1). Les secrets (clé de l'application, mot de passe de
# la base, clé de chiffrement des jetons Outlook) sont fabriqués ici, au hasard, et rangés
# directement dans Secret Manager : personne ne les voit, ils ne sont écrits nulle part
# ailleurs. Relancer le script est sans danger : ce qui existe déjà est gardé, le code est
# reconstruit et la base mise à jour.
set -euo pipefail

REGION="europe-west1"
SERVICE="outil"
SQL_INSTANCE="outil-db"
DB_NAME="outil"
DB_USER="outil"
REPOSITORY="outil"
APP_SA_NAME="outil-app"
SCHEDULER_SA_NAME="outil-planificateur"

say() { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✓ %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
random_secret() { openssl rand -base64 96 | tr -d '\n/+=' | cut -c1-"${1:-50}"; }

PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
[[ -n "$PROJECT" ]] || fail "Aucun projet choisi. Lancez d'abord : gcloud config set project ID-DU-PROJET"
[[ -f Dockerfile && -f manage.py ]] || fail "Lancez ce script depuis le dossier du code (bash deploy/installer.sh)."

APP_SA="${APP_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
SCHEDULER_SA="${SCHEDULER_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
BUCKET="${PROJECT}-documents"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPOSITORY}/application:$(date +%Y%m%d-%H%M%S)"
CONNECTION="${PROJECT}:${REGION}:${SQL_INSTANCE}"

say "Projet : ${PROJECT} — région : ${REGION} (Belgique)"
gcloud projects describe "$PROJECT" --format='value(projectId)' >/dev/null \
  || fail "Projet introuvable ou accès refusé."

say "1/9 Activation des services Google nécessaires (2 à 3 minutes la première fois)"
gcloud services enable run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com cloudscheduler.googleapis.com \
  storage.googleapis.com iam.googleapis.com --quiet \
  || fail "Activation refusée : la facturation est-elle bien associée au projet (étape 1) ?"
ok "Services activés"

say "2/9 Comptes techniques (droits limités au strict nécessaire)"
for sa in "$APP_SA_NAME" "$SCHEDULER_SA_NAME"; do
  gcloud iam service-accounts describe "${sa}@${PROJECT}.iam.gserviceaccount.com" >/dev/null 2>&1 \
    || gcloud iam service-accounts create "$sa" --display-name="Outil cabinet (${sa})" --quiet
done
for role in roles/cloudsql.client roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:${APP_SA}" \
    --role="$role" --condition=None --quiet >/dev/null
done
# Construction de l'application : le compte par défaut des projets récents doit pouvoir
# construire et ranger l'image.
NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${NUMBER}-compute@developer.gserviceaccount.com" \
  --role=roles/cloudbuild.builds.builder --condition=None --quiet >/dev/null
ok "Comptes prêts"

say "3/9 Espace privé pour les documents des clients"
if ! gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${BUCKET}" --location="$REGION" \
    --uniform-bucket-level-access --public-access-prevention --quiet
fi
gcloud storage buckets update "gs://${BUCKET}" --versioning --quiet >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${APP_SA}" --role=roles/storage.objectAdmin --quiet >/dev/null
ok "gs://${BUCKET} (privé, accès public interdit, versions conservées)"

say "4/9 Base de données PostgreSQL 16 (5 à 10 minutes la première fois)"
if ! gcloud sql instances describe "$SQL_INSTANCE" >/dev/null 2>&1; then
  gcloud sql instances create "$SQL_INSTANCE" --database-version=POSTGRES_16 \
    --edition=ENTERPRISE --tier=db-f1-micro --region="$REGION" --storage-size=10 \
    --storage-auto-increase --backup-start-time=02:00 --enable-point-in-time-recovery \
    --retained-backups-count=14 --deletion-protection --quiet
fi
gcloud sql databases describe "$DB_NAME" --instance="$SQL_INSTANCE" >/dev/null 2>&1 \
  || gcloud sql databases create "$DB_NAME" --instance="$SQL_INSTANCE" --quiet
ok "Base prête (sauvegarde chaque nuit, retour possible à n'importe quel moment des 7 derniers jours)"

say "5/9 Secrets (fabriqués au hasard, rangés dans Secret Manager)"
secret_exists() { gcloud secrets describe "$1" >/dev/null 2>&1; }
new_secret() { printf '%s' "$2" | gcloud secrets create "$1" --replication-policy=user-managed \
  --locations="$REGION" --data-file=- --quiet >/dev/null; }
secret_exists DJANGO_SECRET_KEY || new_secret DJANGO_SECRET_KEY "$(random_secret 60)"
secret_exists MAILBOX_TOKEN_KEY || new_secret MAILBOX_TOKEN_KEY \
  "$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"
if ! secret_exists DATABASE_URL; then
  DB_PASSWORD="$(random_secret 40)"
  if gcloud sql users list --instance="$SQL_INSTANCE" --format='value(name)' | grep -qx "$DB_USER"; then
    gcloud sql users set-password "$DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASSWORD" --quiet
  else
    gcloud sql users create "$DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASSWORD" --quiet
  fi
  new_secret DATABASE_URL "postgres://${DB_USER}:${DB_PASSWORD}@/${DB_NAME}?host=/cloudsql/${CONNECTION}"
  unset DB_PASSWORD
fi
ok "DJANGO_SECRET_KEY, DATABASE_URL, MAILBOX_TOKEN_KEY"

say "6/9 Construction de l'application (5 à 10 minutes)"
gcloud artifacts repositories describe "$REPOSITORY" --location="$REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "$REPOSITORY" --repository-format=docker \
       --location="$REGION" --quiet
gcloud builds submit --region="$REGION" --tag="$IMAGE" --quiet .
ok "Image construite"

SECRETS="DJANGO_SECRET_KEY=DJANGO_SECRET_KEY:latest,DATABASE_URL=DATABASE_URL:latest,MAILBOX_TOKEN_KEY=MAILBOX_TOKEN_KEY:latest"
# Connexion Outlook (D-044) : les trois valeurs sont rangées dans Secret Manager quand elle
# est prête ; elles sont alors reprises à chaque mise à jour.
for optional in OUTLOOK_TENANT_ID OUTLOOK_CLIENT_ID OUTLOOK_CLIENT_SECRET; do
  if secret_exists "$optional"; then
    SECRETS="${SECRETS},${optional}=${optional}:latest"
  fi
done
# Google donne deux adresses au service (…-ew.a.run.app et …europe-west1.run.app) :
# l'outil accepte les deux. Séparateur « @ » car les listes contiennent des virgules.
service_urls() {
  gcloud run services describe "$SERVICE" --region="$REGION" \
    --format='value(metadata.annotations."run.googleapis.com/urls")' 2>/dev/null \
    | python3 -c 'import json,sys; t=sys.stdin.read().strip(); print(",".join(json.loads(t)) if t else "")'
}
env_vars() {  # env_vars ADRESSES (séparées par des virgules)
  local urls="${1:-https://localhost}"
  local hosts; hosts="$(printf '%s' "$urls" | sed 's#https://##g')"
  # SITE_URL : adresse mise dans les liens envoyés aux clients (la première de la liste).
  echo "^@^GS_DOCUMENTS_BUCKET=${BUCKET}@DJANGO_ALLOWED_HOSTS=${hosts}@DJANGO_CSRF_TRUSTED_ORIGINS=${urls}@SITE_URL=${urls%%,*}"
}
URLS="$(service_urls || true)"
ENV_VARS="$(env_vars "$URLS")"

job() {  # job NOM COMMANDE... : crée ou met à jour une tâche Cloud Run avec la même image
  local name="$1"; shift
  local args; args="$(IFS=,; echo "$*")"
  local verb=create
  gcloud run jobs describe "$name" --region="$REGION" >/dev/null 2>&1 && verb=update
  gcloud run jobs "$verb" "$name" --region="$REGION" --image="$IMAGE" \
    --service-account="$APP_SA" --set-cloudsql-instances="$CONNECTION" \
    --set-secrets="$SECRETS" --set-env-vars="$ENV_VARS" --memory=1Gi \
    --task-timeout=30m --max-retries=0 --command=python --args="manage.py,${args}" --quiet >/dev/null
}

say "7/9 Mise à jour de la base (migrations)"
job outil-migrations migrate --noinput
gcloud run jobs execute outil-migrations --region="$REGION" --wait --quiet
ok "Base à jour"

say "8/9 Mise en ligne"
gcloud run deploy "$SERVICE" --region="$REGION" --image="$IMAGE" --service-account="$APP_SA" \
  --add-cloudsql-instances="$CONNECTION" --set-secrets="$SECRETS" --set-env-vars="$ENV_VARS" \
  --memory=1Gi --cpu=1 --min-instances=0 --max-instances=3 --allow-unauthenticated --quiet >/dev/null
URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')"
NEW_URLS="$(service_urls || true)"
NEW_URLS="${NEW_URLS:-$URL}"
if [[ "$NEW_URLS" != "$URLS" ]]; then
  # Première installation : les adresses ne sont connues qu'après la mise en ligne.
  ENV_VARS="$(env_vars "$NEW_URLS")"
  gcloud run services update "$SERVICE" --region="$REGION" --set-env-vars="$ENV_VARS" --quiet >/dev/null
  job outil-migrations migrate --noinput
fi
ok "En ligne : ${URL}"

say "9/9 Travaux automatiques toutes les 5 minutes (relances, échéances, sites officiels)"
job outil-travaux run_jobs
gcloud run jobs add-iam-policy-binding outil-travaux --region="$REGION" \
  --member="serviceAccount:${SCHEDULER_SA}" --role=roles/run.invoker --quiet >/dev/null
RUN_URI="https://run.googleapis.com/v2/projects/${PROJECT}/locations/${REGION}/jobs/outil-travaux:run"
if gcloud scheduler jobs describe outil-travaux --location="$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http outil-travaux --location="$REGION" --schedule="*/5 * * * *" \
    --uri="$RUN_URI" --http-method=POST --oauth-service-account-email="$SCHEDULER_SA" --quiet >/dev/null
else
  gcloud scheduler jobs create http outil-travaux --location="$REGION" --schedule="*/5 * * * *" \
    --time-zone="Europe/Brussels" --uri="$RUN_URI" --http-method=POST \
    --oauth-service-account-email="$SCHEDULER_SA" --quiet >/dev/null
fi
ok "Planifié"

# --- Premier compte (seulement lors de la première installation) ---------------------------
if [[ "${PREMIER_COMPTE:-}" == "oui" ]]; then
  say "Création de votre compte administrateur"
  read -r -p "  Votre adresse e-mail professionnelle : " ADMIN_EMAIL
  read -r -p "  Votre prénom : " ADMIN_FIRST
  read -r -p "  Votre nom : " ADMIN_LAST
  while true; do
    read -r -s -p "  Choisissez un mot de passe (12 caractères minimum, il ne s'affiche pas) : " P1; echo
    read -r -s -p "  Retapez-le : " P2; echo
    [[ "$P1" == "$P2" && ${#P1} -ge 12 ]] && break
    echo "  Les deux ne sont pas identiques ou trop courts : recommencez."
  done
  # Secret temporaire, supprimé juste après : le mot de passe n'est écrit nulle part ailleurs.
  printf '%s' "$P1" | gcloud secrets create PREMIER_COMPTE_TEMPORAIRE --replication-policy=user-managed \
    --locations="$REGION" --data-file=- --quiet >/dev/null
  unset P1 P2
  gcloud secrets add-iam-policy-binding PREMIER_COMPTE_TEMPORAIRE --member="serviceAccount:${APP_SA}" \
    --role=roles/secretmanager.secretAccessor --quiet >/dev/null
  gcloud run jobs create outil-premier-compte --region="$REGION" --image="$IMAGE" \
    --service-account="$APP_SA" --set-cloudsql-instances="$CONNECTION" \
    --set-secrets="${SECRETS},PREMIER_COMPTE_MOT_DE_PASSE=PREMIER_COMPTE_TEMPORAIRE:latest" \
    --set-env-vars="$ENV_VARS" --memory=1Gi --max-retries=0 --command=python \
    --args="manage.py,premier_compte,--email,${ADMIN_EMAIL},--prenom,${ADMIN_FIRST},--nom,${ADMIN_LAST}" \
    --quiet >/dev/null
  if gcloud run jobs execute outil-premier-compte --region="$REGION" --wait --quiet; then
    ok "Compte créé pour ${ADMIN_EMAIL}"
  else
    echo "  ⚠ Compte non créé (mot de passe trop simple, ou un compte existe déjà). Voir les journaux de la tâche outil-premier-compte."
  fi
  gcloud run jobs delete outil-premier-compte --region="$REGION" --quiet >/dev/null
  gcloud secrets delete PREMIER_COMPTE_TEMPORAIRE --quiet >/dev/null
  ok "Secret temporaire supprimé"
fi

say "Terminé."
echo "  Adresse de l'outil : ${URL}"
echo "  Première connexion : la double authentification vous sera demandée (application sur téléphone)."
