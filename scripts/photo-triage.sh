#!/usr/bin/env bash
# Find likely screenshots/screen recordings in the photo library and move
# them out for review before the first index. NEVER deletes anything.
#
#   ./photo-triage.sh            # dry run: report candidates, write list
#   ./photo-triage.sh --apply    # move candidates to /srv/data/_triage
#
# Moved files keep their relative paths under the triage dir, so anything
# flagged wrongly can be moved straight back. Review the triage dir by hand
# and delete it yourself when satisfied.
#
# Heuristics:
#   1. filename patterns (Screenshot*, Screen Shot*, Screen Recording*, ...)
#   2. PNGs with no camera Make in EXIF — real photos are JPG/HEIC/RAW;
#      camera-less PNGs are almost always screen grabs or graphics
set -euo pipefail

LIBRARY=${LIBRARY:-/srv/data/Pictures}
TRIAGE=${TRIAGE:-/srv/data/_triage/screenshots}
APPLY=false
[ "${1:-}" = "--apply" ] && APPLY=true

[ -d "$LIBRARY" ] || { echo "$LIBRARY does not exist." >&2; exit 1; }

if ! command -v exiftool >/dev/null 2>&1; then
    echo "==> Installing exiftool..."
    sudo apt-get update
    sudo apt-get install -y libimage-exiftool-perl
fi

matches=$(mktemp)
trap 'rm -f "$matches"' EXIT

echo "==> Scanning filenames..."
find "$LIBRARY" -type f \( \
    -iname 'screenshot*' -o -iname 'screen shot*' -o -iname 'screen_shot*' \
    -o -iname 'screenrecording*' -o -iname 'screen recording*' \
    -o -iname 'screen_recording*' \) >> "$matches"

echo "==> Scanning PNGs for missing camera EXIF (may take a while)..."
exiftool -q -q -m -r -ext png -if 'not $Make' \
    -p '$Directory/$FileName' "$LIBRARY" >> "$matches" || true

sort -u "$matches" -o "$matches"
count=$(wc -l < "$matches" | tr -d ' ')

if [ "$count" -eq 0 ]; then
    echo "No screenshot candidates found."
    exit 0
fi

mkdir -p "$(dirname "$TRIAGE")"
listfile="$(dirname "$TRIAGE")/screenshot-candidates.txt"
cp "$matches" "$listfile"

echo
echo "Found $count candidate(s). Full list: $listfile"
echo "Sample:"
head -n 10 "$matches" | sed 's/^/  /'
[ "$count" -gt 10 ] && echo "  ..."

if ! $APPLY; then
    echo
    echo "Dry run — nothing moved. Review the list, then re-run with --apply."
    exit 0
fi

echo
echo "==> Moving candidates to $TRIAGE (relative paths preserved)..."
while IFS= read -r f; do
    rel=${f#"$LIBRARY"/}
    dest="$TRIAGE/$rel"
    mkdir -p "$(dirname "$dest")"
    mv -n "$f" "$dest"
done < "$matches"

echo "Done. Review $TRIAGE and delete it yourself when satisfied."
echo "To restore something: mv it back to $LIBRARY/<same relative path>."
