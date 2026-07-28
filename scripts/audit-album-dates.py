#!/usr/bin/env python3
"""Read-only audit: compare each album's name-encoded date against the dates
of the assets inside it. Changes nothing — produces a worklist for manual
review (which albums to trust, which to redate, which to inspect).

    ./audit-album-dates.py                 # summary to terminal +
                                           # full CSV to ~/album-date-audit.csv

Albums whose names start with YYYY-MM-DD (or YYYY-MM, or a bare YYYY) are
checked against that date; other albums are listed with their asset date
range only. "off" = asset more than 3 days outside the album's named
date/month/year.
"""
import csv
import json
import os
import re
import sys
import urllib.request
from datetime import date

API = os.environ.get("IMMICH_URL", "http://localhost:2283/api")
OUT = os.path.expanduser("~/album-date-audit.csv")

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


def get_album_assets(album_id):
    """Album detail embeds assets in some Immich versions but not others —
    fall back to a search filtered by album id (same fix as redate-album)."""
    try:
        assets = req("GET", f"/albums/{album_id}?withoutAssets=false").get("assets", [])
    except ApiError:
        assets = []
    if assets:
        return assets
    out, page = [], 1
    while page:
        res = None
        for p in ("/search/metadata", "/search/assets"):
            try:
                res = req("POST", p, {"albumIds": [album_id],
                                      "page": int(page), "size": 250})
                break
            except ApiError:
                continue
        if res is None:
            return out
        chunk = res["assets"]
        out.extend(chunk["items"])
        page = chunk.get("nextPage")
    return out


def album_date(name):
    """Find a date anywhere in the album name — works for both
    '2004-01-29 Mattawa' and 'Mattawa 2004-01-29' styles."""
    name = name or ""
    m = re.search(r"\b((?:19|20)\d{2})[-_.](\d{1,2})[-_.](\d{1,2})\b", name)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return (y, mo, d)
    m = re.search(r"\b((?:19|20)\d{2})[-_.](\d{1,2})\b", name)
    if m and 1 <= int(m.group(2)) <= 12:
        return (int(m.group(1)), int(m.group(2)), None)
    m = re.search(r"\b((?:19|20)\d{2})\b", name)
    if m:
        return (int(m.group(1)), None, None)
    return None


def days_off(asset_date, ymd):
    y, mo, d = ymd
    try:
        if d:
            target = date(y, mo, d)
            return abs((asset_date - target).days)
        if mo:
            lo, hi = date(y, mo, 1), date(y + (mo == 12), (mo % 12) + 1, 1)
        else:
            lo, hi = date(y, 1, 1), date(y + 1, 1, 1)
    except ValueError:
        return None
    if lo <= asset_date < hi:
        return 0
    return min(abs((asset_date - lo).days), abs((asset_date - hi).days))


albums = req("GET", "/albums")
if isinstance(albums, dict):
    albums = albums.get("albums", [])
print(f"{len(albums)} albums; fetching assets (may take a few minutes)...")

rows = []
for i, album in enumerate(albums, 1):
    name = album.get("albumName", "?")
    assets = get_album_assets(album["id"])
    dates = []
    for a in assets:
        s = (a.get("localDateTime") or a.get("fileCreatedAt") or "")[:10]
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            dates.append(date(*(int(g) for g in m.groups())))
    ymd = album_date(name)
    off = None
    if ymd and dates:
        offs = [days_off(dd, ymd) for dd in dates]
        off = sum(1 for o in offs if o is not None and o > 3)
    rows.append({
        "album": name,
        "assets": len(assets),
        "name_date": ("-".join(str(x) for x in ymd if x) if ymd else ""),
        "assets_off": ("" if off is None else off),
        "min_date": min(dates).isoformat() if dates else "",
        "max_date": max(dates).isoformat() if dates else "",
    })
    if i % 100 == 0:
        print(f"  ...{i}/{len(albums)}")

with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

named = [r for r in rows if r["name_date"] != ""]
dated = [r for r in named if r["assets_off"] != ""]
clean = sum(1 for r in dated if r["assets_off"] == 0)
messy = sorted((r for r in dated if r["assets_off"] != 0),
               key=lambda r: -r["assets_off"])
empty = sum(1 for r in rows if r["assets"] == 0)

print(f"\n{len(rows)} albums audited; {len(named)} have a date in their name; "
      f"{len(dated)} of those comparable (assets found); {empty} returned no assets.")
print(f"Consistent with their name-date (±3 days): {clean}")
print(f"\nWorst offenders (assets off vs name-date):")
for r in messy[:20]:
    print(f"  {r['assets_off']:>4}/{r['assets']:<4} off  {r['album']}"
          f"  (assets span {r['min_date']}..{r['max_date']})")
if len(messy) > 20:
    print(f"  ... and {len(messy) - 20} more")
print(f"\nFull report: {OUT}")
print('Fix a specific album: ./scripts/redate-album.py "ALBUM" YYYY-MM-DD --apply')
