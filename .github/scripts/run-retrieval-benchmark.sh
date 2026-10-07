#!/usr/bin/env bash
set -euo pipefail

generator_image="${1:?digest-pinned generator image required}"
candidate_image="${2:?immutable candidate image required}"
expected_image_id="${3:?candidate image ID required}"
digest_pattern='^[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}$'
image_id_pattern='^sha256:[0-9a-f]{64}$'

if [[ ! "$generator_image" =~ $digest_pattern ]] ||
   [[ ! "$candidate_image" =~ $digest_pattern && ! "$candidate_image" =~ $image_id_pattern ]] ||
   [[ ! "$expected_image_id" =~ $image_id_pattern ]]; then
  echo "::error::Benchmark images must use immutable sha256 identities." >&2
  exit 2
fi
actual_image_id="$(docker image inspect --format '{{.Id}}' "$candidate_image")"
if [[ "$actual_image_id" != "$expected_image_id" ]]; then
  echo "::error::Benchmark image differs from the built candidate." >&2
  exit 2
fi

corpus="${RUNNER_TEMP}/benchmark-corpus"
reports="${RUNNER_TEMP}/retrieval-benchmark"
baseline="${RUNNER_TEMP}/retrieval-baseline"
mkdir -p "$corpus" "$reports" "$baseline"

# The candidate is a scratch image containing data only; never start it.
container="$(docker create --network none "$candidate_image" /unused)"
trap 'docker rm -f "$container" >/dev/null' EXIT
docker cp "$container:/embedding-data/." "$corpus/"

# Only the report directory and disposable /tmp are writable. No host credentials
# or Docker socket are mounted, and no packages are installed during evaluation.
status=0
docker run --rm --pull=never --network=none --read-only \
  --cap-drop=ALL --security-opt=no-new-privileges \
  --user "$(id -u):$(id -g)" --tmpfs /tmp:rw,nosuid,nodev \
  --env HOME=/tmp --env PYTHONDONTWRITEBYTECODE=1 \
  --env HF_HUB_OFFLINE=1 --env TRANSFORMERS_OFFLINE=1 \
  --env "EVAL_TARGET=$candidate_image" --env GITHUB_SHA \
  --env GITHUB_STEP_SUMMARY=/reports/summary.md \
  --mount "type=bind,src=${GITHUB_WORKSPACE},dst=/workspace,readonly" \
  --mount "type=bind,src=$corpus,dst=/corpus,readonly" \
  --mount "type=bind,src=$baseline,dst=/baseline,readonly" \
  --mount "type=bind,src=$reports,dst=/reports" \
  "$generator_image" python /workspace/embedding-generation/evaluate_retrieval.py \
    --suite benchmark --top-k 5 \
    --metadata-path /corpus/metadata.json \
    --index-path /corpus/usearch_index.bin \
    --model-path /corpus/embedding-model \
    --baseline /baseline/benchmark.json \
    --output /reports/benchmark.json || status=$?

if [[ -f "$reports/summary.md" ]]; then
  cat "$reports/summary.md" >> "${GITHUB_STEP_SUMMARY}"
fi
exit "$status"
