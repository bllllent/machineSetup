#!/usr/bin/env bash
# Store the OpenAI API key on the server, once, for all projects.
# Writes ~/.config/openai/env (chmod 600) and makes login shells export
# OPENAI_API_KEY. The key is prompted with hidden input — it never touches
# shell history, and never goes in this repo (public).
# Idempotent — re-run to rotate the key.
set -euo pipefail

ENV_FILE="$HOME/.config/openai/env"
mkdir -p "$(dirname "$ENV_FILE")"

if [ -f "$ENV_FILE" ] && grep -q '^OPENAI_API_KEY=' "$ENV_FILE"; then
    echo "A key is already stored at $ENV_FILE."
    read -rp "Replace it? [y/N] " ans
    [ "${ans,,}" = "y" ] || exit 0
fi

read -rsp "Paste OpenAI API key (from platform.openai.com; input hidden): " KEY
echo
[ -n "$KEY" ] || { echo "No key entered." >&2; exit 1; }

umask 077
printf 'OPENAI_API_KEY=%s\n' "$KEY" > "$ENV_FILE"
chmod 600 "$ENV_FILE"

SOURCE_LINE='set -a; [ -f ~/.config/openai/env ] && . ~/.config/openai/env; set +a'
grep -qF "$SOURCE_LINE" "$HOME/.bashrc" 2>/dev/null || echo "$SOURCE_LINE" >> "$HOME/.bashrc"

echo
echo "Stored in $ENV_FILE. New shells export OPENAI_API_KEY automatically."
echo "Docker compose projects: add  env_file: $ENV_FILE"
echo
echo "Test it:"
echo '  source ~/.bashrc'
echo '  curl -s https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY" | head -5'
