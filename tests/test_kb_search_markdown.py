"""Visible Markdown evidence must agree across tokenization and ranking."""

import importlib
from pathlib import Path

import pytest

from arm_kb_search import SearchResources, search
from arm_kb_search.analysis import Synonyms, analyze, atom, name_keys, searchable_text
from arm_kb_search.search import bm25_search, build_bm25_index

scoring = importlib.import_module("arm_kb_search.search")


@pytest.fixture(scope="module")
def synonyms():
    return Synonyms.load(Path(__file__).resolve().parents[1] / "mcp-local/name-synonyms.json")


def resource(text, synonyms):
    rows = [{"chunk_uuid": "0", "url": "https://example.org/guide", "search_text": text}]
    return SearchResources(rows, None, None, build_bm25_index(rows, synonyms),
                           include_disclaimers=False, synonyms=synonyms)


@pytest.mark.parametrize("text", [
    '[AWS CLI]: /guide "Scikit learn"',
    '> [AWS CLI]: /guide\n>   "Scikit learn"',
    '- [AWS CLI]: /guide\n    "Scikit learn"',
    '1. [AWS CLI]: /guide\n     "Scikit learn"',
    '> - [AWS CLI]: /guide\n>     "Scikit learn"',
    '[AWS CLI]: /guide\n  "Scikit learn"\n[AWS CLI]: /other "Scikit learn"',
    '[neutral label](/awscli "Scikit learn")',
    '![neutral label](/awscli "Scikit learn")',
    '[neutral label](/awscli(foo(bar)) "Scikit learn")',
    '[neutral label](/awscli\n  "Scikit learn")',
    'array[neutral label](/awscli "Scikit learn")',
    'word![neutral label](/awscli "Scikit learn")',
    '[![neutral label](/awscli "Scikit learn")](/outer)',
])
def test_hidden_link_metadata_has_no_sparse_or_field_scoring_evidence(text, synonyms):
    state = resource(text, synonyms)
    for query in ["awscli", "AWS CLI", "sklearn", "Scikit learn"]:
        assert search(query, state) == []
        analyzed = scoring._analyze_query(query, synonyms)
        assert scoring._score_lexical_exactness(analyzed, state.metadata[0]) == 0
        # Dense retrieval may supply any row; hidden metadata must not improve it.
        candidate = {"metadata": state.metadata[0], "distance": 0.2}
        empty = {"metadata": {**state.metadata[0], "search_text": "neutral label"}, "distance": 0.2}
        actual = scoring.rerank_candidates(query, [candidate], synonyms=synonyms)[0]
        expected = scoring.rerank_candidates(query, [empty], synonyms=synonyms)[0]
        assert actual["rerank_score"] == expected["rerank_score"]


@pytest.mark.parametrize("text", [
    '```text\n[reference]: Scikit-learn\n```',
    '~~~text\n[reference]: Scikit-learn\n~~~',
    '    [reference]: Scikit-learn',
    'This is visible prose.\n[reference]: Scikit-learn',
    '[^note]: Scikit-learn',
    '[Scikit-learn](/guide "AWS CLI")',
    '> Use [Scikit-learn].\n>\n> [Scikit-learn]: /guide "AWS CLI"',
    '- Use [Scikit-learn].\n\n  [Scikit-learn]: /guide "AWS CLI"',
])
def test_visible_names_survive_markdown_contexts(text, synonyms):
    assert atom("scikitlearn") in analyze(text, synonyms)
    assert [row["url"] for row in search("sklearn", resource(text, synonyms))] == ["https://example.org/guide"]


@pytest.mark.parametrize("text", [
    '```text\n[sklearn]: /guide\n```\n\n[sklearn]',
    'Visible prose\n[sklearn]: /guide\n\n[sklearn]',
    r'\[sklearn](/guide)',
    r'\[sklearn][guide]',
    'array[sklearn](/guide)',
    'array[sklearn][guide]',
])
def test_nonlinks_do_not_authorize_product_names(text, synonyms):
    assert atom("scikitlearn") not in analyze(text, synonyms)


@pytest.mark.parametrize("text", ["AWS\n\nCLI", "AWS\r\n \r\nCLI", "AWS\r\rCLI"])
def test_names_do_not_join_across_paragraphs(text, synonyms):
    assert "awscli" not in name_keys(analyze(text, synonyms), synonyms)
    assert search("awscli", resource(text, synonyms)) == []


