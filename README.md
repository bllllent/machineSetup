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

## 5. Data drive (/srv)

The MS-01 has two 1TB NVMe drives: the YMTC (`nvme0n1`) holds the OS, and the WD Blue SN5100 is a dedicated data drive mounted at `/srv`. Everything under `/srv` (photos, app data) lives on its own disk, separate from the OS.

One-time setup (destructive to the blank drive — it asks for confirmation):
```
./scripts/setup-data-drive.sh
```
Finds the WD Blue by model name, formats it ext4, mounts it at `/srv`, and adds an fstab entry (by UUID, `nofail`) so it remounts on boot. Refuses to run against any drive that has partitions or filesystem signatures on it. Run this **before** the Photoprism setup so the photos land on the data drive.

Note: the OS install only allocated 100G of its LVM volume group — ~850G on the OS drive is unallocated and can be added to `/` later if needed (`lvextend` + `resize2fs`).

## 6. Photoprism

Photo storage layout:
- `/srv/photos` — the pictures themselves. Service-agnostic path on purpose: backups and any future photo app point here, so nothing moves if Photoprism gets swapped out.
- `/srv/photoprism/` — Photoprism's own regenerable data (thumbnail/cache storage, MariaDB, import staging). Safe to delete and rebuild without touching photos.

Deploy on the MS-01:
```
cd ~/machineSetup && git pull
./photoprism/setup.sh
```

The script is idempotent (re-run freely). It installs Docker if missing, creates the directories above, generates `photoprism/.env` with random passwords on first run (gitignored — this repo is public, never commit `.env`), syncs anything offloaded to `~/photos` into `/srv/photos`, starts the stack, and prints the URL and admin login.

First login: **Library → Index** to scan the originals.

## Change log
- 2026-07-20: Initial install, Ubuntu Server 26.04 LTS. F7 one-time boot menu confirmed working from front USB 3.0 port.
- 2026-07-20: Added Photoprism stack (`photoprism/`) with one-shot setup script. Photos live in `/srv/photos`.
- 2026-07-20: Added `scripts/setup-data-drive.sh` — formats the spare WD Blue SN5100 1TB and mounts it at `/srv` as a dedicated data drive.
