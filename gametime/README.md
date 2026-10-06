# Game Time — request internet time, parent approves

Kids with blocked devices open **http://192.168.0.190:8085**, pick how long they
want (30 min / 1 h / 2 h, optional note) and tap. A parent gets a push (ntfy,
optional) or just sees it on **/parent**, approves or denies. On approval the
UniFi firewall policies that block that device are switched **off**; a timer
switches them back **on** when the time runs out. Both pages install to a phone
home screen as an app (Share → Add to Home Screen).

## How it talks to UniFi

One console-local API key (header `X-API-KEY`), two kinds of blocker, both
read-modify-write (fetch the object, flip `enabled`, PUT it back):

- **Traffic rules** (Settings → Policy Engine / Traffic Management: the
  per-device "block internet on a schedule" rules) via the console's own
  `/proxy/network/v2/api/site/default/trafficrules`. This is what the house
  uses today (the "Blake - …" rules).
- **Firewall policies** (zone-based firewall) via Ubiquiti's official
  Integration API `/proxy/network/integration/v1/...` (Network 10.1+; its
  `PATCH` only covers `loggingEnabled`). Skipped automatically while the
  gateway reports the zone-based firewall as not configured, so migrating to
  it later needs no change here.

Nothing is created or deleted; the app only flips `enabled` on rules you pick.
Schedules stay on the rule: disabling a scheduled BLOCK rule opens the device
whatever the clock says, re-enabling hands control back to the schedule.

Create the key in the console: **Settings → Control Plane → Integrations →
Create API Key** (a console-local key; cloud/Site Manager keys are rejected
locally).

## Setup (on the server)

```
cd ~/machineSetup/gametime
./setup.sh            # prompts: API key, parent PIN, optional ntfy topic -> .env (chmod 600, gitignored)
./setup.sh --demo     # or: run with pretend policies, touches nothing
```

Then on `/parent`: unlock with the PIN, **+ New profile** (e.g. "Gaming
PC"), tick the policies that normally block it, save. The kid page now shows
that profile.

## Model

- **Profile** = a name + the rule/policy IDs that *block* it. Granting time
  disables all of them; ending (timer, "Block now", or deleting the profile)
  enables them. Pick the BLOCK rules only; ALLOW windows (dinner, mornings) can
  stay enabled and keep working.
- **Grant** = `until` timestamp per profile, persisted in
  `/srv/data/gametime/state.json`, so a container restart re-asserts a running
  grant and still ends it on time. Extending adds to the remaining time.
- **Request** = pending until approved / denied / cancelled, or expires after 2 h.
  One pending request per profile (a new one replaces it).
- The parent page also shows **every** user-defined policy with a live switch, so
  it doubles as a quick on/off panel for anything else (IoT isolation, etc.).
- "Blocked" / "Open" is computed from the gateway's live rule state **and the
  rules' schedules**: an enabled rule only blocks while its window is running
  (midnight-crossing and back-to-back windows handled), so the kid page shows
  "Open · next block 9:30 PM" or "Blocked until 7:00 AM". Rules flipped by hand
  in the UniFi UI show correctly too.

## Notifications

`NTFY_URL=http://192.168.0.190:8090/<topic>` in `.env` (the self-hosted ntfy in
`../ntfy`, wired automatically by its `setup.sh`; a public `https://ntfy.sh/<topic>`
works too) and the [ntfy](https://ntfy.sh) app on the parent's phone subscribed
to the same server + topic:
every request becomes a push with **buttons** — "Allow 60 min", "Allow 30 min",
"Deny" — that answer it right from the notification. The buttons call
`/act/<request>/<token>/approve|deny` on the server with a per-request signed
token (no login cookie needed, dies once the request is answered), so the phone
must reach the server: at home, or over the WireGuard VPN. Logins and repeated
wrong PINs push too. Without ntfy, just check the parent page (it polls every
10 s). ntfy runs on this server (`../ntfy`), so nothing leaves the house except, for
iPhones, a content-free "new message" poke relayed via ntfy.sh to Apple.

## Security

LAN-only like everything else here (reach it from outside via the UniFi
WireGuard VPN). The kid page is open to anyone on the LAN but can only *ask*.
Parent actions need the PIN; the login cookie is an HMAC of `SECRET`, lasts a
year, and a wrong PIN costs a second (3 s after five failures). Every login and
every wrong attempt is written to the log on the parent page with the device's
IP and type, and pushed via ntfy when configured, so a guessed PIN shows up. The API key is
the real credential: it can change any firewall policy, so `.env` is 0600 and
never in git. The gateway's self-signed certificate is not verified (the API
key is the trust anchor, same LAN).

## Files

- `app.py` — FastAPI: pages, JSON API, scheduler (15 s tick), state file
- `unifi.py` — traffic rules + firewall policies client, `MockUniFi` for demo mode
- `static/` — `index.html` (kid), `parent.html`, `style.css`, PWA manifest
- `setup.sh`, `docker-compose.yml`, `Dockerfile`, `.env.example`

Caddy name (`proxy/Caddyfile`): `https://gametime.100b.amokamok.com` → `:8085`.
