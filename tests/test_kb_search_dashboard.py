"""Search response formatting, dashboard ranking, and resource identity."""

import importlib
from copy import deepcopy

import pytest

from arm_kb_search import resources
from arm_kb_search.response import (
    ARM_CONTENT_DISCLAIMER,
    UTM_SOURCE_PRESERVATION_NOTE,
    lean_result,
    lean_results,
)
from arm_kb_search.search import build_bm25_index, deduplicate_urls

search_module = importlib.import_module("arm_kb_search.search")
LEAN_RESULT_URL = "https://learn.arm.com/learning-paths/servers-and-cloud-computing/demo/"


def result(
    url,
    resolved_url,
    doc_type="Ecosystem Dashboard",
    content_type="markdown",
    edition="",
):
    return {
        "metadata": {
            "url": url,
            "resolved_url": resolved_url,
            "doc_type": doc_type,
            "content_type": content_type,
            "edition": edition,
        }
    }


@pytest.mark.parametrize("curated", [False, True])
def test_dashboard_editions_survive_but_multiple_chunks_per_source_do_not(curated):
    url = "https://developer.arm.com/ecosystem-dashboard/linux?package=calico"
    commercial = result(
        url,
        "https://raw.githubusercontent.com/repo/commit/content/linux/commercial_packages/calico.md",
        edition="commercial",
    )
    opensource = result(
        url,
        "https://raw.githubusercontent.com/repo/commit/content/linux/opensource_packages/calico.md",
        edition="open-source",
    )
    windows = result(
        url.replace("linux", "windows"),
        "https://raw.githubusercontent.com/repo/commit/content/windows/all_packages/calico.md",
    )
    if curated:
        for item in (commercial, opensource, windows):
            item["metadata"]["filter_metadata"] = {
                "doc_type": ["compatibility"], "platform": ["linux", "windows"],
            }
    assert deduplicate_urls([commercial, opensource, commercial, windows]) == [
        commercial,
        opensource,
        windows,
    ]


@pytest.mark.parametrize(
    "platform,package,edition,filenames",
    [
        (
            "linux",
            "kubermatic-kubernetes-platform",
            "commercial",
            ("KKP.md", "kubermatic-kubernetes-platform.md"),
        ),
        ("windows", "github-cli", "", ("gh.md", "github_cli.md")),
    ],
)
def test_duplicate_files_in_same_edition_keep_highest_ranked_hit(
    platform, package, edition, filenames
):
    url = f"https://developer.arm.com/ecosystem-dashboard/{platform}?package={package}"
    first, second = [
        result(
            url,
            f"https://raw.githubusercontent.com/repo/commit/{name}",
            edition=edition,
        )
        for name in filenames
    ]
    assert deduplicate_urls([first, second]) == [first]
    assert deduplicate_urls([second, first]) == [second]
    assert deduplicate_urls([first, second], max_chunks_per_url=2) == [first, second]


@pytest.mark.parametrize("sources", [
    ("first", "second"),
    ("https://raw.githubusercontent.com/repo/main/a.md", "https://raw.githubusercontent.com/repo/main/b.md"),
    ("https://example.com/source?download=1", "https://example.com/source?download=2"),
    ("https://example.com/source#part1", "https://example.com/source#part2"),
])
def test_other_documents_and_legacy_dashboard_keep_url_deduplication(sources):
    for doc_type, content_type in [
        ("Documentation", "markdown"),
        ("Learning Paths", "markdown"),
        ("Install Guides", "html"),
        ("Ecosystem Dashboard", "html"),
    ]:
        first = result("https://example.com", sources[0], doc_type, content_type)
        second = result("https://example.com", sources[1], doc_type, content_type)
        assert deduplicate_urls([first, second]) == [first]
        assert deduplicate_urls([first, second], max_chunks_per_url=2) == [
            first,
            second,
        ]


def test_distinct_public_pages_from_one_acquisition_source_survive():
    source = "https://raw.githubusercontent.com/repo/main/guide.md"
    first = result("https://learn.arm.com/learning-paths/example/install/", source, "Learning Paths")
    second = result("https://learn.arm.com/learning-paths/example/configure/", source, "Learning Paths")
    assert deduplicate_urls([first, second]) == [first, second]


