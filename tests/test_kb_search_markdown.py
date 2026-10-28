"""Visible Markdown evidence must agree across tokenization and ranking."""

import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from arm_kb_search import SearchResources, search
from arm_kb_search.analysis import Synonyms, analyze, atom, name_keys, searchable_text
from arm_kb_search.loaders import load_metadata
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


@pytest.mark.parametrize("text,query,key", [
    ("λsklearn", "sklearn", "scikitlearn"),
    ("sklearné", "sklearn", "scikitlearn"),
    ("awsλcli", "awscli", "awscli"),
    ("工具sklearn", "sklearn", "scikitlearn"),
    ("sklearn工具", "sklearn", "scikitlearn"),
    ("aws工具cli", "awscli", "awscli"),
    ("２sklearn", "sklearn", "scikitlearn"),
    ("sklearn２", "sklearn", "scikitlearn"),
    ("aws２cli", "awscli", "awscli"),
    ("sklearn\u0301", "sklearn", "scikitlearn"),
    ("sk\u0301learn", "sklearn", "scikitlearn"),
    ("aws\u0903cli", "awscli", "awscli"),
    ("sklearn\u20dd", "sklearn", "scikitlearn"),
    ("sklearn\u203f", "sklearn", "scikitlearn"),
    ("sklearn\u00b7", "sklearn", "scikitlearn"),
    ("sklearn\u0387", "sklearn", "scikitlearn"),
    ("İsklearn", "sklearn", "scikitlearn"),
    ("Scikit\u0301-learn", "Scikit-learn", "scikitlearn"),
])
def test_unicode_identifiers_cannot_become_product_aliases(text, query, key, synonyms):
    for is_query in [False, True]:
        tokens = analyze(text, synonyms, query=is_query)
        assert text.lower() in tokens
        assert key not in name_keys(tokens, synonyms)
    assert search(query, resource(text, synonyms)) == []
    assert search(text, resource(query, synonyms)) == []
    # Ordinary literal terms need background rows for positive BM25 IDF.
    rows = [{"chunk_uuid": str(i), "url": f"https://example.org/{i}", "search_text": value}
            for i, value in enumerate([text, "unrelated guide", "background reference"])]
    state = SearchResources(rows, None, None, build_bm25_index(rows, synonyms),
                            include_disclaimers=False, synonyms=synonyms)
    assert [hit["url"] for hit in search(text, state)] == ["https://example.org/0"]
    assert scoring._score_lexical_exactness(
        scoring._analyze_query(query, synonyms), {"search_text": text, "title": text}) == 0


@pytest.mark.parametrize("text", ["AWS λ CLI", "AWS 工具 CLI", "AWS \u0301 CLI"])
def test_unicode_words_keep_name_components_separate(text, synonyms):
    assert "awscli" not in name_keys(analyze(text, synonyms), synonyms)
    assert search("awscli", resource(text, synonyms)) == []


@pytest.mark.parametrize("text", [
    "- AWS\n- CLI", "+ AWS\n+ CLI", "* AWS\n* CLI", "1. AWS\n2. CLI",
    "> - AWS\n> - CLI", "- AWS\n  - CLI", "AWS\n- CLI", "# AWS\n# CLI",
])
def test_markdown_blocks_do_not_assemble_product_names_without_links(text, synonyms):
    for content in [text, text + "\n\n[unused]: /guide"]:
        assert "awscli" not in name_keys(analyze(content, synonyms), synonyms)
        assert search("awscli", resource(content, synonyms)) == []


@pytest.mark.parametrize("text", ["AWS\nCLI", "- AWS CLI\n- other", "- AWS\n  CLI"])
def test_names_survive_within_a_single_markdown_paragraph(text, synonyms):
    assert "awscli" in name_keys(analyze(text, synonyms), synonyms)
    assert search("awscli", resource(text, synonyms))


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
        '[AWS CLI](/guide): Installation',
        'AWS [CLI](/guide)',
        '[AWS](/guide) CLI',
        '[1](/guide). AWS CLI',
        '[# AWS CLI](/guide)',
        '[[AWS CLI]](/guide): visible label',
        '```text\n[reference]: Scikit-learn\n```\n\n[AWS CLI]: /guide',
        '> Use [AWS CLI].\n>\n> [AWS CLI]: /guide "Scikit-learn"',
        '    [reference]: Scikit-learn\n\n[AWS CLI]: /guide',
    ]:
        visible = searchable_text(text)
        assert searchable_text(visible) == visible
        assert analyze(text, synonyms) == analyze(visible, synonyms)
        for field in ("title", "original_text", "search_text"):
            row = {field: text}
            combined = scoring._metadata_text(row, (field,))
            assert combined == visible
            assert analyze(combined, synonyms) == analyze(text, synonyms)


