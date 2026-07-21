#!/usr/bin/env bash
# Format the spare 1TB NVMe (WD Blue SN5100) and mount it at /srv so photos
# and app data live on their own disk, separate from the OS drive.
# Finds the drive by model name (nvme0/nvme1 numbering can swap between
# boots) and refuses to touch any drive that isn't completely blank.
# Idempotent: exits cleanly if /srv is already mounted.
# Usage: ./setup-data-drive.sh [/dev/nvmeXn1]
set -euo pipefail

MOUNTPOINT=/srv
LABEL=srv-data
MODEL_MATCH="SN5100"

if findmnt -n "$MOUNTPOINT" >/dev/null 2>&1; then
    echo "$MOUNTPOINT is already a mountpoint — nothing to do:"
    findmnt "$MOUNTPOINT"
    exit 0
fi

if [ $# -ge 1 ]; then
    DEVICE=$1
else
    NAME=$(lsblk -dno NAME,MODEL | awk -v m="$MODEL_MATCH" '$0 ~ m {print $1; exit}')
    [ -n "$NAME" ] || { echo "No drive matching '$MODEL_MATCH' found; pass the device explicitly." >&2; exit 1; }
    DEVICE=/dev/$NAME
fi

[ -b "$DEVICE" ] || { echo "$DEVICE is not a block device." >&2; exit 1; }

# Refuse anything that isn't verifiably blank.
if [ "$(lsblk -no NAME "$DEVICE" | wc -l)" -ne 1 ]; then
    echo "$DEVICE has partitions — refusing to touch it." >&2; exit 1
fi
if [ -n "$(sudo wipefs -n "$DEVICE" 2>/dev/null)" ]; then
    echo "$DEVICE has filesystem signatures — refusing to touch it." >&2; exit 1
fi

# A mount over a non-empty /srv would shadow the existing files.
if [ -d "$MOUNTPOINT" ] && [ -n "$(ls -A "$MOUNTPOINT" 2>/dev/null)" ]; then
    echo "$MOUNTPOINT already contains files — move them aside first, then re-run." >&2
    exit 1
fi

echo "About to partition and format:"
lsblk -dno NAME,MODEL,SIZE "$DEVICE"
echo "Everything on $DEVICE will be erased, and it will be mounted at $MOUNTPOINT."
read -rp "Type 'yes' to continue: " CONFIRM
[ "$CONFIRM" = "yes" ] || { echo "Aborted."; exit 1; }

sudo parted -s "$DEVICE" mklabel gpt mkpart data ext4 1MiB 100%
sudo partprobe "$DEVICE"
sudo udevadm settle

case "$DEVICE" in
    *[0-9]) PART="${DEVICE}p1" ;;
    *)      PART="${DEVICE}1"  ;;
esac
sudo mkfs.ext4 -q -L "$LABEL" "$PART"

# Mount by UUID with nofail so boot doesn't hang if the drive is ever removed.
UUID=$(sudo blkid -s UUID -o value "$PART")
sudo mkdir -p "$MOUNTPOINT"
if ! grep -q "UUID=$UUID" /etc/fstab; then
    echo "UUID=$UUID $MOUNTPOINT ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab >/dev/null
fi
sudo systemctl daemon-reload
sudo mount "$MOUNTPOINT"

echo
echo "Done — $PART is mounted at $MOUNTPOINT and will remount on boot:"
df -h "$MOUNTPOINT"
