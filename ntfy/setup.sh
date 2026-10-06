#!/usr/bin/env bash
# Self-hosted ntfy (push notifications) on :8090, LAN/VPN only.
#   - starts the container (message cache in a named Docker volume)
#   - creates a private topic for Game Time, wires it into gametime/.env, restarts Game Time
#   - sends a test push
# Idempotent — re-running keeps the existing topic.
set -euo pipefail
cd "$(dirname "$0")"

LAN_IP=$(hostname -I | awk '{print $1}')
if docker info >/dev/null 2>&1; then DOCKER=docker; else DOCKER="sudo docker"; fi

echo "==> Starting ntfy..."
$DOCKER compose up -d
for _ in $(seq 1 20); do curl -sf "http://localhost:8090/v1/health" >/dev/null && break; sleep 1; done

GT_ENV=../gametime/.env
if [ -f "$GT_ENV" ]; then
    TOPIC=$(grep -E '^NTFY_URL=.+' "$GT_ENV" | sed 's#.*/##' || true)
    if [ -z "$TOPIC" ]; then
        TOPIC="gametime-$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n')"
        if grep -q '^NTFY_URL=' "$GT_ENV"; then
            sed -i "s#^NTFY_URL=.*#NTFY_URL=http://$LAN_IP:8090/$TOPIC#" "$GT_ENV"
        else
            echo "NTFY_URL=http://$LAN_IP:8090/$TOPIC" >> "$GT_ENV"
        fi
        echo "==> Game Time now pushes to topic '$TOPIC'; restarting it..."
        (cd ../gametime && $DOCKER compose up -d)
    fi
else
    TOPIC="test"
fi

curl -s -H "Title: ntfy is up at 100 Bosworth" -d "Subscribe to this topic on your phone and Game Time requests will land here." \
     "http://localhost:8090/$TOPIC" >/dev/null && echo "==> Test push sent to '$TOPIC'."

echo
echo "On the phone: install 'ntfy' (App Store / Play Store) -> + -> 'Use another server'"
echo "  Server:  http://$LAN_IP:8090"
echo "  Topic:   $TOPIC"
echo "Web UI:    http://$LAN_IP:8090   (same topic, for a quick look)"
echo "Phones get pushes at home or on the WireGuard VPN only."
