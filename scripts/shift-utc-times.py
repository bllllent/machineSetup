#!/usr/bin/env python3
"""Fix assets whose displayed time is a UTC wall-clock (imported while the
server ran UTC, date derived from file mtime): reinterpret the stored
instant in America/Los_Angeles. NOT a blanket shift — DST is handled
per-asset by the timezone database (-8 in winter, -7 in summer).

Only assets that are safe to shift are touched:
  - no date on disk (no EXIF, no sidecar) — i.e. the mtime-fallback crowd.
    Assets with real EXIF already show correct local time and are skipped.
  - not already timezone-corrected in Immich (exif timeZone unset/UTC) —
    earlier fixes wrote explicit offsets and are skipped.

    ./shift-utc-times.py            # dry run
    ./shift-utc-times.py --apply    # update the Immich DB

Writes the Immich DB only — run sync-dates-to-sidecars.py afterwards to
persist to disk. Idempotent: shifted assets carry an offset and are skipped
on re-runs.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

API = os.environ.get("IMMICH_URL", "http://localhost:2283/api")
TZ = ZoneInfo(os.environ.get("PHOTO_TZ", "America/Los_Angeles"))
PREFIXES = {"/data": "/srv/data/immich", "/usr/src/app/upload": "/srv/data/immich"}
APPLY = "--apply" in sys.argv

key = os.environ.get("IMMICH_API_KEY")
env_path = os.path.expanduser("~/.config/immich/env")
if not key and os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if line.startswith("IMMICH_API_KEY="):
                key = line.strip().split("=", 1)[1]
if not key:
    sys.exit("No IMMICH_API_KEY found.")


class ApiError(Exception):
    pass


def req(method, path, body=None):
    r = urllib.request.Request(API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"x-api-key": key, "Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read() or "{}")
    except urllib.error.HTTPError as e:
        raise ApiError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from None


def search(body):
    last = None
    for path in ("/search/metadata", "/search/assets"):
        try:
            return req("POST", path, body)
        except ApiError as e:
            last = e
    raise last


def host_path(p):
    for c, h in PREFIXES.items():
        if p and p.startswith(c + "/"):
            return h + p[len(c):]
    return p


def tz_corrected(exif_info):
    tz = ((exif_info or {}).get("timeZone") or "").lower()
    return tz not in ("", "utc", "utc+0", "utc+00:00", "z", "+00:00")


print("==> Fetching assets from Immich...")
items, page = [], 1  # (asset_id, host_path, localDateTime, filename, tz_done)
while page:
    res = search({"page": int(page), "size": 250, "withExif": True})
    chunk = res["assets"]
    for a in chunk["items"]:
        items.append((a["id"], host_path(a.get("originalPath") or ""),
                      (a.get("localDateTime") or "")[:19],
                      a.get("originalFileName") or "?",
                      tz_corrected(a.get("exifInfo"))))
    page = chunk.get("nextPage")
print(f"    {len(items)} assets")

if subprocess.run(["which", "exiftool"], capture_output=True).returncode != 0:
    subprocess.run(["sudo", "apt-get", "install", "-y", "libimage-exiftool-perl"],
                   check=True)

print("==> Reading dates from disk (sudo exiftool, several minutes)...")
has_disk_date = set()
paths = [p for _, p, _, _, _ in items if p]
CHUNK = 500
for i in range(0, len(paths), CHUNK):
    run = subprocess.run(
        ["sudo", "exiftool", "-json", "-fast2", "-m", "-q",
         "-DateTimeOriginal", "-CreateDate",
         "-srcfile", "%d%f.%e.xmp", "-srcfile", "@", *paths[i:i + CHUNK]],
        capture_output=True, text=True)
    try:
        data = json.loads(run.stdout or "[]")
    except json.JSONDecodeError:
        data = []
    for entry in data:
        src = entry.get("SourceFile", "")
        orig = src[:-4] if src.endswith(".xmp") else src
        if entry.get("DateTimeOriginal") or entry.get("CreateDate"):
            has_disk_date.add(orig)
    done = min(i + CHUNK, len(paths))
    if done % 5000 < CHUNK or done == len(paths):
        print(f"    ...{done}/{len(paths)}")

todo, skipped_disk, skipped_tz = [], 0, 0
for asset_id, p, local_s, fname, tz_done in items:
    if p in has_disk_date:
        skipped_disk += 1
        continue
    if tz_done:
        skipped_tz += 1
        continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", local_s)
    if not m:
        continue
    utc_dt = datetime(*(int(g) for g in m.groups()), tzinfo=timezone.utc)
    local_dt = utc_dt.astimezone(TZ)
    todo.append((asset_id, fname, local_s, local_dt))

print(f"\n{len(items)} assets: shift {len(todo)}; skipped {skipped_disk} with a "
      f"date on disk (EXIF/sidecar is their truth); skipped {skipped_tz} "
      f"already timezone-corrected.")
for _, fname, local_s, local_dt in todo[:10]:
    print(f"  {fname}: {local_s} (UTC wall) -> {local_dt:%Y-%m-%d %H:%M:%S %z}")
if len(todo) > 10:
    print(f"  ... and {len(todo) - 10} more")

if not todo:
    sys.exit(0)
if not APPLY:
    print("\nDry run — re-run with --apply to update Immich.")
    sys.exit(0)

print("\n==> Updating Immich...")
for n, (asset_id, _, _, local_dt) in enumerate(todo, 1):
    req("PUT", f"/assets/{asset_id}",
        {"dateTimeOriginal": local_dt.isoformat(timespec="milliseconds")})
    if n % 500 == 0:
        print(f"    ...{n}/{len(todo)}")
print(f"Done — {len(todo)} assets shifted. Run sync-dates-to-sidecars.py to "
      f"persist to disk.")