@pytest.mark.parametrize("public_url", [None, ""])
def test_missing_public_url_falls_back_to_resolved_url(public_url):
    source = "https://example.com/guide/#install"
    fallback = result(public_url, source, "Documentation")
    public = result(source, None, "Documentation")
    assert deduplicate_urls([fallback, public]) == [fallback]


@pytest.mark.parametrize("url_fields,expected_page", [
    ({}, "resolved"),
    ({"url": None}, "resolved"),
    ({"url": ""}, "resolved"),
    ({"url": "https://learn.arm.com/public?version=2#install"}, "public"),
])
def test_search_response_returns_usable_url_with_tracking_and_disclaimer(url_fields, expected_page):
    metadata = [
        {
            "chunk_uuid": "guide", "title": "Utility", "search_text": "utility",
            "original_text": "Run utility --help.", "doc_type": "Install Guides",
            "resolved_url": "https://learn.arm.com/resolved?version=2#install",
            **url_fields,
        },
        {"chunk_uuid": "database", "url": "https://example.com/database", "search_text": "database"},
        {"chunk_uuid": "network", "url": "https://example.com/network", "search_text": "network"},
    ]
    state = resources.SearchResources(
        metadata, None, None, build_bm25_index(metadata),
        include_disclaimers=True, utm_source="test-client",
    )

    hits = resources.search("utility", state, k=1)

    assert len(hits) == 1
    assert hits[0]["url"] == f"https://learn.arm.com/{expected_page}?version=2&utm_source=test-client#install"
    assert hits[0]["snippet"] == "Run utility --help."
    assert hits[0]["disclaimer"] == ARM_CONTENT_DISCLAIMER
    assert hits[0]["url_tracking_instruction"] == UTM_SOURCE_PRESERVATION_NOTE


def test_search_response_retains_dashboard_scope_and_defaults_for_old_metadata(
    monkeypatch,
):
    dashboard = result("https://example.com/dashboard", "source")
    dashboard["metadata"].update(platform="linux", edition="commercial")
    legacy = result("https://example.com/guide", "guide", doc_type="Documentation")
    monkeypatch.setattr(
        resources, "hybrid_search", lambda *args, **kwargs: [dashboard, legacy]
    )
    state = resources.SearchResources([], None, None, None, include_disclaimers=False)
    hits = resources.search("query", state)
    assert all("edition" not in hit for hit in hits)
    assert hits[0]["platform"] == ["linux"]
    assert hits[1]["platform"] == []
    assert hits[1]["doc_type"] == ["Documentation"] and hits[1]["product"] == []

    dashboard["metadata"]["filter_metadata"] = {
        "doc_type": ["compatibility"], "product": ["arm"],
        "platform": ["linux", "windows"],
    }
    legacy["metadata"].update(product=None, filter_metadata={"doc_type": ["guide"]})
    snapshot = deepcopy([dashboard, legacy])
    hits = resources.search("query", state)
    assert {key: hits[0][key] for key in ("doc_type", "product", "platform")} == {
        "doc_type": ["compatibility"], "product": ["arm"],
        "platform": ["linux", "windows"],
    }
    assert all("edition" not in hit for hit in hits)
    assert hits[1]["doc_type"] == ["guide"] and hits[1]["product"] == []
    assert hits[1]["platform"] == []
    for name in ("doc_type", "product", "platform"):
        hits[0][name].append("caller mutation")
    assert [dashboard, legacy] == snapshot
    assert resources.search("query", state)[0]["platform"] == ["linux", "windows"]


def test_prefix_removal_only_at_top_and_lean_copy_preserves_every_other_field():
    source = {"url": LEAN_RESULT_URL + "?utm_source=arm-mcp#intro", "snippet":
              "\nDocument Title: Demo\nHeading Path: Intro\n\nBody\nDocument Title: keep\nHeading Path: keep\n",
              "title": "Demo", "heading": ["Intro"], "doc_type": ["Learning Paths"],
              "product": ["Neoverse"], "platform": ["Linux"], "score": .9,
              "context": {"scope": "page", "chunk_index": 0}, "page_url": LEAN_RESULT_URL + "?x=1",
              "parent_page_url": LEAN_RESULT_URL, "future_field": [1], "distance": .1,
              "disclaimer": "legal", "url_tracking_instruction": "tracking"}
    before = deepcopy(source)
    result = lean_result(source)
    assert result == {"url": LEAN_RESULT_URL + "?utm_source=arm-mcp#intro", "snippet":
                      "Body\nDocument Title: keep\nHeading Path: keep", "title": "Demo",
                      "heading": ["Intro"], "doc_type": ["Learning Paths"],
                      "product": ["Neoverse"], "platform": ["Linux"], "score": .9,
                      "context": {"scope": "page", "chunk_index": 0}, "page_url": LEAN_RESULT_URL + "?x=1",
                      "parent_page_url": LEAN_RESULT_URL, "future_field": [1]}
    assert list(result) == [k for k in source if k not in {"distance", "disclaimer", "url_tracking_instruction"}]
    assert source == before
    assert "learning_path" not in lean_result({"url": "https://developer.arm.com/", "snippet": "Text"})


