#!/usr/bin/env bash
# Creates .venv and installs dependencies. Works even when Ubuntu's python3-venv
# package (ensurepip) is missing, by bootstrapping pip with the official get-pip.py.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"

if [ ! -x .venv/bin/python ]; then
  echo "Creating virtual environment in .venv"
  if ! "$PYTHON" -m venv .venv >/dev/null 2>&1; then
    echo "python3-venv is not installed; creating .venv without pip and bootstrapping it"
    rm -rf .venv
    "$PYTHON" -m venv --without-pip .venv
  fi
fi

if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  echo "Downloading get-pip.py from bootstrap.pypa.io"
  tmp="$(mktemp)"
  curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$tmp"
  .venv/bin/python "$tmp" --quiet
  rm -f "$tmp"
fi

.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
echo "Setup complete."
