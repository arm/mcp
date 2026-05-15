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

from .loaders import load_metadata, load_usearch_index
from .evaluation import (
    EvaluationResult,
    RetrievalError,
    RetrievalMiss,
    evaluate_retrieval,
    load_eval_rows,
    print_evaluation,
)
from .search import (
    build_bm25_index,
    bm25_search,
    deduplicate_urls,
    embedding_search,
    hybrid_search,
    rerank_candidates,
    salient_tokens,
    tokenize_for_search,
)

__all__ = [
    "build_bm25_index",
    "bm25_search",
    "deduplicate_urls",
    "embedding_search",
    "evaluate_retrieval",
    "EvaluationResult",
    "hybrid_search",
    "load_eval_rows",
    "load_metadata",
    "load_usearch_index",
    "print_evaluation",
    "rerank_candidates",
    "RetrievalError",
    "RetrievalMiss",
    "salient_tokens",
    "tokenize_for_search",
]
