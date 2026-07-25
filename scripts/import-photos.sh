#!/usr/bin/env bash
# Bulk-import photos into Immich as fully managed assets (not an external
# library), using the official Immich CLI via Docker.
#   ./import-photos.sh [source-dir]     # default /mnt/usb
# Re-runs are safe: already-imported files are skipped by content hash.
# Each photo's parent folder name becomes an Immich album (--album), so
# album folders on the source drive carry over. Loose files directly in the
# source folder land in an album named after the source folder itself.
#
# Before the FIRST import:
#   - enable the storage template (Administration > Settings > Storage
#     Template) so files land as library/<user>/YYYY/MM/<original name>
#   - create an API key (avatar > Account Settings > API Keys); this script
#     prompts for it once and stores it in ~/.config/immich/env (chmod 600)
set -euo pipefail

SOURCE=${1:-/mnt/usb}
[ -d "$SOURCE" ] || { echo "$SOURCE does not exist." >&2; exit 1; }

ENV_FILE="$HOME/.config/immich/env"
if [ ! -f "$ENV_FILE" ]; then
    read -rsp "Paste Immich API key (input hidden): " KEY; echo
    [ -n "$KEY" ] || { echo "No key entered." >&2; exit 1; }
    mkdir -p "$(dirname "$ENV_FILE")"
    umask 077
    printf 'IMMICH_API_KEY=%s\n' "$KEY" > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
fi
. "$ENV_FILE"

# The import copies everything into /srv/data/immich — check it fits.
echo "==> Checking free space (sizing $SOURCE)..."
need_k=$(sudo du -sk "$SOURCE" | awk '{print $1}')
avail_k=$(df -k --output=avail /srv/data | tail -1 | tr -d ' ')
if [ "$avail_k" -lt "$need_k" ]; then
    echo "Not enough space on /srv/data: need ~$((need_k / 1024 / 1024))G, have $((avail_k / 1024 / 1024))G." >&2
    echo "If the old /srv/data/Pictures copy is still there, delete it first — the USB is the original." >&2
    exit 1
fi

echo "==> Importing $SOURCE into Immich (duplicates skipped by hash)..."
# mounted under its own name so --album maps loose root files to the source
# folder's name (not "import")
sudo docker run --rm --network host \
    -v "$SOURCE":"/import/$(basename "$SOURCE")":ro \
    -e IMMICH_INSTANCE_URL=http://localhost:2283/api \
    -e IMMICH_API_KEY="$IMMICH_API_KEY" \
    ghcr.io/immich-app/immich-cli:latest \
    upload --recursive --album /import

echo
echo "Done. Spot-check the timeline in the web UI, then keep the USB as the"
echo "dated offline backup."
