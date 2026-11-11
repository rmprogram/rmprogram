#!/usr/bin/env bash
# Lanza RM Studio IA (Linux / macOS). Crea un entorno virtual la primera vez.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi
exec .venv/bin/python -m rmstudio "$@"
