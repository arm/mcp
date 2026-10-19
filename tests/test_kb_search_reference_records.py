"""Entity and type evidence should select the relevant reference record."""
from dataclasses import replace

import pytest

from arm_kb_search.search import (
    _analyze_query,
    _reference_record_bonus,
    _rerank_candidates,
    rerank_candidates,
)


def candidate(name, doc_type, text, *, heading=None, platform="", product=""):
    return {"rrf_score": 0.03, "metadata": {
        "chunk_uuid": name, "url": "https://example.com/" + name,
        "title": name, "heading": heading or name, "doc_type": doc_type,
        "search_text": text, "original_text": text, "platform": platform,
        "product": product,
    }}


@pytest.mark.parametrize("question", [
    "Can I use Redis on Arm Linux?", "Can I set up Redis on Arm Linux?",
    "Is Redis supported on Arm Linux?", "Is there Redis for Arm Linux?",
    "Does Redis work on Arm Linux?", "Which version of Redis supports Arm Linux?",
])
def test_support_question_prefers_package_record(question):
    card = candidate("Redis", "Ecosystem Dashboard", "Redis supported on Arm Linux", platform="linux")
    guide = candidate("Redis", "Tutorial", "Redis supported on Arm Linux")
    ranked = rerank_candidates(question, [guide, card])
    assert ranked[0]["metadata"]["doc_type"] == "Ecosystem Dashboard"
    assert ranked[0]["rerank_score"] > ranked[1]["rerank_score"]


def test_exact_api_identifier_overcomes_a_generic_competitor():
    question = "Why does svmopa_za32_m take two predicates for outer product accumulation?"
    exact = candidate("Matrix API", "Documentation", "Use svmopa_za32_m with row and column masks.")
    generic = candidate("Matrix API", "Documentation", "Two predicates for outer product accumulation.")
    query = _analyze_query(question)
    assert _rerank_candidates(query, [generic, exact])[0]["metadata"] == exact["metadata"]
    # This control must fail to prefer the API when identifier evidence is removed.
    assert _rerank_candidates(replace(query, code_identifiers=set()), [generic, exact])[0]["metadata"] == generic["metadata"]


@pytest.mark.parametrize("question,heading,platform", [
    ("How can I use Redis on Arm?", "Redis", "linux"),
    ("Tune Redis latency", "Redis", "linux"),
    ("Can I run PostgreSQL on Arm?", "Redis", "linux"),
    ("Can I run Redis on Windows?", "Redis", "linux"),
    ("Can I run Redis on Linux?", "Redis", "windows"),
    ("Is IDEA supported on Windows?", "IntelliJ IDEA", "windows"),
    ("Is Arm supported?", "Arm", "linux"),
])
def test_dashboard_bonus_requires_support_full_name_and_platform(question, heading, platform):
    metadata = candidate(heading, "Ecosystem Dashboard", "", platform=platform)["metadata"]
    assert _reference_record_bonus(_analyze_query(question), metadata, "ecosystem dashboard") == 0


def intrinsic(name="svld1ub_u32", isa="SVE", signature="svuint32_t svld1ub_u32(svbool_t pg, const uint8_t *base);"):
    record = candidate(name, "Intrinsic", f"The intrinsic is part of the {isa} instruction set architecture. "
                       "Here is a brief intrinsic description: Unsigned byte load into 32-bit elements.\n\n"
                       "The signature is as follows:\n`" + signature + "`", product=isa)
    # Production search_text includes the title, heading, doc_type, and ISA.
    record["metadata"]["search_text"] = (
        f"Arm Intrinsics - {name} {isa} {name} Intrinsic {isa} "
        + record["metadata"]["original_text"]
    )
    return record


def test_typed_intrinsic_question_prefers_reference_to_general_guide():
    card = intrinsic()
    guide = candidate("SVE loads", "Tutorial", "SVE intrinsics can load bytes into a svuint32_t vector.")
    ranked = rerank_candidates("Which SVE intrinsic loads uint8_t into svuint32_t?", [guide, card])
    assert ranked[0]["metadata"] == card["metadata"]
    query = replace(_analyze_query("Which SVE intrinsic loads uint8_t into svuint32_t?"), intrinsic_query=False)
    assert _rerank_candidates(query, [guide, card])[0]["metadata"] == guide["metadata"]


def test_bracketed_catalog_name_matches_explicit_acle_identifier():
    record = intrinsic("svadd[_f32]_m")["metadata"]
    assert _reference_record_bonus(_analyze_query("How do I call svadd_f32_m?"), record, "intrinsic") == 0.45


def test_signature_argument_types_distinguish_signed_siblings():
    query = _analyze_query("Which SVE intrinsic loads uint8_t into svuint32_t?")
    unsigned = intrinsic()["metadata"]
    signed = intrinsic("svld1ub_s32", signature="svint32_t svld1ub_s32(svbool_t pg, const uint8_t *base);")["metadata"]
    assert _reference_record_bonus(query, unsigned, "intrinsic") > _reference_record_bonus(query, signed, "intrinsic")
    # The sv prefix is equivalent for the purpose of matching scalar/vector base types.
    assert _reference_record_bonus(_analyze_query("SVE intrinsic for uint32_t"), unsigned, "intrinsic") == 0.35


