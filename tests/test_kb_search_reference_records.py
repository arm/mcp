"""Entity and type evidence should select the relevant reference record."""
from dataclasses import replace

import pytest

from arm_kb_search.search import (
    _analyze_query,
    _evidence_tokens,
    _reference_record_bonus,
    _rerank_candidates,
    rerank_candidates,
    tokenize_for_search,
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
    "Can I run Redis on Arm?", "Is Redis supported on Ubuntu?",
    "Can I create a Redis database on Arm Linux?",
    "Can I generate a file with Redis on Arm Linux?",
    "Can I validate a Redis configuration on Arm Linux?",
    "Where can I inspect Redis validation results for Arm Linux?",
    "Can\tI run Redis on Arm Linux?",
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
    ("Is Redis supported on macOS?", "Redis", "linux"),
    ("Can I run Redis on Android?", "Redis", "linux"),
    ("Is Redis supported on iOS?", "Redis", "linux"),
    ("Can I run Redis on Mac OS X?", "Redis", "linux"),
    ("Is Redis supported on OSX?", "Redis", "linux"),
    ("Can I run Redis on Linux?", "Redis", "windows"),
    ("Is IDEA supported on Windows?", "IntelliJ IDEA", "windows"),
    ("Is Arm supported?", "Arm", "linux"),
])
def test_dashboard_bonus_requires_support_full_name_and_platform(question, heading, platform):
    metadata = candidate(heading, "Ecosystem Dashboard", "", platform=platform)["metadata"]
    assert _reference_record_bonus(_analyze_query(question), metadata, "ecosystem dashboard") == 0


@pytest.mark.parametrize("question,preferred_platform", [
    ("Redis compatibility on Windows.", "windows"),
    ("Redis compatibility on Windows?", "windows"),
    ("Redis compatibility on Windows...", "windows"),
    ("Redis compatibility on macOS.", None),
    ("Redis compatibility on Android.", None),
    ("Redis compatibility on iOS.", None),
    ("Redis compatibility on Linux.", "linux"),
    ("Redis compatibility on Ubuntu.", "linux"),
    ("Can I run Redis on Arm?", "linux"),
])
def test_dashboard_platform_bonus_ignores_sentence_punctuation(question, preferred_platform):
    for platform in ("linux", "windows"):
        metadata = candidate("Redis", "Ecosystem Dashboard", "", platform=platform)["metadata"]
        expected = 0.35 if platform == preferred_platform else 0.0
        assert _reference_record_bonus(_analyze_query(question), metadata, "ecosystem dashboard") == expected


def test_sentence_punctuation_preserves_internal_technical_characters():
    tokens = tokenize_for_search("Node.js. llama.cpp. C++. 3.12.2. arm_neon.h. vaddq_u8... __ARM_FEATURE_SVE.")
    assert _evidence_tokens(tokens) == [
        "node.js", "llama.cpp", "c++", "3.12.2", "arm_neon.h", "vaddq_u8", "__arm_feature_sve",
    ]
    assert "node.js." in tokens  # Prose tokens and their BM25 statistics remain unchanged.
    assert tokenize_for_search("...?!") == []


@pytest.mark.parametrize("question", [
    "Which operation returns svuint32_t", "How do I use svqrdmulh_s32",
    "Find intrinsics for SVE2", "Is Redis supported on Windows",
    "Is there support for Redis", "Build llama.cpp with C++",
])
def test_query_evidence_ignores_sentence_final_period(question):
    plain, punctuated = _analyze_query(question), _analyze_query(question + ".")
    for field in ("acle_types", "intrinsic_isas", "code_identifiers", "intrinsic_query", "support_question"):
        assert getattr(punctuated, field) == getattr(plain, field)


@pytest.mark.parametrize("ctype,isa", [
    ("svuint32_t", "SVE"), ("float32x4_t", "Neon"), ("svbool_t", "SVE"),
])
def test_sentence_final_return_type_contributes_reference_evidence(ctype, isa):
    query = _analyze_query(f"{isa} intrinsic returning {ctype}.")
    record = intrinsic(isa=isa, signature=f"{ctype} example(void);")["metadata"]
    assert query.acle_types == {ctype}
    assert _reference_record_bonus(query, record, "intrinsic") == pytest.approx(0.35)


@pytest.mark.parametrize("name", ["Redis", "Node.js", "C++"])
def test_sentence_final_product_name_keeps_dashboard_evidence(name):
    query = _analyze_query(f"Is there support for {name}.")
    record = candidate(name, "Ecosystem Dashboard", "", platform="linux")["metadata"]
    assert _reference_record_bonus(query, record, "ecosystem dashboard") == 0.35


@pytest.mark.parametrize("ending", [".", "..."])
def test_sentence_final_document_api_keeps_identifier_evidence(ending):
    query = _analyze_query("How do I use svmopa_za32_m.")
    record = candidate("Matrix API", "Documentation", "Use svmopa_za32_m" + ending)
    score = _rerank_candidates(query, [record])[0]["rerank_score"]
    control = _rerank_candidates(replace(query, code_identifiers=set()), [record])[0]["rerank_score"]
    assert score - control == pytest.approx(0.30)


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


