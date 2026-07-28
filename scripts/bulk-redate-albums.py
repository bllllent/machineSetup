#!/usr/bin/env python3
"""Interactive bulk album redate. Walks albums matching a pattern, proposes
the date parsed from each album's name, and asks y/n per album. A "weeks
worth of photos" album is attributed to its start date — EXCEPT assets whose
on-disk EXIF date (sidecar preferred) is within ±10 days of the target:
those have plausible real dates and are left untouched.

    ./bulk-redate-albums.py "2000*"        # all albums starting with 2000
    ./bulk-redate-albums.py "*"            # everything (still y/n per album)

Per album you can answer:
    y            apply the proposed date
    n / enter    skip this album
    YYYY-MM-DD   use a different date (re-shows the plan, then asks again)
    q            quit

Answers apply IMMEDIATELY (the y is the confirmation — no separate --apply).
Re-dated assets get timestamps in alphabetical filename order, one minute
apart from noon (America/Los_Angeles; spacing shrinks for huge albums), in
both Immich and .xmp sidecars. Originals are never modified. Idempotent:
previously written sidecars count as the on-disk date, so a re-run leaves
finished albums alone.
"""
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

API = os.environ.get("IMMICH_URL", "http://localhost:2283/api")
TZ = ZoneInfo(os.environ.get("PHOTO_TZ", "America/Los_Angeles"))
PREFIXES = {"/data": "/srv/data/immich", "/usr/src/app/upload": "/srv/data/immich"}
KEEP_DAYS = 10

key = os.environ.get("IMMICH_API_KEY")
env_path = os.path.expanduser("~/.config/immich/env")
if not key and os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if line.startswith("IMMICH_API_KEY="):
                key = line.strip().split("=", 1)[1]
if not key:
    sys.exit("No IMMICH_API_KEY found.")

if len(sys.argv) != 2:
    sys.exit('Usage: bulk-redate-albums.py "PATTERN"   (e.g. "2000*")')
pattern = sys.argv[1]


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


def host_path(p):
    for c, h in PREFIXES.items():
        if p and p.startswith(c + "/"):
            return h + p[len(c):]
    return p


def name_date(name):
    """Find a date anywhere in the album name — works for both
    '2004-01-29 Mattawa' and 'Mattawa 2004-01-29' styles."""
    name = name or ""
    m = re.search(r"\b((?:19|20)\d{2})[-_.](\d{1,2})[-_.](\d{1,2})\b", name)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            try:
                return date(y, mo, d)
            except ValueError:
                return date(y, mo, 1)
    m = re.search(r"\b((?:19|20)\d{2})[-_.](\d{1,2})\b", name)
    if m and 1 <= int(m.group(2)) <= 12:
        return date(int(m.group(1)), int(m.group(2)), 1)
    m = re.search(r"\b((?:19|20)\d{2})\b", name)
    if m:
        return date(int(m.group(1)), 1, 1)
    return None


def read_disk_dates(paths):
    """On-disk date per original path (existing sidecar preferred, else the
    file's own EXIF). Uses sudo exiftool — library files are root-owned."""
    out = {}
    CHUNK = 400
    for i in range(0, len(paths), CHUNK):
        run = subprocess.run(
            ["sudo", "exiftool", "-json", "-fast2", "-m", "-q",
             "-DateTimeOriginal", "-CreateDate", "-d", "%Y-%m-%d",
             "-srcfile", "%d%f.%e.xmp", "-srcfile", "@", *paths[i:i + CHUNK]],
            capture_output=True, text=True)
        try:
            data = json.loads(run.stdout or "[]")
        except json.JSONDecodeError:
            data = []
        for entry in data:
            src = entry.get("SourceFile", "")
            orig = src[:-4] if src.endswith(".xmp") else src
            s = entry.get("DateTimeOriginal") or entry.get("CreateDate") or ""
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
            out[orig] = date(*(int(g) for g in m.groups())) if m else None
    return out


def plan(assets, disk, target):
    keep, reseq = [], []
    for a in assets:
        dd = disk.get(host_path(a.get("originalPath") or ""))
        if dd and abs((dd - target).days) <= KEEP_DAYS:
            keep.append(a)
        else:
            reseq.append(a)
    return keep, reseq


