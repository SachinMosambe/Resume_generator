#!/usr/bin/env bash
# Run once on the EC2 Ubuntu box from the repo root or backend folder.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="resume-api"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "==> Installing system packages"
sudo apt-get update -y
sudo apt-get install -y python3-pip python3-venv git libreoffice-writer-nogui

echo "==> Creating venv and installing Python deps"
cd "$APP_DIR"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p uploads

if [[ ! -f .env ]]; then
  echo "==> Creating .env from .env.example — EDIT IT before starting"
  cp .env.example .env
  echo "Open $APP_DIR/.env and set AWS_BEARER_TOKEN_BEDROCK and CORS_ORIGINS"
fi

echo "==> Installing systemd service"
sudo tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=Resume Generator API
After=network.target

[Service]
User=ubuntu
WorkingDirectory=${APP_DIR}
Environment=PATH=${APP_DIR}/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=HOME=/home/ubuntu
ExecStart=${APP_DIR}/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo ""
echo "Done. Check status:"
echo "  sudo systemctl status ${SERVICE_NAME} --no-pager"
echo "Health:"
echo "  curl http://127.0.0.1:8000/api/health"
echo ""
echo "Remember: edit ${APP_DIR}/.env then: sudo systemctl restart ${SERVICE_NAME}"
