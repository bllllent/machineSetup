#!/usr/bin/env bash
# Landing page for the MS-01: nginx on port 80 serving landing/site/ from
# this repo checkout. Idempotent — safe to re-run. Updating the page needs
# no restart: edit site/index.html, git pull on the server, refresh.
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
    echo "==> Installing Docker..."
    sudo apt-get update
    sudo apt-get install -y docker.io docker-compose-v2
    sudo systemctl enable --now docker
fi
sudo usermod -aG docker "$USER"

echo "==> Starting landing page..."
sudo docker compose up -d

IP=$(hostname -I | awk '{print $1}')
echo
echo "Landing page: http://${IP}/"
