#!/usr/bin/env python3
"""Daily "on this day" photo memories email.

Finds photos taken on today's month/day in past years (Immich API), asks
OpenAI for a short warm intro, and emails a digest with inline thumbnails.

    ./photo_digest.py              # build and send the email
    ./photo_digest.py --dry-run    # no email: print summary, save HTML preview

Config (all chmod-600 env files, none in the repo):
    ~/.config/immich/env    IMMICH_API_KEY   (created by import-photos.sh)
    ~/.config/openai/env    OPENAI_API_KEY   (created by setup-openai.sh)
    ~/.config/smtp/env      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS,
                            MAIL_FROM, MAIL_TO   (created by setup.sh here)
Runs daily via the systemd timer installed by setup.sh. Sends nothing on
days with no memories. Python stdlib only.
"""
import datetime
import json
import os
import smtplib
import sys
import urllib.request
from email.message import EmailMessage
from email.utils import make_msgid

IMMICH = os.environ.get("IMMICH_URL", "http://localhost:2283/api")
PUBLIC_URL = "https://immich.100b.amokamok.com"
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
MAX_PER_YEAR = 3
MAX_TOTAL = 9
DRY = "--dry-run" in sys.argv


def load_env(path):
    vals = {}
    p = os.path.expanduser(path)
    if os.path.exists(p):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    vals[k] = v
    return vals


IMMICH_KEY = os.environ.get("IMMICH_API_KEY") or load_env("~/.config/immich/env").get("IMMICH_API_KEY")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY") or load_env("~/.config/openai/env").get("OPENAI_API_KEY")
SMTP = load_env("~/.config/smtp/env")

if not IMMICH_KEY:
    sys.exit("No IMMICH_API_KEY (expected in ~/.config/immich/env).")
if not DRY:
    missing = [k for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS",
                           "MAIL_FROM", "MAIL_TO") if not SMTP.get(k)]
    if missing:
        sys.exit(f"~/.config/smtp/env missing {missing} — run setup.sh.")


class ApiError(Exception):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f"HTTP {code}: {detail}")


def http(method, url, body=None, headers=None):
    r = urllib.request.Request(url, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode(errors="replace")[:500]) from None


def immich(method, path, body=None):
    data, _ = http(method, IMMICH + path, body,
                   {"x-api-key": IMMICH_KEY, "Content-Type": "application/json",
                    "Accept": "application/json"})
    return json.loads(data or "{}")


def search(body):
    last = None
    for path in ("/search/metadata", "/search/assets"):
        try:
            return immich("POST", path, body)
        except ApiError as e:
            last = e
    raise last


def thumbnail(asset_id):
    last = None
    for path in (f"/assets/{asset_id}/thumbnail?size=preview",
                 f"/assets/{asset_id}/thumbnail"):
        try:
            return http("GET", IMMICH + path, None, {"x-api-key": IMMICH_KEY})
        except ApiError as e:
            last = e
    raise last


# ---- gather memories -------------------------------------------------------
today = datetime.date.today()
memories = []  # newest year first: [(year, [assets])]
for year in range(today.year - 1, 1969, -1):
    day = f"{year:04d}-{today.month:02d}-{today.day:02d}"
    try:
        res = search({"takenAfter": f"{day}T00:00:00.000Z",
                      "takenBefore": f"{day}T23:59:59.999Z",
                      "withExif": True, "size": 100, "page": 1})
    except ApiError as e:
        sys.exit(f"Immich search failed: {e}")
    items = res.get("assets", {}).get("items", [])
    if items:
        memories.append((year, items))

if not memories:
    print(f"No memories for {today:%m-%d} — nothing to send.")
    sys.exit(0)

total_photos = sum(len(a) for _, a in memories)
print(f"{today}: {total_photos} photos across {len(memories)} year(s): "
      + ", ".join(str(y) for y, _ in memories))

# ---- AI intro ---------------------------------------------------------------
facts = []
for year, assets in memories:
    places = sorted({(a.get("exifInfo") or {}).get("city")
                     for a in assets} - {None, ""})
    facts.append({"year": year, "years_ago": today.year - year,
                  "photo_count": len(assets), "places": places})

intro = "A look back at photos taken on this day over the years."
if OPENAI_KEY:
    try:
        data, _ = http("POST", "https://api.openai.com/v1/chat/completions",
            {"model": MODEL, "messages": [{"role": "user", "content":
                "Write the intro for a family photo-memories email: 2–3 warm,"
                " concise sentences, plain text, at most one emoji. Mention"
                " the standout years/places. Today is "
                f"{today:%B %d, %Y}. The memories: {json.dumps(facts)}"}]},
            {"Authorization": f"Bearer {OPENAI_KEY}",
             "Content-Type": "application/json"})
        intro = json.loads(data)["choices"][0]["message"]["content"].strip()
    except (ApiError, KeyError, json.JSONDecodeError) as e:
        print(f"OpenAI intro failed ({e}) — using fallback intro.", file=sys.stderr)

# ---- build email ------------------------------------------------------------
msg = EmailMessage()
msg["Subject"] = f"On this day at 100 Bosworth — {today:%B %-d}"
msg["From"] = SMTP.get("MAIL_FROM", "photo-digest@localhost")
msg["To"] = SMTP.get("MAIL_TO", "")

parts = [f"<p style='font-size:15px'>{intro}</p>"]
images = []  # (cid, bytes, subtype)
picked = 0
for year, assets in memories:
    ago = today.year - year
    parts.append(f"<h3 style='margin:18px 0 6px'>{year} — "
                 f"{ago} year{'s' if ago != 1 else ''} ago "
                 f"<span style='color:#888;font-weight:normal'>"
                 f"({len(assets)} photo{'s' if len(assets) != 1 else ''})</span></h3>")
    for asset in assets[:MAX_PER_YEAR]:
        if picked >= MAX_TOTAL:
            break
        try:
            img, ctype = thumbnail(asset["id"])
        except ApiError:
            continue
        cid = make_msgid()
        subtype = (ctype.split("/")[1].split(";")[0] if "/" in ctype else "jpeg")
        images.append((cid, img, subtype))
        parts.append(f"<img src='cid:{cid[1:-1]}' width='260' "
                     f"style='border-radius:8px;margin:0 6px 6px 0'>")
        picked += 1

parts.append(f"<p style='margin-top:20px'><a href='{PUBLIC_URL}'>"
             "See everything in Immich →</a></p>")
html = "<div style='font-family:sans-serif;max-width:600px'>" + "".join(parts) + "</div>"

msg.set_content(intro + f"\n\nSee everything: {PUBLIC_URL}")
msg.add_alternative(html, subtype="html")
for cid, img, subtype in images:
    msg.get_payload()[1].add_related(img, maintype="image", subtype=subtype, cid=cid)

if DRY:
    preview = os.path.expanduser("~/photo-digest-preview.html")
    with open(preview, "w") as f:
        f.write(html.replace("cid:", "about:blank#"))
    print(f"Dry run — would email {picked} photos to {SMTP.get('MAIL_TO', '<unset>')}."
          f" Preview (without images): {preview}")
    sys.exit(0)

port = int(SMTP["SMTP_PORT"])
if port == 465:
    server = smtplib.SMTP_SSL(SMTP["SMTP_HOST"], port, timeout=60)
else:
    server = smtplib.SMTP(SMTP["SMTP_HOST"], port, timeout=60)
    server.starttls()
with server:
    server.login(SMTP["SMTP_USER"], SMTP["SMTP_PASS"])
    server.send_message(msg)
print(f"Sent {picked} photos to {SMTP['MAIL_TO']}.")
