# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
"""Behavioral contracts for corpus-evidenced whole technical names."""

import json

import pytest


def package(label, row_id=0, **fields):
    return {"chunk_uuid": str(row_id), "doc_type": "Ecosystem Dashboard",
            "heading_path": ["Linux", label, "Overview"],
            "url": f"https://example.com/{row_id}", **fields}


def lookup(metadata):
    # Import in the test call so an absent implementation produces a test failure.
    from arm_kb_search.names import NameIndex
    return NameIndex(metadata)


FAMILIES = [
    ("AWS CLI", "awscli", ["AWS CLI", "aws-cli", "aws_cli", "awscli", "AWS . CLI"]),
    ("Docker Compose", "dockercompose", ["Docker Compose", "docker-compose", "docker_compose", "dockercompose"]),
    ("Node.js", "nodejs", ["Node.js", "Node JS", "node-js", "node_js", "nodejs"]),
    ("Visual Studio Code", "visualstudiocode", ["Visual Studio Code", "visual-studio-code", "visual_studio_code", "visualstudiocode", "Visual_studio.Code"]),
]


@pytest.mark.parametrize("label,key,spellings", FAMILIES)
def test_explicit_label_boundaries_allow_spelling_cross_products(label, key, spellings):
    for source in spellings:
        # A joined spelling alone cannot create boundaries; an explicit label does.
        index = lookup([package(label), package(source, 1)])
        for spelling in spellings:
            assert index.keys(f"Install {spelling}.") == frozenset({key})
            assert index.candidates(spelling) == [0, 1]
            assert index.project(f"Install {spelling}.") == f"Install __name_{key}."


@pytest.mark.parametrize("text", [
    "aws--cli", "aws__cli", "aws..cli", "aws - _ cli", "aws\ncli",
    "aws\r\ncli", "aws cli_tools", "aws cli2", "aws cli-v2", "aws cli+",
    "aws cli#", ".aws cli", "myaws cli", "x_aws cli", "aws cli.foo",
    "aws cli.2", "aws cli._thing", "aws\vcli", "aws/cl i",
])
def test_names_do_not_cross_code_boundaries_or_unsupported_separators(text):
    assert lookup([package("AWS CLI")]).keys(text) == frozenset()


@pytest.mark.parametrize("text", ["(AWS CLI)", "aws\tcli", "aws \t-\t cli", "AWS.CLI.", "awscli,", "aws cli. Next"])
def test_horizontal_spacing_and_surrounding_sentence_punctuation_are_allowed(text):
    assert lookup([package("AWS CLI")]).keys(text) == frozenset({"awscli"})


def test_match_offsets_repetition_and_projection_use_original_text():
    index = lookup([package("AWS CLI")])
    text = "é AWS_CLI and aws.cli."
    assert [(m.key, m.start, m.end) for m in index.match(text)] == [("awscli", 2, 9), ("awscli", 14, 21)]
    assert index.keys(text) == frozenset({"awscli"})
    assert index.project(text) == "é __name_awscli and __name_awscli."
    assert index.atom("awscli") == "__name_awscli"


def test_unknown_names_and_uninvented_component_boundaries_stay_literal():
    index = lookup([package("Node.js"), package("JavaScript", 1), package("Java", 2)])
    assert index.project("unknown-tool Java Script No de JS") == "unknown-tool Java Script No de JS"
    assert index.keys("JavaScript") == frozenset()
    assert index.keys("Java Script") == frozenset()


def test_longest_name_consumes_nested_shorter_names_even_for_restricted_projection():
    index = lookup([package("Visual Studio"), package("Visual Studio Code", 1), package("Studio Code", 2)])
    assert index.keys("Visual Studio Code") == frozenset({"visualstudiocode"})
    assert index.project("Visual Studio Code", keys={"visualstudio"}) == "Visual Studio Code"
    assert index.project("Visual Studio Code and Visual Studio", keys={"visualstudio"}) == "Visual Studio Code and __name_visualstudio"


