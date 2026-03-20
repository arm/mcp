"""Run a small retrieval evaluation over the local metadata and index."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sentence_transformers import SentenceTransformer


REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_LOCAL_DIR = REPO_ROOT / "mcp-local"
if str(MCP_LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_LOCAL_DIR))

from utils.search_utils import build_bm25_index, deduplicate_urls, hybrid_search, load_metadata, load_usearch_index  # noqa: E402


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
        embedding_model.get_sentence_embedding_dimension(),
    )
    bm25_index = build_bm25_index(metadata)

    with eval_path.open() as file:
        eval_rows = json.load(file)

    hits_at_1 = 0
    hits_at_3 = 0
    hits_at_5 = 0
    reciprocal_ranks = []
    misses = []

    for row in eval_rows:
        raw_results = hybrid_search(
            row["question"],
            usearch_index,
            metadata,
            embedding_model,
            bm25_index,
            k=top_k,
        )
        results = deduplicate_urls(raw_results, max_chunks_per_url=1)[:top_k]
        ranked_urls = [item["metadata"].get("url") for item in results]
        expected = set(row["expected_urls"])

        match_rank = None
        for index, url in enumerate(ranked_urls, start=1):
            if url in expected:
                match_rank = index
                break

        if match_rank == 1:
            hits_at_1 += 1
        if match_rank is not None and match_rank <= 3:
            hits_at_3 += 1
        if match_rank is not None and match_rank <= 5:
            hits_at_5 += 1
        reciprocal_ranks.append(0 if match_rank is None else 1 / match_rank)

        if match_rank is None:
            misses.append(
                {
                    "question": row["question"],
                    "expected_urls": row["expected_urls"],
                    "ranked_urls": ranked_urls,
                }
            )

    total = len(eval_rows)
    print(f"Questions: {total}")
    print(f"Hit@1: {hits_at_1 / total:.2%}")
    print(f"Hit@3: {hits_at_3 / total:.2%}")
    print(f"Hit@5: {hits_at_5 / total:.2%}")
    print(f"MRR: {sum(reciprocal_ranks) / total:.3f}")
    print(f"Misses: {len(misses)}")
    for miss in misses[:10]:
        print()
        print(f"Q: {miss['question']}")
        print(f"Expected: {miss['expected_urls']}")
        print(f"Got: {miss['ranked_urls']}")
    return 0


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
