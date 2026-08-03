#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
embedding_dir="$repo_root/embedding-generation"

kb_endpoint_repo="${KB_ENDPOINT_REPO:-"$repo_root/../knowledge-base-endpoint"}"
fetch_script="$kb_endpoint_repo/scripts/fetch-latest-embeddings.sh"

eval_file="${EVAL_FILE:-"$embedding_dir/eval_questions.json"}"
top_k="${TOP_K:-5}"
embedding_model_dir="${EMBEDDING_MODEL_DIR:-"$embedding_dir/.cache/embedding-model"}"
embeddings_image="${EMBEDDINGS_IMAGE:-armlimited/arm-mcp:embeddings-latest}"

if [[ ! -x "$fetch_script" ]]; then
  echo "Could not find executable fetch script: $fetch_script" >&2
  echo "Set KB_ENDPOINT_REPO=/path/to/knowledge-base-endpoint if needed." >&2
  exit 1
fi

data_dir="${DATA_DIR:-}"
cleanup=0

if [[ -z "$data_dir" ]]; then
  data_dir="$(mktemp -d "${TMPDIR:-/tmp}/mcp-embeddings-latest.XXXXXX")"
  cleanup=1
fi

if [[ "$cleanup" -eq 1 ]]; then
  trap 'rm -rf "$data_dir"' EXIT
fi

echo "Fetching $embeddings_image into $data_dir"
DATA_DIR="$data_dir" EMBEDDINGS_IMAGE="$embeddings_image" "$fetch_script"

echo "Evaluating $eval_file"
cd "$embedding_dir"

echo "Acquiring locked embedding model in $embedding_model_dir"
python3 acquire-model.py \
  --lock embedding-model.lock.json \
  --output "$embedding_model_dir"

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python3 evaluate_retrieval.py \
  --metadata-path "$data_dir/metadata.json" \
  --index-path "$data_dir/usearch_index.bin" \
  --eval-path "$eval_file" \
  --model-path "$embedding_model_dir" \
  --top-k "$top_k"
