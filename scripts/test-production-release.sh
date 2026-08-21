#!/usr/bin/env bash

set -Eeuo pipefail

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-healthscope-release-test}"
export HEALTHSCOPE_HTTP_PORT="${HEALTHSCOPE_HTTP_PORT:-18080}"
production_env_file="${HEALTHSCOPE_ENV_FILE:-.env.production}"

compose=(
  docker compose
  --env-file "${production_env_file}"
  --file compose.production.yaml
  --file compose.release-test.yaml
  --profile operations
)
base_url="http://127.0.0.1:${HEALTHSCOPE_HTTP_PORT}"
response_dir="$(mktemp -d)"
tls_dir="${response_dir}/postgres-tls"
mkdir -p "${tls_dir}"
openssl req -new -x509 -days 1 -nodes \
  -out "${tls_dir}/server.crt" \
  -keyout "${tls_dir}/server.key" \
  -subj "/CN=database" >/dev/null 2>&1
chmod 600 "${tls_dir}/server.key"
export HEALTHSCOPE_RELEASE_TEST_TLS_DIR="${tls_dir}"

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
assert services["verify-restore"]["command"] == ["healthscope-verify-restore"]
assert all("build" not in service for service in services.values())
assert not services["api"].get("ports")
assert not services["database"].get("ports")
assert str(services["frontend"]["ports"][0]["published"]) == sys.argv[2]
PY

expect_configuration_failure() {
  local name=$1
  shift

  if "${compose[@]}" run --rm --no-deps "$@" api \
    python -c 'import healthscope.main' >"${response_dir}/${name}.log" 2>&1; then
    echo "Production container accepted unsafe ${name} configuration." >&2
    return 1
  fi
}

expect_configuration_failure "debug" -e HEALTHSCOPE_DEBUG=true
expect_configuration_failure "database-backend" -e HEALTHSCOPE_DATABASE_URL=sqlite:///healthscope.db
expect_configuration_failure \
  "database-tls" \
  -e HEALTHSCOPE_DATABASE_URL=postgresql+psycopg://healthscope:unique-release-value@database/healthscope
expect_configuration_failure \
  "database-placeholder" \
  -e HEALTHSCOPE_DATABASE_URL=postgresql+psycopg://healthscope:replace-with-a-secret@db.internal/healthscope?sslmode=require

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
assert re.search(
    r"^Content-Security-Policy:\s*default-src 'self'",
    headers,
    re.IGNORECASE | re.MULTILINE,
)
assert re.search(r"^X-Content-Type-Options:\s*nosniff\s*$", headers, re.IGNORECASE | re.MULTILINE)
assert not re.search(r"^Cache-Control:", headers, re.IGNORECASE | re.MULTILINE)

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

curl --fail --silent --show-error \
  --dump-header "${response_dir}/overview.headers" \
  "${base_url}/overview" >"${response_dir}/overview.html"
grep --quiet '<div id="root"></div>' "${response_dir}/overview.html"
python - \
  "${response_dir}/overview.headers" \
  "${response_dir}/overview.html" \
  "${response_dir}/asset-url.txt" <<'PY'
import re
import sys


def read_headers(path: str) -> dict[str, str]:
    with open(path, encoding="utf-8") as response_file:
        lines = response_file.read().splitlines()[1:]
    return {
        name.lower(): value.strip()
        for line in lines
        if ":" in line
        for name, value in [line.split(":", 1)]
    }


headers = read_headers(sys.argv[1])
assert headers["cache-control"] == "no-cache"
assert headers["content-security-policy"] == (
    "default-src 'self'; base-uri 'self'; connect-src 'self'; form-action 'self'; "
    "frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'"
)
assert headers["cross-origin-opener-policy"] == "same-origin"
assert headers["permissions-policy"] == "camera=(), geolocation=(), microphone=()"
assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
assert headers["x-content-type-options"] == "nosniff"
assert headers["x-frame-options"] == "DENY"

with open(sys.argv[2], encoding="utf-8") as response_file:
    document = response_file.read()
asset_match = re.search(r'<script[^>]+src="([^"]+\.js)"', document)
assert asset_match is not None
with open(sys.argv[3], "w", encoding="utf-8") as asset_file:
    asset_file.write(asset_match.group(1))
PY

asset_url="$(<"${response_dir}/asset-url.txt")"
curl --fail --silent --show-error \
  --dump-header "${response_dir}/asset.headers" \
  "${base_url}${asset_url}" >/dev/null
python - "${response_dir}/asset.headers" <<'PY'
import sys

with open(sys.argv[1], encoding="utf-8") as response_file:
    headers = {
        name.lower(): value.strip()
        for line in response_file.read().splitlines()[1:]
        if ":" in line
        for name, value in [line.split(":", 1)]
    }

assert headers["cache-control"] == "public, max-age=31536000, immutable"
assert headers["content-security-policy"].startswith("default-src 'self'")
assert headers["x-content-type-options"] == "nosniff"
PY

HEALTHSCOPE_E2E_BASE_URL="${base_url}" npm --prefix frontend run test:e2e

current_revision="$("${compose[@]}" exec --no-TTY api alembic current)"
grep --quiet '(head)' <<<"${current_revision}"

"${compose[@]}" exec --no-TTY api python - <<'PY'
from healthscope.config import get_settings
from healthscope.database import create_database_engine
from healthscope.services.ingestion_lock import (
    HospitalIngestionAlreadyRunningError,
    acquire_hospital_ingestion_lock,
)

settings = get_settings()
engine = create_database_engine(settings.database_url)
try:
    with acquire_hospital_ingestion_lock(
        engine,
        source_dataset_id=settings.cms_hospital_dataset_id,
    ):
        try:
            with acquire_hospital_ingestion_lock(
                engine,
                source_dataset_id=settings.cms_hospital_dataset_id,
            ):
                raise AssertionError("Overlapping ingestion acquired the same dataset lock")
        except HospitalIngestionAlreadyRunningError:
            pass
finally:
    engine.dispose()
PY

if "${compose[@]}" run --rm --no-deps verify-restore \
  >"${response_dir}/empty-restore.log" 2>&1; then
  echo "Restore verification unexpectedly accepted an empty migrated database." >&2
  exit 1
fi
grep --quiet 'No completed hospital snapshot' "${response_dir}/empty-restore.log"

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

if HEALTHSCOPE_RELEASE_TEST_DATABASE_URL="postgresql+psycopg://healthscope_release_test:healthscope-release-test-only@database:1/healthscope_release_test?sslmode=require" \
  "${compose[@]}" run --rm --no-deps migrate >"${response_dir}/migration-failure.log" 2>&1; then
  echo "Migration unexpectedly succeeded with an unreachable database." >&2
  exit 1
fi

echo "Production release smoke and failure-path checks passed."