@pytest.mark.parametrize(("snippet", "expected"), [
    ("", ""),
    ("\n  \nDocument Title: Demo\nHeading Path: Start\n\n", ""),
    ("Body\nDocument Title: keep\nHeading Path: keep", "Body\nDocument Title: keep\nHeading Path: keep"),
])
def test_prefix_stripping_boundaries(snippet, expected):
    assert lean_result({"title": "Demo", "heading": "Start", "snippet": snippet})["snippet"] == expected


def test_response_notice_once_on_first_arm_result_without_mutation():
    source = [
        {"url": "https://github.com/arm/example", "snippet": "External"},
        {"url": LEAN_RESULT_URL, "snippet": "Arm one", "disclaimer": ARM_CONTENT_DISCLAIMER},
        {"url": LEAN_RESULT_URL + "step/", "snippet": "Arm two", "disclaimer": ARM_CONTENT_DISCLAIMER},
    ]
    before = deepcopy(source)
    result = lean_results(source)
    assert [r["url"] for r in result] == [r["url"] for r in source]
    assert "disclaimer" not in result[0] and "disclaimer" not in result[2]
    assert result[1]["disclaimer"] == (
        "For all results in this response sourced from arm.com or its subdomains: "
        + ARM_CONTENT_DISCLAIMER
    )
    assert source == before


@pytest.mark.parametrize("source", [[], [{"url": LEAN_RESULT_URL, "snippet": "No notice requested"}],
    [{"url": "https://github.com/arm/example", "snippet": "External"}],
    [{"url": "https://arm.com.example.org/", "snippet": "External", "disclaimer": "not Arm"}]])
def test_no_notice_for_empty_external_or_disclaimer_disabled_results(source):
    assert all("disclaimer" not in r for r in lean_results(source))


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
    before = deepcopy(source)
    result = lean_result(source)
    assert result["heading_path"] == (
        "Enabling Arm Architecture Specific Features > Large-System Extensions (LSE)"
    )
    assert result["heading"] == heading
    assert result["title"] == "C/C++ on Graviton"
    assert result["snippet"] == "Use objdump to inspect the compiled instructions."
    assert source == before


@pytest.mark.parametrize("heading", ["Intro", ["Intro"]])
def test_flat_heading_is_not_duplicated_as_a_path(heading):
    result = lean_result({"title": "Demo", "heading": heading,
                          "snippet": "Document Title: Demo\nHeading Path: Intro\n\nBody"})
    assert "heading_path" not in result
    assert result["heading"] == heading
    assert result["snippet"] == "Body"


def test_existing_structured_heading_path_is_preserved():
    source = {"title": "Demo", "heading": "Leaf", "heading_path": ["Parent", "Leaf"],
              "snippet": "Document Title: Demo\nHeading Path: Parent > Leaf\n\nBody"}
    before = deepcopy(source)
    result = lean_result(source)
    assert result["heading_path"] == ["Parent", "Leaf"]
    assert result["snippet"] == "Body"
    assert source == before


def test_body_heading_label_does_not_become_result_metadata():
    result = lean_result({"heading": "Intro", "snippet": "Body\nHeading Path: example text"})
    assert "heading_path" not in result
    assert result["snippet"] == "Body\nHeading Path: example text"


@pytest.mark.parametrize("body", [
    "Document Title: required user input\nKeep this field.",
    "Heading Path: optional user input\nKeep this field.",
    "Document Title: required user input\nHeading Path: optional user input\nKeep both fields.",
])
def test_generated_header_does_not_consume_body_labels(body):
    result = lean_result({
        "title": "Example",
        "heading": "Input fields",
        "snippet": "Document Title: Example\nHeading Path: Parent > Input fields\n\n" + body,
    })
    assert result["snippet"] == body
    assert result["heading_path"] == "Parent > Input fields"


