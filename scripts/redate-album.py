#!/usr/bin/env python3
"""Set the date of every asset in an Immich album (e.g. scanned/digitized
photos whose file metadata is meaningless but whose album says when).

    ./redate-album.py "ALBUM NAME" YYYY-MM-DD            # dry run
    ./redate-album.py "ALBUM NAME" YYYY-MM-DD --apply    # actually update

Times are assigned starting at 12:00:00, one second apart in the assets'
current order, so the album keeps a stable sort instead of 400 identical
timestamps. Assets already on the target date are left untouched.
Uses the API key stored by import-photos.sh (~/.config/immich/env).
"""
import json
import os
import re
import sys
import urllib.request

API = os.environ.get("IMMICH_URL", "http://localhost:2283/api")

key = os.environ.get("IMMICH_API_KEY")
env_path = os.path.expanduser("~/.config/immich/env")
if not key and os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if line.startswith("IMMICH_API_KEY="):
                key = line.strip().split("=", 1)[1]
if not key:
    sys.exit("No IMMICH_API_KEY found (run scripts/import-photos.sh once, or export it).")

args = [a for a in sys.argv[1:] if a != "--apply"]
APPLY = "--apply" in sys.argv
if len(args) != 2 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args[1]):
    sys.exit('Usage: redate-album.py "ALBUM NAME" YYYY-MM-DD [--apply]')
album_name, target_date = args


def req(method, path, body=None):
    r = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"x-api-key": key, "Content-Type": "application/json",
                 "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(r) as resp:
            return json.loads(resp.read() or "{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read().decode(errors='replace')}")


albums = req("GET", "/albums")
matches = [a for a in albums if a.get("albumName") == album_name]
if not matches:
    near = [a["albumName"] for a in albums
            if album_name.lower() in a.get("albumName", "").lower()]
    hint = f" Similar: {near}" if near else ""
    sys.exit(f'No album named "{album_name}".{hint}')
if len(matches) > 1:
    sys.exit(f'Multiple albums named "{album_name}" — rename one first.')

assets = req("GET", f"/albums/{matches[0]['id']}").get("assets", [])
assets.sort(key=lambda a: a.get("localDateTime") or a.get("fileCreatedAt") or "")

changed = skipped = 0
for i, asset in enumerate(assets):
    have = (asset.get("localDateTime") or asset.get("fileCreatedAt") or "")[:10]
    if have == target_date:
        skipped += 1
        continue
    hh, rem = divmod(i, 3600)
    mi, ss = divmod(rem, 60)
    new_dt = f"{target_date}T{12 + hh:02d}:{mi:02d}:{ss:02d}.000Z"
    print(f"{asset.get('originalFileName')}: {have or '??'} -> {new_dt[:19]}")
    if APPLY:
        req("PUT", f"/assets/{asset['id']}", {"dateTimeOriginal": new_dt})
    changed += 1

verb = "Updated" if APPLY else "Would update"
print(f"\n{len(assets)} assets in album. {verb} {changed}; already on {target_date}: {skipped}.")
if not APPLY and changed:
    print("Dry run — re-run with --apply to write the changes.")
