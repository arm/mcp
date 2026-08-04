#!/usr/bin/env bash

set -euo pipefail

usage() {
    echo "Usage: $0 <package-name> [--allow-missing]" >&2
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
    usage
    exit 2
fi

package_name="$1"
allow_missing="false"

if [[ $# -eq 2 ]]; then
    if [[ "$2" != "--allow-missing" ]]; then
        usage
        exit 2
    fi
    allow_missing="true"
fi

: "${GH_TOKEN:?GH_TOKEN must be set}"
: "${GITHUB_REPOSITORY_OWNER:?GITHUB_REPOSITORY_OWNER must be set}"

image="ghcr.io/${GITHUB_REPOSITORY_OWNER}/${package_name}"
endpoint="/orgs/${GITHUB_REPOSITORY_OWNER}/packages/container/${package_name}"
error_file="$(mktemp)"
trap 'rm -f "${error_file}"' EXIT

if visibility="$(gh api "${endpoint}" --jq .visibility 2>"${error_file}")"; then
    if [[ "${visibility}" != "private" ]]; then
        echo "::error::Refusing to use ${image} because it is ${visibility}, not private."
        exit 1
    fi

    echo "Verified that ${image} is private."
    exit 0
fi

if grep -q "HTTP 404" "${error_file}"; then
    if [[ "${allow_missing}" == "true" ]]; then
        echo "${image} does not exist yet; the first GHCR publication will create it as private."
        exit 0
    fi

    echo "::error::Expected published package ${image} was not found."
    exit 1
fi

cat "${error_file}" >&2
exit 1
