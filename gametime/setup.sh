#!/usr/bin/env bash
# Game Time: kids request internet time, a parent approves, UniFi blocking
# policies switch off for that long and back on when it runs out.
#   - prompts once for the UniFi API key + a parent PIN (stored in .env, gitignored)
#   - builds and starts the container on :8085, state in /srv/data/gametime
# Idempotent — safe to re-run. `./setup.sh --demo` runs with pretend policies.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
    if [ "${1:-}" = "--demo" ]; then
        read -rp "Parent PIN for the demo [1234]: " PIN; PIN=${PIN:-1234}
        umask 077
        printf 'UNIFI_MOCK=1\nPARENT_PIN=%s\nSECRET=%s\nPUBLIC_URL=http://%s:8085\n' \
            "$PIN" "$SECRET" "$(hostname -I | awk '{print $1}')" > .env
    else
        echo "UniFi API key: open the console (https://192.168.0.1) -> Settings -> Control Plane"
        echo "-> Integrations -> Create API Key (a console-local key; cloud keys don't work)."
        read -rp  "  Gateway URL [https://192.168.0.1]: " HOST; HOST=${HOST:-https://192.168.0.1}
        read -rsp "  UniFi API key (hidden): " KEY; echo
        read -rp  "  Parent PIN: " PIN
        read -rp  "  ntfy topic URL for push notifications (optional, e.g. https://ntfy.sh/gametime-$(head -c4 /dev/urandom | od -An -tx1 | tr -d ' \n')): " NTFY
        [ -n "$KEY" ] && [ -n "$PIN" ] || { echo "API key and PIN are required." >&2; exit 1; }
        umask 077
        cat > .env <<EOT
UNIFI_HOST=$HOST
UNIFI_API_KEY=$KEY
UNIFI_SITE=default
PARENT_PIN=$PIN
SECRET=$SECRET
PUBLIC_URL=http://$(hostname -I | awk '{print $1}'):8085
NTFY_URL=$NTFY
MAX_MINUTES=240
EOT
    fi
    chmod 600 .env
    echo "Stored in $(pwd)/.env"
fi

# sudo only where needed (user may own /srv/data and be in the docker group)
mkdir -p /srv/data/gametime 2>/dev/null || { sudo mkdir -p /srv/data/gametime; sudo chown "$USER:$USER" /srv/data/gametime; }
if docker info >/dev/null 2>&1; then DOCKER=docker; else DOCKER="sudo docker"; fi

echo "==> Building and starting Game Time..."
$DOCKER compose up -d --build

echo
echo "Kid page:     http://$(hostname -I | awk '{print $1}'):8085"
echo "Parent page:  http://$(hostname -I | awk '{print $1}'):8085/parent"
echo "Logs:         sudo docker logs -f gametime"
