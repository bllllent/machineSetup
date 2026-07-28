# Scripts reference

Everything here follows the same conventions:

- **Dry-run by default** where anything changes: run bare to see the plan, add `--apply` to do it. (`bulk-redate-albums.py` is interactive instead — your `y` is the confirmation. `audit-album-dates.py` is read-only and has no apply at all.)
- **Idempotent** — safe to re-run; already-correct things are skipped.
- **Secrets and keys** come from `~/.config/<service>/env` files (chmod 600, never in this repo — it's public). Immich API key: `~/.config/immich/env`; OpenAI: `~/.config/openai/env`; SMTP: `~/.config/smtp/env`.
- **Originals are never modified.** Metadata corrections go to Immich's database (via API) *and* to `.xmp` sidecar files next to the originals — the portable, app-independent layer. Sidecar writes use `sudo` (library files are root-owned). See "metadata philosophy" in the main README.
- Python scripts are stdlib-only — nothing to install. Shell scripts install what they need via apt.

## Server setup (one-time)

| Script | What it does |
|---|---|
| `setup-data-drive.sh` | Formats the blank WD Blue 1TB and mounts it at `/srv` (fstab by UUID, `nofail`). Finds the drive by model name; refuses to touch any drive with partitions or filesystem signatures; asks for a typed `yes`. |
| `setup-os-drive-space.sh` | Grows `/` to the full OS drive (the installer left ~850G unallocated in LVM). Live, non-destructive. |
| `harden-ssh.sh` | Key-only SSH — except password login stays allowed from the LAN as break-glass. Refuses to run until an authorized key exists, so it can't lock you out. Physical console is unaffected. |
| `setup-openai.sh` | Prompts (hidden) for the OpenAI API key and stores it in `~/.config/openai/env`; login shells export `OPENAI_API_KEY`. Re-run to rotate. |

## Retired-stack cleanup

| Script | What it does |
|---|---|
| `remove-photoprism.sh` | Removes the retired Photoprism stack: containers, images, `/srv/photoprism`, leftover repo dir. Photo library untouched. |
| `remove-ollama.sh` | Removes the retired Ollama + Open WebUI stack: containers, model volumes, images. Safe if it never ran. |

## Photo library — importing

| Script | What it does |
|---|---|
| `import-photos.sh [SOURCE]` | Bulk-imports a folder into Immich (official CLI via Docker). Folder names become albums (`--album`); re-runs skip already-imported files by content hash, so it's resumable. Checks free space first. Prompts once for an Immich API key. |
| `photo-triage.sh [--apply]` | Optional pre-import cleanup: moves likely screenshots/screen-recordings out of a source folder into a review dir (never deletes; relative paths preserved for easy undo). `LIBRARY=/mnt/usb/... ` to point it. |
| `stamp-unknown-date.sh <folder> [DATE] [--apply]` | Writes a sentinel date (default 1970-01-01 = "date unknown") into EXIF **and** filenames of *source* files (pre-import only — never run against the Immich library; changes hashes, so never re-import a stamped folder without deleting its assets from Immich first). Largely superseded by the sidecar approach. |

## Photo library — dates & metadata

The cleanup toolkit, in the order you'd typically use it:

| Script | What it does |
|---|---|
| `audit-album-dates.py` | **Read-only.** Compares every album's name-encoded date (`2000-12-25 Movies`) against the dates of the photos inside. Terminal summary + full CSV (`~/album-date-audit.csv`). This is the worklist-maker. |
| `bulk-redate-albums.py "PATTERN"` | Interactive bulk redate: albums matching the pattern (`"2004*"`), one y/n prompt each, date proposed from the album name (type a different `YYYY-MM-DD` to override). Assets whose on-disk EXIF is within ±10 days of the target keep their real timestamps; the rest get re-sequenced. Auto-skips albums with nothing to do. |
| `redate-album.py "ALBUM" DATE [--all] [--apply]` | Single-album version: every asset to one date, timestamped in alphabetical filename order one minute apart from noon Pacific. `--all` re-sequences even assets already on the date. |
| `fix-dates-from-filenames.py [--apply]` | Whole-library sweep: filenames that encode dates (`20030101_175857.jpg`, `2010_12_31_2051.mov`, `IMG_...`) become the truth where Immich disagrees. Detects and fixes UTC-rendered times; skips "batch export" groups (filenames seconds apart with organically spread dates — there the filename is the export time, not capture). |
| `set-album-location.py "ALBUM" (--place "City, Country" \| LAT LON) [--force] [--apply]` | Approximate GPS for a whole album, in Immich + sidecars. Geocodes via OpenStreetMap. Only fills photos with *no* GPS unless `--force`. |
| `sync-dates-to-sidecars.py [--apply]` | The flush: sweeps the whole library and writes Immich's date into a sidecar wherever the file on disk disagrees by >25h. Run after curation sessions so corrections persist outside the database. Records Immich's *current belief* — right or wrong — so curate first, flush second. |

Timezone for assigned timestamps is `America/Los_Angeles` everywhere; override per-run with `PHOTO_TZ=...`.

## Sharing

| Script | What it does |
|---|---|
| `share-albums.py <email> [--editor] [--apply]` | Shares **all** albums you own with another Immich user (partner sharing covers the timeline but not albums — this fills the gap). Re-run after new imports; already-shared albums are skipped. |
| `rename-albums.py [--apply]` | Renames albums from `YYYY-MM-DD_Description` to `Description YYYY-MM-DD` (underscores → spaces, date moves to the end). Collision-safe. The date-parsing scripts find dates anywhere in the name, so they keep working after the rename — but year patterns for `bulk-redate-albums.py` become `"*2004*"` instead of `"2004*"`. |

## Related, elsewhere in the repo

- `immich/setup.sh`, `proxy/setup.sh` — service deployment (see main README sections).
- `automations/photo-digest/` — daily "on this day" memories email (Immich photos + OpenAI intro) on a systemd timer; `setup.sh` there prompts for SMTP and installs the timer.
