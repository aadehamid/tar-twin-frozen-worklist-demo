#!/usr/bin/env bash
# Deploy the Unit 200 demo stack to the exe.dev VM and enforce docs/hosting.md section 6 checks.
set -euo pipefail

VM_HOST="${VM_HOST:-tar-frozen-work-list.exe.xyz}"
REMOTE_DIR="${REMOTE_DIR:-/opt/tar-twin}"
REPO_URL="${REPO_URL:-https://github.com/aadehamid/tar-twin-frozen-worklist-demo.git}"
GIT_REF="${1:-main}"

echo "==> Deploying ref ${GIT_REF} to ${VM_HOST}:${REMOTE_DIR}"
ssh "${VM_HOST}" bash -s -- "${REMOTE_DIR}" "${REPO_URL}" "${GIT_REF}" <<'REMOTE'
set -euo pipefail
REMOTE_DIR="$1"
REPO_URL="$2"
GIT_REF="$3"

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

echo "==> Checking VM disk space"
df -h /

echo "==> Bringing up Docker Compose stack"
docker compose --env-file "${REMOTE_DIR}/.env" up -d --build --remove-orphans

echo "==> Waiting for health checks on /impactweb/ and /twin/"
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/impactweb/api/v1/utils/health-check/ >/dev/null 2>&1 \
     && curl -fsS http://127.0.0.1:8000/twin/api/v1/utils/health-check/ >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

curl -fsS http://127.0.0.1:8000/ >/dev/null
curl -fsS http://127.0.0.1:8000/impactweb/api/v1/utils/health-check/ >/dev/null
curl -fsS http://127.0.0.1:8000/twin/api/v1/utils/health-check/ >/dev/null

echo "==> Enforcing docs/hosting.md section 6 isolation checks"
# 1. Verify twin holds zero Postgres credentials
if docker compose --env-file "${REMOTE_DIR}/.env" exec -T twin env | grep -qE '^(POSTGRES_|DATABASE_URL)='; then
  echo "ERROR: twin container contains Postgres credentials!" >&2
  exit 1
fi

# 2. Verify only edge uses host network mode and only expected ports are published
docker compose --env-file "${REMOTE_DIR}/.env" ps
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}"

echo "==> Pruning dangling images to protect VM disk budget"
docker image prune -f >/dev/null

echo "Deploy verified on $(hostname) at commit $(git rev-parse --short HEAD)."
REMOTE
