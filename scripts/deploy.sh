#!/usr/bin/env bash
# Deploy prebuilt tagged images to the exe.dev VM and enforce docs/hosting.md sections 2 & 6 checks.
# Never builds Vite/Docker images on the 4 GB VM; images are built in CI and pulled from ghcr.io.
set -euo pipefail

VM_HOST="${VM_HOST:-tar-frozen-work-list.exe.xyz}"
REMOTE_DIR="${REMOTE_DIR:-/opt/tar-twin}"
REPO_URL="${REPO_URL:-https://github.com/aadehamid/tar-twin-frozen-worklist-demo.git}"
GIT_REF="${1:-main}"
IMAGE_TAG="${2:-${GIT_REF}}"

echo "==> Deploying ref ${GIT_REF} (image tag ${IMAGE_TAG}) to ${VM_HOST}:${REMOTE_DIR}"
ssh "${VM_HOST}" bash -s -- "${REMOTE_DIR}" "${REPO_URL}" "${GIT_REF}" "${IMAGE_TAG}" <<'REMOTE'
set -euo pipefail
REMOTE_DIR="$1"
REPO_URL="$2"
GIT_REF="$3"
IMAGE_TAG="$4"

sudo mkdir -p "${REMOTE_DIR}"
sudo chown -R "$(id -u):$(id -g)" "${REMOTE_DIR}"

if [[ ! -d "${REMOTE_DIR}/repo/.git" ]]; then
  git clone "${REPO_URL}" "${REMOTE_DIR}/repo"
fi

cd "${REMOTE_DIR}/repo"
git fetch --all --tags
git checkout "${GIT_REF}"
if git show-ref --verify --quiet "refs/remotes/origin/${GIT_REF}"; then
  git reset --hard "origin/${GIT_REF}"
fi

if [[ ! -f "${REMOTE_DIR}/.env" ]]; then
  echo "ERROR: ${REMOTE_DIR}/.env not found. Create it with mode 600 before deploying." >&2
  exit 1
fi

PERM=$(stat -c "%a" "${REMOTE_DIR}/.env")
if [[ "${PERM}" != "600" ]]; then
  echo "ERROR: ${REMOTE_DIR}/.env permissions are ${PERM}, expected 600." >&2
  exit 1
fi

export IMPACTWEB_IMAGE="ghcr.io/aadehamid/tar-twin-impactweb:${IMAGE_TAG}"
export TWIN_IMAGE="ghcr.io/aadehamid/tar-twin-twin:${IMAGE_TAG}"
export NEO4J_IMAGE="ghcr.io/aadehamid/tar-twin-neo4j:${IMAGE_TAG}"

echo "==> Checking VM disk space"
df -h /

echo "==> Taking paired pre-deploy backup if stack is currently running (docs/hosting.md section 5)"
if curl -fsS http://127.0.0.1:18001/api/v1/utils/health-check/ >/dev/null 2>&1 \
   && curl -fsS http://127.0.0.1:18002/api/v1/utils/health-check/ >/dev/null 2>&1; then
  ENV_FILE="${REMOTE_DIR}/.env" bash "${REMOTE_DIR}/repo/scripts/backup.sh" "${REMOTE_DIR}/backups" </dev/null
else
  echo "No running stack detected yet (initial deploy); skipping pre-deploy backup."
fi

echo "==> Pulling prebuilt images (no VM builds per docs/hosting.md section 2)"
docker compose --env-file "${REMOTE_DIR}/.env" pull </dev/null

echo "==> Restarting stack with --no-build"
docker compose --env-file "${REMOTE_DIR}/.env" up -d --no-build --remove-orphans </dev/null
docker compose --env-file "${REMOTE_DIR}/.env" restart edge </dev/null

echo "==> Waiting for health checks on /impactweb/ and /twin/"
HEALTHY=0
for i in $(seq 1 30); do
  if curl -fsS -H "Host: tar-frozen-work-list.exe.xyz" http://127.0.0.1:8000/impactweb/api/v1/utils/health-check/ >/dev/null 2>&1 \
     && curl -fsS -H "Host: tar-frozen-work-list.exe.xyz" http://127.0.0.1:8000/twin/api/v1/utils/health-check/ >/dev/null 2>&1; then
    HEALTHY=1
    break
  fi
  sleep 2
done
if [[ "${HEALTHY}" -ne 1 ]]; then
  echo "ERROR: Health checks failed after deploy" >&2
  exit 1
fi

curl -fsS -H "Host: tar-frozen-work-list.exe.xyz" http://127.0.0.1:8000/ >/dev/null

echo "==> Enforcing docs/hosting.md section 6 isolation & port checks (fail closed)"
# 1. Verify twin holds zero Postgres credentials
if docker compose --env-file "${REMOTE_DIR}/.env" exec -T twin env </dev/null | grep -qE '^(POSTGRES_|DATABASE_URL)='; then
  echo "ERROR: twin container contains Postgres credentials!" >&2
  exit 1
fi

# 2. Verify docker compose config network_mode and port mappings strictly
CFG_JSON=$(docker compose --env-file "${REMOTE_DIR}/.env" config --format json </dev/null)
PS_JSON=$(docker compose --env-file "${REMOTE_DIR}/.env" ps --format json </dev/null)

python3 - "$CFG_JSON" "$PS_JSON" <<'PY'
import json, sys

cfg = json.loads(sys.argv[1])
svcs = cfg.get("services") or {}

# Only edge may use network_mode: host
for name, svc in svcs.items():
    nm = svc.get("network_mode")
    if name == "edge":
        assert nm == "host", f"edge must use network_mode: host, got {nm!r}"
    else:
        assert nm != "host", f"service {name} must NOT use network_mode: host"

# Validate actual published ports from docker compose ps
ps_lines = [line.strip() for line in sys.argv[2].splitlines() if line.strip()]
records = []
if ps_lines and ps_lines[0].startswith("["):
    records = json.loads(sys.argv[2])
else:
    records = [json.loads(line) for line in ps_lines]

expected_pub = {
    "edge": set(),
    "impactweb": {("127.0.0.1", 18001, 8000)},
    "twin": {("127.0.0.1", 18002, 8000)},
    "postgres": set(),
    "neo4j": set(),
}
for rec in records:
    svc_name = rec.get("Service")
    pubs = set()
    for p in rec.get("Publishers") or []:
        if p.get("PublishedPort"):
            pubs.add((p.get("URL", ""), int(p["PublishedPort"]), int(p["TargetPort"])))
    if svc_name in expected_pub and pubs != expected_pub[svc_name]:
        sys.stderr.write(f"ERROR: unexpected published ports for {svc_name}: got {pubs}, expected {expected_pub[svc_name]}\n")
        sys.exit(1)

print("Hosting section 6 port and network isolation checks PASSED.")
PY

docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" </dev/null

echo "==> Pruning dangling images to protect VM disk budget"
docker image prune -f </dev/null >/dev/null

echo "Deploy verified on $(hostname) at commit $(git rev-parse --short HEAD)."
REMOTE
