#!/usr/bin/env bash
# Paired restore of IMPACT Web (Postgres) and Twin-only state with cutoff verification (docs/hosting.md section 5).
set -euo pipefail

PAIR_DIR="${1:?Usage: scripts/restore.sh <backup-pair-dir>}"
IMPACTWEB_URL="${IMPACTWEB_URL:-http://127.0.0.1:18001}"
TWIN_URL="${TWIN_URL:-http://127.0.0.1:18002}"
TWIN_SYNC_TOKEN="${TWIN_SYNC_TOKEN:?TWIN_SYNC_TOKEN is required}"
POSTGRES_USER="${POSTGRES_USER:-impactweb}"
POSTGRES_DB="${POSTGRES_DB:-impactweb}"

for f in watermarks.json impactweb.sql twin-only.json; do
  [[ -f "${PAIR_DIR}/${f}" ]] || { echo "Missing ${PAIR_DIR}/${f}" >&2; exit 1; }
done

# 1. Refuse mismatched backup pair before touching stores
python3 - "${PAIR_DIR}/watermarks.json" "${PAIR_DIR}/twin-only.json" <<'PY'
import json, sys
wm = json.load(open(sys.argv[1]))["cutoffs"]
tw = json.load(open(sys.argv[2]))["cutoffs"]
if wm != tw:
    sys.stderr.write(f"Refusing mismatched backup pair: pg={wm} vs twin={tw}\n")
    sys.exit(1)
print("Pair cutoffs match:", wm)
PY

# 2. Restore Postgres dump
docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" < "${PAIR_DIR}/impactweb.sql"

# 3. Replay each exercise feed from IMPACT Web into Twin
EXERCISES=$(python3 -c 'import json,sys; print("\n".join(sorted(json.load(open(sys.argv[1]))["cutoffs"].keys())))' "${PAIR_DIR}/watermarks.json")
for ex_id in $EXERCISES; do
  curl -fsS -X POST "${TWIN_URL}/api/v1/sync?exercise_id=${ex_id}&use_ai=true" >/dev/null
done

# 4. Import twin-only state (server re-verifies cutoffs and refuses 409 on mismatch)
curl -fsS -X POST "${TWIN_URL}/api/v1/backup/import" \
  -H "Authorization: Bearer ${TWIN_SYNC_TOKEN}" \
  -H "Content-Type: application/json" \
  --data-binary "@${PAIR_DIR}/twin-only.json" >/dev/null

echo "Paired restore complete from ${PAIR_DIR}"