def test_name_fragments_do_not_join_across_metadata_fields(synonyms):
    query = scoring._analyze_query("AWS CLI", synonyms)
    assert scoring._score_lexical_exactness(query, {"title": "AWS", "heading": "CLI"}) == 0
    assert scoring._score_lexical_exactness(query, {"heading_path": ["AWS", "CLI"]}) == 0


def test_literal_identifier_cannot_impersonate_a_canonical_name(synonyms):
    rows = [{"chunk_uuid": str(i), "url": f"https://example.org/{i}", "search_text": text}
            for i, text in enumerate(["__name_scikitlearn", "Scikit-learn", "background"])]
    state = SearchResources(rows, None, None, build_bm25_index(rows, synonyms),
                            include_disclaimers=False, synonyms=synonyms)
    assert not name_keys(analyze("__name_scikitlearn", synonyms), synonyms)
    for query in ["sklearn", "Scikit-learn"]:
        assert [row["url"] for row in search(query, state)] == ["https://example.org/1"]
    assert [row["url"] for row in search("__name_scikitlearn", state)] == ["https://example.org/0"]


def test_all_reserved_name_identifiers_remain_literal(synonyms):
    for key in synonyms.keys:
        for query in [False, True]:
            assert not name_keys(analyze("__name_" + key, synonyms, query=query), synonyms)


def test_url_identifiers_cannot_impersonate_name_atoms(synonyms):
    metadata = {"url": "https://example.org/__name_scikitlearn", "search_text": "neutral"}
    for query in ["sklearn", "Scikit learn"]:
        assert scoring._score_lexical_exactness(scoring._analyze_query(query, synonyms), metadata) == 0


def test_intrinsic_name_channel_cannot_impersonate_product_atoms(synonyms):
    rows = [{"chunk_uuid": "0", "url": "https://example.org/guide", "search_text": "neutral",
             "heading": "__name_scikitlearn", "doc_type": "Intrinsic"}]
    state = SearchResources(rows, None, None, build_bm25_index(rows, synonyms),
                            include_disclaimers=False, synonyms=synonyms)
    assert search("sklearn", state) == []
    assert [row["url"] for row in search("__name_scikitlearn", state)] == ["https://example.org/guide"]


def test_positive_name_scores_across_small_corpora_and_filters(synonyms):
    for size in range(1, 7):
        for named in range(1, size + 1):
            rows = [{"search_text": "sklearn" if i < named else "background"} for i in range(size)]
            index = build_bm25_index(rows, synonyms)
            for query in ["sklearn", "Scikit-learn", "scikit_learn", "Scikit learn"]:
                for ids in [None, tuple(range(size)), (0,), (size - 1,)]:
                    hits = bm25_search(query, rows, index, k=size, synonyms=synonyms, eligible_ids=ids)
                    expected = set(range(named)) & (set(ids) if ids is not None else set(range(size)))
                    assert {hit["metadata_id"] for hit in hits} == expected
                    assert all(hit["bm25_score"] > 0 for hit in hits)


@pytest.mark.parametrize("suffix", ["tools", "package", "instructions", "latest release"])
@pytest.mark.parametrize("context", ["", " on RHEL"])
def test_installation_bonus_requires_the_named_product(suffix, context, synonyms):
    query = scoring._analyze_query(f"install Arm Compiler for Linux {suffix}{context}", synonyms)
    assert query.entity_query_tokens == {atom("armcompilerforlinux")}
    _, unrelated_bonus = scoring._document_type_bonuses(
        query, {"doc_type": "Install Guide"}, title_tokens=set(suffix.split()),
        heading_tokens=set(), url_tokens=set(), title_url_tokens=set(suffix.split()),
    )
    assert unrelated_bonus < scoring.INSTALL_GUIDE_BONUS


def test_markdown_cleanup_is_idempotent(synonyms):
    for text in [
        'Use [AWS CLI](/guide "Scikit-learn").',
        '```text\n[reference]: Scikit-learn\n```\n\n[AWS CLI]: /guide',
        '> Use [AWS CLI].\n>\n> [AWS CLI]: /guide "Scikit-learn"',
        '    [reference]: Scikit-learn\n\n[AWS CLI]: /guide',
    ]:
        visible = searchable_text(text)
        assert searchable_text(visible) == visible
        assert analyze(text, synonyms) == analyze(visible, synonyms)
