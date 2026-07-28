#!/usr/bin/env python3
"""Set the date of every asset in an Immich album (e.g. scanned/digitized
photos whose file metadata is meaningless but whose album says when).
Writes BOTH layers: Immich's database via the API, and an .xmp sidecar next
to each changed original (originals never modified — hashes stay valid).

    ./redate-album.py "ALBUM NAME" YYYY-MM-DD            # dry run
    ./redate-album.py "ALBUM NAME" YYYY-MM-DD --apply    # actually update

Assets are processed in ALPHABETICAL filename order and timestamped one
minute apart starting at noon (America/Los_Angeles, override with PHOTO_TZ),
so chronological order matches filename order — right for digitized batches
and camera-counter names. The spacing shrinks automatically for albums too
large to fit noon..midnight at one minute each. Assets already on the target
date keep their existing times (pass --all to re-sequence those too — only
do that when their current times are junk, not real EXIF). Sidecars are
written with sudo exiftool (library files are root-owned).
Uses the API key stored by import-photos.sh (~/.config/immich/env).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("PHOTO_TZ", "America/Los_Angeles"))
# container path of the upload library -> host path
PREFIXES = {"/data": "/srv/data/immich", "/usr/src/app/upload": "/srv/data/immich"}


def host_path(p):
    for c, h in PREFIXES.items():
        if p and p.startswith(c + "/"):
            return h + p[len(c):]
    return p

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

args = [a for a in sys.argv[1:] if a not in ("--apply", "--all")]
APPLY = "--apply" in sys.argv
ALL = "--all" in sys.argv
if len(args) != 2 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args[1]):
    sys.exit('Usage: redate-album.py "ALBUM NAME" YYYY-MM-DD [--all] [--apply]')
album_name, target_date = args


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


def get_album_assets(album):
    """Album responses embed assets in some Immich versions but not others;
    fall back to a search filtered by album id."""
    try:
        assets = req("GET", f"/albums/{album['id']}?withoutAssets=false").get("assets", [])
    except ApiError:
        assets = []
    if assets:
        return assets
    out, page, last = [], 1, None
    while page:
        res = None
        for path in ("/search/metadata", "/search/assets"):
            try:
                res = req("POST", path,
                          {"albumIds": [album["id"]], "page": int(page), "size": 250})
                break
            except ApiError as e:
                last = f"POST {path} -> {e}"
        if res is None:
            sys.exit(f"Could not list album assets. Server said:\n{last}")
        chunk = res["assets"]
        out.extend(chunk["items"])
        page = chunk.get("nextPage")
    return out


try:
    albums = req("GET", "/albums")
except ApiError as e:
    sys.exit(f"GET /albums -> {e}")
matches = [a for a in albums if a.get("albumName") == album_name]
if not matches:
    near = [a["albumName"] for a in albums
            if album_name.lower() in a.get("albumName", "").lower()]
    hint = f" Similar: {near}" if near else ""
    sys.exit(f'No album named "{album_name}".{hint}')
if len(matches) > 1:
    sys.exit(f'Multiple albums named "{album_name}" — rename one first.')

album = matches[0]
print(f'Album "{album["albumName"]}" reports {album.get("assetCount", "?")} assets.')
assets = get_album_assets(album)
assets.sort(key=lambda a: (a.get("originalFileName") or "").lower())

y, mo, d = (int(x) for x in target_date.split("-"))
base = datetime(y, mo, d, 12, 0, 0, tzinfo=TZ)
# one minute apart in filename order; shrink to fit noon..midnight if needed
window = 11 * 3600 + 59 * 60
step = 60 if len(assets) * 60 <= window else max(1, window // len(assets))
if step != 60:
    print(f"Large album: spacing timestamps {step}s apart to fit the day.")

changed = skipped = 0
sidecars = []  # (host path, "YYYY:MM:DD HH:MM:SS")
for i, asset in enumerate(assets):
    have = (asset.get("localDateTime") or asset.get("fileCreatedAt") or "")[:10]
    if have == target_date and not ALL:
        skipped += 1
        continue
    dt_i = base + timedelta(seconds=i * step)
    print(f"{asset.get('originalFileName')}: {have or '??'} -> {dt_i:%Y-%m-%d %H:%M:%S}")
    if APPLY:
        try:
            req("PUT", f"/assets/{asset['id']}",
                {"dateTimeOriginal": dt_i.isoformat(timespec="milliseconds")})
        except ApiError as e:
            sys.exit(f"PUT /assets/{asset['id']} -> {e}")
        path = asset.get("originalPath")
        if not path:
            try:
                path = req("GET", f"/assets/{asset['id']}").get("originalPath")
            except ApiError:
                path = None
        hp = host_path(path)
        if hp:
            sidecars.append((hp, f"{dt_i:%Y:%m:%d %H:%M:%S}"))
    changed += 1

if APPLY and sidecars:
    if subprocess.run(["which", "exiftool"], capture_output=True).returncode != 0:
        print("Installing exiftool...")
        subprocess.run(["sudo", "apt-get", "install", "-y",
                        "libimage-exiftool-perl"], check=True)
    print(f"==> Writing {len(sidecars)} .xmp sidecars (sudo)...")
    with tempfile.NamedTemporaryFile("w", suffix=".args", delete=False) as f:
        for hp, exif_dt in sidecars:
            f.write("-q\n-m\n-overwrite_original\n-srcfile\n%d%f.%e.xmp\n")
            f.write(f"-XMP:DateTimeOriginal={exif_dt}\n{hp}\n-execute\n")
        argfile = f.name
    os.chmod(argfile, 0o644)
    try:
        subprocess.run(["sudo", "exiftool", "-@", argfile], check=True)
    finally:
        os.unlink(argfile)

verb = "Updated" if APPLY else "Would update"
print(f"\n{len(assets)} assets in album. {verb} {changed} (Immich + "
      f"{len(sidecars) if APPLY else 'their'} sidecars); "
      f"already on {target_date}: {skipped}.")
if not APPLY and changed:
    print("Dry run — re-run with --apply to write the changes.")
