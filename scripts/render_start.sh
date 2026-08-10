#!/usr/bin/env bash
set -euo pipefail

mkdir -p data data/exports

if [ ! -f data/songs.db ]; then
  echo "No persistent SQLite database found; starting with an empty schema."
fi

PYTHON_BIN="${PYTHON_BIN:-python}"
exec "$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"
