#!/usr/bin/env python3
"""Set an approximate GPS location for every photo in an Immich album, in
BOTH places at once:
  - Immich's database via the API (map/search update immediately)
  - an .xmp sidecar next to each original file (industry-standard, read by
    Lightroom/digiKam/PhotoPrism/Immich — survives switching apps)
Originals are NEVER modified, so Immich's content hashes stay valid.

    ./set-album-location.py "ALBUM NAME" --place "Banff, Canada"
    ./set-album-location.py "ALBUM NAME" 51.1784 -115.5708
    ...                                              --apply   # do it

By default only photos WITHOUT GPS are touched (real camera coordinates are
never clobbered by approximate ones); add --force to override all.
--place geocodes via OpenStreetMap Nominatim (one request, no key).
Sidecars are written with sudo exiftool (library files are root-owned).
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

API = os.environ.get("IMMICH_URL", "http://localhost:2283/api")
# container path of the upload library -> host path
PREFIXES = {"/data": "/srv/data/immich", "/usr/src/app/upload": "/srv/data/immich"}

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
FORCE = "--force" in sys.argv
args = [a for a in sys.argv[1:] if a not in ("--apply", "--force")]

USAGE = 'Usage: set-album-location.py "ALBUM" (--place "City, Country" | LAT LON) [--force] [--apply]'
lat = lon = place = None
if len(args) == 3 and args[1] == "--place":
    album_name, place = args[0], args[2]
elif len(args) == 3:
    try:
        album_name, lat, lon = args[0], float(args[1]), float(args[2])
    except ValueError:
        sys.exit(USAGE)
else:
    sys.exit(USAGE)


class ApiError(Exception):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f"HTTP {code}: {detail}")


def req(method, url, body=None, headers=None):
    h = headers or {"x-api-key": key, "Content-Type": "application/json",
                    "Accept": "application/json"}
    r = urllib.request.Request(url if url.startswith("http") else API + url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read() or "{}")
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode(errors="replace")[:500]) from None


if lat is None:
    q = urllib.parse.urlencode({"q": place, "format": "json", "limit": 1})
    res = req("GET", f"https://nominatim.openstreetmap.org/search?{q}", None,
              {"User-Agent": "machineSetup-photo-tools/1.0"})
    if not res:
        sys.exit(f'Could not geocode "{place}".')
    lat, lon = float(res[0]["lat"]), float(res[0]["lon"])
    print(f'"{place}" -> {lat:.4f}, {lon:.4f} ({res[0].get("display_name", "")})')

# ---- find the album (same version-tolerant lookup as redate-album) ----------
albums = req("GET", "/albums")
if isinstance(albums, dict):
    albums = albums.get("albums", [])
matches = [a for a in albums if a.get("albumName") == album_name]
if not matches:
    near = [a["albumName"] for a in albums
            if album_name.lower() in a.get("albumName", "").lower()]
    sys.exit(f'No album named "{album_name}".' + (f" Similar: {near}" if near else ""))
album = matches[0]

detail = req("GET", f"/albums/{album['id']}?withoutAssets=false")
assets = detail.get("assets", [])
if not assets:
    out, page = [], 1
    while page:
        res = None
        for path in ("/search/metadata", "/search/assets"):
            try:
                res = req("POST", path, {"albumIds": [album["id"]],
                                         "page": int(page), "size": 250})
                break
            except ApiError:
                continue
        if res is None:
            sys.exit("Could not list album assets.")
        chunk = res["assets"]
        out.extend(chunk["items"])
        page = chunk.get("nextPage")
    assets = out

# ---- decide which assets to touch -------------------------------------------
todo, has_gps = [], 0
for a in assets:
    info = a.get("exifInfo") or req("GET", f"/assets/{a['id']}").get("exifInfo") or {}
    if info.get("latitude") is not None and not FORCE:
        has_gps += 1
        continue
    todo.append(a)

print(f'Album "{album_name}": {len(assets)} assets; '
      f"{has_gps} already have GPS (skipped); {len(todo)} to set.")
if not todo:
    sys.exit(0)
for a in todo[:8]:
    print(f"  {a.get('originalFileName')}")
if len(todo) > 8:
    print(f"  ... and {len(todo) - 8} more")

if not APPLY:
    print("\nDry run — re-run with --apply to update Immich + write sidecars.")
    sys.exit(0)

# ---- 1) Immich DB via API ----------------------------------------------------
print("==> Updating Immich...")
for a in todo:
    req("PUT", f"/assets/{a['id']}", {"latitude": lat, "longitude": lon})

# ---- 2) .xmp sidecars on disk -------------------------------------------------
def host_path(p):
    for c, h in PREFIXES.items():
        if p and p.startswith(c + "/"):
            return h + p[len(c):]
    return p

paths = []
for a in todo:
    p = a.get("originalPath") or req("GET", f"/assets/{a['id']}").get("originalPath")
    hp = host_path(p)
    if hp:
        paths.append(hp)

if subprocess.run(["which", "exiftool"], capture_output=True).returncode != 0:
    print("Installing exiftool...")
    subprocess.run(["sudo", "apt-get", "install", "-y", "libimage-exiftool-perl"], check=True)

print(f"==> Writing {len(paths)} .xmp sidecars (sudo — library files are root-owned)...")
CHUNK = 400
for i in range(0, len(paths), CHUNK):
    subprocess.run(
        ["sudo", "exiftool", "-q", "-srcfile", "%d%f.%e.xmp", "-overwrite_original",
         f"-XMP:GPSLatitude={lat}", f"-XMP:GPSLongitude={lon}",
         *paths[i:i + CHUNK]],
        check=True)

print(f"\nDone: {len(todo)} assets set to {lat:.4f}, {lon:.4f} in Immich, "
      f"{len(paths)} sidecars written.")
