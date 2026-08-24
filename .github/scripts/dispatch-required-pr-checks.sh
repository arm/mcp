#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "usage: $0 <branch>" >&2
  exit 2
fi

branch="$1"
# Keep this list synchronized with the status checks required by the main
# branch ruleset. Each workflow must support workflow_dispatch.
workflows=(
  integration-tests.yml
  embedding-unit-tests.yml
  scorecard.yml
)

for workflow in "${workflows[@]}"; do
  gh workflow run "${workflow}" --ref "${branch}"
  echo "Dispatched ${workflow} for ${branch}."
done
