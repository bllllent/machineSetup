# TODO

## Game Time + ntfy — pick up here (state as of 2026-10-06)

What's running: Game Time at http://192.168.0.190:8085 (live against the UDM, profile "Blake" = his 3 BLOCK rules), ntfy at http://192.168.0.190:8090, both LAN/VPN only. Code + docs: `gametime/README.md`, `ntfy/`, README sections 15–16.

1. **Subscribe the phone to ntfy** — ntfy app → + → "Use another server":
   ```
   Server:  http://192.168.0.190:8090
   Topic:   gametime-e99e201cd8fe        (also in gametime/.env on the server)
   ```
   You should see the "ntfy is up at 100 Bosworth" test message. Requests then arrive with Allow / Deny buttons.
2. **Change the parent PIN** (still the placeholder `1234`): on the server edit `PARENT_PIN=` in `~/machineSetup/gametime/.env`, then `cd ~/machineSetup/gametime && docker compose up -d`.
3. **Rotate the UniFi API key** (it went through chat): console → Settings → Control Plane → Integrations → delete the old key, create a new one, paste into `UNIFI_API_KEY=` in `gametime/.env`, `docker compose up -d`.
4. Try it for real: Blake asks from his PC/phone, you answer from the push. Watch the log on `/parent`.

## Make Game Time + ntfy reachable away from home

Today: everything is LAN-only by design (README §12: no ports open, UniFi WireGuard for remote). Two ways to change that, pick one:

**Option A — keep it private, just finish the VPN (recommended first step, ~15 min)**
- UniFi console → Settings → VPN → WireGuard: add a profile per phone (yours, Blake's), import with the WireGuard app, enable "on-demand"/always-on.
- Then the existing URLs (`http://192.168.0.190:8085`, ntfy, and `*.100b.amokamok.com` once Caddy is up) just work anywhere, pushes included. Nothing becomes public, nothing else to secure.
- Downside: each phone needs the VPN app and a profile; iPhone pushes still rely on the VPN being up.

**Option B — actually public, via Cloudflare Tunnel (no ports opened, ~1 h)**
- `cloudflared` container on the MS-01 (`tunnel/` stack to write), tunnel to Cloudflare, public hostnames `gametime.amokamok.com` → `localhost:8085` and `ntfy.amokamok.com` → `localhost:8090` (real certs from Cloudflare, no DNS-01 needed).
- Must-haves before flipping it on:
  - Put **Cloudflare Access** (Zero Trust, free tier) in front of `/parent` and `/api/parent/*` — email one-time-code login for the two of you. A 4-digit PIN alone is not enough on the public internet. Leave `/`, `/api/status`, `/api/request` and `/act/*` open (the kid page only *asks*; `/act` links carry their own signed token).
  - ntfy: turn on auth in `ntfy/server.yml` (`auth-default-access: deny-all`, one user for the phone, one write-only token for Game Time) — a public topic name is guessable eventually. Set `base-url` to the public name.
  - Game Time `PUBLIC_URL` → the public name (buttons in pushes must use it); `uvicorn --proxy-headers` already on, so logged IPs stay real.
  - Rate limiting on `/api/login` is a 1 s delay today — add a real lockout (e.g. 10 fails → 15 min) before going public.
- Then iPhone pushes work anywhere without VPN (ntfy.sh still only gets the content-free poke).

**Option C — port forwarding on the UDM.** No: exposes the gateway's attack surface, dynamic IP, and breaks the "nothing exposed" principle for little gain over A/B.

Either way, still deploy Caddy first (section below) so names + HTTPS exist on the LAN; B builds on it.

## DNS + HTTPS (Cloudflare + Caddy proxy)

1. **Create a Cloudflare API token** (dashboard → My Profile → API Tokens → Create Token):
   - "Edit zone DNS" template, scoped to `amokamok.com`
   - Also add permission Zone → Zone → Read
   - Copy the token (shown once)
2. On the server:
   ```
   cd ~/machineSetup && git pull
   ./proxy/setup.sh        # paste token; creates DNS records, builds Caddy (few min), replaces nginx landing
   ```
3. Verify the padlock: https://100b.amokamok.com and https://immich.100b.amokamok.com
   (cert issuance takes ~a minute after start; `sudo docker logs caddy` if not)
4. Point the Immich mobile app / bookmarks at `https://immich.100b.amokamok.com`

## Photo memories digest — blocked on Google SMTP

1. **Create a Google App Password** (the SMTP login — regular password won't work):
   - Google Account → Security → 2-Step Verification (must be on) → App passwords
   - Create one named `photo-digest`, copy the 16-character password
2. On the server:
   ```
   cd ~/machineSetup && git pull
   ./automations/photo-digest/setup.sh        # paste app password at the SMTP prompt
   ```
3. Check the timer fires at a sane local hour — `timedatectl`; if the server is on UTC:
   ```
   sudo timedatectl set-timezone America/Los_Angeles
   ```
4. Test:
   ```
   ./automations/photo-digest/photo_digest.py --dry-run   # no email
   ./automations/photo-digest/photo_digest.py             # real send
   ```

## Photo date cleanup — PAUSED for manual review (filenames often wrong; album folders more accurate)

State: 363 filename-based date fixes applied (Immich DB only). Timezone-shift batch NOT applied. **No sidecars written yet — do not run `sync-dates-to-sidecars.py --apply` until review is done** (it fossilizes Immich's current beliefs to disk).

1. Review worklist: `./scripts/audit-album-dates.py` → summary + `~/album-date-audit.csv`
2. Fix albums where the folder name is the truth: `./scripts/redate-album.py "ALBUM" YYYY-MM-DD --apply`
3. Manual UI edits for the rest
4. When satisfied: `./scripts/fix-dates-from-filenames.py` dry run (timezone batch — review whether filenames are trustworthy enough), then `./scripts/sync-dates-to-sidecars.py --apply` to persist everything to disk
5. One-off to eyeball: `20210126_201442.avi` (filename is digitization date; content may be 2008)

## Parked / future

- Revisit backups as a whole (photos currently: USB in drawer + Immich daily DB dumps in `/srv/data/immich/backups`) — candidate: `scripts/backup-to-usb.sh`
- Home Assistant: `sudo systemctl enable --now bluetooth` so the Bluetooth integration can use the onboard adapter; add the UniFi Protect integration (needs a local console user, not the API key)
- WireGuard profiles for family phones (UniFi console → Settings → VPN) — see "reachable away from home" Option A above; also makes Immich mobile sync work away from home
- More automations on the photo-digest template: network watchdog, server health reporter
- Identify `middlesea` (Supermicro server) and `thermal-pi` — landing cards if they serve UIs
- Wyze Hub on odd subnet 10.20.10.185 — check in UniFi console
