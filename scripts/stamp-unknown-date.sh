#!/usr/bin/env bash
# Stamp scanned photos of unknown date with a sentinel date in BOTH the EXIF
# data and the filename, so "date unknown" survives in the files themselves.
#   ./stamp-unknown-date.sh <folder> [YYYY-MM-DD] [--apply]
# Default date: 1970-01-01. Dry run unless --apply.
#
# Run this against SOURCE folders (e.g. on the USB drive) — NEVER against
# /srv/data/immich/library, which Immich manages by path and content hash.
# For photos already imported, set the date in Immich separately with
# redate-album.py. Re-importing stamped files without first deleting the
# old assets in Immich creates duplicates (the stamp changes the hash).
#
# EXIF time is set to noon, not midnight — midnight UTC rolls back to the
# previous day in western timezones. Renames prefix the sentinel
# (photo3.jpg -> 1970_01_01_photo3.jpg); already-prefixed files are skipped,
# so re-running is safe.
set -euo pipefail

FOLDER=""
DATE="1970-01-01"
APPLY=false
for arg in "$@"; do
    case "$arg" in
        --apply) APPLY=true ;;
        [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) DATE=$arg ;;
        *) FOLDER=$arg ;;
    esac
done
[ -n "$FOLDER" ] && [ -d "$FOLDER" ] || {
    echo "Usage: $0 <folder> [YYYY-MM-DD] [--apply]" >&2; exit 1; }

if ! command -v exiftool >/dev/null 2>&1; then
    echo "==> Installing exiftool..."
    sudo apt-get update
    sudo apt-get install -y libimage-exiftool-perl
fi

PREFIX=${DATE//-/_}
EXIF_DATE="${DATE//-/:} 12:00:00"
count=0

while IFS= read -r -d '' f; do
    base=$(basename "$f")
    case "$base" in "$PREFIX"_*) continue ;; esac
    echo "$base -> ${PREFIX}_${base}"
    if $APPLY; then
        exiftool -q -overwrite_original -AllDates="$EXIF_DATE" "$f"
        mv -n "$f" "$(dirname "$f")/${PREFIX}_${base}"
    fi
    count=$((count + 1))
done < <(find "$FOLDER" -type f \( -iname '*.jpg' -o -iname '*.jpeg' \
    -o -iname '*.png' -o -iname '*.tif' -o -iname '*.tiff' \
    -o -iname '*.heic' \) -print0)

echo
if $APPLY; then
    echo "Stamped $count file(s) with $EXIF_DATE (EXIF AllDates) and renamed."
else
    echo "Dry run — $count file(s) would be stamped. Re-run with --apply."
fi
