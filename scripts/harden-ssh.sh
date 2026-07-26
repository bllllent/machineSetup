#!/usr/bin/env bash
# Lock SSH down to key-based auth — except from inside the house.
# Break-glass design (in case the machine holding the keys is lost):
#   - password SSH stays allowed from the LAN (trusted + IoT subnets only)
#   - key-only from everywhere else (VPN included)
#   - the physical console (keyboard+HDMI) is untouched by any of this
# Idempotent. REFUSES to run until at least one authorized key is installed —
# run this from your Mac first:
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

# break-glass: password login allowed from inside the house only
Match Address 192.168.0.0/24,192.168.10.0/24
    PasswordAuthentication yes
    KbdInteractiveAuthentication yes
EOF

sudo sshd -t
sudo systemctl reload ssh
echo
echo "Done — SSH is key-only, except password login still works from the LAN"
echo "(192.168.0.x / 192.168.10.x). Root login disabled everywhere."
echo "Keep this session open and verify a fresh 'ssh' from your Mac works."