def test_conflicting_segmented_signatures_disable_the_whole_joined_key():
    index = lookup([package("AB C"), package("A BC", 1), package("ABC", 2)])
    assert index.keys("ABC AB C A BC") == frozenset()
    assert "abc" not in index.inventory
    excluded = index.report()["excluded"]
    assert len(excluded) == 3
    assert all(item["reason"] == "conflicting_component_signatures" for item in excluded)
    assert {item["source"]["label"] for item in excluded} == {"AB C", "A BC", "ABC"}


def test_joined_labels_only_corroborate_a_segmented_signature():
    index = lookup([package("awscli"), package("AWS-CLI", 1)])
    assert index.keys("AWS CLI") == frozenset({"awscli"})
    assert len(index.inventory) == 1
    assert lookup([package("awscli")]).keys("AWS CLI") == frozenset()


@pytest.mark.parametrize("label", ["C", "C++", "C#", ".NET", "Python 3", "Node.js2", "svadd_f32_m", "uint32_t", "int32_t", "My/Tool", "aws--cli"])
def test_protected_name_labels_do_not_invent_formatting_equivalence(label):
    index = lookup([package(label)])
    expected = frozenset()
    assert index.keys("C plus plus C sharp NET Python Node JS svadd f m uint t int t My Tool aws cli") == expected
    if label != "C":
        assert index.report()["excluded"]


@pytest.mark.parametrize("text", ["C++", "C#", "C_version", "C2", ".C", "std::C++"])
def test_single_letter_labels_cannot_consume_meaningful_symbols(text):
    assert lookup([package("C")]).keys(text) == frozenset()


@pytest.mark.parametrize("connector", ["for", "on", "with", "using", "and", "or", "from", "to", "in", "via", "through"])
def test_installation_prose_is_reported_instead_of_guessing_products(connector):
    title = f"Install AWS CLI {connector} Linux"
    index = lookup([{"doc_type": "Install Guides", "title": title, "chunk_uuid": "guide", "url": "https://example.com/guide"}])
    assert index.keys("AWS CLI") == frozenset()
    excluded = index.report()["excluded"]
    assert excluded[0]["reason"] == "prose_connector"
    assert excluded[0]["source"]["label"] == title
    assert excluded[0]["source"]["field"] == "title"
    # Explicit package labels do not use the title-prose heuristic.
    assert lookup([package(f"Tools {connector} Linux")]).keys(f"Tools-{connector}-Linux") == frozenset({f"tools{connector}linux"})


def test_installation_titles_and_package_heading_fallback_are_inventory_sources():
    index = lookup([
        {"doc_type": "Install Guide", "title": "Docker Compose", "chunk_uuid": "guide"},
        {"doc_type": "Ecosystem Dashboard", "heading": "Node.js", "chunk_uuid": "dashboard"},
        {"doc_type": "Tutorial", "title": "Unknown Tool", "url": "https://aws-cli.example.com"},
    ])
    assert index.keys("DockerCompose Node JS Unknown Tool AWS CLI") == frozenset({"dockercompose", "nodejs"})
    assert index.candidates("node-js") == [1]


@pytest.mark.parametrize("title", ["Access via API", "Access via Internet Browser", "Access through API"])
def test_generic_access_titles_do_not_turn_prose_into_product_names(title):
    index = lookup([{"doc_type": "Install Guides", "title": title, "chunk_uuid": "access"},
                    package("AWS CLI", 1)])
    query = f"Can I {title.lower()} on Arm?"
    assert index.project(query) == query
    assert index.candidates(query) == []
    assert index.keys("aws_cli") == {"awscli"}


def test_label_extraction_is_bounded_by_components_and_character_count():
    labels = ["A B C D E F G H", "A B C D E F G H I", "A" * 79 + " B"]
    index = lookup([package(label, i) for i, label in enumerate(labels)])
    assert index.keys("ABCDEFGH") == frozenset({"abcdefgh"})
    assert len(index.report()["excluded"]) == 2
    json.dumps(index.report())


def test_candidates_use_field_prominence_then_row_id_and_ignore_url_names():
    index = lookup([
        package("AWS CLI", 0),
        {"original_text": "AWS CLI"},
        {"keywords": ["aws-cli"]},
        {"product": "awscli"},
        {"heading": "AWS_CLI"},
        {"title": "AWS CLI"},
        {"heading_path": ["Overview", "AWS CLI"]},
        {"url": "https://example.com/aws-cli"},
    ])
    assert index.candidates("awscli") == [5, 0, 4, 6, 2, 3, 1]


