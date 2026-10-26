"""Prepared evidence must preserve raw-name scoring and reject stale snapshots."""

import importlib
import json
from collections import Counter
from unittest.mock import patch

import pytest

from arm_kb_search.names import NameIndex

search_module = importlib.import_module("arm_kb_search.search")


def row(number, title, text, **fields):
    return dict(
        chunk_uuid=str(number),
        title=title,
        original_text=text,
        search_text=title + " " + text,
        url=f"https://example.org/{number}",
        doc_type="Install Guides",
        **fields,
    )


def prepared(rows, tmp_path):
    path = tmp_path / "names.json"
    NameIndex.precompute(rows, path)
    return NameIndex.load_precomputed(rows, path)


@pytest.mark.parametrize(
    "query", ["awscli", "AWS-CLI", "aws_cli", "AWS.CLI", "AWS CLI."]
)
def test_roundtrip_keeps_complete_name_and_filters_before_cap(query, tmp_path):
    rows = [
        row(0, "AWS CLI", "client"),
        row(1, "AWS SAM CLI", "other"),
        row(2, "AWSCLI", "client"),
    ]
    rows += [row(i, "AWS CLI", "client") for i in range(3, 110)]
    index = prepared(rows, tmp_path)
    assert index.keys(query) == frozenset({"awscli"})
    assert index.candidates(query, eligible_ids=(2, 109), limit=1) == [2]
    assert 1 not in index.candidates(query)


def test_changed_corpus_or_reordered_rows_rejected(tmp_path):
    rows = [row(0, "AWS CLI", "client"), row(1, "Node.js", "server")]
    prepared(rows, tmp_path)
    with pytest.raises(ValueError, match="corpus"):
        NameIndex.load_precomputed(rows[::-1], tmp_path / "names.json")
    rows[0]["original_text"] = "changed body"
    with pytest.raises(ValueError, match="corpus"):
        NameIndex.load_precomputed(rows, tmp_path / "names.json")


def test_body_patch_preserves_unmatched_word_occurrences_and_punctuation(tmp_path):
    rows = [
        row(0, "AWS CLI", "aws cli aws. AWSCLI. Docker-Compose and docker"),
        row(1, "Docker Compose", "services"),
    ]
    index = prepared(rows, tmp_path)
    frequencies = Counter(search_module._bm25_tokens(rows[0]["search_text"]))
    actual = index.body_tokens(0, frequencies, {"awscli", "dockercompose"})
    assert actual == {
        "__name_awscli",
        "aws.",
        "__name_dockercompose",
        "and",
        "docker",
        "install",
        "guides",
    }
    assert frequencies == Counter(search_module._bm25_tokens(rows[0]["search_text"]))


def test_cached_fields_cannot_create_names_across_fields_or_overlap(tmp_path):
    rows = [
        row(0, "Visual Studio Code", "AWS", heading="CLI"),
        row(1, "Visual Studio", "short"),
        row(2, "AWS CLI", "client"),
    ]
    index = prepared(rows, tmp_path)
    assert (
        index.project_field(rows[0], "title", 0, "Visual Studio Code", {"visualstudio"})
        == "Visual Studio Code"
    )
    assert (
        index.project_field(
            rows[0], "title", 0, "Visual Studio Code", {"visualstudiocode"}
        )
        == "__name_visualstudiocode"
    )
    assert 0 not in index.candidates("awscli")


def test_loaded_scoring_does_not_rescan_names_or_retokenize_body(tmp_path):
    body = "AWS CLI is installed. Docker Compose uses docker. " * 30
    rows = [
        row(0, "AWS CLI", body),
        row(1, "Docker Compose", "services"),
        row(2, "Other", "background"),
    ]
    index = prepared(rows, tmp_path)
    bm25 = search_module.build_bm25_index(rows)
    query = search_module._analyze_query("install aws_cli docker-compose", index)
    reference = search_module._analyze_query(
        "install aws_cli docker-compose", NameIndex(rows)
    )
    expected = search_module._rerank_candidates(reference, [{"metadata": rows[0]}])[0][
        "rerank_score"
    ]
    tokenizer = search_module.tokenize_for_search

    def guard(text):
        assert len(text) < len(body), "document body tokenized again"
        return tokenizer(text)

    with (
        patch.object(index, "match", side_effect=AssertionError("document name scan")),
        patch.object(search_module, "tokenize_for_search", side_effect=guard),
    ):
        actual = search_module._rerank_candidates(
            query,
            [{"metadata": rows[0], "metadata_id": 0}],
            bm25_index=bm25,
        )[0]["rerank_score"]
    assert actual == pytest.approx(expected)


