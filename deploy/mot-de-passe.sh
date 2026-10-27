#!/usr/bin/env bash
# Dépannage : donner un nouveau mot de passe à un compte de l'outil (D-081).
# À lancer dans Cloud Shell :  cd ~/outil && bash deploy/mot-de-passe.sh
# Le mot de passe ne s'affiche pas et n'est écrit nulle part : il passe par un secret
# temporaire, supprimé à la fin quoi qu'il arrive. La double authentification reste demandée.
set -euo pipefail

REGION="europe-west1"
SERVICE="outil"
SQL_INSTANCE="outil-db"
APP_SA_NAME="outil-app"
JOB="outil-mot-de-passe"
TEMP_SECRET="NOUVEAU_MOT_DE_PASSE_TEMPORAIRE"

say() { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✓ %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
[[ -n "$PROJECT" ]] || fail "Aucun projet Google Cloud choisi dans Cloud Shell."
APP_SA="${APP_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
CONNECTION="${PROJECT}:${REGION}:${SQL_INSTANCE}"
BUCKET="${PROJECT}-documents"

cleanup() {
  gcloud run jobs delete "$JOB" --region="$REGION" --quiet >/dev/null 2>&1 || true
  gcloud secrets delete "$TEMP_SECRET" --quiet >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Même image et mêmes réglages que l'outil en ligne (repris de la tâche des migrations).
IMAGE="$(gcloud run jobs describe outil-migrations --region="$REGION" \
  --format='value(spec.template.spec.template.spec.containers[0].image)' 2>/dev/null || true)"
[[ -n "$IMAGE" ]] || fail "Outil introuvable : lancez d'abord l'installation (deploy/installer.sh)."
SECRETS="DJANGO_SECRET_KEY=DJANGO_SECRET_KEY:latest,DATABASE_URL=DATABASE_URL:latest,MAILBOX_TOKEN_KEY=MAILBOX_TOKEN_KEY:latest"
URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')"
ENV_VARS="^@^GS_DOCUMENTS_BUCKET=${BUCKET}@DJANGO_ALLOWED_HOSTS=${URL#https://}@DJANGO_CSRF_TRUSTED_ORIGINS=${URL}@SITE_URL=${URL}"

say "Nouveau mot de passe"
read -r -p "  Adresse e-mail du compte : " EMAIL
while true; do
  read -r -s -p "  Nouveau mot de passe (12 caractères minimum, il ne s'affiche pas) : " P1; echo
  read -r -s -p "  Retapez-le : " P2; echo
  [[ "$P1" == "$P2" && ${#P1} -ge 12 ]] && break
  echo "  Les deux ne sont pas identiques ou trop courts : recommencez."
done
printf '%s' "$P1" | gcloud secrets create "$TEMP_SECRET" --replication-policy=user-managed \
  --locations="$REGION" --data-file=- --quiet >/dev/null
unset P1 P2
gcloud secrets add-iam-policy-binding "$TEMP_SECRET" --member="serviceAccount:${APP_SA}" \
  --role=roles/secretmanager.secretAccessor --quiet >/dev/null
gcloud run jobs create "$JOB" --region="$REGION" --image="$IMAGE" \
  --service-account="$APP_SA" --set-cloudsql-instances="$CONNECTION" \
  --set-secrets="${SECRETS},NOUVEAU_MOT_DE_PASSE=${TEMP_SECRET}:latest" \
  --set-env-vars="$ENV_VARS" --memory=1Gi --max-retries=0 --command=python \
  --args="manage.py,nouveau_mot_de_passe,--email,${EMAIL}" --quiet >/dev/null
if gcloud run jobs execute "$JOB" --region="$REGION" --wait --quiet >/dev/null 2>&1; then
  ok "Mot de passe changé pour ${EMAIL}. Connectez-vous : ${URL}"
else
  sleep 5
  REASON="$(gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"${JOB}\"" \
    --freshness=10m --limit=30 --format='value(textPayload)' 2>/dev/null \
    | grep -m1 -E "Aucun compte|refusé" || true)"
  echo "  ⚠ Rien n'a été changé. ${REASON:-Voir les journaux de la tâche ${JOB}.}"
fi
cleanup
ok "Secret temporaire supprimé"