def pieces(parent_uuid, parent_chunk_uuid, texts):
    rows = []
    start = 0
    for number, text in enumerate(texts, 1):
        rows.append({
            "uuid": f"{parent_uuid}:{parent_chunk_uuid}:{number}",
            "chunk_uuid": f"{parent_chunk_uuid}:{parent_uuid}:{number}",
            "parent_uuid": parent_uuid, "parent_chunk_uuid": parent_chunk_uuid,
            "source_start": start, "source_end": start + len(text),
            "source_part": number, "source_parts": len(texts),
            "original_text": text, "search_text": "Install guide " + text,
            "url": "https://example.com/guide?version=2#install",
            "title": "Install guide", "heading": "Install", "doc_type": "Install Guides",
        })
        start += len(text)
    return rows


@pytest.mark.parametrize("body", [
    "Heading Path: optional user input\nKeep this field.",
    "Document Title: required user input\nKeep this field.",
    "Document Title: Install guide\nHeading Path: optional user input\n\nKeep this field.",
    "Document Title: Other document\nHeading Path: Install\n\nKeep this field.",
    "Document Title: Install guide\nHeading Path: Install\nKeep this field.",
])
def test_lean_incomplete_embedding_slice_preserves_unverified_header_labels(body, monkeypatch):
    row = pieces("parent", "chunk", ["Earlier text. ", body])[1]
    state = resources.SearchResources([row], None, None, None, include_disclaimers=False)
    monkeypatch.setattr(resources, "hybrid_search", lambda *args, **kwargs: [{"metadata": row}])
    hit = resources.search("guide", state)[0]
    assert hit["snippet"] == body
    result = lean_result(hit)
    assert result["snippet"] == body
    assert "heading_path" not in result


@pytest.mark.parametrize("title", [None, ""])
def test_lean_preserves_header_like_body_without_title_metadata(title):
    body = "Document Title: Example\nHeading Path: Intro\n\nKeep this text."
    result = lean_result({"title": title, "heading": "Intro", "snippet": body})
    assert result["snippet"] == body
    assert "heading_path" not in result


@pytest.mark.parametrize("selected_part", [0, 1, 2])
def test_search_returns_exact_parent_without_changing_retrieval(monkeypatch, selected_part):
    texts = ["Prerequisites: café\r\n  ", "\tcommand --flag\n", "\nVerify the result.  "]
    family = pieces("parent", "chunk", texts)
    # Parent identity, rather than URL or either ID alone, determines context.
    others = pieces("parent", "other", ["Unrelated ", "section."])
    others += pieces("other", "chunk", ["Another ", "parent."])
    plain = {"url": "https://example.com/plain", "original_text": "Unsplit text"}
    legacy = {"url": "https://example.com/legacy", "content": "Legacy content"}
    metadata = list(reversed(family + others + [plain, legacy]))
    snapshot = deepcopy(metadata)
    bm25 = resources.build_bm25_index(metadata)
    state = resources.SearchResources(metadata, None, None, bm25, include_disclaimers=False)
    selected = family[selected_part]

    def ranked(query, index, rows, model, lexical_index, **kwargs):
        assert rows is metadata and rows == snapshot
        assert lexical_index is bm25
        return [
            {"metadata": selected, "distance": 0.25, "rerank_score": 0.8},
            {"metadata": plain, "rerank_score": 0.4},
            {"metadata": legacy, "rerank_score": 0.2},
        ]

    monkeypatch.setattr(resources, "hybrid_search", ranked)
    hits = resources.search("install", state)

    assert [hit["snippet"] for hit in hits] == ["".join(texts), "Unsplit text", "Legacy content"]
    assert [hit["score"] for hit in hits] == [0.8, 0.4, 0.2]
    assert hits[0]["distance"] == 0.25
    for key in ("url", "title", "heading"):
        assert hits[0][key] == selected[key]
    assert hits[0]["doc_type"] == [selected["doc_type"]]
    assert metadata == snapshot  # Neither dense nor BM25 inputs are expanded.


@pytest.mark.parametrize("field,offset", [
    (None, 0), ("source_start", 1), ("source_start", -1), ("source_end", 1),
], ids=["missing", "gap", "overlap", "length"])
def test_incomplete_or_invalid_parent_falls_back_to_selected_piece(field, offset):
    family = pieces("parent", "chunk", ["Before ", "command", " after"])
    selected = family[1]
    if field is None:
        family.pop()
    else:
        selected[field] += offset
    state = resources.SearchResources(family, None, None, None)
    assert state.snippet_for(selected) == selected["original_text"]


