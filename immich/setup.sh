#!/usr/bin/env bash
# Immich setup for the MS-01. Idempotent — safe to re-run.
#   - installs Docker if missing
#   - creates /srv/data/immich (uploads) and /srv/immich (app state)
#   - generates .env with a random DB password on first run (gitignored)
#   - starts the stack and prints the URL
# First run in the web UI: create the admin account, then add
# /srv/data/Pictures as an external library (Administration > External
# Libraries) and let it scan.
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
    echo "==> Installing Docker..."
    sudo apt-get update
    sudo apt-get install -y docker.io docker-compose-v2
    sudo systemctl enable --now docker
fi
sudo usermod -aG docker "$USER"

echo "==> Creating data directories..."
sudo mkdir -p /srv/data/immich /srv/immich/postgres /srv/immich/model-cache
sudo chown "$USER":"$USER" /srv/data /srv/data/immich /srv/immich /srv/immich/model-cache

if [ ! -f .env ]; then
    echo "==> Generating .env..."
    sed "s/^DB_PASSWORD=.*/DB_PASSWORD=$(openssl rand -base64 18 | tr -d '/+=')/" .env.example > .env
    chmod 600 .env
fi

echo "==> Starting Immich..."
sudo docker compose up -d

IP=$(hostname -I | awk '{print $1}')
echo
echo "Immich is starting at: http://${IP}:2283"
echo "First visit: create the admin account in the web UI, then add"
echo "/srv/data/Pictures as an external library and let it scan."
echo "(DB password lives in $(pwd)/.env — gitignored, do not commit)"
