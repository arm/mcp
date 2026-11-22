"""Search response presentation contracts; no model or network required."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import lean_results as lean

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
    assert lean.strip_snippet_prefix(snippet) == expected


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
