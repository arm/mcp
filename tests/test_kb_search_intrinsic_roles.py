"""Descriptive ranking must honor operand roles and preserve unrelated requests."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest
from usearch.index import Index

from arm_kb_search import SearchResources, search
from arm_kb_search.intrinsic_roles import match_bonus, query_roles
from arm_kb_search.search import _analyze_query, _rerank_candidates, build_bm25_index


def record(name, signature, categories, isa="SVE", description=""):
    text = (
        f"Here is a brief intrinsic description: {description}\n\n"
        f"The signature for this intrinsic is as follows:\n`{signature}`"
    )
    return {"heading": name, "title": name, "product": isa, "doc_type": "Intrinsic",
            "url": f"https://example.com/{name}", "chunk_uuid": name,
            "keywords": f"Intrinsic,{isa},{name},{categories}", "original_text": text,
            "search_text": f"{name} {isa} Intrinsic {categories} {text}"}


def load_record(name="svld1ub_u32", scalar="uint8_t", vector="svuint32_t"):
    return record(name, f"{vector} {name}(svbool_t pg, const {scalar} *base);",
                  "Load,Load consecutive elements", description="Load bytes with zero extension.")


def scores(question, records):
    parsed = query_roles(question)
    assert parsed is not None
    return [match_bonus(parsed, row) for row in records]


def test_memory_input_and_result_types_are_not_interchangeable():
    byte_to_word = load_record()
    word_to_byte = load_record("svld1_u8", "uint32_t", "svuint8_t")
    right, wrong = scores("Which SVE intrinsic loads uint8_t into svuint32_t?", [byte_to_word, word_to_byte])
    assert right > wrong
    right, wrong = scores("Which SVE intrinsic loads uint32_t into svuint8_t?", [word_to_byte, byte_to_word])
    assert right > wrong


def test_predicate_width_is_distinct_from_scalar_bound_width():
    def predicate(name, scalar):
        return record(name, f"svbool_t {name}({scalar} op1, {scalar} op2);", "While counter meets condition")
    right, wrong = scores(
        "Create an SVE predicate for 32-bit lanes using a 64-bit scalar bound.",
        [predicate("svwhilelt_b32_u64", "uint64_t"), predicate("svwhilelt_b64_u32", "uint32_t")],
    )
    assert right > wrong
    assert _analyze_query("Create an SVE predicate for 32-bit lanes using a 64-bit scalar bound.").intrinsic_query


def test_fp32_lanes_beat_a_similarly_wide_fp16_vector():
    f32 = record("vld3q_f32", "float32x4x3_t vld3q_f32(const float32_t *ptr);", "Load,Load multiple structures", "Neon")
    f16 = record("vld3q_f16", "float16x8x3_t vld3q_f16(const float16_t *ptr);", "Load,Load multiple structures", "Neon")
    right, wrong = scores("Which Neon intrinsic loads three vectors of four FP32 elements?", [f32, f16])
    assert right > wrong


@pytest.mark.parametrize("question", [
    "Which SVE intrinsic gives the runtime number of 64-bit elements in a full vector?",
    "Which SVE intrinsic handles 32-bit elements?",
    "How do I install an SVE intrinsics compiler?",
    "Compare SVE and Neon intrinsic loads.",
    "Which SME intrinsic loads a tile?",
    "How can I reduce Redis latency?",
])
def test_unknown_operations_and_unrelated_requests_abstain(question):
    assert query_roles(question) is None
    assert match_bonus(query_roles(question), load_record()) == 0


@pytest.mark.parametrize("changes", [
    {"doc_type": "Tutorial"}, {"product": "SME"}, {"heading": ""},
    {"original_text": "No structured signature is available."},
    {"original_text": "The signature is as follows: `svuint32_t svld1ub_u32 malformed`"},
    {"original_text": "The signature is as follows: `svuint32_t svld1ub_u32(argument);`"},
])
def test_unsupported_or_missing_reference_facts_are_neutral(changes):
    metadata = {**load_record(), **changes}
    assert match_bonus(query_roles("Which SVE intrinsic loads uint8_t into svuint32_t?"), metadata) == 0


@pytest.mark.parametrize("api_name", ["svld1ub_u32", "svunknown_u32"])
def test_named_intrinsic_keeps_existing_ranking(api_name):
    records = [load_record(), load_record("svld1_u8", "uint32_t", "svuint8_t")]
    candidates = [{"rrf_score": 0.03, "metadata": row} for row in records]
    query = _analyze_query(f"Why does intrinsic {api_name} load uint8_t into svuint32_t?")
    assert query.intrinsic_roles is not None
    assert _rerank_candidates(query, candidates) == _rerank_candidates(replace(query, intrinsic_roles=None), candidates)


def test_interleaved_requests_do_not_leak_roles_or_mutate_metadata():
    records = [load_record(), load_record("svld1_u8", "uint32_t", "svuint8_t")]
    original = deepcopy(records)
    candidates = [{"rrf_score": 0.03, "metadata": row} for row in records]
    questions = ["Which SVE intrinsic loads uint8_t into svuint32_t?",
                 "Which SVE intrinsic loads uint32_t into svuint8_t?",
                 "How can I reduce Redis latency?"]
    def rank(question):
        return _rerank_candidates(_analyze_query(question), candidates)
    expected = [rank(q) for q in questions]
    with ThreadPoolExecutor(max_workers=4) as executor:
        actual = list(executor.map(rank, questions * 20))
    assert actual == expected * 20
    assert records == original


def test_public_search_preserves_metadata_filter_eligibility():
    metadata = [load_record(), record("vld1_u8", "uint8x8_t vld1_u8(const uint8_t *ptr);", "Load", "Neon")]
    index = Index(ndim=2, metric="l2sq", dtype="f32")
    index.add(np.arange(2), np.zeros((2, 2), dtype=np.float32), threads=1)
    class Model:
        def encode(self, queries):
            return np.zeros((len(queries), 2), dtype=np.float32)
    resources = SearchResources(metadata, Model(), index, build_bm25_index(metadata), include_disclaimers=False)
    question = "Which SVE intrinsic loads uint8_t into svuint32_t?"
    baseline = search(question, resources, k=5)
    filtered = search(question, resources, k=5, filters={"product": "Neon"})
    assert [row["url"] for row in filtered] == [metadata[1]["url"]]
    assert search(question, resources, k=5, filters={"product": "SME"}) == []
    assert search(question, resources, k=5) == baseline
