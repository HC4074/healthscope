#!/usr/bin/env bash

set -Eeuo pipefail

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-healthscope-release-test}"
export HEALTHSCOPE_HTTP_PORT="${HEALTHSCOPE_HTTP_PORT:-18080}"

compose=(
  docker compose
  --file compose.production.yaml
  --file compose.release-test.yaml
)
base_url="http://127.0.0.1:${HEALTHSCOPE_HTTP_PORT}"
response_dir="$(mktemp -d)"

cleanup() {
  local exit_code=$?
  trap - EXIT

  if (( exit_code != 0 )); then
    "${compose[@]}" ps --all || true
    "${compose[@]}" logs --no-color database migrate api frontend || true
  fi

  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "${response_dir}"
  exit "${exit_code}"
}
trap cleanup EXIT

wait_for_status() {
  local expected_status=$1
  local url=$2
  local output_file=$3
  local actual_status

  for _ in {1..60}; do
    actual_status="$(
      curl --silent --show-error --output "${output_file}" --write-out '%{http_code}' "${url}" || true
    )"
    if [[ "${actual_status}" == "${expected_status}" ]]; then
      return 0
    fi
    sleep 1
  done

  echo "Expected HTTP ${expected_status} from ${url}; received ${actual_status}." >&2
  return 1
}

"${compose[@]}" config --format json >"${response_dir}/compose.json"
python - "${response_dir}/compose.json" "${HEALTHSCOPE_HTTP_PORT}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as config_file:
    services = json.load(config_file)["services"]

assert services["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
assert services["api"]["depends_on"]["database"]["condition"] == "service_healthy"
assert services["frontend"]["depends_on"]["api"]["condition"] == "service_healthy"
assert "--no-access-log" in services["api"]["command"]
assert not services["api"].get("ports")
assert not services["database"].get("ports")
assert str(services["frontend"]["ports"][0]["published"]) == sys.argv[2]
PY

"${compose[@]}" up --detach --wait --wait-timeout 180 database api frontend

curl --fail --silent --show-error \
  --dump-header "${response_dir}/health.headers" \
  "${base_url}/api/v1/health?release_probe=must-not-be-logged" >"${response_dir}/health.json"
python - "${response_dir}/health.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as response_file:
    response = json.load(response_file)

assert response["status"] == "ok"
assert response["environment"] == "production"
PY

python - "${response_dir}/health.headers" "${response_dir}/request-id.txt" <<'PY'
import re
import sys

with open(sys.argv[1], encoding="utf-8") as response_file:
    headers = response_file.read()

match = re.search(r"^X-Request-ID:\s*(\S+)\s*$", headers, re.IGNORECASE | re.MULTILINE)
assert match is not None
assert re.fullmatch(r"[0-9a-f]{32}", match.group(1))

with open(sys.argv[2], "w", encoding="utf-8") as request_id_file:
    request_id_file.write(match.group(1))
PY

"${compose[@]}" logs --no-color frontend api >"${response_dir}/request.log"
request_id="$(<"${response_dir}/request-id.txt")"
grep --quiet "\"request_id\":\"${request_id}\"" "${response_dir}/request.log"
grep --quiet '"event":"http_request_completed"' "${response_dir}/request.log"
grep --quiet '"event":"proxy_request_completed"' "${response_dir}/request.log"
if grep --quiet 'release_probe\|must-not-be-logged' "${response_dir}/request.log"; then
  echo "Production access logs included a query-string marker." >&2
  exit 1
fi

curl --fail --silent --show-error "${base_url}/api/v1/ready" >"${response_dir}/ready.json"
python - "${response_dir}/ready.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as response_file:
    response = json.load(response_file)

assert response == {"status": "ready", "database": "available"}
PY

curl --fail --silent --show-error "${base_url}/overview" >"${response_dir}/overview.html"
grep --quiet '<div id="root"></div>' "${response_dir}/overview.html"

current_revision="$("${compose[@]}" exec --no-TTY api alembic current)"
grep --quiet '(head)' <<<"${current_revision}"

"${compose[@]}" stop database
wait_for_status 503 "${base_url}/api/v1/ready" "${response_dir}/not-ready.json"
python - "${response_dir}/not-ready.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as response_file:
    response = json.load(response_file)

assert response == {"status": "not_ready", "database": "unavailable"}
PY

"${compose[@]}" start database
wait_for_status 200 "${base_url}/api/v1/ready" "${response_dir}/recovered.json"

if HEALTHSCOPE_RELEASE_TEST_DATABASE_URL="postgresql+psycopg://healthscope_release_test:healthscope-release-test-only@database:1/healthscope_release_test" \
  "${compose[@]}" run --rm --no-deps migrate >"${response_dir}/migration-failure.log" 2>&1; then
  echo "Migration unexpectedly succeeded with an unreachable database." >&2
  exit 1
fi

echo "Production release smoke and failure-path checks passed."
