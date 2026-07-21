#!/usr/bin/env bash
# Grow / to use the entire OS-drive volume group (the Ubuntu installer only
# allocated 100G of ~950G). The OS drive holds the system, apps, and Docker
# images; the WD Blue at /srv holds data; backups go to external USB drives.
# Runs live, non-destructive, idempotent — safe to re-run.
set -euo pipefail

VG=ubuntu-vg
LV=ubuntu-lv

free=$(sudo vgs --noheadings -o vg_free --units g --nosuffix "$VG" | tr -d ' ')
if [ "${free%%.*}" -eq 0 ]; then
    echo "==> No unallocated space left in $VG — nothing to do."
else
    echo "==> Growing / by ${free}G..."
    sudo lvextend -l +100%FREE -r "$VG/$LV"
fi

echo
df -h /
