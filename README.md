# Minisforum MS-01 — Linux Install Notes

Hardware: Minisforum MS-01 Mini Workstation
OS: Ubuntu Server 26.04 LTS
Purpose: home server running Immich and other Docker services; AI for hobby projects via the hosted OpenAI API

## 1. Create the boot USB (on Mac, command line)

1. Download the Ubuntu Server 26.04 LTS ISO from ubuntu.com/download/server.
2. Insert the USB stick (8GB+, will be erased) and find its disk identifier:
   ```
   diskutil list
   ```
   Match by size (e.g. `/dev/disk4`).
3. Unmount it (don't eject):
   ```
   diskutil unmountDisk /dev/disk4
   ```
4. Write the ISO using the **raw** disk device (`rdisk`, not `disk` — much faster):
   ```
   sudo dd if=~/Downloads/ubuntu-26.04-live-server-amd64.iso of=/dev/rdisk4 bs=1m
   ```
   - No progress bar by default — press **Ctrl+T** during the write to print progress.
5. When it finishes (prints records in/out), eject cleanly:
   ```
   diskutil eject /dev/disk4
   ```

Double-check the disk number before running `dd` — wrong disk = overwritten Mac drive.

Keep this USB drive — reuse it for reinstalls.

## 2. Boot the MS-01 from USB

1. Power on the MS-01.
2. Tap **F7** repeatedly right away → opens the one-time boot menu.
   - **F7 is the key that works.** (Del opens full BIOS setup instead, if needed.)
3. Select the "UEFI: [USB drive name]" entry.
4. Proceed with the Ubuntu Server installer.

### Front port layout
- 1x USB 3.0 (10Gbps) — use this one for the boot drive.
- 2x USB 2.0 (480Mbps) — front, don't use for boot media.
- USB4/USB-C ports are on the rear — avoid for booting installers.

### If it doesn't boot
- Make sure you're mashing **F7** immediately at power-on, not waiting for the Minisforum splash to finish.
- If no boot menu appears at all: enter BIOS with **Del**, disable **Secure Boot** and **Fast Boot**, confirm **Boot Mode** is UEFI.
- If still nothing: re-flash the USB (corrupted ISO/write is a common silent failure) or try a different stick.

## 3. Git + machineSetup repo

On the MS-01 (console/SSH):
```
sudo apt update
sudo apt install -y git
git clone https://github.com/bllllent/machineSetup.git
```
Clones into `~/machineSetup`. This repo is the home for setup scripts/configs going forward — check files in as the stack gets built out.

## 4. Post-install stack

- Docker + Docker Compose for all services (Immich, etc.) on one flat host.
- No discrete GPU on the MS-01 — AI for projects uses the hosted OpenAI API (section 8) rather than local models.

> **Script reference:** every script in `scripts/` is catalogued in [scripts/README.md](scripts/README.md) — conventions, usage, and what each one does.

## 5. Storage layout

Two 1TB NVMe drives:

- **YMTC (`nvme0n1`) — OS drive:** the system, apps, and Docker images, all on `/` (grown to the full ~950G — the installer only allocated 100G).
- **WD Blue SN5100 — data drive, mounted at `/srv`:** personal media under `/srv/data/` — the Immich-managed photo library (`/srv/data/immich`), later `Music`, … — and regenerable app state (`/srv/immich`). Back up `/srv/data` wholesale; app state can always be rebuilt.

Backups: external USB drives (photos are on a single internal disk — keep a current copy elsewhere).

One-time setup, in order:
```
./scripts/setup-data-drive.sh      # format the blank WD Blue, mount at /srv (asks for confirmation)
./scripts/setup-os-drive-space.sh  # grow / to the full OS drive (live, non-destructive)
```

Both scripts are idempotent. `setup-data-drive.sh` finds the WD Blue by model name (nvme numbering can swap between boots), refuses to touch any drive with partitions or filesystem signatures, and mounts by UUID with `nofail`. Run these **before** the photo app setup so the photos land on the data drive.

Photos are fully Immich-managed (imported, not an external library) so the app can delete/trash/dedupe. The storage template keeps the on-disk layout portable — `library/<user>/YYYY/MM/<original filename>` — so a future app swap is still just files (as happened with Photoprism → Immich; `scripts/remove-photoprism.sh` cleans that retired stack off the server). The source USB drive is kept as the dated offline backup of the original folder structure.

## 6. Photo triage (optional, before import)

Screenshots/screen recordings can be cleaned out of the source before importing:

```
LIBRARY=/mnt/usb ./scripts/photo-triage.sh            # dry run — reports candidates
LIBRARY=/mnt/usb ./scripts/photo-triage.sh --apply    # moves them to /srv/data/_triage
```

Heuristics: screenshot-style filenames, plus PNGs with no camera EXIF. Nothing is ever deleted — candidates move to the triage dir with relative paths preserved, so false positives can be moved straight back. Note `--apply` moves files *off the USB source*.

Alternatively skip this and clean up in-app after import (search + bulk delete, Utilities → Duplicates) — possible because the library is imported, not external.

Geolocation grouping is *not* needed as pre-processing: Immich reverse-geocodes on import (offline) and provides map view and search-by-place.

## 7. Immich

Deploy:
```
./immich/setup.sh
```
Then in the web UI at `http://<server-ip>:2283`:
1. Create the admin account (first visitor becomes admin).
2. **Before importing:** Administration → Settings → Storage Template → enable, so imports land as `/srv/data/immich/library/<user>/YYYY/MM/<original filename>`.
3. Create an API key (avatar → Account Settings → API Keys), then bulk-import:
   ```
   ./scripts/import-photos.sh /mnt/usb
   ```
   Album folders on the drive become Immich albums (parent folder name). Re-runs are safe — already-imported files are skipped by content hash.
4. After the import: fix assets whose date metadata was missing (old videos fall back to file mtime) but whose filename encodes the real date (`YYYY_MM_DD_HHMM.ext`):
   ```
   ./scripts/fix-dates-from-filenames.py            # dry run
   ./scripts/fix-dates-from-filenames.py --apply
   ```
   Idempotent — safe to re-run after later imports.
   For albums whose *name* says when (scans, digitized film), redate the whole album:
   ```
   ./scripts/redate-album.py "1999-07-07 Hal's Birthday" 1999-07-07 --apply
   ```
   Scans with *no* known date use a sentinel — `1970-01-01` means "date unknown":
   ```
   ./scripts/redate-album.py "Early_years" 1970-01-01 --apply
   ```
   (Immich's database is the source of truth — filenames/EXIF are deliberately not rewritten. `scripts/stamp-unknown-date.sh` exists for stamping *pre-import* source folders, but changes file hashes: never re-import a stamped folder without deleting its assets from Immich first.)

   Approximate GPS for a whole album (e.g. scans from a trip), written to Immich **and** `.xmp` sidecars next to the originals so it survives an app change (originals untouched, hashes stay valid; photos that already have real GPS are skipped unless `--force`):
   ```
   ./scripts/set-album-location.py "2009-11 Banff" --place "Banff, Canada" --apply
   ```
   Persist all Immich date corrections into sidecars the same way (whole-library sweep; only writes where the file on disk disagrees with Immich by >25h — re-run after future date fixes):
   ```
   ./scripts/sync-dates-to-sidecars.py            # dry run
   ./scripts/sync-dates-to-sidecars.py --apply
   ```
5. Optional: Administration → Settings → Video Transcoding → enable Quick Sync (the iGPU is already passed through).
6. Install the Immich mobile app and point it at the server URL for automatic phone backup — uploads land in the same `/srv/data/immich` library.

**Immich is the source of truth** — date corrections, albums, and edits live in its database, not in the files (filenames/EXIF are not kept in sync; a re-import from files would lose all corrections). Immich's automatic daily DB dumps (Administration → Settings → Backup Settings — verify enabled) land in `/srv/data/immich/backups`, so the wholesale `/srv/data` backup captures both files and database. Live app state (`/srv/immich/`: Postgres, model cache) is restorable from those dumps and stays outside the backup.

## 8. OpenAI API (for projects)

Hobby projects call the hosted OpenAI API — no local models. One-time key setup on the server:

```
./scripts/setup-openai.sh
```

Prompts for the key (hidden input — never in shell history, never in this repo, which is public) and stores it in `~/.config/openai/env` (chmod 600). Login shells export `OPENAI_API_KEY` automatically; Docker Compose projects can add `env_file: /home/bwilliams/.config/openai/env`. Re-run the script to rotate the key.

An Ollama + Open WebUI stack was briefly added, then dropped in favor of the hosted API. If it was ever started, `./scripts/remove-ollama.sh` cleans it off the server (containers, model volumes, images).

## 9. Landing page

"100 Bosworth" dashboard at `https://100b.amokamok.com`, linking to everything on (and around) the server. Served by the Caddy proxy (section 11) straight from `landing/site/` in the repo checkout, so updating the page is: edit the `services` array in `landing/site/index.html`, commit, `git pull` on the server, refresh — no container restart. Same-host apps take a `url` (their HTTPS name); network devices (printer, router, cameras) take their IP `url`. Each card gets a live reachability dot.

## 10. SSH keys

From the Mac (one-time): `ssh-copy-id bwilliams@192.168.0.190`, confirm passwordless `ssh 100bsa` works (Mac `~/.ssh/config` has the `100bsa` host alias), then on the server:

```
./scripts/harden-ssh.sh
```

SSH becomes key-only **except from inside the house**: password login stays allowed from the LAN subnets (192.168.0.x / 192.168.10.x) as break-glass in case the machine holding the keys is lost. Root login disabled everywhere; the physical console (keyboard + HDMI) is unaffected and always accepts the password. Drop-in at `/etc/ssh/sshd_config.d/99-hardening.conf`; the script refuses to run until an authorized key is installed, so it can't lock you out.

## 11. DNS + HTTPS (Caddy reverse proxy)

Every app gets a real name with a real cert, LAN-only: `https://100b.amokamok.com` (landing), `https://immich.100b.amokamok.com`, `https://ha.100b.amokamok.com`, … One wildcard cert for `*.100b.amokamok.com` via Cloudflare DNS-01 — proves domain ownership through the API, so **no ports are opened to the internet** and renewal is automatic.

```
./proxy/setup.sh
```

Prompts once for a Cloudflare API token ("Edit zone DNS" template scoped to `amokamok.com`, plus Zone→Zone→Read; stored in `proxy/.env`, gitignored), upserts the DNS records (`100b` and `*.100b` → the server's LAN IP, DNS-only/grey-cloud), builds Caddy with the Cloudflare DNS plugin, and replaces the old nginx landing container.

Add an app behind the proxy: one matcher+handle pair in `proxy/Caddyfile`, then `cd proxy && sudo docker compose up -d --force-recreate` (config is a bind mount — no rebuild), plus a card on the landing page.

## 12. Remote access

UniFi WireGuard ("One-Click VPN" on the gateway) — no services are exposed to the internet. Add devices in the UniFi console → Settings → VPN. The `*.100b.amokamok.com` names resolve publicly (to the private LAN IP), so the same HTTPS URLs work at home and over the VPN, including Immich mobile sync.

## 13. Automations

AI-powered scripts under `automations/`, each with its own `setup.sh` that installs a systemd timer. They read API keys from the `~/.config/*/env` files (never from the repo).

- **photo-digest** — daily "on this day" email: photos from past years via the Immich API, a short OpenAI-written intro, inline thumbnails. `./automations/photo-digest/setup.sh` (prompts for SMTP once — Gmail needs an App Password), then test with `photo_digest.py --dry-run`. Sends nothing on days with no memories. Timer: 08:00 server time.

## Change log
- 2026-07-20: Initial install, Ubuntu Server 26.04 LTS. F7 one-time boot menu confirmed working from front USB 3.0 port.
- 2026-07-20: Added Photoprism stack (`photoprism/`) with one-shot setup script. Photos live in `/srv/photos`.
- 2026-07-20: Added `scripts/setup-data-drive.sh` — formats the spare WD Blue SN5100 1TB and mounts it at `/srv` as a dedicated data drive.
- 2026-07-20: Added `scripts/setup-os-drive-space.sh` — grows `/` to 200G and turns the rest of the OS drive's unallocated LVM space into `/backup`.
- 2026-07-20: Reworked `setup-os-drive-space.sh` — `/` now gets the whole OS drive (apps + Docker images); backups go to external USB drives instead of an internal `/backup` volume.
- 2026-07-20: Photos moved from `/srv/photos` to `/srv/data/Pictures` — personal media now lives under one `/srv/data/` tree for wholesale backup.
- 2026-07-20: Added Immich stack (`immich/`) — likely primary photo app (mobile auto-backup); archive mounted read-only as an external library. Added `scripts/photo-triage.sh` for pre-index screenshot cleanup.
- 2026-07-21: Removed Photoprism — Immich is the photo app. `scripts/remove-photoprism.sh` cleans the retired stack off the server (containers, images, `/srv/photoprism`).
- 2026-07-21: Added Ollama + Open WebUI stack (`ollama/`); default model gpt-oss:20b, OpenAI-compatible API on `:11434/v1`.
- 2026-07-21: Dropped Ollama in favor of the hosted OpenAI API — `scripts/setup-openai.sh` stores the key; `scripts/remove-ollama.sh` cleans the local stack off the server.
- 2026-07-21: Switched Immich from external library to full import (`scripts/import-photos.sh`) — enables in-app delete/dedupe and folder→album mapping; storage template keeps the on-disk layout portable. `/srv/data/Pictures` retired; USB kept as offline backup.
- 2026-07-22: Added `scripts/fix-dates-from-filenames.py` — corrects Immich dates for old videos with no creation metadata, using `YYYY_MM_DD_HHMM` filenames as ground truth.
- 2026-07-25: Added `scripts/redate-album.py` — sets every asset in an album to a given date (for scans/digitized photos where the album name is the real date).
- 2026-07-25: Added `scripts/stamp-unknown-date.sh` — writes the 1970-01-01 "date unknown" sentinel into EXIF + filenames of source files. Import script now maps loose root files to an album named after the source folder.
- 2026-07-25: Decision: Immich's database is the source of truth for dates/albums (files are not kept in sync). Daily DB dumps into `/srv/data/immich/backups` make the `/srv/data` backup capture everything.
- 2026-07-25: Added landing page (`landing/`) — nginx on port 80 serving a repo-managed dashboard of all server apps and network devices.
- 2026-07-27: Added `scripts/bulk-redate-albums.py` — interactive pattern-matched album redating (y/n per album, date proposed from album name, assets with real EXIF within ±10 days kept). `redate-album.py` now sequences alphabetically a minute apart and writes sidecars.
- 2026-07-28: Added `scripts/rename-albums.py` — album names become `Description YYYY-MM-DD`; date-parsers now find dates anywhere in album names.
- 2026-07-25: Added SSH hardening (`scripts/harden-ssh.sh`) and the Caddy proxy (`proxy/`) — wildcard HTTPS for `*.100b.amokamok.com` via Cloudflare DNS-01, LAN-only, replaces the nginx landing container. Remote access: UniFi WireGuard (no exposed ports).
- 2026-07-26: Added `automations/photo-digest` — daily "on this day" memories email (Immich photos + OpenAI intro) on a systemd timer.
- 2026-07-26: Metadata portability: `scripts/set-album-location.py` (album GPS → Immich + `.xmp` sidecars) and `scripts/sync-dates-to-sidecars.py` (all Immich date corrections → sidecars). Originals never modified.
