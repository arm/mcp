"""Offline Learning Path presentation contracts; no model or network required."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import learning_paths as lp

ROOT = "https://learn.arm.com/learning-paths/servers-and-cloud-computing/demo/"


def row(page="", heading=("Overview",), text="Body", version="0", **extra):
    return {"url": ROOT + page + "#" + "-".join(heading), "title": "Demo" if not page else page,
            "heading_path": list(heading), "original_text": text, "version": version,
            "doc_type": "Learning Paths", **extra}


class Resources:
    def __init__(self, rows):
        self.metadata = rows

    def snippet_for(self, item):
        return item["original_text"]


def index(rows):
    return lp.LearningPathIndex(Resources(rows))


@pytest.mark.parametrize(("url", "expected"), [
    (ROOT + "install/?utm_source=arm-mcp#build", ROOT),
    (ROOT.rstrip("/") + "?utm_source=arm-mcp#intro", ROOT),
    (ROOT + "?redirect=/evil/", ROOT),
    ("https://learn.arm.com/learning-paths/category/", None),
    ("https://learn.arm.com/learning-paths/category?x=/slug/", None),
    ("https://example.org/?next=" + ROOT, None),
    ("https://learn.arm.com.evil/learning-paths/cat/demo/", None),
    ("http://learn.arm.com/learning-paths/cat/demo/", None),
])
def test_root_lookup_is_anchored_and_strips_tracking_only_for_identity(url, expected):
    assert lp.learning_path_root(url, normalize_missing_slash=True) == expected


def test_prefix_removal_only_at_top_and_lean_copy_preserves_every_other_field():
    source = {"url": ROOT + "?utm_source=arm-mcp#intro", "snippet":
              "\nDocument Title: Demo\nHeading Path: Intro\n\nBody\nDocument Title: keep\nHeading Path: keep\n",
              "title": "Demo", "heading": ["Intro"], "doc_type": ["Learning Paths"],
              "product": ["Neoverse"], "platform": ["Linux"], "score": .9,
              "context": {"scope": "page", "chunk_index": 0}, "page_url": ROOT + "?x=1",
              "parent_page_url": ROOT, "future_field": [1], "distance": .1,
              "disclaimer": "legal", "url_tracking_instruction": "tracking"}
    before = copy.deepcopy(source)
    result = lp.lean_result(source)
    assert result == {"url": ROOT + "?utm_source=arm-mcp#intro", "snippet":
                      "Body\nDocument Title: keep\nHeading Path: keep", "title": "Demo",
                      "heading": ["Intro"], "doc_type": ["Learning Paths"],
                      "product": ["Neoverse"], "platform": ["Linux"], "score": .9,
                      "context": {"scope": "page", "chunk_index": 0}, "page_url": ROOT + "?x=1",
                      "parent_page_url": ROOT, "future_field": [1], "learning_path": ROOT}
    assert list(result) == [k for k in source if k not in {"distance", "disclaimer", "url_tracking_instruction"}] + ["learning_path"]
    assert source == before
    assert "learning_path" not in lp.lean_result({"url": "https://developer.arm.com/", "snippet": "Text"})


def test_full_pages_version_order_heading_hierarchy_prefixes_and_no_mutation():
    rows = [row("second/", text="Second body", version="2"),
            row("first/", ("Z", "Child"), "Child body", "1"),
            row(text="Document Title: Demo\nHeading Path: Overview\n\nRoot body"),
            row("first/", ("Z",), "Parent body", "1")]
    before = copy.deepcopy(rows)
    result = index(rows).get(ROOT)
    assert set(result) == {"learning_path", "mode", "page", "chars", "text", "note"}
    assert result["learning_path"] == ROOT and result["mode"] == "full" and result["page"] is None
    assert result["text"] == (f"# Demo\n{ROOT}\n\n## Page 1: Demo\n{ROOT}\n\n### Overview\nRoot body\n\n"
                              f"## Page 2: first/\n{ROOT}first/\n\n### Z\nParent body\n\n### Z > Child\nChild body\n\n"
                              f"## Page 3: second/\n{ROOT}second/\n\n### Overview\nSecond body")
    assert result["chars"] == len(result["text"])
    assert "Cite page URLs exactly" in result["note"]
    assert rows == before


@pytest.mark.parametrize("heading", [("About this Learning Path",), ("What you've accomplished",),
    ("What you’ve accomplished",), ("Share",), ("Give Feedback",), ("Continue Learning",),
    ("Frequently Asked Questions",), ("Parent", "Share")])
def test_navigation_headings_are_excluded(heading):
    result = index([row(text="keep"), row(heading=heading, text="DROP")]).get(ROOT)
    assert "keep" in result["text"] and "DROP" not in result["text"]


@pytest.mark.parametrize("fragment", ["learning-path-step-active", "learning-path-title", "ads-masthead-title"])
def test_navigation_fragments_and_next_steps_are_excluded(fragment):
    result = index([row(text="keep"), row(text="DROP", url=ROOT + "#prefix-" + fragment),
                    row("_next-steps/", text="DROP")]).get(ROOT)
    assert "keep" in result["text"] and "DROP" not in result["text"]


def test_stored_manifest_and_chunk_indices_override_version_and_heading_order():
    pages = [ROOT, ROOT + "z/", ROOT + "a/"]
    rows = [row("a/", text="Last", version="1"), row("z/", ("A",), "Z second", "9"),
            row(text="Root"), row("z/", ("Z",), "Z first", "9")]
    for i, item in enumerate(rows):
        item["document_context"] = {"learning_path_pages": pages, "chunk_index": [0, 1, 0, 0][i]}
    result = index(rows).get(ROOT)["text"]
    assert result.index("Root") < result.index("Z first") < result.index("Z second") < result.index("Last")


def test_top_level_chunk_and_page_indices_are_used():
    rows = [row("a/", ("A",), "Second chunk", "1", chunk_index=1, page_index=2),
            row("z/", text="First page", version="9", page_index=1),
            row("a/", ("Z",), "First chunk", "1", chunk_index=0, page_index=2)]
    result = index(rows).get(ROOT)["text"]
    assert result.index("First page") < result.index("First chunk") < result.index("Second chunk")


def test_commands_contains_only_fences_and_unfenced_shell_lines_once():
    source = "Prose\n```bash\nsudo apt update\nexport X=1\n$ run\necho ok\n```\nMore prose\n sudo outside\nexport OUT=1\n$ outside\nno command"
    result = index([row(text=source), row("empty/", text="Prose only", version="1")]).get(ROOT, mode="commands")
    assert result["text"] == "```bash\nsudo apt update\nexport X=1\n$ run\necho ok\n```\n sudo outside\nexport OUT=1\n$ outside"
    assert result["text"].count("sudo apt update") == 1
    assert result["mode"] == "commands" and ROOT in result["note"]


def test_outline_counts_original_text_and_oversized_fallback_is_actionable():
    rows = [row(text="Document Title: Demo\n\n12345"), row("step/", text="x" * 80001, version="1")]
    catalog = index(rows)
    outline = catalog.get(ROOT, mode="outline")
    assert outline["text"] == f"- Page 1: Demo — {ROOT} (27 chars)\n- Page 2: step/ — {ROOT}step/ (80001 chars)"
    fallback = catalog.get(ROOT)
    assert fallback["mode"] == "outline" and fallback["text"] == outline["text"]
    assert "80000" in fallback["note"] and "page=" in fallback["note"]


def test_page_selection_accepts_tracking_fragments_and_missing_trailing_slash():
    citation = ROOT + "step/?utm_source=arm-mcp&x=1#intro"
    catalog = index([row(text="Root"), row("step/", text="Step only", version="1", url=citation)])
    for kwargs in ({"url": citation}, {"url": ROOT, "page": ROOT + "step#part"},
                   {"url": ROOT + "step/?other=1", "page": citation}):
        result = catalog.get(**kwargs)
        assert "Step only" in result["text"] and "Root" not in result["text"]
        assert ROOT + "step/?utm_source=arm-mcp&x=1" in result["text"]
        assert result["page"] == kwargs.get("page", kwargs["url"])


@pytest.mark.parametrize("kwargs", [{"url": "https://example.org/"}, {"url": ROOT + "missing/"},
    {"url": ROOT, "page": ROOT + "missing"}, {"url": ROOT, "mode": "invalid"},
    {"url": ROOT, "page": "https://learn.arm.com/learning-paths/cat/other/"}])
def test_invalid_requests_return_clear_errors(kwargs):
    result = index([row()]).get(**kwargs)
    assert set(result) == {"error", "hint"}
    assert result["error"] and result["hint"]


def test_array_doc_types_and_split_embedding_chunks_are_reassembled_once():
    from arm_kb_search import SearchResources

    source = "Document Title: Demo\n\nfirst second"
    pieces = []
    start = 0
    for part, text in enumerate([source[:20], source[20:]], 1):
        pieces.append(row(text=text, doc_type=["Learning Paths", "guide"], parent_uuid="page",
                          parent_chunk_uuid="chunk", source_part=part, source_parts=2,
                          source_start=start, source_end=start + len(text),
                          document_context={"chunk_index": 0}))
        start += len(text)
    resources = SearchResources([pieces[1], pieces[0], pieces[0]], object(), None, None)
    result = lp.LearningPathIndex(resources).get(ROOT)
    assert result["text"].count("first second") == 1
    assert result["text"].count("### Overview") == 1
    assert "(34 chars)" in lp.LearningPathIndex(resources).get(ROOT, mode="outline")["text"]


def test_lean_search_root_requires_slash_but_lookup_accepts_bare_root():
    bare = ROOT.rstrip("/") + "?utm_source=arm-mcp#intro"
    assert "learning_path" not in lp.lean_result({"url": bare, "snippet": "Body"})
    assert index([row()]).get(bare)["learning_path"] == ROOT


def test_same_url_with_distinct_chunk_positions_preserves_both_sections():
    rows = [row(text="Second", chunk_index=1), row(text="First", chunk_index=0)]
    text = index(rows).get(ROOT)["text"]
    assert text.index("First") < text.index("Second")
    assert text.count("### Overview") == 2
