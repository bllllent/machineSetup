#!/usr/bin/env bash
# Photoprism setup for the MS-01. Idempotent — safe to re-run.
#   - installs Docker if missing
#   - creates /srv/photos (originals) and /srv/photoprism (app data)
#   - generates .env with random passwords on first run (gitignored)
#   - moves photos offloaded to ~/photos into /srv/photos
#   - starts the stack and prints the URL + login
set -euo pipefail

cd "$(dirname "$0")"

PHOTOS_DIR=/srv/photos
APP_DIR=/srv/photoprism

if ! command -v docker >/dev/null 2>&1; then
    echo "==> Installing Docker..."
    sudo apt-get update
    sudo apt-get install -y docker.io docker-compose-v2
    sudo systemctl enable --now docker
fi
sudo usermod -aG docker "$USER"

echo "==> Creating data directories..."
sudo mkdir -p "$PHOTOS_DIR" "$APP_DIR"/storage "$APP_DIR"/import "$APP_DIR"/mariadb
sudo chown "$USER":"$USER" "$PHOTOS_DIR" "$APP_DIR" "$APP_DIR"/storage "$APP_DIR"/import

if [ ! -f .env ]; then
    echo "==> Generating .env with random passwords..."
    cat > .env <<EOF
PHOTOPRISM_ADMIN_PASSWORD=$(openssl rand -base64 18 | tr -d '/+=')
PHOTOPRISM_DB_PASSWORD=$(openssl rand -base64 18 | tr -d '/+=')
PHOTOPRISM_DB_ROOT_PASSWORD=$(openssl rand -base64 18 | tr -d '/+=')
EOF
    chmod 600 .env
fi

# Photos offloaded from USB land in ~/photos first; sync them into the
# canonical location. Copies, never deletes — clean up ~/photos yourself
# once you've verified the library.
if [ -d "$HOME/photos" ] && [ -n "$(ls -A "$HOME/photos" 2>/dev/null)" ]; then
    echo "==> Syncing ~/photos into $PHOTOS_DIR..."
    rsync -avh "$HOME/photos/" "$PHOTOS_DIR/"
fi

echo "==> Starting Photoprism..."
sudo docker compose up -d

IP=$(hostname -I | awk '{print $1}')
echo
echo "Photoprism is starting at: http://${IP}:2342"
echo "Login: admin / $(grep '^PHOTOPRISM_ADMIN_PASSWORD=' .env | cut -d= -f2-)"
echo "(passwords live in $(pwd)/.env — gitignored, do not commit)"
echo
echo "First login: Library -> Index to scan $PHOTOS_DIR."
