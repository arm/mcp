"""Run a retrieval evaluation over the local metadata and index."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sentence_transformers import SentenceTransformer


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arm_kb_search import (  # noqa: E402
    build_bm25_index,
    deduplicate_urls,
    embedding_dimension,
    hybrid_search,
    load_metadata,
    load_usearch_index,
)
from arm_kb_search.evaluation import evaluate_retrieval, load_eval_rows, print_evaluation  # noqa: E402


def sentence_transformer_cache_folder() -> str | None:
    return os.getenv("SENTENCE_TRANSFORMERS_HOME") or None


def evaluate(index_path: Path, metadata_path: Path, eval_path: Path, model_name: str, top_k: int) -> int:
    metadata = load_metadata(str(metadata_path))
    if not metadata:
        print(f"Metadata not found or empty: {metadata_path}")
        return 1

    embedding_model = SentenceTransformer(
        model_name,
        cache_folder=sentence_transformer_cache_folder(),
        local_files_only=True,
    )
    usearch_index = load_usearch_index(
        str(index_path),
        embedding_dimension(embedding_model),
    )
    bm25_index = build_bm25_index(metadata)
    eval_rows = load_eval_rows(eval_path)

    def retrieve_urls(question: str, top_k: int) -> list[str | None]:
        raw_results = hybrid_search(
            question,
            usearch_index,
            metadata,
            embedding_model,
            bm25_index,
            k=top_k,
        )
        results = deduplicate_urls(raw_results, max_chunks_per_url=1)[:top_k]
        return [item["metadata"].get("url") for item in results]

    result = evaluate_retrieval(eval_rows, retrieve_urls, top_k)
    print_evaluation(result)
    return 1 if result.errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval over the generated local knowledge base.")
    parser.add_argument("--index-path", default="usearch_index.bin")
    parser.add_argument("--metadata-path", default="metadata.json")
    parser.add_argument("--eval-path", default="eval_questions.json")
    parser.add_argument("--model-name", default="all-MiniLM-L6-v2")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    return evaluate(
        index_path=Path(args.index_path),
        metadata_path=Path(args.metadata_path),
        eval_path=Path(args.eval_path),
        model_name=args.model_name,
        top_k=args.top_k,
    )


if __name__ == "__main__":
    raise SystemExit(main())
