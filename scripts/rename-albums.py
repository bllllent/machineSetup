#!/usr/bin/env python3
"""Rename albums from 'YYYY-MM-DD_Description_with_underscores' (or with
spaces) to 'Description YYYY-MM-DD' — description first, date at the end,
underscores become spaces.

    ./rename-albums.py            # dry run — shows every rename
    ./rename-albums.py --apply    # rename via the API

Handles partial leading dates too (YYYY-MM, YYYY). Albums with no leading
date, or that are ONLY a date, are left alone. Renames that would collide
with another album's name are skipped with a warning.
"""
import json
import os
import re
import sys
import urllib.request

API = os.environ.get("IMMICH_URL", "http://localhost:2283/api")
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


def req(method, path, body=None):
    r = urllib.request.Request(API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"x-api-key": key, "Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read() or "{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")


LEAD = re.compile(r"^((?:19|20)\d{2}(?:[-_.]\d{1,2})?(?:[-_.]\d{1,2})?)[ _\-.]+(.+)$")


def new_name(name):
    m = LEAD.match((name or "").strip())
    if not m:
        return None
    datepart, desc = m.groups()
    datepart = datepart.replace("_", "-").replace(".", "-")
    desc = re.sub(r"_+", " ", desc)
    desc = re.sub(r"\s{2,}", " ", desc).strip()
    if not desc:
        return None
    return f"{desc} {datepart}"


albums = req("GET", "/albums")
if isinstance(albums, dict):
    albums = albums.get("albums", [])

taken = {a.get("albumName", "") for a in albums}
renames, skipped_collisions = [], []
for a in albums:
    old = a.get("albumName", "")
    new = new_name(old)
    if not new or new == old:
        continue
    if new in taken:
        skipped_collisions.append((old, new))
        continue
    taken.add(new)
    renames.append((a["id"], old, new))

for _, old, new in renames:
    print(f"{old}\n  -> {new}")
for old, new in skipped_collisions:
    print(f"SKIP (name collision): {old} -> {new}")

print(f"\n{len(albums)} albums; {len(renames)} to rename; "
      f"{len(skipped_collisions)} skipped for collisions; "
      f"{len(albums) - len(renames) - len(skipped_collisions)} unchanged.")

if not renames:
    sys.exit(0)
if not APPLY:
    print("Dry run — re-run with --apply to rename.")
    sys.exit(0)

for album_id, old, new in renames:
    req("PATCH", f"/albums/{album_id}", {"albumName": new})
print(f"Renamed {len(renames)} albums.")
