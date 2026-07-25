#!/usr/bin/env bash
# Lock SSH down to key-based auth only. Idempotent.
# REFUSES to run until at least one authorized key is installed (otherwise
# you'd lock yourself out) — run this from your Mac first:
#   ssh-copy-id bwilliams@<server-ip>
# and confirm `ssh <server>` works without a password.
set -euo pipefail

if [ ! -s "$HOME/.ssh/authorized_keys" ]; then
    echo "No keys in ~/.ssh/authorized_keys — run ssh-copy-id from your Mac first." >&2
    echo "Refusing to disable password auth (it would lock you out)." >&2
    exit 1
fi

echo "==> Authorized keys present:"
awk '{print "  " $3 " (" $1 ")"}' "$HOME/.ssh/authorized_keys"

sudo tee /etc/ssh/sshd_config.d/99-hardening.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF

sudo systemctl reload ssh
echo
echo "Done — password logins disabled, root login disabled."
echo "Keep this session open and verify a fresh 'ssh' from your Mac works."
