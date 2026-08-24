#!/usr/bin/env bash
set -euo pipefail

for required in \
  PROMOTION_BRANCH \
  COMMIT_MESSAGE \
  PR_TITLE \
  PR_BODY \
  SUMMARY_TITLE \
  CANDIDATE \
  GH_TOKEN; do
  if [ -z "${!required:-}" ]; then
    echo "::error::${required} is required to propose a pin update."
    exit 1
  fi
done
if [ "$#" -eq 0 ]; then
  echo "::error::At least one generated pin file must be selected."
  exit 1
fi

files=("$@")
git checkout -B "${PROMOTION_BRANCH}"
if git diff --quiet -- "${files[@]}"; then
  echo "The generated artifact already matches the checked-in pin." \
    >> "${GITHUB_STEP_SUMMARY}"
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add -- "${files[@]}"
git commit -m "${COMMIT_MESSAGE}"

git fetch origin \
  "${PROMOTION_BRANCH}:refs/remotes/origin/${PROMOTION_BRANCH}" || true
git push --force-with-lease origin "HEAD:refs/heads/${PROMOTION_BRANCH}"

body_file="${RUNNER_TEMP}/pin-promotion-${GITHUB_RUN_ID}.md"
printf '%s\n' "${PR_BODY}" > "${body_file}"

pr_url="$(gh pr list \
  --base main \
  --head "${PROMOTION_BRANCH}" \
  --state open \
  --json url \
  --jq '.[0].url // empty')"
if [ -z "${pr_url}" ]; then
  pr_url="$(gh pr create \
    --base main \
    --head "${PROMOTION_BRANCH}" \
    --title "${PR_TITLE}" \
    --body-file "${body_file}")"
else
  gh pr edit "${pr_url}" \
    --title "${PR_TITLE}" \
    --body-file "${body_file}"
fi

.github/scripts/dispatch-required-pr-checks.sh "${PROMOTION_BRANCH}"

{
  echo "### ${SUMMARY_TITLE}"
  echo ""
  echo "- Pull request: ${pr_url}"
  echo "- Candidate: \`${CANDIDATE}\`"
  if [ -n "${SUMMARY_DETAILS:-}" ]; then
    printf '%s\n' "${SUMMARY_DETAILS}"
  fi
} >> "${GITHUB_STEP_SUMMARY}"
