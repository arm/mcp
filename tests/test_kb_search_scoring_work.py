# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
"""Score-preserving query-local work reuse, without a corpus token cache."""

import importlib
from collections import Counter

import pytest
from arm_kb_search import SearchResources, search
from arm_kb_search.names import NameIndex

s = importlib.import_module("arm_kb_search.search")


def rows():
    return [
        dict(
            chunk_uuid=str(i),
            title=title,
            heading=title,
            doc_type="Install Guides",
            original_text=body,
            search_text=title + " " + body,
            url=f"https://example.org/{i}",
        )
        for i, (title, body) in enumerate(
            [
                ("Maple Studio", "editor documentation"),
                ("Other Tool", "background instructions"),
                ("Unrelated Package", "reference"),
            ]
        )
    ]


def test_single_name_scoring_does_not_rebuild_unused_body_view(tmp_path, monkeypatch):
    data = rows()
    path = tmp_path / "names.json"
    NameIndex.precompute(data, path)
    index = NameIndex.load_precomputed(data, path)
    query = s._analyze_query("maplestudio", index)
    bm25 = s.build_bm25_index(data)
    body = index.body_tokens(0, bm25.doc_freqs[0], query.name_keys)
    original = s._matching_metadata_text

    def checked(query, row, fields):
        assert "search_text" not in fields, (
            "body string rebuilt despite no phrase or capability evidence"
        )
        return original(query, row, fields)

    monkeypatch.setattr(s, "_matching_metadata_text", checked)
    assert s._score_lexical_exactness(query, data[0], body) == pytest.approx(1.15)


def test_search_reuses_field_projection_across_scoring_stages_only_within_query(
    tmp_path, monkeypatch
):
    data = rows()
    path = tmp_path / "names.json"
    NameIndex.precompute(data, path)
    index = NameIndex.load_precomputed(data, path)
    resources = SearchResources(
        data,
        object(),
        None,
        s.build_bm25_index(data),
        include_disclaimers=False,
        prepared_name_index=index,
    )
    original = s._matching_metadata_text
    counts = Counter()

    def counted(query, row, fields):
        if fields == ("title",):
            counts[row["chunk_uuid"]] += 1
        return original(query, row, fields)

    monkeypatch.setattr(s, "_matching_metadata_text", counted)
    assert (
        search("install maple_studio", resources, k=1)[0]["url"]
        == "https://example.org/0"
    )
    assert counts["0"] == 1, (
        "title projection repeated across lexical and final scoring"
    )
    counts.clear()
    assert search("other tool", resources, k=1)[0]["url"] == "https://example.org/1"
    assert counts["1"] == 1


def test_non_capability_query_skips_unused_support_evidence_text(tmp_path, monkeypatch):
    data = rows()
    path = tmp_path / "names.json"
    NameIndex.precompute(data, path)
    index = NameIndex.load_precomputed(data, path)
    bm25 = s.build_bm25_index(data)
    query = s._analyze_query("maplestudio", index)
    original = s._metadata_text

    def guard(metadata, fields):
        assert "search_text" not in fields, "unused support evidence body rebuilt"
        return original(metadata, fields)

    monkeypatch.setattr(s, "_metadata_text", guard)
    assert s._rerank_candidates(
        query, [{"metadata": data[0], "metadata_id": 0}], bm25_index=bm25
    )


def test_resolved_url_only_keeps_install_guide_identity_credit():
    common = dict(
        title="Installation guide",
        heading="Setup",
        doc_type="Install Guides",
        search_text="Instructions",
        original_text="Instructions",
    )
    url = "https://example.org/install/widget"
    query = s._analyze_query("install widget")
    with_url = s._rerank_candidates(query, [{"metadata": dict(common, url=url)}])[0][
        "rerank_score"
    ]
    with_resolved_url = s._rerank_candidates(
        query,
        [{"metadata": dict(common, resolved_url=url)}],
    )[0]["rerank_score"]
    assert with_resolved_url == pytest.approx(with_url)


def test_field_overlap_preserves_arithmetic_order_for_stable_ties():
    # One ULP can change a prepass tie, then alter resource-rank fusion.
    query = s._analyze_query("alpha bravo charlie delta echo foxtrot golf")
    actual = s._score_lexical_exactness(query, {"title": "golf echo charlie alpha"})
    assert actual == 0.45 * (4 / 7)


def test_lexical_prepass_preserves_tied_candidate_order():
    query = s._analyze_query("alpha bravo charlie delta echo foxtrot golf")
    first = {
        "metadata": {
            "chunk_uuid": "B",
            "keywords": "golf echo charlie alpha",
            "search_text": "golf",
        }
    }
    second = {
        "metadata": {
            "chunk_uuid": "A",
            "search_text": "golf foxtrot echo delta charlie bravo",
        }
    }
    ranked = s._rank_lexical_candidates(query, [first, second], k=2)
    assert [item["metadata"]["chunk_uuid"] for item in ranked] == ["B", "A"]


def test_query_name_matching_is_reused_for_candidate_lookup(tmp_path, monkeypatch):
    data = rows()
    path = tmp_path / "names.json"
    NameIndex.precompute(data, path)
    index = NameIndex.load_precomputed(data, path)
    resources = SearchResources(data, None, None, s.build_bm25_index(data),
                                include_disclaimers=False, prepared_name_index=index)
    query = "install maple_studio on Linux"
    calls = []
    original = index.match

    def counted(text):
        if text == query:
            calls.append(text)
        return original(text)

    monkeypatch.setattr(index, "match", counted)
    assert search(query, resources, k=1)[0]["url"] == "https://example.org/0"
    assert len(calls) == 1
