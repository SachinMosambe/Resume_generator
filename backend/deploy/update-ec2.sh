#!/usr/bin/env bash
# Pull latest main and restart the API on EC2.
# Run from the EC2 box: bash backend/deploy/update-ec2.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP_DIR="${ROOT}/backend"
SERVICE_NAME="resume-api"
BUILD_ID="$(date -u +%Y%m%d%H%M%S)"

echo "==> Updating repo at ${ROOT}"
cd "$ROOT"
git fetch origin
git checkout main
git pull --ff-only origin main

echo "==> Installing Python deps"
cd "$APP_DIR"
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -r requirements.txt

# Prefer SSM-backed env when the parameter exists (CI/CD path).
if [[ ! -f .env ]] || [[ "${RESUME_FORCE_ENV_SYNC:-}" == "1" ]]; then
  if command -v aws >/dev/null 2>&1; then
    echo "==> Syncing .env from SSM Parameter Store"
    bash "$(dirname "$0")/ensure-env-from-ssm.sh" || {
      echo "WARN: SSM env sync failed; continuing with existing .env if present" >&2
    }
  fi
fi

if [[ ! -f .env ]]; then
  echo "ERROR: missing ${APP_DIR}/.env — create it or put dotenv at /resume-generator/prod/env in SSM" >&2
  exit 1
fi

# Stamp health so you can verify the live build.
if grep -q '^APP_BUILD_ID=' .env 2>/dev/null; then
  sed -i "s/^APP_BUILD_ID=.*/APP_BUILD_ID=${BUILD_ID}/" .env
else
  echo "APP_BUILD_ID=${BUILD_ID}" >> .env
fi

echo "==> Restarting ${SERVICE_NAME}"
sudo systemctl restart "$SERVICE_NAME"
sleep 2
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true

echo ""
echo "Verify deploy:"
echo "  curl -s http://127.0.0.1:8000/api/health"
echo "Expected build_id: ${BUILD_ID}"
curl -s http://127.0.0.1:8000/api/health || true
echo ""
