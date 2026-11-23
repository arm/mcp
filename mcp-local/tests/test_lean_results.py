"""Search response presentation contracts; no model or network required."""

import copy

import pytest

from arm_kb_search import response as lean

ROOT = "https://learn.arm.com/learning-paths/servers-and-cloud-computing/demo/"


def test_prefix_removal_only_at_top_and_lean_copy_preserves_every_other_field():
    source = {"url": ROOT + "?utm_source=arm-mcp#intro", "snippet":
              "\nDocument Title: Demo\nHeading Path: Intro\n\nBody\nDocument Title: keep\nHeading Path: keep\n",
              "title": "Demo", "heading": ["Intro"], "doc_type": ["Learning Paths"],
              "product": ["Neoverse"], "platform": ["Linux"], "score": .9,
              "context": {"scope": "page", "chunk_index": 0}, "page_url": ROOT + "?x=1",
              "parent_page_url": ROOT, "future_field": [1], "distance": .1,
              "disclaimer": "legal", "url_tracking_instruction": "tracking"}
    before = copy.deepcopy(source)
    result = lean.lean_result(source)
    assert result == {"url": ROOT + "?utm_source=arm-mcp#intro", "snippet":
                      "Body\nDocument Title: keep\nHeading Path: keep", "title": "Demo",
                      "heading": ["Intro"], "doc_type": ["Learning Paths"],
                      "product": ["Neoverse"], "platform": ["Linux"], "score": .9,
                      "context": {"scope": "page", "chunk_index": 0}, "page_url": ROOT + "?x=1",
                      "parent_page_url": ROOT, "future_field": [1]}
    assert list(result) == [k for k in source if k not in {"distance", "disclaimer", "url_tracking_instruction"}]
    assert source == before
    assert "learning_path" not in lean.lean_result({"url": "https://developer.arm.com/", "snippet": "Text"})



@pytest.mark.parametrize(("snippet", "expected"), [
    ("", ""),
    ("\n  \nDocument Title: Demo\nHeading Path: Start\n", ""),
    ("Body\nDocument Title: keep\nHeading Path: keep", "Body\nDocument Title: keep\nHeading Path: keep"),
])
def test_prefix_stripping_boundaries(snippet, expected):
    assert lean.lean_result({"snippet": snippet})["snippet"] == expected


def test_response_notice_once_on_first_arm_result_without_mutation():
    from arm_kb_search.response import ARM_CONTENT_DISCLAIMER

    source = [
        {"url": "https://github.com/arm/example", "snippet": "External"},
        {"url": ROOT, "snippet": "Arm one", "disclaimer": ARM_CONTENT_DISCLAIMER},
        {"url": ROOT + "step/", "snippet": "Arm two", "disclaimer": ARM_CONTENT_DISCLAIMER},
    ]
    before = copy.deepcopy(source)
    result = lean.lean_results(source)
    assert [r["url"] for r in result] == [r["url"] for r in source]
    assert "disclaimer" not in result[0] and "disclaimer" not in result[2]
    assert result[1]["disclaimer"] == (
        "For all results in this response sourced from arm.com or its subdomains: "
        + ARM_CONTENT_DISCLAIMER
    )
    assert source == before


@pytest.mark.parametrize("source", [[], [{"url": ROOT, "snippet": "No notice requested"}],
    [{"url": "https://github.com/arm/example", "snippet": "External"}],
    [{"url": "https://arm.com.example.org/", "snippet": "External", "disclaimer": "not Arm"}]])
def test_no_notice_for_empty_external_or_disclaimer_disabled_results(source):
    assert all("disclaimer" not in r for r in lean.lean_results(source))


@pytest.mark.parametrize("heading", ["Large-System Extensions (LSE)", ["Large-System Extensions (LSE)"], ""])
def test_full_heading_context_survives_prefix_removal(heading):
    source = {
        "url": "https://github.com/aws/aws-graviton-getting-started/blob/main/c-c++.md",
        "title": "C/C++ on Graviton",
        "heading": heading,
        "snippet": (
            "Document Title: C/C++ on Graviton\n"
            "Heading Path: Enabling Arm Architecture Specific Features > Large-System Extensions (LSE)\n\n"
            "Use objdump to inspect the compiled instructions."
        ),
    }
    before = copy.deepcopy(source)
    result = lean.lean_result(source)
    assert result["heading_path"] == (
        "Enabling Arm Architecture Specific Features > Large-System Extensions (LSE)"
    )
    assert result["heading"] == heading
    assert result["title"] == "C/C++ on Graviton"
    assert result["snippet"] == "Use objdump to inspect the compiled instructions."
    assert source == before


@pytest.mark.parametrize("heading", ["Intro", ["Intro"]])
def test_flat_heading_is_not_duplicated_as_a_path(heading):
    result = lean.lean_result({"heading": heading, "snippet": "Heading Path: Intro\n\nBody"})
    assert "heading_path" not in result
    assert result["heading"] == heading
    assert result["snippet"] == "Body"


def test_existing_structured_heading_path_is_preserved():
    source = {"heading": "Leaf", "heading_path": ["Parent", "Leaf"],
              "snippet": "Heading Path: Parent > Leaf\n\nBody"}
    before = copy.deepcopy(source)
    result = lean.lean_result(source)
    assert result["heading_path"] == ["Parent", "Leaf"]
    assert result["snippet"] == "Body"
    assert source == before


def test_body_heading_label_does_not_become_result_metadata():
    result = lean.lean_result({"heading": "Intro", "snippet": "Body\nHeading Path: example text"})
    assert "heading_path" not in result
    assert result["snippet"] == "Body\nHeading Path: example text"
