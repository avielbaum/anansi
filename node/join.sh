#!/usr/bin/env sh
# One-step volunteer setup for Linux and macOS. Usage: ./node/join.sh --gateway URL --token TOKEN [--dry-run]
# Makes a private Python environment in ~/.anansi-venv (httpx only), then runs node/join.py.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
command -v python3 >/dev/null 2>&1 || { echo "Python 3.10 or newer is required (https://www.python.org/downloads/)."; exit 2; }
if [ ! -x "$HOME/.anansi-venv/bin/python" ]; then
  python3 -m venv "$HOME/.anansi-venv"
  "$HOME/.anansi-venv/bin/pip" install --quiet httpx
fi
exec "$HOME/.anansi-venv/bin/python" "$HERE/join.py" "$@"
