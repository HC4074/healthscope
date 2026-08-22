#!/usr/bin/env bash

set -Eeuo pipefail

repository_root="$(git rev-parse --show-toplevel)"
script="${repository_root}/scripts/prepare-production-release.sh"
test_dir="$(mktemp -d)"
fake_bin="${test_dir}/bin"
mkdir -p "${fake_bin}"

cleanup() {
  rm -rf "${test_dir}"
}
trap cleanup EXIT

cat >"${fake_bin}/gh" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

expected_sha="0123456789abcdef0123456789abcdef01234567"
arguments=" $* "

[[ "${arguments}" == *" attestation verify "* ]]
[[ "${arguments}" == *" --repo HC4074/healthscope "* ]]
[[ "${arguments}" == *" --signer-workflow HC4074/healthscope/.github/workflows/deployment-ci.yml "* ]]
[[ "${arguments}" == *" --source-digest ${expected_sha} "* ]]
[[ "${arguments}" == *" --source-ref refs/heads/main "* ]]
[[ "${arguments}" == *" --deny-self-hosted-runners "* ]]

if [[ "${arguments}" == *"healthscope-api:sha-${expected_sha}"* ]]; then
  image="ghcr.io/hc4074/healthscope-api"
  digest="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
else
  image="ghcr.io/hc4074/healthscope-frontend"
  digest="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
fi

if [[ "${HEALTHSCOPE_TEST_MISMATCH:-false}" == "true" ]] && \
  [[ "${arguments}" == *"https://spdx.dev/Document/v2.3"* ]]; then
  digest="cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
fi

printf '%s@sha256:%s\n' "${image}" "${digest}"
EOF
chmod +x "${fake_bin}/gh"

release_sha="0123456789abcdef0123456789abcdef01234567"
expected_output="HEALTHSCOPE_API_IMAGE=ghcr.io/hc4074/healthscope-api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
HEALTHSCOPE_FRONTEND_IMAGE=ghcr.io/hc4074/healthscope-frontend@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

actual_output="$(PATH="${fake_bin}:${PATH}" "${script}" "${release_sha}")"
[[ "${actual_output}" == "${expected_output}" ]]

if PATH="${fake_bin}:${PATH}" "${script}" short-sha >"${test_dir}/invalid.log" 2>&1; then
  echo "Release preparation accepted an invalid commit SHA." >&2
  exit 1
fi
grep --quiet "exactly 40 lowercase hexadecimal" "${test_dir}/invalid.log"

if HEALTHSCOPE_TEST_MISMATCH=true PATH="${fake_bin}:${PATH}" \
  "${script}" "${release_sha}" >"${test_dir}/mismatch.log" 2>&1; then
  echo "Release preparation accepted mismatched attestations." >&2
  exit 1
fi
grep --quiet "Provenance and SBOM attestations disagree" "${test_dir}/mismatch.log"

echo "Production release preparation checks passed."
