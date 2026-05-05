#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
songs crawl-taiwanbible-all \
  --delay "${CRAWLER_DELAY_SECONDS:-1}" \
  --concurrency "${CRAWLER_CONCURRENCY:-5}"
