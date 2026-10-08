"""Run a retrieval evaluation over the local metadata and index."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arm_kb_search import (  # noqa: E402
    load_search_resources,
    search,
)
from arm_kb_search.evaluation import (  # noqa: E402
    evaluate_retrieval,
    load_eval_rows,
    print_evaluation,
)
from arm_kb_search.search import deduplicate_urls, embedding_search  # noqa: E402


def evaluate(
    index_path: Path,
    metadata_path: Path,
    eval_path: Path,
    model_path: Path,
    top_k: int,
    mode: str = "hybrid",
    output: Path | None = None,
) -> int:
    if not metadata_path.exists() or metadata_path.stat().st_size == 0:
        print(f"Metadata not found or empty: {metadata_path}")
        return 1

    resources = load_search_resources(
        metadata_path=str(metadata_path),
        usearch_index_path=str(index_path),
        model_path=str(model_path),
    )
    eval_rows = load_eval_rows(eval_path)
    retrieved = {}

    def retrieve_urls(question: str, top_k: int) -> list[str | None]:
        if mode == "semantic":
            candidates = embedding_search(
                question,
                resources.usearch_index,
                resources.metadata,
                resources.embedding_model,
                max(100, top_k * 20),
            )
            items = [
                {
                    **{
                        key: item["metadata"].get(key)
                        for key in ("url", "title", "heading", "doc_type")
                    },
                    "distance": item["distance"],
                }
                for item in deduplicate_urls(candidates)[:top_k]
            ]
        else:
            items = search(question, resources, k=top_k)
        retrieved[question] = items
        return [item.get("url") for item in items]

    result = evaluate_retrieval(eval_rows, retrieve_urls, top_k)
    print_evaluation(result, label=f"{mode} retrieval")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "mode": mode,
                    "index_size": len(resources.metadata),
                    "model_path": str(model_path),
                    "evaluation": asdict(result),
                    "retrieved": retrieved,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 1 if result.errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate retrieval over the generated local knowledge base."
    )
    parser.add_argument("--index-path", default="usearch_index.bin")
    parser.add_argument("--metadata-path", default="metadata.json")
    parser.add_argument("--eval-path", default="eval_questions.json")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--mode", choices=("hybrid", "semantic"), default="hybrid")
    parser.add_argument(
        "--output",
        type=Path,
        help="Save metrics and retrieved chunks, including vector distances.",
    )
    args = parser.parse_args()

    return evaluate(
        index_path=Path(args.index_path),
        metadata_path=Path(args.metadata_path),
        eval_path=Path(args.eval_path),
        model_path=Path(args.model_path),
        top_k=args.top_k,
        mode=args.mode,
        output=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