@pytest.mark.parametrize("text", [
    'AWS [CLI](/guide)', '[AWS](/guide) CLI', '[AWS](/aws) [CLI](/cli)',
    '[AWS CLI](/guide): Installation', '> AWS [CLI](/guide)', '- [AWS](/guide) CLI',
    'AWS\n[CLI](/guide)', 'AWS [CLI][guide]\n\n[guide]: /guide "Scikit-learn"',
    '[AWS][guide] CLI\n\n[guide]: /guide', 'AWS [CLI][]\n\n[CLI]: /guide',
    'AWS [CLI]\n\n[CLI]: /guide', '[AWS](/guide)CLI',
])
def test_partial_links_preserve_name_adjacency(text, synonyms, tmp_path, monkeypatch):
    from arm_kb_search import resources

    visible = searchable_text(text)
    assert searchable_text(visible) == visible
    for query_mode in (False, True):
        assert atom("awscli") in analyze(text, synonyms, query=query_mode)
        assert analyze(visible, synonyms, query=query_mode) == analyze(text, synonyms, query=query_mode)
    rows = [{"chunk_uuid": "0", "url": "https://example.org/guide", "original_text": text}]
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(rows))
    table = str(Path(__file__).resolve().parents[1] / "mcp-local/name-synonyms.json")
    monkeypatch.setattr(resources, "load_embedding_model", lambda *args, **kwargs: None)
    monkeypatch.setattr(resources, "embedding_dimension", lambda model: 3)
    monkeypatch.setattr(resources, "load_usearch_index", lambda *args: None)
    for cached in (False, True):
        if cached:
            resources.write_keyword_cache(str(metadata), synonyms_path=table)
        state = resources.load_search_resources(str(metadata), "unused", synonyms_path=table,
                                                include_disclaimers=False)
        assert [hit["url"] for hit in search("awscli", state)] == ["https://example.org/guide"]
        assert search("sklearn", state) == []
        query = scoring._analyze_query("awscli", synonyms)
        assert scoring._score_lexical_exactness(query, rows[0]) > 0
        candidate = {"metadata": rows[0], "metadata_id": 0, "distance": 0.2}
        direct = scoring.rerank_candidates("awscli", [candidate], synonyms=synonyms)
        indexed = scoring._rerank_candidates(query, [candidate], state.bm25_index)
        assert direct[0]["rerank_score"] == indexed[0]["rerank_score"]


@pytest.mark.parametrize("text", [
    'array[AWS](/guide) CLI', 'AWS[CLI](/guide)', '[AWS](/guide)\n\nCLI',
    '- [AWS](/guide)\n- CLI', '[AWS](/guide)_extra CLI', '[sklearn](/guide)\u0301',
    'AWS [CLI](/guide)\u0301', 'AWS [CLI](/guide)()',
])
def test_partial_links_do_not_erase_identifier_or_block_boundaries(text, synonyms):
    visible = searchable_text(text)
    for query_mode in (False, True):
        assert not {"awscli", "scikitlearn"} & name_keys(analyze(text, synonyms, query=query_mode), synonyms)
        assert analyze(visible, synonyms, query=query_mode) == analyze(text, synonyms, query=query_mode)
    rows = [{"chunk_uuid": "0", "url": "https://example.org/guide", "original_text": text}]
    state = SearchResources(rows, None, None, build_bm25_index(rows, synonyms),
                            include_disclaimers=False, synonyms=synonyms)
    assert search("awscli", state) == []
    assert search("sklearn", state) == []


def test_declared_multiword_names_survive_partial_links(synonyms):
    rules = json.loads((Path(__file__).resolve().parents[1] / "mcp-local/name-synonyms.json").read_text())
    for key, forms in rules.items():
        for form in forms:
            words = form.split()
            if len(words) < 2:
                continue
            for start in range(len(words)):
                for end in range(start + 1, len(words) + 1):
                    linked = " ".join([*words[:start], "[" + " ".join(words[start:end]) + "](/guide)", *words[end:]])
                    assert atom(key) in analyze(linked, synonyms), linked
                    assert atom(key) in analyze(linked, synonyms, query=True), linked


