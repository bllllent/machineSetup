#!/usr/bin/env python3
"""Persist Immich's dates into .xmp sidecars, so every date correction made
in Immich (redated albums, 1970-01-01 "unknown" sentinels, filename fixes)
survives outside Immich's database. Originals are NEVER modified — hashes
stay valid. Sidecars are the industry-standard carrier (read by Immich,
Lightroom, digiKam, PhotoPrism).

Sweeps the whole library:
  1. every asset's date according to Immich (its database is the truth)
  2. every file's date on disk (existing sidecar preferred, else the file's
     own EXIF) — read in bulk with exiftool
  3. where they disagree by more than ~a day, write the Immich date into a
     .xmp sidecar next to the original

    ./sync-dates-to-sidecars.py            # dry run — report the divergent set
    ./sync-dates-to-sidecars.py --apply    # write the sidecars (sudo exiftool)

Idempotent: sidecars are read back on later runs, so corrected assets drop
out of the divergent set. Differences under 25h are ignored (timezone noise,
not wrong dates). Expect the read phase to take some minutes on a big library.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime

API = os.environ.get("IMMICH_URL", "http://localhost:2283/api")
PREFIXES = {"/data": "/srv/data/immich", "/usr/src/app/upload": "/srv/data/immich"}
TOLERANCE_S = 25 * 3600
APPLY = "--apply" in sys.argv

key = os.environ.get("IMMICH_API_KEY")
env_path = os.path.expanduser("~/.config/immich/env")
if not key and os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if line.startswith("IMMICH_API_KEY="):
                key = line.strip().split("=", 1)[1]
if not key:
    sys.exit("No IMMICH_API_KEY found (run scripts/import-photos.sh once, or export it).")


class ApiError(Exception):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f"HTTP {code}: {detail}")


def req(method, path, body=None):
    r = urllib.request.Request(API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"x-api-key": key, "Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read() or "{}")
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode(errors="replace")[:500]) from None


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


def parse_dt(s):
    if not s:
        return None
    m = re.match(r"(\d{4})\D(\d{2})\D(\d{2})\D(\d{2})\D(\d{2})\D(\d{2})", s)
    if not m:
        return None
    try:
        return datetime(*(int(g) for g in m.groups()))
    except ValueError:
        return None


# ---- 1) Immich's view --------------------------------------------------------
print("==> Fetching assets from Immich...")
items, page = [], 1
while page:
    res = search({"page": int(page), "size": 250, "withExif": True})
    chunk = res["assets"]
    for a in chunk["items"]:
        p = host_path(a.get("originalPath") or "")
        want = (a.get("localDateTime") or "")[:19]
        if p and want:
            items.append((p, want))
    page = chunk.get("nextPage")
print(f"    {len(items)} assets")

# ---- 2) what the files on disk say (sidecar preferred, else EXIF) -------------
if subprocess.run(["which", "exiftool"], capture_output=True).returncode != 0:
    print("Installing exiftool...")
    subprocess.run(["sudo", "apt-get", "install", "-y", "libimage-exiftool-perl"], check=True)

print("==> Reading dates from disk (sudo exiftool, may take several minutes)...")
current = {}
CHUNK = 500
for i in range(0, len(items), CHUNK):
    paths = [p for p, _ in items[i:i + CHUNK]]
    out = subprocess.run(
        ["sudo", "exiftool", "-json", "-fast2", "-m", "-q",
         "-DateTimeOriginal", "-CreateDate", "-d", "%Y-%m-%dT%H:%M:%S",
         "-srcfile", "%d%f.%e.xmp", "-srcfile", "@", *paths],
        capture_output=True, text=True)
    try:
        data = json.loads(out.stdout or "[]")
    except json.JSONDecodeError:
        data = []
    for entry in data:
        src = entry.get("SourceFile", "")
        orig = src[:-4] if src.endswith(".xmp") else src
        current[orig] = entry.get("DateTimeOriginal") or entry.get("CreateDate")
    done = min(i + CHUNK, len(items))
    if done % 5000 < CHUNK or done == len(items):
        print(f"    ...{done}/{len(items)}")

# ---- 3) diff -------------------------------------------------------------------
divergent = []
no_file_date = 0
for p, want_s in items:
    want = parse_dt(want_s)
    if want is None:
        continue
    have = parse_dt(current.get(p))
    if have is None:
        no_file_date += 1
        divergent.append((p, want_s, "no date in file"))
    elif abs((have - want).total_seconds()) > TOLERANCE_S:
        divergent.append((p, want_s, current.get(p)))

print(f"\n{len(items)} assets checked: {len(items) - len(divergent)} already agree "
      f"(±25h), {len(divergent)} divergent ({no_file_date} with no date in the file).")
for p, want_s, have_s in divergent[:10]:
    print(f"  {os.path.basename(p)}: file says {have_s} -> sidecar {want_s}")
if len(divergent) > 10:
    print(f"  ... and {len(divergent) - 10} more")

if not divergent:
    sys.exit(0)
if not APPLY:
    print("\nDry run — re-run with --apply to write the sidecars.")
    sys.exit(0)

# ---- write sidecars in one exiftool process ------------------------------------
print(f"\n==> Writing {len(divergent)} sidecars...")
with tempfile.NamedTemporaryFile("w", suffix=".args", delete=False) as f:
    for p, want_s, _ in divergent:
        exif_dt = want_s[:10].replace("-", ":") + " " + want_s[11:]
        f.write("-q\n-m\n-overwrite_original\n-srcfile\n%d%f.%e.xmp\n")
        f.write(f"-XMP:DateTimeOriginal={exif_dt}\n{p}\n-execute\n")
    argfile = f.name
os.chmod(argfile, 0o644)
try:
    subprocess.run(["sudo", "exiftool", "-@", argfile], check=True)
finally:
    os.unlink(argfile)
print(f"Done — {len(divergent)} sidecars written.")
