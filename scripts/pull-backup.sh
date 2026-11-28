#!/usr/bin/env bash
# Copy the latest paired backups off the exe.dev VM to the operator's local machine (docs/hosting.md section 5).
set -euo pipefail

VM_HOST="${VM_HOST:-tar-frozen-work-list.exe.xyz}"
REMOTE_DIR="${REMOTE_DIR:-/opt/tar-twin/backups}"
LOCAL_DIR="${1:-./backups/$(date +%Y-%m-%d)}"

mkdir -p "$LOCAL_DIR"
rsync -avz --protect-args "${VM_HOST}:${REMOTE_DIR}/" "${LOCAL_DIR}/"
echo "Copied backups from ${VM_HOST}:${REMOTE_DIR} to ${LOCAL_DIR}"
