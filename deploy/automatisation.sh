#!/usr/bin/env bash
# Mise en place, UNE SEULE FOIS, du site d'essai et des mises à jour automatiques (D-130).
#
# À lancer depuis Google Cloud Shell, dans le dossier du code, après « gh auth login » :
#     bash deploy/automatisation.sh
#
# Ce que ça crée :
#   - le site d'essai « outil-essai » : sa propre base (données fictives uniquement), son propre
#     espace de documents, ses propres secrets et son propre compte technique, qui n'a accès à
#     rien du vrai site (ni base, ni documents, ni secrets) ;
#   - l'autorisation pour GitHub de mettre à jour les deux sites, sans aucune clé stockée chez
#     GitHub (« fédération d'identité » : seul CE dépôt est accepté) ;
#   - les trois réglages que les automatismes GitHub lisent (projet, autorisation, compte).
#
# Ensuite : chaque modification de Claude arrive toute seule sur le site d'essai ; le vrai site
# n'est mis à jour que quand Jeremy dit « c'est bon ». Relancer ce script est sans danger.
set -euo pipefail

REGION="europe-west1"
SERVICE="outil"
SQL_INSTANCE="outil-db"
REPOSITORY="outil"
APP_SA_NAME="outil-app"
ESSAI_SERVICE="outil-essai"
ESSAI_DB="outil_essai"
ESSAI_DB_USER="outil_essai"
ESSAI_SA_NAME="outil-essai"
DEPLOY_SA_NAME="outil-deploiement"
POOL="github"
PROVIDER="github-oidc"
GITHUB_REPO="${GITHUB_REPO:-jeremydewaelheyns1-creator/Outil-cabinet-}"

say() { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✓ %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
random_secret() { openssl rand -base64 96 | tr -d '\n/+=' | cut -c1-"${1:-50}"; }
secret_exists() { gcloud secrets describe "$1" >/dev/null 2>&1; }
# Un compte technique tout juste créé met parfois une minute à être connu partout chez Google :
# on réessaie au lieu d'échouer.
retry() {
  local i
  for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
    "$@" 2>/dev/null && return 0
    [[ $i -eq 1 ]] && echo "  (Google enregistre le compte, on patiente…)"
    sleep 10
  done
  "$@"
}
new_secret() { printf '%s' "$2" | gcloud secrets create "$1" --replication-policy=user-managed \
  --locations="$REGION" --data-file=- --quiet >/dev/null; }

PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
[[ -n "$PROJECT" ]] || fail "Aucun projet choisi. Lancez d'abord : gcloud config set project ID-DU-PROJET"
[[ -f Dockerfile && -f manage.py ]] || fail "Lancez ce script depuis le dossier du code."
gcloud run services describe "$SERVICE" --region="$REGION" >/dev/null 2>&1 \
  || fail "Le vrai site n'est pas encore installé : lancez d'abord bash deploy/installer.sh"

NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
APP_SA="${APP_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
ESSAI_SA="${ESSAI_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
DEPLOY_SA="${DEPLOY_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
ESSAI_BUCKET="${PROJECT}-essai-documents"
CONNECTION="${PROJECT}:${REGION}:${SQL_INSTANCE}"
# Le site d'essai démarre avec la même version que le vrai site.
IMAGE="$(gcloud run services describe "$SERVICE" --region="$REGION" \
  --format='value(spec.template.spec.containers[0].image)')"

say "1/7 Services Google pour l'autorisation de GitHub"
gcloud services enable iamcredentials.googleapis.com sts.googleapis.com --quiet
ok "Activés"

say "2/7 Compte technique du site d'essai (aucun accès au vrai site)"
gcloud iam service-accounts describe "$ESSAI_SA" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$ESSAI_SA_NAME" --display-name="Outil cabinet (site d'essai)" --quiet
retry gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:${ESSAI_SA}" \
  --role=roles/cloudsql.client --condition=None --quiet >/dev/null
ok "${ESSAI_SA}"

say "3/7 Base et documents du site d'essai (données fictives uniquement)"
gcloud sql databases describe "$ESSAI_DB" --instance="$SQL_INSTANCE" >/dev/null 2>&1 \
  || gcloud sql databases create "$ESSAI_DB" --instance="$SQL_INSTANCE" --quiet
if ! secret_exists DATABASE_URL_ESSAI; then
  DB_PASSWORD="$(random_secret 40)"
  if gcloud sql users list --instance="$SQL_INSTANCE" --format='value(name)' | grep -qx "$ESSAI_DB_USER"; then
    gcloud sql users set-password "$ESSAI_DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASSWORD" --quiet
  else
    gcloud sql users create "$ESSAI_DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASSWORD" --quiet
  fi
  new_secret DATABASE_URL_ESSAI "postgres://${ESSAI_DB_USER}:${DB_PASSWORD}@/${ESSAI_DB}?host=/cloudsql/${CONNECTION}"
  unset DB_PASSWORD
fi
secret_exists DJANGO_SECRET_KEY_ESSAI || new_secret DJANGO_SECRET_KEY_ESSAI "$(random_secret 60)"
secret_exists MAILBOX_TOKEN_KEY_ESSAI || new_secret MAILBOX_TOKEN_KEY_ESSAI \
  "$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"
ESSAI_SECRETS_LIST=(DATABASE_URL_ESSAI DJANGO_SECRET_KEY_ESSAI MAILBOX_TOKEN_KEY_ESSAI)
secret_exists MISTRAL_API_KEY && ESSAI_SECRETS_LIST+=(MISTRAL_API_KEY)
for secret in "${ESSAI_SECRETS_LIST[@]}"; do  # seulement ses propres secrets (et la clé IA)
  retry gcloud secrets add-iam-policy-binding "$secret" --member="serviceAccount:${ESSAI_SA}" \
    --role=roles/secretmanager.secretAccessor --quiet >/dev/null
done
if ! gcloud storage buckets describe "gs://${ESSAI_BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${ESSAI_BUCKET}" --location="$REGION" \
    --uniform-bucket-level-access --public-access-prevention --quiet
fi
retry gcloud storage buckets add-iam-policy-binding "gs://${ESSAI_BUCKET}" \
  --member="serviceAccount:${ESSAI_SA}" --role=roles/storage.objectAdmin --quiet >/dev/null
ok "Base ${ESSAI_DB}, documents gs://${ESSAI_BUCKET}"

SECRETS="DJANGO_SECRET_KEY=DJANGO_SECRET_KEY_ESSAI:latest,DATABASE_URL=DATABASE_URL_ESSAI:latest,MAILBOX_TOKEN_KEY=MAILBOX_TOKEN_KEY_ESSAI:latest"
secret_exists MISTRAL_API_KEY && SECRETS="${SECRETS},MISTRAL_API_KEY=MISTRAL_API_KEY:latest"
service_urls() {
  gcloud run services describe "$ESSAI_SERVICE" --region="$REGION" \
    --format='value(metadata.annotations."run.googleapis.com/urls")' 2>/dev/null \
    | python3 -c 'import json,sys; t=sys.stdin.read().strip(); print(",".join(json.loads(t)) if t else "")'
}
env_vars() {
  local urls="${1:-https://localhost}"
  local hosts; hosts="$(printf '%s' "$urls" | sed 's#https://##g')"
  echo "^@^GS_DOCUMENTS_BUCKET=${ESSAI_BUCKET}@DJANGO_ALLOWED_HOSTS=${hosts}@DJANGO_CSRF_TRUSTED_ORIGINS=${urls}@SITE_URL=${urls%%,*}@DJANGO_EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend@SITE_ESSAI=1"
}
job() {  # job NOM COMMANDE... : tâche du site d'essai, même image
  local name="$1"; shift
  local args; args="$(IFS=,; echo "$*")"
  local verb=create
  gcloud run jobs describe "$name" --region="$REGION" >/dev/null 2>&1 && verb=update
  gcloud run jobs "$verb" "$name" --region="$REGION" --image="$IMAGE" \
    --service-account="$ESSAI_SA" --set-cloudsql-instances="$CONNECTION" \
    --set-secrets="$SECRETS" --set-env-vars="$ENV_VARS" --memory=1Gi \
    --task-timeout=30m --max-retries=0 --command=python --args="manage.py,${args}" --quiet >/dev/null
}

say "4/7 Mise en ligne du site d'essai"
ENV_VARS="$(env_vars "$(service_urls || true)")"
job outil-essai-migrations migrate --noinput
gcloud run jobs execute outil-essai-migrations --region="$REGION" --wait --quiet
gcloud run deploy "$ESSAI_SERVICE" --region="$REGION" --image="$IMAGE" --service-account="$ESSAI_SA" \
  --add-cloudsql-instances="$CONNECTION" --set-secrets="$SECRETS" --set-env-vars="$ENV_VARS" \
  --memory=1Gi --cpu=1 --min-instances=0 --max-instances=1 --allow-unauthenticated --quiet >/dev/null
URLS="$(service_urls)"
ENV_VARS="$(env_vars "$URLS")"
gcloud run services update "$ESSAI_SERVICE" --region="$REGION" --set-env-vars="$ENV_VARS" --quiet >/dev/null
job outil-essai-migrations migrate --noinput
ok "En ligne : ${URLS%%,*}"

say "5/7 Votre compte sur le site d'essai, puis les dossiers fictifs"
if [[ -z "${COMPTE_ESSAI:-}" ]]; then
  read -r -p "  Créer votre compte sur le site d'essai ? (oui / non si c'est déjà fait) : " COMPTE_ESSAI
fi
if [[ "${COMPTE_ESSAI}" == "oui" ]]; then
  read -r -p "  Votre adresse e-mail (pour vous connecter au site d'essai) : " ADMIN_EMAIL
  read -r -p "  Votre prénom : " ADMIN_FIRST
  read -r -p "  Votre nom : " ADMIN_LAST
  while true; do
    read -r -s -p "  Mot de passe du site d'essai (12 caractères minimum, il ne s'affiche pas) : " P1; echo
    read -r -s -p "  Retapez-le : " P2; echo
    [[ "$P1" == "$P2" && ${#P1} -ge 12 ]] && break
    echo "  Les deux ne sont pas identiques ou trop courts : recommencez."
  done
  printf '%s' "$P1" | gcloud secrets create ESSAI_COMPTE_TEMPORAIRE --replication-policy=user-managed \
    --locations="$REGION" --data-file=- --quiet >/dev/null
  unset P1 P2
  gcloud secrets add-iam-policy-binding ESSAI_COMPTE_TEMPORAIRE --member="serviceAccount:${ESSAI_SA}" \
    --role=roles/secretmanager.secretAccessor --quiet >/dev/null
  gcloud run jobs create outil-essai-compte --region="$REGION" --image="$IMAGE" \
    --service-account="$ESSAI_SA" --set-cloudsql-instances="$CONNECTION" \
    --set-secrets="${SECRETS},PREMIER_COMPTE_MOT_DE_PASSE=ESSAI_COMPTE_TEMPORAIRE:latest" \
    --set-env-vars="$ENV_VARS" --memory=1Gi --max-retries=0 --command=python \
    --args="manage.py,premier_compte,--email,${ADMIN_EMAIL},--prenom,${ADMIN_FIRST},--nom,${ADMIN_LAST}" \
    --quiet >/dev/null
  if gcloud run jobs execute outil-essai-compte --region="$REGION" --wait --quiet; then
    ok "Compte créé pour ${ADMIN_EMAIL} sur le site d'essai"
  else
    echo "  ⚠ Compte non créé (mot de passe trop simple, ou un compte existe déjà)."
  fi
  gcloud run jobs delete outil-essai-compte --region="$REGION" --quiet >/dev/null
  gcloud secrets delete ESSAI_COMPTE_TEMPORAIRE --quiet >/dev/null
fi

# Puis les dossiers fictifs. Le compte « démo » reçoit un mot de passe tiré au hasard, jamais affiché : inutilisable.
job outil-essai-demo demo --mot-de-passe "$(random_secret 32)"
if gcloud run jobs execute outil-essai-demo --region="$REGION" --wait --quiet; then
  ok "Dossiers fictifs créés"
else
  ok "Dossiers fictifs déjà présents"
fi
gcloud run jobs delete outil-essai-demo --region="$REGION" --quiet >/dev/null

say "6/7 Autorisation de GitHub (dépôt ${GITHUB_REPO} uniquement, aucune clé stockée)"
gcloud iam service-accounts describe "$DEPLOY_SA" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$DEPLOY_SA_NAME" --display-name="Outil cabinet (mises à jour depuis GitHub)" --quiet
retry gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:${DEPLOY_SA}" \
  --role=roles/run.admin --condition=None --quiet >/dev/null
retry gcloud artifacts repositories add-iam-policy-binding "$REPOSITORY" --location="$REGION" \
  --member="serviceAccount:${DEPLOY_SA}" --role=roles/artifactregistry.writer --quiet >/dev/null
for runtime in "$APP_SA" "$ESSAI_SA"; do  # pour lancer les deux sites avec leur propre compte
  retry gcloud iam service-accounts add-iam-policy-binding "$runtime" \
    --member="serviceAccount:${DEPLOY_SA}" --role=roles/iam.serviceAccountUser --quiet >/dev/null
done
gcloud iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools create "$POOL" --location=global \
       --display-name="GitHub (mises à jour)" --quiet
if ! gcloud iam workload-identity-pools providers describe "$PROVIDER" --location=global \
     --workload-identity-pool="$POOL" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --location=global \
    --workload-identity-pool="$POOL" --display-name="GitHub Actions" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='${GITHUB_REPO}'" --quiet
fi
retry gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${GITHUB_REPO}" \
  --quiet >/dev/null
PROVIDER_NAME="projects/${NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"
ok "GitHub peut mettre à jour les sites, rien d'autre"

say "7/7 Réglages lus par les automatismes GitHub"
if gh auth status >/dev/null 2>&1; then
  gh variable set GCP_PROJECT --repo "$GITHUB_REPO" --body "$PROJECT"
  gh variable set GCP_WIF_PROVIDER --repo "$GITHUB_REPO" --body "$PROVIDER_NAME"
  gh variable set GCP_DEPLOY_SA --repo "$GITHUB_REPO" --body "$DEPLOY_SA"
  ok "Réglages enregistrés dans GitHub"
else
  echo "  ⚠ Pas connecté à GitHub (gh auth login) : relancez ce script après vous être connecté."
fi

say "Terminé."
echo "  Site d'essai : ${URLS%%,*}  (données fictives uniquement)"
echo "  Chaque modification arrive d'abord sur le site d'essai, toute seule."
echo "  Le vrai site n'est mis à jour que quand vous dites « c'est bon »."
