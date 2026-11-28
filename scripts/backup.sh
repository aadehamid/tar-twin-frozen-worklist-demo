#!/usr/bin/env bash
# Paired watermark backup of IMPACT Web (Postgres) and Twin-only state (docs/hosting.md section 5).
set -euo pipefail

BACKUP_DIR="${1:-/opt/tar-twin/backups}"
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

# Detect server auth mode so local mode uses JWT bearer auth and exe mode uses edge auth headers.
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

STAMP=$(date -u +"%Y%m%dT%H%M%SZ")
OUT_DIR="${BACKUP_DIR}/${STAMP}"
mkdir -p "$OUT_DIR"

cleanup() {
  curl -fsS -X POST "${IMPACTWEB_URL}/api/v1/admin/maintenance" \
    -H "Content-Type: application/json" \
    "${auth_admin_headers[@]}" \
    -d '{"enabled": false}' >/dev/null 2>&1 || true
}
trap cleanup EXIT

# 1. Enter maintenance mode (atomically blocks new writes and drains in-flight writes)
MAINT_RESP=$(curl -fsS -X POST "${IMPACTWEB_URL}/api/v1/admin/maintenance" \
  -H "Content-Type: application/json" \
  "${auth_admin_headers[@]}" \
  -d '{"enabled": true}')
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d.get("maintenance_mode") is True and d.get("in_flight_writes", 0) == 0, d' "$MAINT_RESP"

# 2. Record per-exercise change-feed cutoffs
WM_JSON=$(curl -fsS -H "Authorization: Bearer ${TWIN_SYNC_TOKEN}" "${IMPACTWEB_URL}/api/v1/admin/watermarks")
printf '%s\n' "$WM_JSON" > "${OUT_DIR}/watermarks.json"

# 3. Drain twin sync for every exercise up to its cutoff
EXERCISES=$(python3 -c 'import json,sys; print("\n".join(sorted((json.loads(sys.argv[1]).get("cutoffs") or {}).keys())))' "$WM_JSON")
for ex_id in $EXERCISES; do
  curl -fsS -X POST -H "Authorization: Bearer ${TWIN_SYNC_TOKEN}" "${TWIN_URL}/api/v1/sync?exercise_id=${ex_id}" >/dev/null
done

# 4. Dump Postgres and export twin-only state
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --clean --if-exists </dev/null > "${OUT_DIR}/impactweb.sql"
curl -fsS -H "Authorization: Bearer ${TWIN_SYNC_TOKEN}" "${TWIN_URL}/api/v1/backup/export" > "${OUT_DIR}/twin-only.json"

# 5. Verify both files carry matching per-exercise cutoffs
python3 - "$OUT_DIR/watermarks.json" "$OUT_DIR/twin-only.json" <<'PY'
import json, sys
wm = json.load(open(sys.argv[1]))["cutoffs"]
tw = json.load(open(sys.argv[2]))["cutoffs"]
for ex_id, seq in wm.items():
    if int(tw.get(ex_id, -1)) != int(seq):
        sys.stderr.write(f"Cutoff mismatch for {ex_id}: pg={seq}, twin={tw.get(ex_id)}\n")
        sys.exit(1)
print("Paired backup verified:", wm)
PY

echo "Backup written to ${OUT_DIR}"
