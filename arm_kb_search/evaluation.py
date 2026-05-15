"""Shared retrieval evaluation helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


EvalRow = dict[str, object]
RetrieveUrls = Callable[[str, int], list[str | None]]


@dataclass
class RetrievalMiss:
    question: str
    expected_urls: list[str]
    ranked_urls: list[str | None]


@dataclass
class RetrievalError:
    question: str
    error: str


@dataclass
class EvaluationResult:
    total: int
    hits_at_1: int
    hits_at_3: int
    hits_at_5: int
    reciprocal_ranks: list[float]
    misses: list[RetrievalMiss]
    errors: list[RetrievalError]

    @property
    def hit_at_1(self) -> float:
        return self.hits_at_1 / self.total if self.total else 0

    @property
    def hit_at_3(self) -> float:
        return self.hits_at_3 / self.total if self.total else 0

    @property
    def hit_at_5(self) -> float:
        return self.hits_at_5 / self.total if self.total else 0

    @property
    def mrr(self) -> float:
        return sum(self.reciprocal_ranks) / self.total if self.total else 0


def load_eval_rows(eval_path: Path) -> list[EvalRow]:
    with eval_path.open() as file:
        rows = json.load(file)
    if not isinstance(rows, list):
        raise ValueError(f"Expected {eval_path} to contain a JSON list")
    return rows


def evaluate_retrieval(eval_rows: list[EvalRow], retrieve_urls: RetrieveUrls, top_k: int) -> EvaluationResult:
    hits_at_1 = 0
    hits_at_3 = 0
    hits_at_5 = 0
    reciprocal_ranks = []
    misses = []
    errors = []

    for row in eval_rows:
        question = str(row["question"])
        expected_urls = list(row["expected_urls"])

        try:
            ranked_urls = retrieve_urls(question, top_k)[:top_k]
        except Exception as exc:
            ranked_urls = []
            errors.append(RetrievalError(question=question, error=str(exc)))

        expected = set(expected_urls)
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
                RetrievalMiss(
                    question=question,
                    expected_urls=expected_urls,
                    ranked_urls=ranked_urls,
                )
            )

    return EvaluationResult(
        total=len(eval_rows),
        hits_at_1=hits_at_1,
        hits_at_3=hits_at_3,
        hits_at_5=hits_at_5,
        reciprocal_ranks=reciprocal_ranks,
        misses=misses,
        errors=errors,
    )


def print_evaluation(result: EvaluationResult, label: str | None = None) -> None:
    if label:
        print(label)
    print(f"Questions: {result.total}")
    print(f"Hit@1: {result.hit_at_1:.2%}")
    print(f"Hit@3: {result.hit_at_3:.2%}")
    print(f"Hit@5: {result.hit_at_5:.2%}")
    print(f"MRR: {result.mrr:.3f}")
    print(f"Errors: {len(result.errors)}")
    print(f"Misses: {len(result.misses)}")

    for error in result.errors[:10]:
        print()
        print(f"Q: {error.question}")
        print(f"Error: {error.error}")

    for miss in result.misses[:10]:
        print()
        print(f"Q: {miss.question}")
        print(f"Expected: {miss.expected_urls}")
        print(f"Got: {miss.ranked_urls}")