@pytest.mark.parametrize("fields,query", [
    ({"title": "AWS", "heading": "CLI", "original_text": "neutral", "search_text": "AWS CLI neutral"}, "awscli"),
    ({"heading_path": ["AWS", "CLI"], "original_text": "neutral", "search_text": "AWS CLI neutral"}, "awscli"),
    ({"title": "AWS", "original_text": "CLI", "search_text": "AWS CLI"}, "awscli"),
    ({"product": "AWS", "version": "CLI", "original_text": "", "search_text": "AWS CLI"}, "awscli"),
    ({"keywords": ["AWS", "CLI"], "original_text": "", "search_text": "AWS CLI"}, "awscli"),
    ({"original_text": "", "search_text": "sklearn"}, "sklearn"),
    ({"title": "neutral", "original_text": '[AWS CLI]: /guide\n  "Scikit-learn documentation"',
      "search_text": 'neutral [AWS CLI]: /guide\n  "Scikit-learn documentation"'}, "sklearn"),
    ({"title": "neutral", "content": '[AWS CLI]: /guide\n  "Scikit-learn documentation"',
      "search_text": 'neutral [AWS CLI]: /guide\n  "Scikit-learn documentation"'}, "sklearn"),
    ({"title": "[AWS CLI]", "original_text": "[AWS CLI]: /guide", "search_text": "[AWS CLI] [AWS CLI]: /guide"}, "awscli"),
    ({"title": "AWS", "heading_path": ["CLI"], "original_text":
      'Document Title: AWS\nHeading Path: CLI\n\n[AWS CLI]: /guide\n  "Scikit-learn documentation"',
      "search_text": 'AWS CLI Document Title: AWS\nHeading Path: CLI\n\n[AWS CLI]: /guide\n  "Scikit-learn documentation"'}, "awscli"),
])
def test_existing_snapshots_keep_field_and_body_evidence_separate(tmp_path, fields, query, synonyms):
    row = {"chunk_uuid": "0", "url": "https://example.org/guide", **fields}
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps([row]))
    rows = load_metadata(str(path))
    original = deepcopy(rows)
    index = build_bm25_index(rows, synonyms)
    state = SearchResources(rows, None, None, index, include_disclaimers=False, synonyms=synonyms)
    assert search(query, state) == []
    analyzed = scoring._analyze_query(query, synonyms)
    candidate = {"metadata": rows[0], "metadata_id": 0, "distance": 0.2}
    for cached in [None, scoring._body_tokens(candidate, index)]:
        assert scoring._score_lexical_exactness(analyzed, rows[0], cached) == 0
    direct = scoring.rerank_candidates(query, [candidate], synonyms=synonyms)
    indexed = scoring._rerank_candidates(analyzed, [candidate], index)
    assert direct[0]["rerank_score"] == indexed[0]["rerank_score"]
    assert rows == original


@pytest.mark.parametrize("fields", [
    {"title": "AWS CLI", "original_text": "neutral"},
    {"heading_path": ["neutral", "AWS CLI"], "original_text": "neutral"},
    {"title": "neutral", "original_text": "Use AWS CLI."},
    {"title": "neutral", "content": "Use AWS CLI."},
    {"original_text": "Use [AWS CLI].\n\n[AWS CLI]: /guide"},
])
def test_structured_fields_preserve_real_names_without_flattened_search_text(fields, synonyms):
    rows = [{"chunk_uuid": "0", "url": "https://example.org/guide", **fields}]
    state = SearchResources(rows, None, None, build_bm25_index(rows, synonyms),
                            include_disclaimers=False, synonyms=synonyms)
    assert [hit["url"] for hit in search("awscli", state)] == ["https://example.org/guide"]


@pytest.mark.parametrize("name", ["PyTorch", "sklearn"])
@pytest.mark.parametrize("suffix", ["\u0301", "()"])
def test_identifier_boundaries_cannot_grant_a_product_support_bonus(name, suffix, synonyms):
    query = scoring._analyze_query(f"Is {name}{suffix} supported on Arm Linux?", synonyms)
    row = {"heading": name, "platform": "linux"}
    assert scoring._reference_record_bonus(query, row, "ecosystem dashboard") == 0


@pytest.mark.parametrize("url", [
    "https://example.org/sklearn%CC%81",
    "https://example.org/?tool=sklearn%CC%81",
    "https://example.org/#sklearn%CC%81",
])
def test_encoded_unicode_identifiers_cannot_supply_url_name_evidence(url, synonyms):
    query = scoring._analyze_query("sklearn", synonyms)
    assert scoring._score_lexical_exactness(query, {"url": url, "original_text": "neutral"}) == 0


def test_encoded_whole_product_names_still_supply_url_evidence(synonyms):
    query = scoring._analyze_query("sklearn", synonyms)
    row = {"url": "https://example.org/Scikit%20learn", "original_text": "neutral"}
    assert scoring._score_lexical_exactness(query, row) > 0


def test_non_latin_literal_identifier_remains_searchable(synonyms):
    text = "किताब"
    rows = [{"chunk_uuid": str(i), "url": f"https://example.org/{i}", "original_text": value}
            for i, value in enumerate([text, "background", "unrelated"])]
    state = SearchResources(rows, None, None, build_bm25_index(rows, synonyms),
                            include_disclaimers=False, synonyms=synonyms)
    assert [hit["url"] for hit in search(text, state)] == ["https://example.org/0"]
