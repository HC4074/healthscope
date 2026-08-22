#!/usr/bin/env bash

set -Eeuo pipefail

repository="HC4074/healthscope"
source_ref="refs/heads/main"
signer_workflow="HC4074/healthscope/.github/workflows/deployment-ci.yml"

usage() {
  echo "Usage: $0 <full-40-character-commit-sha>" >&2
}

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

release_sha=$1
if [[ ! "${release_sha}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Release SHA must contain exactly 40 lowercase hexadecimal characters." >&2
  exit 2
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI (gh) is required to verify release attestations." >&2
  exit 2
fi

verify_attestation() {
  local image_tag=$1
  local predicate_type=$2

  gh attestation verify \
    "oci://${image_tag}" \
    --repo "${repository}" \
    --signer-workflow "${signer_workflow}" \
    --source-digest "${release_sha}" \
    --source-ref "${source_ref}" \
    --deny-self-hosted-runners \
    --predicate-type "${predicate_type}" \
    --format json \
    --jq '.[].verificationResult.statement.subject[] | "\(.name)@sha256:\(.digest.sha256)"'
}

resolve_image() {
  local image_name=$1
  local image_tag="ghcr.io/hc4074/healthscope-${image_name}:sha-${release_sha}"
  local provenance_ref
  local sbom_ref

  provenance_ref="$(verify_attestation "${image_tag}" "https://slsa.dev/provenance/v1")"
  sbom_ref="$(verify_attestation "${image_tag}" "https://spdx.dev/Document/v2.3")"

  if [[ ! "${provenance_ref}" =~ ^ghcr\.io/hc4074/healthscope-${image_name}@sha256:[0-9a-f]{64}$ ]]; then
    echo "Verified provenance returned an unexpected ${image_name} subject." >&2
    exit 1
  fi
  if [[ "${provenance_ref}" != "${sbom_ref}" ]]; then
    echo "Provenance and SBOM attestations disagree for the ${image_name} image." >&2
    exit 1
  fi

  printf '%s' "${provenance_ref}"
}

api_image="$(resolve_image api)"
frontend_image="$(resolve_image frontend)"

cat <<EOF
HEALTHSCOPE_API_IMAGE=${api_image}
HEALTHSCOPE_FRONTEND_IMAGE=${frontend_image}
EOF
