# Copyright © 2025, Arm Limited and Contributors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
class EvaluationCaseResult:
    question_id: str
    question: str
    expected_urls: list[str]
    ranked_urls: list[str | None]
    match_rank: int | None
    reciprocal_rank: float
    error: str | None = None

    @property
    def hit_at_1(self) -> bool:
        return self.match_rank == 1

    @property
    def hit_at_3(self) -> bool:
        return self.match_rank is not None and self.match_rank <= 3

    @property
    def hit_at_5(self) -> bool:
        return self.match_rank is not None and self.match_rank <= 5


@dataclass
class EvaluationResult:
    total: int
    hits_at_1: int
    hits_at_3: int
    hits_at_5: int
    reciprocal_ranks: list[float]
    cases: list[EvaluationCaseResult]
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
    cases = []
    misses = []
    errors = []

    for row in eval_rows:
        question_id = str(row.get("id") or row["question"])
        question = str(row["question"])
        expected_urls = list(row["expected_urls"])
        error = None

        try:
            ranked_urls = retrieve_urls(question, top_k)[:top_k]
        except Exception as exc:
            ranked_urls = []
            error = str(exc)
            errors.append(RetrievalError(question=question, error=error))

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
        reciprocal_rank = 0 if match_rank is None else 1 / match_rank
        reciprocal_ranks.append(reciprocal_rank)
        cases.append(
            EvaluationCaseResult(
                question_id=question_id,
                question=question,
                expected_urls=expected_urls,
                ranked_urls=ranked_urls,
                match_rank=match_rank,
                reciprocal_rank=reciprocal_rank,
                error=error,
            )
        )

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
        cases=cases,
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
