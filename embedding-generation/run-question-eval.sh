#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

sources_file="vector-db-sources.csv"
eval_file="eval_questions.json"
top_k="5"
python_bin="${PYTHON:-python3}"
embedding_base_image="${EMBEDDING_BASE_IMAGE:-armlimited/arm-mcp:mcp-embedding-base}"
embedding_model="all-MiniLM-L6-v2"
refresh_intrinsic_chunks=0
skip_intrinsic_copy=0

usage() {
  cat <<'USAGE'
Usage: ./run-question-eval.sh [options]

Build the local vector store from vector-db-sources.csv and run retrieval eval.

Options:
  --sources FILE                 CSV to chunk (default: vector-db-sources.csv)
  --eval FILE                    Eval questions JSON (default: eval_questions.json)
  --top-k N                      Number of search results to evaluate (default: 5)
  --refresh-intrinsic-chunks     Re-copy intrinsic chunks from the embedding base image
  --skip-intrinsic-copy          Use the existing intrinsic_chunks directory as-is
  -h, --help                     Show this help

Environment:
  PYTHON                         Python executable (default: python3)
  EMBEDDING_BASE_IMAGE           Image with /embedding-data/intrinsic_chunks
                                 (default: armlimited/arm-mcp:mcp-embedding-base)
USAGE
}

require_value() {
  if [[ $# -lt 2 || "${2:-}" == --* ]]; then
    echo "Missing value for $1" >&2
    usage >&2
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sources)
      require_value "$@"
      sources_file="$2"
      shift 2
      ;;
    --eval)
      require_value "$@"
      eval_file="$2"
      shift 2
      ;;
    --top-k)
      require_value "$@"
      top_k="$2"
      shift 2
      ;;
    --refresh-intrinsic-chunks)
      refresh_intrinsic_chunks=1
      shift
      ;;
    --skip-intrinsic-copy)
      skip_intrinsic_copy=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$sources_file" ]]; then
  echo "Sources CSV not found: $sources_file" >&2
  exit 1
fi

if [[ ! -f "$eval_file" ]]; then
  echo "Eval questions file not found: $eval_file" >&2
  exit 1
fi

if [[ "$skip_intrinsic_copy" -eq 0 ]]; then
  if [[ "$refresh_intrinsic_chunks" -eq 1 ]]; then
    rm -rf intrinsic_chunks
  fi

  if ! compgen -G "intrinsic_chunks/*.yaml" >/dev/null; then
    mkdir -p intrinsic_chunks
    echo "Copying intrinsic chunks from $embedding_base_image"
    docker run --rm \
      --entrypoint sh \
      -v "$PWD/intrinsic_chunks:/out" \
      "$embedding_base_image" \
      -c 'cp -a /embedding-data/intrinsic_chunks/. /out/'
  else
    echo "Using existing intrinsic_chunks directory"
  fi
fi

echo "Generating chunks from $sources_file"
"$python_bin" generate-chunks.py "$sources_file"

echo "Ensuring embedding model is cached locally"
"$python_bin" -c "from sentence_transformers import SentenceTransformer; import os; SentenceTransformer('$embedding_model', cache_folder=os.getenv('SENTENCE_TRANSFORMERS_HOME') or None)"

echo "Creating local vector store"
"$python_bin" local_vectorstore_creation.py

echo "Evaluating retrieval questions from $eval_file"
"$python_bin" evaluate_retrieval.py --eval-path "$eval_file" --model-name "$embedding_model" --top-k "$top_k"
