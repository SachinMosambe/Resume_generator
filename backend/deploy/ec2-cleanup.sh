#!/usr/bin/env bash
# Free disk + add swap so large resume generates don't OOM-kill resume-api.
set -euo pipefail

echo "==> Before"
df -h / | tail -1
free -h

UPLOADS="${HOME}/Resume_generator/backend/uploads"

echo "==> Clear generated/uploaded resume artifacts (keep format templates)"
if [[ -d "${UPLOADS}/resumes" ]]; then
  find "${UPLOADS}/resumes" -type f -delete
  find "${UPLOADS}/resumes" -mindepth 1 -type d -empty -delete || true
  mkdir -p "${UPLOADS}/resumes"
fi

find /tmp -maxdepth 1 -type d -name 'resume_gen_*' -exec rm -rf {} + 2>/dev/null || true
rm -f /tmp/resume-backend-deploy.tgz 2>/dev/null || true

echo "==> Clear caches"
rm -rf "${HOME}/.cache/pip/"* 2>/dev/null || true
find "${HOME}/Resume_generator" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "${HOME}/Resume_generator" -type d -name '.pytest_cache' -prune -exec rm -rf {} + 2>/dev/null || true
sudo apt-get clean -y >/dev/null 2>&1 || true
sudo journalctl --vacuum-size=50M >/dev/null 2>&1 || true

if [[ -d "${HOME}/Resume_generator/frontend/node_modules" ]]; then
  echo "==> Remove frontend node_modules"
  rm -rf "${HOME}/Resume_generator/frontend/node_modules"
fi

echo "==> Ensure 2G swap exists"
if [[ "$(swapon --show | wc -l)" -eq 0 ]]; then
  if [[ ! -f /swapfile ]]; then
    sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
  fi
  sudo swapon /swapfile
  if ! grep -q '^/swapfile' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  fi
fi

sudo sync
sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || true
sudo systemctl restart resume-api
sleep 3
sudo systemctl is-active resume-api
curl -fsS http://127.0.0.1:8000/api/health || true
echo

echo "==> After"
df -h / | tail -1
free -h
swapon --show || true
du -sh "${UPLOADS}" "${HOME}/.cache" 2>/dev/null || true
echo "upload files remaining: $(find "${UPLOADS}" -type f 2>/dev/null | wc -l)"
