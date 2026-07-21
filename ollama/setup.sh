#!/usr/bin/env bash
# Ollama + Open WebUI setup for the MS-01. Idempotent — safe to re-run.
#   - installs Docker if missing
#   - starts Ollama (API :11434) and Open WebUI (:3000)
#   - pulls the default model, gpt-oss:20b (OpenAI's open-weights model,
#     ~13GB download; MoE, so it runs acceptably on CPU with 32GB RAM)
# Pick a different model:  MODEL=llama3.1:8b ./setup.sh
# Skip the model pull:     MODEL=none ./setup.sh
set -euo pipefail

cd "$(dirname "$0")"

MODEL=${MODEL:-gpt-oss:20b}

if ! command -v docker >/dev/null 2>&1; then
    echo "==> Installing Docker..."
    sudo apt-get update
    sudo apt-get install -y docker.io docker-compose-v2
    sudo systemctl enable --now docker
fi
sudo usermod -aG docker "$USER"

echo "==> Starting Ollama + Open WebUI..."
sudo docker compose up -d

if [ "$MODEL" != "none" ]; then
    echo "==> Pulling $MODEL (large download on first run; instant if present)..."
    sudo docker exec ollama ollama pull "$MODEL"
fi

IP=$(hostname -I | awk '{print $1}')
echo
echo "Open WebUI (chat):        http://${IP}:3000  (first visitor creates the admin account)"
echo "Ollama API:               http://${IP}:11434"
echo "OpenAI-compatible API:    http://${IP}:11434/v1"
echo
echo "More models: sudo docker exec ollama ollama pull <name>"
echo "CPU-friendly picks: llama3.1:8b, qwen2.5:7b, gemma2:9b"
