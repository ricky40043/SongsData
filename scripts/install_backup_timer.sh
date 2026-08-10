#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  exec sudo "$0" "$@"
fi

install -m 0644 "$ROOT_DIR/deploy/songsdata-cloud-backup.service" \
  /etc/systemd/system/songsdata-cloud-backup.service
install -m 0644 "$ROOT_DIR/deploy/songsdata-cloud-backup.timer" \
  /etc/systemd/system/songsdata-cloud-backup.timer
systemctl daemon-reload
systemctl enable --now songsdata-cloud-backup.timer
systemctl --no-pager --full status songsdata-cloud-backup.timer
