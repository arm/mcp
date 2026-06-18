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
    EvaluationCaseResult,
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
    deduplication_candidate_count,
    embedding_search,
    hybrid_search,
    lexical_prepass_search,
    rerank_candidates,
    salient_tokens,
    tokenize_for_search,
)
from .resources import (
    SearchResources,
    embedding_dimension,
    load_embedding_model,
    load_search_resources,
    search,
    sentence_transformer_cache_folder,
)
from .response import (
    ARM_CONTENT_DISCLAIMER,
    add_disclaimer_to_arm_results,
    add_utm_source_to_results,
    add_utm_source_to_url,
    is_arm_domain_url,
)

__all__ = [
    "add_disclaimer_to_arm_results",
    "add_utm_source_to_results",
    "add_utm_source_to_url",
    "ARM_CONTENT_DISCLAIMER",
    "build_bm25_index",
    "bm25_search",
    "deduplicate_urls",
    "deduplication_candidate_count",
    "embedding_search",
    "embedding_dimension",
    "evaluate_retrieval",
    "EvaluationCaseResult",
    "EvaluationResult",
    "hybrid_search",
    "is_arm_domain_url",
    "lexical_prepass_search",
    "load_embedding_model",
    "load_eval_rows",
    "load_metadata",
    "load_search_resources",
    "load_usearch_index",
    "print_evaluation",
    "rerank_candidates",
    "RetrievalError",
    "RetrievalMiss",
    "salient_tokens",
    "search",
    "SearchResources",
    "sentence_transformer_cache_folder",
    "tokenize_for_search",
]
