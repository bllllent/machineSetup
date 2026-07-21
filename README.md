# Minisforum MS-01 — Linux Install Notes

Hardware: Minisforum MS-01 Mini Workstation
OS: Ubuntu Server 26.04 LTS
Purpose: home server running Photoprism, Ollama (local AI), and other Docker services

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

- Docker + Docker Compose for all services (Photoprism, Ollama, etc.) on one flat host.
- No discrete GPU on the MS-01 — Ollama runs on CPU (fine for 7B–13B models).

## 5. Storage layout

Two 1TB NVMe drives:

- **YMTC (`nvme0n1`) — OS drive:** the system, apps, and Docker images, all on `/` (grown to the full ~950G — the installer only allocated 100G).
- **WD Blue SN5100 — data drive, mounted at `/srv`:** personal media under `/srv/data/` (`Pictures`, later `Music`, …) and regenerable app data (`/srv/photoprism`). Back up `/srv/data` wholesale; app data can always be rebuilt.

Backups: external USB drives (photos are on a single internal disk — keep a current copy elsewhere).

One-time setup, in order:
```
./scripts/setup-data-drive.sh      # format the blank WD Blue, mount at /srv (asks for confirmation)
./scripts/setup-os-drive-space.sh  # grow / to the full OS drive (live, non-destructive)
```

Both scripts are idempotent. `setup-data-drive.sh` finds the WD Blue by model name (nvme numbering can swap between boots), refuses to touch any drive with partitions or filesystem signatures, and mounts by UUID with `nofail`. Run these **before** the Photoprism setup so the photos land on the data drive.

## 6. Photoprism

Photo storage layout:
- `/srv/data/Pictures` — the pictures themselves. Service-agnostic path on purpose: backups and any future photo app point here, so nothing moves if Photoprism gets swapped out.
- `/srv/photoprism/` — Photoprism's own regenerable data (thumbnail/cache storage, MariaDB, import staging). Safe to delete and rebuild without touching photos.

Deploy on the MS-01:
```
cd ~/machineSetup && git pull
./photoprism/setup.sh
```

The script is idempotent (re-run freely). It installs Docker if missing, creates the directories above, generates `photoprism/.env` with random passwords on first run (gitignored — this repo is public, never commit `.env`), syncs anything offloaded to `~/photos` into `/srv/data/Pictures`, starts the stack, and prints the URL and admin login.

First login: **Library → Index** to scan the originals.

## Change log
- 2026-07-20: Initial install, Ubuntu Server 26.04 LTS. F7 one-time boot menu confirmed working from front USB 3.0 port.
- 2026-07-20: Added Photoprism stack (`photoprism/`) with one-shot setup script. Photos live in `/srv/photos`.
- 2026-07-20: Added `scripts/setup-data-drive.sh` — formats the spare WD Blue SN5100 1TB and mounts it at `/srv` as a dedicated data drive.
- 2026-07-20: Added `scripts/setup-os-drive-space.sh` — grows `/` to 200G and turns the rest of the OS drive's unallocated LVM space into `/backup`.
- 2026-07-20: Reworked `setup-os-drive-space.sh` — `/` now gets the whole OS drive (apps + Docker images); backups go to external USB drives instead of an internal `/backup` volume.
- 2026-07-20: Photos moved from `/srv/photos` to `/srv/data/Pictures` — personal media now lives under one `/srv/data/` tree for wholesale backup.
