#!/usr/bin/env bash
# Remove the retired Ollama + Open WebUI stack from the server, if it was
# ever started: containers, volumes (downloaded models — re-downloadable),
# and images. Safe to run even if the stack never ran.
set -euo pipefail

echo "==> Stopping and removing containers + volumes..."
sudo docker compose -p ollama down -v --remove-orphans 2>/dev/null \
    || sudo docker rm -f ollama open-webui 2>/dev/null \
    || true
sudo docker volume rm ollama_models ollama_open-webui 2>/dev/null || true

echo "==> Removing images..."
sudo docker image rm ollama/ollama:latest ghcr.io/open-webui/open-webui:main 2>/dev/null || true

echo "Done."