def write_sidecars(jobs):
    """Write .xmp sidecars for [(host_path, 'YYYY:MM:DD HH:MM:SS')]. Dedupes,
    removes empty husk sidecars (leftovers of interrupted writes confuse
    exiftool), and tolerates per-file failures instead of crashing."""
    seen, uniq = set(), []
    for hp, dtv in jobs:
        if hp not in seen:
            seen.add(hp)
            uniq.append((hp, dtv))
    for hp, _ in uniq:
        sc = hp + ".xmp"
        try:
            if os.path.exists(sc) and os.path.getsize(sc) == 0:
                subprocess.run(["sudo", "rm", "-f", sc], check=True)
        except OSError:
            pass
    with tempfile.NamedTemporaryFile("w", suffix=".args", delete=False) as f:
        for hp, dtv in uniq:
            f.write("-q\n-m\n-overwrite_original\n-srcfile\n%d%f.%e.xmp\n")
            f.write(f"-XMP:DateTimeOriginal={dtv}\n{hp}\n-execute\n")
        argfile = f.name
    os.chmod(argfile, 0o644)
    try:
        run = subprocess.run(["sudo", "exiftool", "-@", argfile],
                             capture_output=True, text=True)
    finally:
        os.unlink(argfile)
    if run.returncode != 0:
        errs = [l for l in (run.stderr or "").splitlines() if l.strip()]
        print("    WARNING: some sidecars failed (Immich itself was updated; "
              "re-running the album retries them):")
        for l in errs[:5]:
            print(f"      {l}")


def apply_album(assets, disk, target):
    assets = sorted(assets, key=lambda a: (a.get("originalFileName") or "").lower())
    keep, _ = plan(assets, disk, target)
    keep_ids = {a["id"] for a in keep}
    base = datetime(target.year, target.month, target.day, 12, 0, 0, tzinfo=TZ)
    window = 11 * 3600 + 59 * 60
    step = 60 if len(assets) * 60 <= window else max(1, window // len(assets))
    sidecars = []
    changed = 0
    for i, a in enumerate(assets):
        if a["id"] in keep_ids:
            continue
        dt_i = base + timedelta(seconds=i * step)
        req("PUT", f"/assets/{a['id']}",
            {"dateTimeOriginal": dt_i.isoformat(timespec="milliseconds")})
        hp = host_path(a.get("originalPath") or "")
        if hp:
            sidecars.append((hp, f"{dt_i:%Y:%m:%d %H:%M:%S}"))
        changed += 1
    if sidecars:
        write_sidecars(sidecars)
    return changed


if subprocess.run(["which", "exiftool"], capture_output=True).returncode != 0:
    subprocess.run(["sudo", "apt-get", "install", "-y", "libimage-exiftool-perl"],
                   check=True)

albums = req("GET", "/albums")
if isinstance(albums, dict):
    albums = albums.get("albums", [])
matches = sorted((a for a in albums
                  if fnmatch.fnmatchcase(a.get("albumName", "").lower(),
                                         pattern.lower())),
                 key=lambda a: a.get("albumName", ""))
if not matches:
    sys.exit(f'No albums match "{pattern}".')
print(f'{len(matches)} album(s) match "{pattern}". Answers apply immediately.\n')

applied = skipped = clean = 0
for album in matches:
    name = album.get("albumName", "?")
    assets = get_album_assets(album["id"])
    if not assets:
        print(f"--- {name}: no assets, skipping")
        continue
    paths = [host_path(a.get("originalPath") or "") for a in assets]
    disk = read_disk_dates([p for p in paths if p])
    target = name_date(name)

    if target:
        _, reseq0 = plan(assets, disk, target)
        if not reseq0:
            print(f"--- {name}: re-date 0 — already clean, skipping")
            clean += 1
            continue

    while True:
        if target:
            keep, reseq = plan(assets, disk, target)
            print(f"--- {name}  ({len(assets)} assets)")
            print(f"    target {target}: re-date {len(reseq)}, keep real EXIF "
                  f"(within ±{KEEP_DAYS}d): {len(keep)}")
            for a in reseq[:3]:
                print(f"      re-date: {a.get('originalFileName')}")
            for a in keep[:3]:
                dd = disk.get(host_path(a.get("originalPath") or ""))
                print(f"      keep:    {a.get('originalFileName')} ({dd})")
        else:
            print(f"--- {name}  ({len(assets)} assets) — no date in album name")
        ans = input("    [y]=apply  [n/enter]=skip  YYYY-MM-DD=other date  [q]=quit: ").strip()
        if ans.lower() == "q":
            print(f"\nDone: {applied} applied, {skipped} skipped, "
                  f"{clean} already clean.")
            sys.exit(0)
        if ans == "" or ans.lower() == "n":
            skipped += 1
            break
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ans):
            try:
                target = date(*(int(x) for x in ans.split("-")))
            except ValueError:
                print("    Not a real date.")
            continue
        if ans.lower() == "y" and target:
            n = apply_album(assets, disk, target)
            print(f"    applied — {n} re-dated.\n")
            applied += 1
            break
        print("    Answer y, n, q, or a YYYY-MM-DD date.")

print(f"\nDone: {applied} applied, {skipped} skipped, {clean} already clean.")
