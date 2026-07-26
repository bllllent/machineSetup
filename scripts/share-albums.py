#!/usr/bin/env python3
"""Share ALL albums you own with another Immich user (family member).
Partner sharing covers the timeline but NOT albums — this fills the gap.

    ./share-albums.py user@email            # dry run
    ./share-albums.py user@email --apply    # share
    ./share-albums.py user@email --editor --apply   # let them add/organize

Idempotent: albums already shared with that user are skipped, so re-run it
after importing new folders. Uses the API key from ~/.config/immich/env.
"""
import json
import os
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

args = [a for a in sys.argv[1:] if not a.startswith("--")]
APPLY = "--apply" in sys.argv
ROLE = "editor" if "--editor" in sys.argv else "viewer"
if len(args) != 1:
    sys.exit("Usage: share-albums.py <user-email> [--editor] [--apply]")
target_email = args[0].lower()


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


me = req("GET", "/users/me")
users = req("GET", "/users")
target = next((u for u in users if u.get("email", "").lower() == target_email), None)
if not target:
    sys.exit(f"No user with email {target_email}. Users: "
             + ", ".join(u.get("email", "?") for u in users))
if target["id"] == me["id"]:
    sys.exit("That's you — pick the family member's account.")


def shared_user_ids(album):
    ids = {u.get("user", {}).get("id") for u in album.get("albumUsers", [])}
    ids |= {u.get("id") for u in album.get("sharedUsers", [])}
    ids.discard(None)
    return ids


def share(album_id):
    try:
        req("PUT", f"/albums/{album_id}/users",
            {"albumUsers": [{"userId": target["id"], "role": ROLE}]})
    except ApiError:
        # older API shape
        req("PUT", f"/albums/{album_id}/users", {"sharedUserIds": [target["id"]]})


def owner_id(album):
    return album.get("ownerId") or album.get("owner", {}).get("id")


albums = req("GET", "/albums")
if isinstance(albums, dict):  # some versions wrap the list
    albums = albums.get("albums", [])

print(f'API key authenticates as: {me.get("email", me.get("id"))}')
print(f"Albums visible: {len(albums)}")

mine = [a for a in albums if owner_id(a) == me["id"]]
if not mine and albums:
    # this API version omits owner info from the list response — fetch each
    # album's detail, which carries owner and current shares
    print("List response omits owner info — checking album details "
          f"({len(albums)} albums, may take a minute)...")
    for i, a in enumerate(albums, 1):
        detail = req("GET", f"/albums/{a['id']}")
        if owner_id(detail) == me["id"]:
            a["albumUsers"] = detail.get("albumUsers", [])
            a["sharedUsers"] = detail.get("sharedUsers", [])
            mine.append(a)
        if i % 200 == 0:
            print(f"  ...{i}/{len(albums)}")
    if not mine:
        owners = {owner_id(a) for a in albums}
        by_id = {u["id"]: u.get("email", "?") for u in users}
        print("None are owned by this key's user. Album owners found: "
              + ", ".join(by_id.get(o, str(o)) for o in owners))
        sys.exit("Create the API key from the account that owns the albums, "
                 "or export IMMICH_API_KEY with that account's key.")

todo = [a for a in mine if target["id"] not in shared_user_ids(a)]
done = len(mine) - len(todo)

failed = 0
for album in todo:
    print(f'{"sharing" if APPLY else "would share"}: {album["albumName"]}')
    if APPLY:
        try:
            share(album["id"])
        except ApiError as e:
            failed += 1
            print(f"  FAILED: {e}")

verb = "Shared" if APPLY else "Would share"
print(f"\n{len(mine)} albums owned. {verb} {len(todo) - failed} with {target_email} "
      f"as {ROLE}; already shared: {done}"
      + (f"; FAILED: {failed}" if failed else "") + ".")
if not APPLY and todo:
    print("Dry run — re-run with --apply to share.")
