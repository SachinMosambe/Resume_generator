#!/usr/bin/env bash
# Materialize backend/.env from SSM Parameter Store (SecureString).
# Parameter path: /resume-generator/prod/env  (full dotenv body)
# Optional overrides as separate params under /resume-generator/prod/
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${APP_DIR}/.env"
PARAM_NAME="${RESUME_ENV_SSM_PARAM:-/resume-generator/prod/env}"
REGION="${AWS_REGION:-ap-south-1}"

echo "==> Fetching ${PARAM_NAME} from SSM (${REGION})"
VALUE="$(aws ssm get-parameter \
  --name "$PARAM_NAME" \
  --with-decryption \
  --region "$REGION" \
  --query 'Parameter.Value' \
  --output text)"

if [[ -z "${VALUE}" || "${VALUE}" == "None" ]]; then
  echo "ERROR: empty parameter ${PARAM_NAME}" >&2
  exit 1
fi

umask 077
printf '%s\n' "$VALUE" > "${ENV_FILE}.tmp"
mv -f "${ENV_FILE}.tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "==> Wrote ${ENV_FILE}"