@pytest.mark.parametrize("question", [
    "Which SME intrinsic loads uint8_t?", "Which Neon intrinsic loads uint8_t?",
    "Which SME intrinsic works with SVE uint8_t vectors?",
    "Which intrinsic loads bytes?",
])
def test_intrinsic_bonus_requires_intent_and_matching_isa(question):
    assert _reference_record_bonus(_analyze_query(question), intrinsic()["metadata"], "intrinsic") == 0


def test_legacy_metadata_gets_no_reference_bonus():
    query = _analyze_query("Is Redis supported on Linux?")
    legacy = candidate("Redis", "", "Redis supported on Linux")["metadata"]
    assert _reference_record_bonus(query, legacy, "") == 0


def test_query_analysis_excludes_types_and_generic_architectures_from_api_names():
    query = _analyze_query("SME2 ZA svbool_t uint8x16_t x86_64 svmopa_za32_m")
    assert query.intrinsic_isas == {"sme"}
    assert query.acle_types == {"svbool_t", "uint8x16_t"}
    assert query.code_identifiers == {"svmopa_za32_m"}


@pytest.mark.parametrize("catalog_name,c_name", [
    ("svqrdmulh[_s32]", "svqrdmulh_s32"),
    ("svst1_scatter[_u32base]_index[_s32]", "svst1_scatter_u32base_index_s32"),
])
def test_canonical_intrinsic_name_retrieved_without_semantic_match(catalog_name, c_name):
    from arm_kb_search.search import build_bm25_index, hybrid_search

    target = intrinsic(catalog_name)["metadata"]
    sibling = intrinsic("svqrdmulh[_u32]")["metadata"]
    guide = candidate("Arithmetic guide", "Documentation", "General arithmetic advice")["metadata"]
    metadata = [target, sibling, guide]
    bm25 = build_bm25_index(metadata)
    hits = hybrid_search(c_name, None, metadata, object(), bm25, k=1)
    assert [x["metadata"] for x in hits] == [target]
    assert hybrid_search(c_name, None, metadata, object(), bm25, k=1, eligible_ids=(1, 2)) == []


def test_canonical_name_indexing_does_not_rewrite_other_document_types():
    from arm_kb_search.search import build_bm25_index, bm25_search

    metadata = [candidate("example[_s32]", "Documentation", "example[_s32]")["metadata"],
                candidate("Other", "Documentation", "Other documentation")["metadata"],
                candidate("Third", "Documentation", "Additional reference")["metadata"]]
    assert bm25_search("example_s32", metadata, build_bm25_index(metadata)) == []


@pytest.mark.parametrize("query", ["SVE load vector", "svqrdmulh", "svmissing_s32"])
def test_alias_channel_leaves_nonmatching_sparse_scores_identical(query):
    import numpy as np
    from rank_bm25 import BM25Okapi
    from arm_kb_search.search import _bm25_tokens, build_bm25_index

    metadata = [intrinsic("svqrdmulh[_s32]")["metadata"],
                intrinsic("svqrdmulh[_u32]")["metadata"],
                candidate("Guide", "Documentation", "SVE load vector examples")["metadata"],
                candidate("Other", "Documentation", "Different advice")["metadata"]]
    original = BM25Okapi([_bm25_tokens(x["search_text"]) for x in metadata])
    actual = build_bm25_index(metadata)
    tokens = _bm25_tokens(query)
    np.testing.assert_array_equal(actual.get_scores(tokens), original.get_scores(tokens))
    np.testing.assert_array_equal(actual.get_batch_scores(tokens, [0, 2]),
                                  original.get_batch_scores(tokens, [0, 2]))


def test_sparse_name_evidence_survives_a_large_non_intrinsic_corpus():
    from arm_kb_search.search import build_bm25_index, hybrid_search

    target = intrinsic("svqrdmulh[_s32]")["metadata"]
    metadata = [candidate(f"Guide {i}", "Documentation", f"guide{i} rounding halfway values")["metadata"]
                for i in range(450)]
    metadata.extend(candidate(f"Unrelated {i}", "Documentation", f"unrelated{i}")["metadata"]
                    for i in range(50))
    metadata.append(target)
    hits = hybrid_search("svqrdmulh_s32 rounding halfway values", None, metadata, object(),
                         build_bm25_index(metadata), k=5)
    assert any(x["metadata"] == target for x in hits)


def test_descriptive_intrinsic_request_without_literal_intrinsic_word():
    assert _reference_record_bonus(_analyze_query("Which SVE load reads bytes?"), intrinsic()["metadata"], "intrinsic") == 0.10
