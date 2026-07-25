#!/usr/bin/env python3
"""Fix Immich asset dates using filenames of the form YYYY_MM_DD_HHMM.ext
(e.g. 2010_12_31_2051.mov). Old camera videos often carry no creation
metadata, so Immich falls back to file mtime — the filename is the truth.

Walks every asset via the Immich API, finds filenames matching the pattern,
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
PATTERN = re.compile(r"^(\d{4})_(\d{2})_(\d{2})_(\d{2})(\d{2})\.\w+$", re.IGNORECASE)


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
        m = PATTERN.match(asset.get("originalFileName") or "")
        if not m:
            continue
        y, mo, d, hh, mi = m.groups()
        # reject filenames that only look like dates (e.g. 9999_88_77_9999)
        if not (1980 <= int(y) <= 2035 and 1 <= int(mo) <= 12
                and 1 <= int(d) <= 31 and int(hh) < 24 and int(mi) < 60):
            continue
        want_date = f"{y}-{mo}-{d}"
        have = (asset.get("localDateTime") or asset.get("fileCreatedAt") or "")
        if have[:10] == want_date:
            already_ok += 1
            continue
        mismatched += 1
        print(f"{asset['originalFileName']}: {have[:10] or '??'} -> {want_date} {hh}:{mi}")
        if APPLY:
            req("PUT", f"/assets/{asset['id']}",
                {"dateTimeOriginal": f"{want_date}T{hh}:{mi}:00.000Z"})
    page = assets.get("nextPage")

verb = "Fixed" if APPLY else "Would fix"
print(f"\nChecked {checked} assets. {verb} {mismatched}; already correct: {already_ok}.")
if not APPLY and mismatched:
    print("Dry run — re-run with --apply to write the changes.")
