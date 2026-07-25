#!/usr/bin/env bash
# Caddy reverse proxy for 100 Bosworth: HTTPS names for everything.
#   - prompts once for a Cloudflare API token (stored in .env, gitignored)
#   - upserts DNS: 100b.amokamok.com and *.100b.amokamok.com -> LAN IP
#     (DNS-only / grey cloud — these resolve to a private address)
#   - builds Caddy with the Cloudflare DNS plugin (first build takes minutes)
#   - replaces the old nginx landing container (Caddy serves landing/site/)
# Idempotent — safe to re-run.
set -euo pipefail

cd "$(dirname "$0")"

ZONE=amokamok.com
DOMAIN=100b.$ZONE
LAN_IP=$(hostname -I | awk '{print $1}')

if ! command -v docker >/dev/null 2>&1; then
    echo "==> Installing Docker..."
    sudo apt-get update
    sudo apt-get install -y docker.io docker-compose-v2
    sudo systemctl enable --now docker
fi
sudo usermod -aG docker "$USER"
command -v jq >/dev/null 2>&1 || { sudo apt-get update; sudo apt-get install -y jq; }

if [ ! -f .env ]; then
    echo "Cloudflare token: dashboard -> My Profile -> API Tokens -> Create Token"
    echo "-> 'Edit zone DNS' template scoped to $ZONE, plus Zone -> Zone -> Read."
    read -rsp "Paste Cloudflare API token (input hidden): " TOK; echo
    [ -n "$TOK" ] || { echo "No token entered." >&2; exit 1; }
    umask 077
    printf 'CLOUDFLARE_API_TOKEN=%s\n' "$TOK" > .env
    chmod 600 .env
fi
# shellcheck disable=SC1091
. ./.env

CF=https://api.cloudflare.com/client/v4
auth() { curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" "$@"; }

ZONE_ID=$(auth "$CF/zones?name=$ZONE" | jq -r '.result[0].id // empty')
[ -n "$ZONE_ID" ] || { echo "Zone $ZONE not found — is the domain on Cloudflare and the token scoped to it (incl. Zone Read)?" >&2; exit 1; }

upsert() { # $1=record name
    local name=$1 rid body ok
    rid=$(auth "$CF/zones/$ZONE_ID/dns_records?type=A&per_page=100" \
          | jq -r --arg n "$name" '.result[] | select(.name == $n) | .id' | head -n1)
    body=$(jq -n --arg n "$name" --arg c "$LAN_IP" \
           '{type: "A", name: $n, content: $c, ttl: 300, proxied: false}')
    if [ -n "$rid" ]; then
        ok=$(auth -X PUT "$CF/zones/$ZONE_ID/dns_records/$rid" -d "$body" | jq -r .success)
    else
        ok=$(auth -X POST "$CF/zones/$ZONE_ID/dns_records" -d "$body" | jq -r .success)
    fi
    [ "$ok" = "true" ] || { echo "Failed to upsert DNS record $name" >&2; exit 1; }
    echo "    $name -> $LAN_IP"
}

echo "==> Ensuring DNS records (DNS-only, private IP)..."
upsert "$DOMAIN"
upsert "*.$DOMAIN"

echo "==> Retiring the old nginx landing container (Caddy takes over port 80)..."
sudo docker rm -f landing 2>/dev/null || true

echo "==> Building and starting Caddy (first build compiles the plugin — a few minutes)..."
sudo docker compose up -d --build

echo
echo "Landing:  https://$DOMAIN"
echo "Immich:   https://immich.$DOMAIN"
echo "HA:       https://ha.$DOMAIN   (502 until Home Assistant is installed)"
echo "First cert issuance takes ~a minute after start; check: sudo docker logs caddy"