@pytest.mark.parametrize(
    "text",
    [
        ".NET C++ C# svadd[_f32]_m svint32_t svuint32_t",
        "aws cli2 aws cli_tools .awscli",
        "Visual Studio Code and Visual Studio",
        "AWS_CLI. aws CLI and aws",
    ],
)
def test_precomputed_scoring_matches_existing_raw_field_semantics(text, tmp_path):
    rows = [
        row(0, "AWS CLI", text),
        row(1, "Visual Studio Code", "long"),
        row(2, "Visual Studio", "short"),
    ]
    index = prepared(rows, tmp_path)
    bm25 = search_module.build_bm25_index(rows)
    original = NameIndex(rows)
    for query in [
        "awscli",
        "visualstudio",
        "visual-studio_code",
        "aws cli visual studio code",
        "C++ svadd_f32_m",
    ]:
        expected = search_module._rerank_candidates(
            search_module._analyze_query(query, original),
            [{"metadata": rows[0]}],
        )[0]["rerank_score"]
        actual = search_module._rerank_candidates(
            search_module._analyze_query(query, index),
            [{"metadata": rows[0], "metadata_id": 0}],
            bm25_index=bm25,
        )[0]["rerank_score"]
        assert actual == pytest.approx(expected)


@pytest.mark.parametrize("mutation", ["postings", "span", "name", "truncated", "root"])
def test_corrupt_artifact_rejected_at_load_with_clear_error(tmp_path, mutation):
    rows = [row(0, "Maple Studio", "editor")]
    prepared(rows, tmp_path)
    path = tmp_path / "names.json"
    data = json.loads(path.read_text())
    if mutation == "postings":
        data["postings"]["maplestudio"] = [[-1, 0], [99, 0]]
    elif mutation == "span":
        data["rows"][0]["spans"]["title"]["0"][0][2] = 10000
    elif mutation == "name":
        data["names"][0] = "differentname"
    elif mutation == "truncated":
        data.pop("matcher_specs")
    else:
        data = []
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="artifact"):
        NameIndex.load_precomputed(rows, path)


@pytest.mark.parametrize("ids", [[None], [""], ["same", "same"]])
def test_build_rejects_missing_or_duplicate_row_identity(tmp_path, ids):
    rows = [row(i, "Maple Studio", "editor") for i in range(len(ids))]
    for item, identity in zip(rows, ids):
        item["chunk_uuid"] = identity
    with pytest.raises(ValueError, match="chunk_uuid"):
        NameIndex.precompute(rows, tmp_path / "names.json")
    assert not (tmp_path / "names.json").exists()


def test_ascii_artifact_preserves_unicode_provenance(tmp_path):
    rows = [row(0, "Maple Studio", "editor 💻", keywords=["你好"])]
    index = prepared(rows, tmp_path)
    assert (tmp_path / "names.json").read_bytes().isascii()
    assert index.report() == NameIndex(rows).report()


def test_valid_checksum_cannot_authorize_out_of_range_posting(tmp_path):
    from arm_kb_search.prepared_names import _checksum

    rows = [row(0, "Maple Studio", "editor")]
    prepared(rows, tmp_path)
    path = tmp_path / "names.json"
    data = json.loads(path.read_text())
    data["postings"]["maplestudio"] = [[10, 0]]
    data["checksum"] = _checksum(data)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="artifact posting"):
        NameIndex.load_precomputed(rows, path)


def test_prepared_aliases_keep_unsupported_complete_label_blockers(tmp_path):
    rows = [
        dict(
            chunk_uuid=str(i),
            doc_type="ecosystem dashboard",
            heading_path=["Catalog", label],
            title=label,
            original_text=label,
            search_text=label,
        )
        for i, label in enumerate(
            ["Maple Studio Editor (MSE)", "Maple Studio Editor (Open Source)"]
        )
    ]
    path = tmp_path / "names.json"
    aliases = [dict(canonical="Maple Studio Editor", labels=["Maple Studio Editor (MSE)"],
                    aliases=["MSE"], provenance="test catalog label")]
    NameIndex.precompute(rows, path, aliases)
    index = NameIndex.load_precomputed(rows, path)
    assert index.candidates("mse") == [0]
    assert index.keys("Maple Studio Editor (Open Source)") == frozenset()
    assert index.keys("Maple Studio Editor (MSE)") == frozenset({"maplestudioeditor"})
