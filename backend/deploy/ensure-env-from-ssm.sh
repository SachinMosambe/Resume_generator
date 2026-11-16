#!/usr/bin/env bash
# Materialize backend/.env from SSM Parameter Store (SecureString).
# Parameter path: /resume-generator/prod/env  (full dotenv body)
# Optional overrides as separate params under /resume-generator/prod/
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${APP_DIR}/.env"
PARAM_NAME="${RESUME_ENV_SSM_PARAM:-/resume-generator/prod/env}"
REGION="${AWS_REGION:-ap-south-1}"

# SSM agent sessions often lack a login PATH; include common aws CLI locations.
export PATH="/usr/local/bin:/usr/bin:/home/ubuntu/.local/bin:${PATH:-}"

if ! command -v aws >/dev/null 2>&1; then
  echo "WARN: aws CLI not found on PATH; skipping env sync" >&2
  exit 1
fi

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
