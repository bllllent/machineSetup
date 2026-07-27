# TODO

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
- Home Assistant install (`ha.100b.amokamok.com` + landing card already wired)
- WireGuard profiles for family phones (UniFi console → Settings → VPN) so Immich mobile sync works away from home
- More automations on the photo-digest template: network watchdog, server health reporter
- Identify `middlesea` (Supermicro server) and `thermal-pi` — landing cards if they serve UIs
- Wyze Hub on odd subnet 10.20.10.185 — check in UniFi console
