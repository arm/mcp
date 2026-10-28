"""Prepared keyword data must preserve evidence and reject stale snapshots."""

import gzip
import importlib
import json

import pytest

from arm_kb_search import resources
from arm_kb_search.analysis import Synonyms

scoring = importlib.import_module("arm_kb_search.search")


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    rows = [
        {"chunk_uuid": "0", "url": "https://example.org/0", "title": "AWS", "heading": "CLI",
         "original_text": 'Use PyTorch.'},
        {"chunk_uuid": "1", "url": "https://example.org/1", "original_text": "Scikit-learn"},
        {"chunk_uuid": "2", "url": "https://example.org/2", "original_text": "sklearn\u0301"},
        {"chunk_uuid": "3", "url": "https://example.org/3", "heading": "vaddq_s32",
         "doc_type": "Intrinsic", "original_text": "Use vaddq_s32 on AArch64."},
    ]
    rows.extend({"chunk_uuid": str(i), "url": f"https://example.org/{i}", "original_text": text}
                for i, text in enumerate(("AWS CLI", "Install awscli.",
                                          "AWS-CLI: Installation"), start=len(rows)))
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(rows))
    synonyms = tmp_path / "names.json"
    synonyms.write_text(json.dumps({"awscli": ["AWS CLI", "awscli"],
                                   "scikitlearn": ["Scikit-learn", "sklearn"],
                                   "pytorch": ["PyTorch"]}))
    monkeypatch.setattr(resources, "load_embedding_model", lambda *args, **kwargs: None)
    monkeypatch.setattr(resources, "embedding_dimension", lambda model: 3)
    monkeypatch.setattr(resources, "load_usearch_index", lambda *args: None)
    return rows, metadata, synonyms


def load(metadata, synonyms, **kwargs):
    return resources.load_search_resources(str(metadata), "unused", synonyms_path=str(synonyms),
                                           include_disclaimers=False, **kwargs)


def test_keyword_cache_matches_uncached_retrieval_without_tokenizing(snapshot, monkeypatch):
    rows, metadata, synonyms = snapshot
    before = load(metadata, synonyms)
    resources.write_keyword_cache(str(metadata), synonyms_path=str(synonyms))

    def unexpected_tokenization(*args, **kwargs):
        pytest.fail("A matching keyword cache must avoid document tokenization")

    monkeypatch.setattr(scoring, "_bm25_tokens", unexpected_tokenization)
    after = load(metadata, synonyms)
    assert after.bm25_index.doc_freqs == before.bm25_index.doc_freqs
    assert after.bm25_index.doc_len == before.bm25_index.doc_len
    assert after.bm25_index.idf == before.bm25_index.idf
    for query in ("awscli", "pytorch", "sklearn", "Scikit-learn", "sklearn\u0301", "vaddq_s32", "arm64"):
        assert resources.search(query, after) == resources.search(query, before)
    assert {hit["url"] for hit in resources.search("awscli", after)} == {row["url"] for row in rows[4:]}
    assert [hit["url"] for hit in resources.search("sklearn", after)] == [rows[1]["url"]]


@pytest.mark.parametrize("change", ["metadata", "order", "synonyms", "analyzer"])
def test_keyword_cache_invalidates_when_inputs_change(snapshot, monkeypatch, change):
    rows, metadata, synonyms = snapshot
    cache = resources.write_keyword_cache(str(metadata), synonyms_path=str(synonyms))
    if change == "metadata":
        rows[1]["original_text"] = "PyTorch"
        metadata.write_text(json.dumps(rows))
    elif change == "order":
        metadata.write_text(json.dumps(list(reversed(rows))))
    elif change == "synonyms":
        synonyms.write_text(json.dumps({"awscli": ["AWS CLI", "awscli"]}))
    else:
        original = resources._keyword_fingerprint
        monkeypatch.setattr(resources, "_keyword_fingerprint",
                            lambda *args: {**original(*args), "source": {"analysis.py": "changed"}})
    assert resources._load_keyword_cache(cache, str(metadata), str(synonyms), len(rows)) is None
    actual = load(metadata, synonyms)
    expected = load(metadata, synonyms, keyword_cache_path=str(metadata.parent / "missing"))
    assert actual.bm25_index.doc_freqs == expected.bm25_index.doc_freqs
    assert actual.bm25_index.idf == expected.bm25_index.idf


@pytest.mark.parametrize("corruption", ["truncated", "json", "rows", "negative", "large", "float", "bool", "term"])
def test_invalid_keyword_cache_falls_back(snapshot, corruption):
    rows, metadata, synonyms = snapshot
    expected = load(metadata, synonyms)
    cache = resources.write_keyword_cache(str(metadata), synonyms_path=str(synonyms))
    with gzip.open(cache, "rt") as stream:
        header = stream.readline()
        data = json.load(stream)
    if corruption == "truncated":
        cache.write_bytes(cache.read_bytes()[:-12])
    else:
        if corruption == "rows":
            data["documents"].pop()
        elif corruption == "term":
            data["vocabulary"][0] = None
        elif corruption != "json":
            data["documents"][0][0] = {"negative": -1, "large": 1000000, "float": 1.5, "bool": True}[corruption]
        with gzip.open(cache, "wt") as stream:
            stream.write(header)
            stream.write("{" if corruption == "json" else json.dumps(data))
    actual = load(metadata, synonyms)
    assert actual.bm25_index.doc_freqs == expected.bm25_index.doc_freqs
    assert actual.bm25_index.idf == expected.bm25_index.idf


@pytest.mark.parametrize("rows", [[], [{"original_text": ""}], [{"original_text": "sklearn"}]])
def test_cache_handles_empty_and_single_document_corpora(snapshot, rows):
    _, metadata, synonyms = snapshot
    metadata.write_text(json.dumps(rows))
    before = load(metadata, synonyms)
    resources.write_keyword_cache(str(metadata), synonyms_path=str(synonyms))
    after = load(metadata, synonyms)
    if before.bm25_index is None:
        assert after.bm25_index is None
    else:
        assert after.bm25_index.get_scores(["__name_scikitlearn"]).tolist() == (
            before.bm25_index.get_scores(["__name_scikitlearn"]).tolist())
        assert after.bm25_index.get_scores(["__name_scikitlearn"])[0] > 0


def test_cache_is_deterministic_and_inherits_metadata_read_permissions(snapshot):
    _, metadata, synonyms = snapshot
    metadata.chmod(0o640)
    cache = resources.write_keyword_cache(str(metadata), synonyms_path=str(synonyms))
    first = cache.read_bytes()
    resources.write_keyword_cache(str(metadata), synonyms_path=str(synonyms))
    assert cache.read_bytes() == first
    assert cache.stat().st_mode & 0o777 == 0o640


def test_disabled_synonyms_do_not_reuse_an_alias_cache(snapshot):
    rows, metadata, synonyms = snapshot
    cache = resources.write_keyword_cache(str(metadata), synonyms_path=str(synonyms))
    assert resources._load_keyword_cache(cache, str(metadata), None, len(rows)) is None


def test_prepared_corpus_requires_matching_metadata_count():
    with pytest.raises(ValueError, match="row counts"):
        scoring.build_bm25_index([{"original_text": "PyTorch"}], Synonyms({}), tokenized_corpus=[])