@pytest.mark.parametrize("ending", ["?", ".", "..."])
def test_signature_argument_types_distinguish_signed_siblings(ending):
    query = _analyze_query("Which SVE intrinsic loads uint8_t into svuint32_t" + ending)
    unsigned = intrinsic()["metadata"]
    signed = intrinsic("svld1ub_s32", signature="svint32_t svld1ub_s32(svbool_t pg, const uint8_t *base);")["metadata"]
    assert _reference_record_bonus(query, unsigned, "intrinsic") == pytest.approx(0.35)
    assert _reference_record_bonus(query, signed, "intrinsic") == pytest.approx(0.225)
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
    ("vaddq_u8", "vaddq_u8"),
    ("svcntb", "svcntb"),
    ("__crc32b", "__crc32b"),
])
@pytest.mark.parametrize("query_format", ["{}", "{}.", "{}...", "{}?", "`{}`.", '"{}".'])
def test_canonical_intrinsic_name_retrieved_without_semantic_match(catalog_name, c_name, query_format):
    from arm_kb_search.search import build_bm25_index, hybrid_search

    target = intrinsic(catalog_name, signature=f"svint32_t {catalog_name}(void);")["metadata"]
    sibling = intrinsic("svqrdmulh[_u32]")["metadata"]
    guide = candidate("Arithmetic guide", "Documentation", "General arithmetic advice")["metadata"]
    metadata = [target, sibling, guide]
    bm25 = build_bm25_index(metadata)
    query = query_format.format(c_name)
    hits = hybrid_search(query, None, metadata, object(), bm25, k=1)
    assert [x["metadata"] for x in hits] == [target]
    assert hybrid_search(query, None, metadata, object(), bm25, k=1, eligible_ids=(1, 2)) == []
    assert hybrid_search(query, None, metadata, object(), bm25, k=1, eligible_ids=(0, 2))[0]["metadata"] == target


def test_canonical_name_indexing_does_not_rewrite_other_document_types():
    from arm_kb_search.search import build_bm25_index, bm25_search

    metadata = [candidate("example[_s32]", "Documentation", "example[_s32]")["metadata"],
                candidate("Other", "Documentation", "Other documentation")["metadata"],
                candidate("Third", "Documentation", "Additional reference")["metadata"]]
    assert bm25_search("example_s32", metadata, build_bm25_index(metadata)) == []


@pytest.mark.parametrize("query", [
    "SVE load vector", "SVE load vector.", "svqrdmulh", "svmissing_s32", "svmissing_s32.", "svqrdmulh_s32.extra",
])
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


def test_descriptive_request_does_not_use_removed_role_intent_detector():
    assert _reference_record_bonus(_analyze_query("Which SVE load reads bytes?"), intrinsic()["metadata"], "intrinsic") == 0.0


@pytest.mark.parametrize("question", [
    "Can I optimize Redis latency on Arm Linux?",
    "Can I benchmark Redis on Arm Linux?",
    "Can I debug Redis on Arm Linux?",
    "Is there a way to tune Redis latency on Arm Linux?",
    "Are there tips to optimize Redis on Arm Linux?",
    "Recommend a Redis performance tuning guide for Arm Linux.",
    "Recommend a tutorial for Redis.",
    "Is there a Redis guide for tuning.",
    "Can I generate a Redis latency report on Arm Linux?",
    "Can I validate Redis throughput on Arm Linux?",
    "How  can I use Redis on Arm Linux?",
])
def test_procedural_questions_do_not_receive_availability_bonus(question):
    card = candidate("Redis", "Ecosystem Dashboard", "Redis on Arm Linux", platform="linux")
    assert not _analyze_query(question).support_question
    assert _reference_record_bonus(_analyze_query(question), card["metadata"], "ecosystem dashboard") == 0


@pytest.mark.parametrize("package,expected", [("Redis", .35), ("PostgreSQL", 0)])
def test_dashboard_subsection_uses_package_identity(package, expected):
    record = candidate("Features", "Ecosystem Dashboard", "", platform="linux")["metadata"]
    record["heading_path"] = ["Linux", package, "Features"]
    query = _analyze_query("Which Redis features are supported on Linux?")
    assert _reference_record_bonus(query, record, "ecosystem dashboard") == expected


@pytest.mark.parametrize("catalog_name,c_name", [
    ("svadd[_f32]_m", "svadd_f32_m"),
    ("svst1_scatter[_u32base]_index[_s32]", "svst1_scatter_u32base_index_s32"),
])
@pytest.mark.parametrize("ending", ["?", ".", "..."])
def test_literal_catalog_names_receive_canonical_evidence(catalog_name, c_name, ending):
    from arm_kb_search.search import build_bm25_index, hybrid_search

    target = intrinsic(catalog_name, signature=f"svfloat32_t {catalog_name}(void);")["metadata"]
    metadata = [target] + [candidate(f"Guide {i}", "Documentation", "Unrelated guide")["metadata"] for i in range(3)]
    index = build_bm25_index(metadata)
    for spelling in (catalog_name, c_name):
        query = "How do I call " + spelling + ending
        analysis = _analyze_query(query)
        assert c_name in analysis.code_identifiers
        assert analysis.code_identifiers == {c_name}
        assert _reference_record_bonus(analysis, target, "intrinsic") == .45
        assert hybrid_search(query, None, metadata, object(), index, k=1)[0]["metadata"] == target
        assert hybrid_search(query, None, metadata, object(), index, eligible_ids=(1, 2, 3)) == []


