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
- **WD Blue SN5100 — data drive, mounted at `/srv`:** personal media under `/srv/data/` (`Pictures`, later `Music`, …) and regenerable app data (`/srv/immich`). Back up `/srv/data` wholesale; app data can always be rebuilt.

Backups: external USB drives (photos are on a single internal disk — keep a current copy elsewhere).

One-time setup, in order:
```
./scripts/setup-data-drive.sh      # format the blank WD Blue, mount at /srv (asks for confirmation)
./scripts/setup-os-drive-space.sh  # grow / to the full OS drive (live, non-destructive)
```

Both scripts are idempotent. `setup-data-drive.sh` finds the WD Blue by model name (nvme numbering can swap between boots), refuses to touch any drive with partitions or filesystem signatures, and mounts by UUID with `nofail`. Run these **before** the photo app setup so the photos land on the data drive.

`/srv/data/Pictures` is deliberately a service-agnostic path: backups and any future photo app point here, so nothing moves if the app gets swapped out (as happened with Photoprism → Immich; `scripts/remove-photoprism.sh` cleans the retired stack off the server).

## 6. Photo triage (before first index)

Clean likely screenshots/screen recordings out of the library before indexing (Immich mounts the archive read-only, so junk has to be removed on disk):

```
./scripts/photo-triage.sh            # dry run — reports candidates, writes a list
./scripts/photo-triage.sh --apply    # moves them to /srv/data/_triage/screenshots
```

Heuristics: screenshot-style filenames, plus PNGs with no camera EXIF. Nothing is ever deleted — candidates move to the triage dir with relative paths preserved, so false positives can be moved straight back. Review and delete the triage dir by hand.

Geolocation grouping is *not* needed as pre-processing: Immich reverse-geocodes on index (offline) and provides map view and search-by-place without reorganizing any files.

## 7. Immich

Deploy:
```
./immich/setup.sh
```
Then in the web UI at `http://<server-ip>:2283`:
1. Create the admin account (first visitor becomes admin).
2. Administration → External Libraries → add `/srv/data/Pictures` and scan. The archive is mounted read-only — Immich indexes it in place and can never modify the originals.
3. Optional: Administration → Settings → Video Transcoding → enable Quick Sync (the iGPU is already passed through).
4. Install the Immich mobile app and point it at the server URL for automatic phone backup. Phone uploads land in `/srv/data/immich` (Immich-managed), which the wholesale `/srv/data` backup covers.

App state (Postgres, ML model cache) lives in `/srv/immich/` — regenerable, not part of the data backup.

## 8. OpenAI API (for projects)

Hobby projects call the hosted OpenAI API — no local models. One-time key setup on the server:

```
./scripts/setup-openai.sh
```

Prompts for the key (hidden input — never in shell history, never in this repo, which is public) and stores it in `~/.config/openai/env` (chmod 600). Login shells export `OPENAI_API_KEY` automatically; Docker Compose projects can add `env_file: /home/bwilliams/.config/openai/env`. Re-run the script to rotate the key.

An Ollama + Open WebUI stack was briefly added, then dropped in favor of the hosted API. If it was ever started, `./scripts/remove-ollama.sh` cleans it off the server (containers, model volumes, images).

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