def passage(identifier, url, distance=0.5, resolved_url=None):
    return {
        "metadata": {
            "chunk_uuid": identifier,
            "url": url,
            "resolved_url": resolved_url or url,
        },
        "distance": distance,
        "rerank_score": 1.0,
    }


def test_different_sections_keep_their_answer_passages():
    page = "https://example.com/ci/"
    artifacts = passage("artifacts", page + "#artifacts", resolved_url=page)
    troubleshooting = passage("troubleshooting", page + "#troubleshooting", resolved_url=page)
    duplicate = passage("duplicate", page + "?utm_source=mcp#troubleshooting", resolved_url=page)

    result = search_module.deduplicate_urls([artifacts, troubleshooting, duplicate])

    assert [r["metadata"]["chunk_uuid"] for r in result] == ["artifacts", "troubleshooting"]


def test_distinct_resource_parameters_and_intrinsics_survive():
    items = [
        passage("a", "https://example.com/intrinsics/#q=svcntw"),
        passage("b", "https://example.com/intrinsics/#q=svcnth"),
        passage("v1", "https://example.com/reference?version=1#syntax"),
        passage("v2", "https://example.com/reference?version=2#syntax"),
    ]
    assert len(search_module.deduplicate_urls(items)) == 4


def test_semantic_fusion_keeps_hybrid_order_without_dense_evidence():
    items = [passage("first", "https://example.com/first"), passage("second", "https://example.com/second")]
    for item in items:
        del item["distance"]
    assert search_module.fuse_semantic_resource_ranks(items) == items


def test_semantic_fusion_deduplicates_tracking_aliases_without_losing_sections():
    items = [
        passage("first", "https://Example.com/doc/?b=2&utm_source=mcp&a=1#intro", 0.5),
        passage("alias", "https://example.com/doc?a=1&b=2&utm_medium=tool#intro", 0.1),
        passage("answer", "https://example.com/doc?a=1&b=2#troubleshoot", 0.2),
    ]

    result = search_module.fuse_semantic_resource_ranks(items)

    assert [r["metadata"]["chunk_uuid"] for r in result] == ["first", "answer"]
    assert result[0]["metadata"]["url"] == items[0]["metadata"]["url"]


def test_hybrid_fuses_before_cutting_off_candidate_pool(monkeypatch):
    items = [passage(str(i), f"https://example.com/page{i}", distance=0.5 + i / 100) for i in range(10)]
    items[8]["distance"] = 0.1
    items[8]["metadata"].update(
        url="https://example.com/page0#troubleshooting", resolved_url="https://example.com/page0",
    )
    monkeypatch.setattr(search_module, "_rerank_candidates", lambda query, candidates, **kwargs: items)

    results = search_module.hybrid_search("target", None, [], object(), None, k=5)

    assert results[0]["metadata"]["chunk_uuid"] == "0"
    assert "8" in [r["metadata"]["chunk_uuid"] for r in results]
    assert next(r for r in results if r["metadata"]["chunk_uuid"] == "8")["metadata"]["url"].endswith("#troubleshooting")


@pytest.mark.parametrize("curated", [False, True])
def test_fusion_keeps_dashboard_editions_and_collapses_source_file_aliases(curated):
    url = "https://developer.arm.com/ecosystem-dashboard/linux?package=calico"
    items = [
        passage("commercial", url, 0.5, "https://raw.githubusercontent.com/repo/a.md"),
        passage("alias", url, 0.1, "https://raw.githubusercontent.com/repo/b.md"),
        passage("open", url, 0.2, "https://raw.githubusercontent.com/repo/c.md"),
    ]
    for item in items:
        item["metadata"].update(
            doc_type="Ecosystem Dashboard", content_type="markdown",
            edition="open-source" if item["metadata"]["chunk_uuid"] == "open" else "commercial",
        )

    if curated:
        for item in items:
            item["metadata"]["filter_metadata"] = {"doc_type": ["compatibility"]}
    result = search_module.fuse_semantic_resource_ranks(items)

    assert [item["metadata"]["chunk_uuid"] for item in result] == ["commercial", "open"]
    assert [item["metadata"]["edition"] for item in result] == ["commercial", "open-source"]


