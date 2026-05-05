#!/usr/bin/env bash
set -euo pipefail

mkdir -p data data/exports

if [ ! -f data/songs.db ] && [ -f app/seed/songs.db.gz ]; then
  echo "Restoring SQLite seed database..."
  gzip -dc app/seed/songs.db.gz > data/songs.db
fi

PYTHON_BIN="${PYTHON_BIN:-python}"
exec "$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"
