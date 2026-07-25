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

## 9. Landing page (port 80)

Dashboard linking to everything on (and around) the server:

```
./landing/setup.sh
```

nginx serves `landing/site/` straight from the repo checkout (bind mount), so updating the page is: edit the `services` array in `landing/site/index.html`, commit, `git pull` on the server, refresh — no container restart. Same-host apps take a `port` (links follow whatever hostname/IP you browsed by); other devices (printer, router, Home Assistant) take a full `url` — commented examples included. Each card gets a live reachability dot.

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
