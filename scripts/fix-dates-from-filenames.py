#!/usr/bin/env python3
"""Fix Immich asset dates using date-encoding filenames. Old cameras often
wrote no creation metadata, so Immich falls back to file mtime — the
filename is the truth. Supported patterns:

    2010_12_31_2051.mov         YYYY_MM_DD_HHMM
    20030101_175857.jpg         YYYYMMDD_HHMMSS
    IMG_20030101_175857.jpg     IMG/VID/PXL prefix variants

Times are written with an explicit America/Los_Angeles offset (override
with PHOTO_TZ), so near-midnight shots can't drift into the previous day.

Walks every asset via the Immich API, finds filenames matching a pattern,
and where Immich's date disagrees, sets dateTimeOriginal from the filename.

    ./fix-dates-from-filenames.py            # dry run — prints what it would fix
    ./fix-dates-from-filenames.py --apply    # actually update

Idempotent: assets whose date already matches are skipped, so re-running
(e.g. after importing more files) only touches new mismatches.
Uses the API key stored by import-photos.sh (~/.config/immich/env).
Python stdlib only — no packages needed.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

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

APPLY = "--apply" in sys.argv
TZ = ZoneInfo(os.environ.get("PHOTO_TZ", "America/Los_Angeles"))

PATTERNS = [
    re.compile(r"^(\d{4})_(\d{2})_(\d{2})_(\d{2})(\d{2})\.\w+$", re.IGNORECASE),
    re.compile(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.\w+$", re.IGNORECASE),
    re.compile(r"^(?:IMG|VID|PXL)[-_](\d{4})(\d{2})(\d{2})[-_](\d{2})(\d{2})(\d{2})\.\w+$",
               re.IGNORECASE),
]


def date_from_name(name):
    """Parse a filename-encoded local datetime; None if no pattern matches
    or the numbers aren't a plausible real date."""
    for pat in PATTERNS:
        m = pat.match(name or "")
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        y, mo, d, hh, mi = g[:5]
        ss = g[5] if len(g) > 5 else 0
        if not (1980 <= y <= 2035 and 1 <= mo <= 12 and 1 <= d <= 31
                and hh < 24 and mi < 60 and ss < 60):
            return None
        try:
            return datetime(y, mo, d, hh, mi, ss, tzinfo=TZ)
        except ValueError:
            return None
    return None


class ApiError(Exception):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f"HTTP {code}: {detail}")


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
        raise ApiError(e.code, e.read().decode(errors="replace")) from None


# the paginated asset-search endpoint moved between Immich versions
SEARCH_PATHS = ["/search/metadata", "/search/assets"]


def search_page(page):
    last = None
    for path in SEARCH_PATHS:
        try:
            return req("POST", path, {"page": page, "size": 250})
        except ApiError as e:
            last = f"POST {path} -> {e}"
    sys.exit(f"Asset search failed. Server said:\n{last}")


page, checked, mismatched, already_ok = 1, 0, 0, 0
while page:
    result = search_page(int(page))
    assets = result["assets"]
    for asset in assets["items"]:
        checked += 1
        dt = date_from_name(asset.get("originalFileName"))
        if dt is None:
            continue
        want_date = dt.date().isoformat()
        have = (asset.get("localDateTime") or asset.get("fileCreatedAt") or "")
        if have[:10] == want_date:
            already_ok += 1
            continue
        mismatched += 1
        print(f"{asset['originalFileName']}: {have[:10] or '??'} -> "
              f"{want_date} {dt:%H:%M:%S}")
        if APPLY:
            req("PUT", f"/assets/{asset['id']}",
                {"dateTimeOriginal": dt.isoformat(timespec="milliseconds")})
    page = assets.get("nextPage")

verb = "Fixed" if APPLY else "Would fix"
print(f"\nChecked {checked} assets. {verb} {mismatched}; already correct: {already_ok}.")
if not APPLY and mismatched:
    print("Dry run — re-run with --apply to write the changes.")