@pytest.mark.parametrize("query", ["svadd[_f32]_m.extra", "svadd[_f32]_missing", "svadd[_f32_m"])
def test_partial_catalog_names_do_not_receive_exact_bonus(query):
    record = intrinsic("svadd[_f32]_m")["metadata"]
    assert _reference_record_bonus(_analyze_query(query), record, "intrinsic") == 0


@pytest.mark.parametrize("name", ["vaddq_u8", "svadd[_f32]_m"])
@pytest.mark.parametrize("count", [1, 2])
def test_exact_names_remain_searchable_in_small_snapshots(name, count):
    from arm_kb_search.search import bm25_search, build_bm25_index

    metadata = [intrinsic(name)["metadata"] for _ in range(count)]
    index = build_bm25_index(metadata)
    for query in (name, name + ".", name.replace("[", "").replace("]", "") + "."):
        hits = bm25_search(query, metadata, index)
        assert len(hits) == count
        assert all(hit["bm25_score"] > 0 for hit in hits)


def test_api_evidence_treats_literal_catalog_and_expanded_spellings_equally():
    question = "How do I use svadd[_f32]_m?"
    query = _analyze_query(question)
    record = candidate("SVE API", "Documentation", "Use svadd[_f32]_m.")
    score = _rerank_candidates(query, [record])[0]["rerank_score"]
    control = _rerank_candidates(replace(query, code_identifiers=set()), [record])[0]["rerank_score"]
    assert score - control == pytest.approx(.30)


@pytest.mark.parametrize("separator", ["\n", "\r\n", " ", "\n\n"])
def test_signature_evidence_accepts_acquisition_whitespace(separator):
    record = intrinsic()["metadata"]
    record["original_text"] = record["original_text"].replace("follows:\n", "follows:" + separator)
    query = _analyze_query("SVE intrinsic for svuint32_t")
    assert _reference_record_bonus(query, record, "intrinsic") == .35


@pytest.mark.parametrize("text", [None, ""])
def test_identifier_queries_tolerate_empty_optional_search_text(text):
    record = candidate("svmopa_za32_m", "Documentation", text)
    assert rerank_candidates("How do I use svmopa_za32_m?", [record])[0]["metadata"] == record["metadata"]


@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize("catalog_name", ["svadd[_f32]_m", "svst1_scatter[_u32base]_index[_s32]"])
@pytest.mark.parametrize("ending", ["", ".", "..."])
def test_hybrid_and_public_search_preserve_catalog_names_in_small_snapshots(count, catalog_name, ending):
    from arm_kb_search import SearchResources, search
    from arm_kb_search.search import build_bm25_index, hybrid_search

    target = intrinsic(catalog_name, signature=f"svfloat32_t {catalog_name}(void);")["metadata"]
    sibling = intrinsic("svadd[_u32]_m", signature="svuint32_t svadd[_u32]_m(void);")["metadata"]
    metadata = [target, sibling][:count]
    index = build_bm25_index(metadata)
    resources = SearchResources(metadata, object(), None, index, include_disclaimers=False)
    for name in (catalog_name, catalog_name.replace("[", "").replace("]", "")):
        query = name + ending
        hits = hybrid_search(query, None, metadata, object(), index, k=1)
        assert [hit["metadata"] for hit in hits] == [target]
        assert [hit["url"] for hit in search(query, resources, k=1)] == [target["url"]]
        assert hybrid_search(query, None, metadata, object(), index, k=1, eligible_ids=(0,))[0]["metadata"] == target
        assert all(hit["metadata"] != target for hit in
                   hybrid_search(query, None, metadata, object(), index, eligible_ids=tuple(range(1, count))))


def test_preserving_catalog_names_does_not_repeat_prose_query_terms():
    from rank_bm25 import BM25Okapi
    from arm_kb_search.search import _bm25_tokens, bm25_search, hybrid_search

    metadata = [intrinsic("svadd[_f32]_m")["metadata"]]
    metadata.extend(candidate(f"Guide {i}", "Documentation", "Unrelated advice")["metadata"] for i in range(5))
    # A plain prose index deliberately has no canonical-name channel.
    index = BM25Okapi([_bm25_tokens(row["search_text"]) for row in metadata])
    query = "SVE sve svadd[_f32]_m. svadd[_f32]_m."
    lexical_query = " ".join(dict.fromkeys(tokenize_for_search(query)))
    expected = bm25_search(lexical_query, metadata, index, k=10)
    actual = hybrid_search(query, None, metadata, object(), index, k=10)
    assert expected
    assert {r["metadata"]["chunk_uuid"]: r["bm25_score"] for r in actual} == {
        r["metadata"]["chunk_uuid"]: r["bm25_score"] for r in expected
    }
