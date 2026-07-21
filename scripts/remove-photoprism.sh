#!/usr/bin/env bash
# Remove the retired Photoprism stack from the server: containers, images,
# app data (/srv/photoprism), and the leftover photoprism/ repo dir (its
# untracked .env survives git pull). Does NOT touch the photo library.
set -euo pipefail

echo "==> Stopping and removing Photoprism containers..."
sudo docker compose -p photoprism down --remove-orphans 2>/dev/null \
    || sudo docker rm -f photoprism-photoprism-1 photoprism-mariadb-1 2>/dev/null \
    || true

echo "==> Removing images..."
sudo docker image rm photoprism/photoprism:latest mariadb:11 2>/dev/null || true

echo "==> Removing app data /srv/photoprism..."
sudo rm -rf /srv/photoprism

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
if [ -d "$REPO_DIR/photoprism" ]; then
    echo "==> Removing leftover $REPO_DIR/photoprism (untracked .env)..."
    rm -rf "$REPO_DIR/photoprism"
fi

echo "Done. Photo library (/srv/data) untouched."
