#!/usr/bin/env bash
# Use the ~850G the Ubuntu installer left unallocated in the OS drive's
# LVM volume group:
#   - grow / from 100G to 200G (Docker images, Ollama models)
#   - put the rest in a "backup" LV mounted at /backup — the backup target
#     for /srv/photos, so photos and their backup sit on different disks
# Idempotent — safe to re-run; never reformats an existing backup volume.
set -euo pipefail

VG=ubuntu-vg
ROOT_LV=ubuntu-lv
ROOT_TARGET_G=200
BACKUP_LV=backup
MOUNTPOINT=/backup

root_size=$(sudo lvs --noheadings -o lv_size --units g --nosuffix "$VG/$ROOT_LV" | tr -d ' ')
if [ "${root_size%%.*}" -lt "$ROOT_TARGET_G" ]; then
    echo "==> Growing / from ${root_size}G to ${ROOT_TARGET_G}G..."
    sudo lvextend -L "${ROOT_TARGET_G}G" -r "$VG/$ROOT_LV"
else
    echo "==> / is already ${root_size}G — leaving it."
fi

if ! sudo lvs "$VG/$BACKUP_LV" >/dev/null 2>&1; then
    free=$(sudo vgs --noheadings -o vg_free --units g --nosuffix "$VG" | tr -d ' ')
    echo "==> Creating '$BACKUP_LV' LV with the remaining ${free}G..."
    sudo lvcreate -l 100%FREE -n "$BACKUP_LV" "$VG"
else
    echo "==> '$BACKUP_LV' LV already exists — not touching it."
fi

# Format only if the LV has no filesystem yet (fresh, or an interrupted
# earlier run). An existing filesystem — i.e. actual backups — is never
# reformatted.
DEV="/dev/$VG/$BACKUP_LV"
UUID=$(sudo blkid -s UUID -o value "$DEV" 2>/dev/null || true)
if [ -z "$UUID" ]; then
    echo "==> Formatting $DEV..."
    sudo mkfs.ext4 -q -L "$BACKUP_LV" "$DEV"
    UUID=$(sudo blkid -s UUID -o value "$DEV")
fi

sudo mkdir -p "$MOUNTPOINT"
if ! grep -q "UUID=$UUID" /etc/fstab; then
    echo "UUID=$UUID $MOUNTPOINT ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab >/dev/null
fi
sudo systemctl daemon-reload
mountpoint -q "$MOUNTPOINT" || sudo mount "$MOUNTPOINT"

echo
echo "Done:"
df -h / "$MOUNTPOINT"