def test_postings_prefer_raw_body_and_never_cross_fields_or_list_elements():
    index = lookup([
        package("AWS CLI"),
        {"title": "AWS", "heading": "CLI"},
        {"heading_path": ["AWS", "CLI"]},
        {"keywords": ["AWS", "CLI"]},
        {"original_text": "unrelated", "search_text": "AWS CLI"},
        {"original_text": "Use aws-cli", "search_text": "unrelated"},
        {"search_text": "Use aws_cli"},
        {"content": "Use aws_cli"},
    ])
    assert index.candidates("AWS CLI") == [0, 5, 7]


def test_intrinsic_records_neither_seed_names_nor_receive_name_postings():
    index = lookup([package("AWS CLI"), {"doc_type": "Intrinsic", "heading": "AWS CLI", "original_text": "AWS CLI"}])
    assert index.candidates("aws-cli") == [0]
    assert not lookup([{"doc_type": "Intrinsic", "heading": "AWS CLI", "title": "AWS CLI"}]).inventory


def test_filtering_happens_before_the_total_candidate_limit_and_deduplicates_names():
    index = lookup([package("AWS CLI"), package("Node.js", 1)] + [{"title": "AWS CLI Node.js"} for _ in range(120)])
    assert index.candidates("awscli nodejs", eligible_ids={115, 116, 117}, limit=2) == [115, 116]
    assert index.candidates("awscli nodejs", limit=3) == [2, 3, 4]
    assert len(index.candidates("awscli nodejs")) == 100
    assert index.candidates("awscli", eligible_ids=set()) == []
    assert index.candidates("awscli", limit=0) == []
    assert index.candidates("unknown") == []


def test_joined_only_labels_remain_inventory_evidence_without_scoring_singletons():
    index = lookup([package("JavaScript"), package("Java", 1)])
    assert index.keys("JavaScript Java Script Java") == frozenset()
    assert index.candidates("JavaScript Java") == []
    assert index.project("JavaScript Java Script Java") == "JavaScript Java Script Java"
    assert set(index.inventory) == {"javascript", "java"}
    assert index.report()["counts"]["joined_only_names"] == 2
    assert {item["key"] for item in index.report()["joined_only"]} == {"javascript", "java"}


def test_javascript_only_receives_equivalence_when_an_explicit_split_is_evidenced():
    index = lookup([package("JavaScript"), package("Java", 1), package("Java Script", 2)])
    assert index.keys("JavaScript Java Script Java") == frozenset({"javascript"})
    assert index.project("JavaScript Java Script Java") == "__name_javascript __name_javascript Java"


def test_shared_joined_prefixes_validate_gaps_against_the_selected_terminal():
    index = lookup([package("AB CD"), package("A BC E", 1), package("AB CDE", 2)])
    assert index.keys("A BC D") == frozenset()
    assert index.keys("AB CD") == frozenset({"abcd"})
    assert index.keys("A BC E") == frozenset({"abce"})
    assert index.keys("AB CDE") == frozenset({"abcde"})
    assert index.keys("AB C D E") == frozenset()
    assert index.keys("AB CD E") == frozenset({"abcd"})


@pytest.mark.parametrize("text", ["aws_cli()", "ns::aws_cli", "aws_cli[index]", "aws_cli::member", "aws_cli:member"])
def test_api_calls_namespace_members_and_indexed_identifiers_remain_literal(text):
    index = lookup([package("AWS CLI")])
    assert index.keys(text) == frozenset()
    assert index.project(text) == text


@pytest.mark.parametrize("text", ["(AWS CLI)", "[AWS CLI]", "Use AWS CLI (on Linux)", "Tool: AWS CLI"])
def test_wrappers_and_whitespace_delimited_prose_still_allow_whole_names(text):
    assert lookup([package("AWS CLI")]).keys(text) == frozenset({"awscli"})


def test_flattened_fallback_cannot_invent_names_without_raw_body():
    index = lookup([package("AWS CLI"),
                    {"title": "AWS", "heading": "CLI", "search_text": "AWS CLI"},
                    {"original_text": "", "search_text": "AWS CLI"}])
    assert index.candidates("awscli") == [0]
