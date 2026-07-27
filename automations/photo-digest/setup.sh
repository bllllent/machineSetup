#!/usr/bin/env bash
# Photo memories digest: daily "on this day" email with photos from Immich.
#   - prompts once for SMTP settings (stored in ~/.config/smtp/env, chmod 600)
#   - installs a systemd timer (daily 08:00 server time)
# Idempotent — safe to re-run. Test any time with:
#   ./photo_digest.py --dry-run     (no email)
#   ./photo_digest.py               (sends for real)
set -euo pipefail

cd "$(dirname "$0")"
SCRIPT="$(pwd)/photo_digest.py"

ENV_FILE="$HOME/.config/smtp/env"
if [ ! -f "$ENV_FILE" ]; then
    echo "SMTP settings (for Gmail: smtp.gmail.com, port 587, and an App"
    echo "Password from Google Account -> Security -> 2-Step -> App passwords):"
    read -rp  "  SMTP host [smtp.gmail.com]: " HOST; HOST=${HOST:-smtp.gmail.com}
    read -rp  "  SMTP port [587]: " PORT; PORT=${PORT:-587}
    read -rp  "  SMTP user (login email): " USER_
    read -rsp "  SMTP password (hidden): " PASS; echo
    read -rp  "  Send digest to [${USER_}]: " TO; TO=${TO:-$USER_}
    [ -n "$USER_" ] && [ -n "$PASS" ] || { echo "Host/user/password required." >&2; exit 1; }
    mkdir -p "$(dirname "$ENV_FILE")"
    umask 077
    cat > "$ENV_FILE" <<EOF
SMTP_HOST=$HOST
SMTP_PORT=$PORT
SMTP_USER=$USER_
SMTP_PASS=$PASS
MAIL_FROM=$USER_
MAIL_TO=$TO
EOF
    chmod 600 "$ENV_FILE"
    echo "Stored in $ENV_FILE."
fi

echo "==> Installing systemd timer (daily 08:00 server time)..."
sudo tee /etc/systemd/system/photo-digest.service >/dev/null <<EOF
[Unit]
Description=Photo memories digest email
After=network-online.target

[Service]
Type=oneshot
User=$USER
ExecStart=/usr/bin/python3 $SCRIPT
EOF

sudo tee /etc/systemd/system/photo-digest.timer >/dev/null <<EOF
[Unit]
Description=Daily photo memories digest

[Timer]
OnCalendar=*-*-* 08:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now photo-digest.timer

echo
echo "Timer installed: $(systemctl show photo-digest.timer -p NextElapseUSecRealtime --value)"
echo "Note: 08:00 SERVER time — check 'timedatectl' matches your expectation."
echo "Test now:   $SCRIPT --dry-run"
echo "Send now:   $SCRIPT"
echo "Logs:       journalctl -u photo-digest.service"
