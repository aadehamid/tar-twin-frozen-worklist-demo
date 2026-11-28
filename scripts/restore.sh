#!/usr/bin/env bash
# Paired restore of IMPACT Web (Postgres) and Twin-only state with cutoff verification (docs/hosting.md section 5).
set -euo pipefail

PAIR_DIR="${1:?Usage: scripts/restore.sh <backup-pair-dir>}"
ENV_FILE="${ENV_FILE:-.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
IMPACTWEB_URL="${IMPACTWEB_URL:-http://127.0.0.1:18001}"
TWIN_URL="${TWIN_URL:-http://127.0.0.1:18002}"
TWIN_SYNC_TOKEN="${TWIN_SYNC_TOKEN:-local-dev-twin-sync-token}"
FACILITATOR_TOKEN="${FACILITATOR_TOKEN:-}"
FACILITATOR_EMAIL="${FACILITATOR_EMAIL:-facilitator@demo.local}"
FACILITATOR_PASSWORD="${FACILITATOR_PASSWORD:-demo-pass-2028}"
EDGE_AUTH_SECRET="${EDGE_AUTH_SECRET:-}"
POSTGRES_USER="${POSTGRES_USER:-impactweb}"
POSTGRES_DB="${POSTGRES_DB:-impactweb}"

for f in watermarks.json impactweb.sql twin-only.json; do
  [[ -f "${PAIR_DIR}/${f}" ]] || { echo "Missing ${PAIR_DIR}/${f}" >&2; exit 1; }
done

AUTH_MODE=$(curl -fsS "${IMPACTWEB_URL}/api/v1/auth/mode" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("auth_mode", "local"))')

auth_admin_headers=()
if [[ "$AUTH_MODE" == "exe" ]]; then
  if [[ -z "$EDGE_AUTH_SECRET" ]]; then
    echo "ERROR: AUTH_MODE=exe requires EDGE_AUTH_SECRET (and FACILITATOR_EMAIL) to toggle maintenance mode." >&2
    exit 1
  fi
  auth_admin_headers=(-H "X-Edge-Auth: ${EDGE_AUTH_SECRET}" -H "X-ExeDev-Email: ${FACILITATOR_EMAIL}")
else
  if [[ -z "$FACILITATOR_TOKEN" ]]; then
    if [[ -z "$FACILITATOR_PASSWORD" ]]; then
      echo "ERROR: AUTH_MODE=local requires FACILITATOR_TOKEN or FACILITATOR_PASSWORD to toggle maintenance mode." >&2
      exit 1
    fi
    FACILITATOR_TOKEN=$(curl -fsS -X POST "${IMPACTWEB_URL}/api/v1/auth/login" \
      -H "Content-Type: application/json" \
      -d "$(python3 -c 'import json,sys; print(json.dumps({"email": sys.argv[1], "password": sys.argv[2]}))' "$FACILITATOR_EMAIL" "$FACILITATOR_PASSWORD")" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
  fi
  auth_admin_headers=(-H "Authorization: Bearer ${FACILITATOR_TOKEN}")
fi

cleanup() {
  curl -fsS -X POST "${IMPACTWEB_URL}/api/v1/admin/maintenance" \
    -H "Content-Type: application/json" \
    "${auth_admin_headers[@]}" \
    -d '{"enabled": false}' >/dev/null 2>&1 || true
}
trap cleanup EXIT

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

# 2. Enter maintenance mode and restore Postgres dump
MAINT_RESP=$(curl -fsS -X POST "${IMPACTWEB_URL}/api/v1/admin/maintenance" \
  -H "Content-Type: application/json" \
  "${auth_admin_headers[@]}" \
  -d '{"enabled": true}')
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d.get("maintenance_mode") is True and d.get("in_flight_writes", 0) == 0, d' "$MAINT_RESP"

docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" < "${PAIR_DIR}/impactweb.sql"

# 3. Reset Twin exercise scope to seq 0 before replaying each restored feed from start
EXERCISES=$(python3 -c 'import json,sys; print("\n".join(sorted(json.load(open(sys.argv[1]))["cutoffs"].keys())))' "${PAIR_DIR}/watermarks.json")
for ex_id in $EXERCISES; do
  curl -fsS -X POST -H "Authorization: Bearer ${TWIN_SYNC_TOKEN}" "${TWIN_URL}/api/v1/backup/reset-scope?exercise_id=${ex_id}" >/dev/null
  curl -fsS -X POST -H "Authorization: Bearer ${TWIN_SYNC_TOKEN}" "${TWIN_URL}/api/v1/sync?exercise_id=${ex_id}&use_ai=true" >/dev/null
done

# 4. Import twin-only state (server re-verifies cutoffs and refuses 409 on mismatch)
curl -fsS -X POST "${TWIN_URL}/api/v1/backup/import" \
  -H "Authorization: Bearer ${TWIN_SYNC_TOKEN}" \
  -H "Content-Type: application/json" \
  --data-binary "@${PAIR_DIR}/twin-only.json" >/dev/null

echo "Paired restore complete from ${PAIR_DIR}"