def test_fusion_uses_public_identity_across_acquisition_sources():
    page = "https://learn.arm.com/learning-paths/example/install/"
    source = "https://raw.githubusercontent.com/repo/main/guide.md"
    items = [
        passage("best", page, 0.5, source),
        passage("duplicate", page, 0.1, source.replace("guide.md", "copy.md")),
        passage("other", page.replace("/install/", "/configure/"), 0.2, source),
    ]
    for item in items:
        item["metadata"].update(doc_type="Learning Paths", content_type="markdown")

    results = search_module.fuse_semantic_resource_ranks(items)

    assert [item["metadata"]["chunk_uuid"] for item in results] == ["best", "other"]
    assert results[0]["metadata"] == items[0]["metadata"]


def package_record(name="Redis", platform="linux", **metadata):
    record = result(f"https://example.com/{name}", None)
    record["metadata"].update(
        heading=name, platform=platform, search_text=f"{name} supported on Arm {platform}", **metadata,
    )
    return record


@pytest.mark.parametrize("question", [
    "Can\tI run Redis on Arm?", "Is there Redis for Arm Linux?",
    "Which version of Redis supports Arm Linux?", "Where should I download Redis?",
])
def test_support_question_prefers_package_record(question):
    card = package_record()
    guide = package_record(doc_type="Tutorial")
    baseline = search_module.rerank_candidates(question, [guide, card])
    for record, doc_type in ((guide, "learning"), (card, "compatibility")):
        record["metadata"]["filter_metadata"] = {
            "doc_type": [doc_type], "product": ["arm"], "platform": ["linux", "windows"],
        }
    ranked = search_module.rerank_candidates(question, [guide, card])
    assert ranked[0]["metadata"]["doc_type"] == "Ecosystem Dashboard"
    assert ranked[0]["rerank_score"] > ranked[1]["rerank_score"]
    assert [row["rerank_score"] for row in ranked] == [row["rerank_score"] for row in baseline]


@pytest.mark.parametrize("question,name,platform,expected", [
    ("Redis compatibility on Windows...", "Redis", "windows", .35),
    ("Is Redis supported on Ubuntu?", "Redis", "linux", .35),
    ("Is there support for Node.js.", "Node.js", "linux", .35),
    ("Is there support for C++.", "C++", "linux", .35),
    ("Can I run Redis on Windows?", "Redis", "linux", 0),
    ("Can I run Redis on Arm?", "Redis", "windows", 0),
    ("Is Redis supported on macOS.", "Redis", "linux", 0),
    ("Can I run Redis on Android?", "Redis", "linux", 0),
    ("Is Redis supported on iOS?", "Redis", "linux", 0),
    ("Can I run Redis on Mac OS X?", "Redis", "linux", 0),
    ("Is Redis supported on OSX?", "Redis", "linux", 0),
    ("Can I run PostgreSQL on Arm?", "Redis", "linux", 0),
    ("Is IDEA supported on Windows?", "IntelliJ IDEA", "windows", 0),
    ("Is Arm supported?", "Arm", "linux", 0),
    ("How  can I use Redis on Arm?", "Redis", "linux", 0),
    ("Can I debug Redis on Arm Linux?", "Redis", "linux", 0),
    ("Can I generate a Redis latency report?", "Redis", "linux", 0),
    ("Is there a way to tune Redis latency?", "Redis", "linux", 0),
    ("Recommend a tutorial for Redis.", "Redis", "linux", 0),
])
def test_dashboard_bonus_requires_support_package_and_platform(question, name, platform, expected):
    record = package_record(name, platform)["metadata"]
    query = search_module._analyze_query(question)
    assert search_module._reference_record_bonus(query, record, "ecosystem dashboard") == expected


@pytest.mark.parametrize("package,expected", [("Redis", .35), ("PostgreSQL", 0)])
def test_dashboard_subsection_uses_package_identity(package, expected):
    record = package_record("Features", heading_path=["Linux", package, "Features"])["metadata"]
    query = search_module._analyze_query("Which Redis features are supported on Linux?")
    assert search_module._reference_record_bonus(query, record, "ecosystem dashboard") == expected


def test_legacy_metadata_gets_no_reference_bonus():
    query = search_module._analyze_query("Is Redis supported on Linux?")
    assert search_module._reference_record_bonus(query, {"heading": "Redis"}, "") == 0
