"""Repository acquisition, Hugo source handling and Learn pipeline routing."""

import csv
import datetime as dt
import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from document_chunking import chunk_parsed_document, parse_html
from learn_repository import (
    LearnSources,
    Repository,
    acquire_repository,
    heading_anchors,
    parse_repository_markdown,
    read_archive,
)

SHA = "a" * 40


def markdown(title, body="", **metadata):
    import yaml

    return "---\n" + yaml.safe_dump(dict(title=title, **metadata)) + "---\n" + body


def repository(files, kind="arm-learning-paths"):
    return Repository(
        "ArmDeveloperEcosystem/" + kind,
        SHA,
        files,
        now=dt.datetime(2026, 10, 27, tzinfo=dt.timezone.utc),
    )


@pytest.fixture
def learn_build(gc, monkeypatch, tmp_path):
    """Configure a Learn-only build; tests supply the CSV and repository."""
    sources = LearnSources(None)
    monkeypatch.setattr(gc, "learn_sources", sources)
    monkeypatch.setattr(gc, "yaml_dir", str(tmp_path / "chunks"))
    monkeypatch.setattr(gc, "details_file", str(tmp_path / "details.csv"))
    monkeypatch.setattr(gc, "prepare_intrinsic_chunks", lambda: None)
    monkeypatch.setattr(gc, "reconcile_ecosystem_sources", lambda **_: None)
    monkeypatch.setattr("sys.argv", ["generate-chunks.py", str(tmp_path / "sources.csv")])
    monkeypatch.setenv("SKIP_DISCOVERY", "1")
    return sources


@pytest.mark.parametrize("root_route", ["/learning-paths/cross-platform/new/", "/tutorials/new/"])
@pytest.mark.parametrize("lesson_route", [None, "/lessons/demo-step/"])
def test_discovered_sources_inherit_verified_tags_through_chunks(
    gc, monkeypatch, tmp_path, root_route, lesson_route,
):
    root = "https://learn.arm.com" + root_route
    repo = repository({
        "content/learning-paths/cross-platform/new/_index.md": markdown(
            "New AWS Graviton lesson", "Learn on Arm.", url=root_route,
            operatingsystems=["Linux", "Windows"], armips=["Cortex-M", "Mali"],
            tools_software_languages=["SME2", "SVE", "SVE2", "Neon", "Python"],
            platforms=["Arm AGI CPU", "AWS Graviton"],
        ),
        "content/learning-paths/cross-platform/new/lesson.md": markdown(
            "Lesson", "Build the example.", **({"url": lesson_route} if lesson_route else {})),
        "content/install-guides/new.md": markdown("New tool", "Install it.", tool_install=True),
    })
    sources = LearnSources(None)
    sources.repositories["learning_paths"] = repo
    monkeypatch.setattr(sources.public, "discovered_sources", lambda: [])
    monkeypatch.setattr(gc, "learn_sources", sources)
    gc.discover_learn_sources()
    path = tmp_path / "sources.csv"
    gc.save_sources_csv(path)
    config, count = gc.readInCSV(path)
    assert count == 2
    for i in range(count):
        chunks = gc.create_chunks_for_source(
            config["urls"][i], config["source_names"][i], config["site_names"][i],
            config["focus"][i], metadata_overrides=config["metadata_overrides"][i],
        )
        expected = {"doc_type": ["guide"], "product": ["arm"], "platform": []}
        if config["urls"][i] == root:
            expected = {"doc_type": ["learning"], "product": ["arm"], "platform": [
                "linux", "windows", "cortex-m", "mali", "sme2", "sve", "sve2", "neon", "agi-cpu",
            ]}
            assert len({chunk.url for chunk in chunks}) == 2
        assert chunks and all(chunk.toDict()["filter_metadata"] == expected for chunk in chunks)
    cleared = gc.create_chunks_for_source(root, "New", "Learning Paths", "", metadata_overrides={"platform": []})
    assert cleared and all(chunk.filter_metadata == {
        "doc_type": ["learning"], "product": ["arm"], "platform": [],
    } for chunk in cleared)


def test_learn_platform_metadata_uses_authored_scope_and_flags_unknown_os():
    repo = repository({
        "content/learning-paths/cross-platform/new/_index.md": markdown(
            "Root", "Learn.", operatingsystems=["Linux"], armips=["Cortex-M55"],
            tools_software_languages=["SME2"], platforms=["Arm AGI CPU"],
        ),
        "content/learning-paths/cross-platform/new/child.md": markdown(
            "Child", "Neon is only an incidental mention.", operatingsystems=["FutureOS"],
            armips=[], tools_software_languages=[], platforms=[],
        ),
    })
    root = "https://learn.arm.com/learning-paths/cross-platform/new/"
    assert repo.platform_tags(root) == ["linux", "cortex-m", "sme2", "agi-cpu"]
    with pytest.warns(UserWarning, match="FutureOS"):
        assert repo.platform_tags(root + "child/") == []


def test_relocated_lesson_inherits_only_fields_without_child_overrides():
    repo = repository({
        "content/learning-paths/cross-platform/new/_index.md": markdown(
            "Root", "Learn.", url="/tutorials/new/", operatingsystems=["Linux"],
            armips=["Cortex-M55"], tools_software_languages=["SME2"],
        ),
        "content/learning-paths/cross-platform/new/child.md": markdown(
            "Child", "Build the example.", url="/lessons/demo-step/",
            operatingsystems=["Windows"], armips=[],
        ),
    })
    assert repo.platform_tags("https://learn.arm.com/lessons/demo-step/") == ["windows", "sme2"]


def test_discovery_and_multipart_guides_share_the_repository(gc, monkeypatch):
    repo = repository(
        {
            "content/learning-paths/cross-platform/demo/_index.md": markdown(
                "Build on Arm",
                learning_objectives=["Build native binaries."],
                subjects="CI-CD",
            ),
            "content/learning-paths/cross-platform/demo/build.md": markdown(
                "Build", "Use the Arm runner."
            ),
            "content/install-guides/docker/_index.md": markdown(
                "Docker", "Choose your install.", tool_install=True, multi_install=True
            ),
            "content/install-guides/docker/engine.md": markdown(
                "Docker Engine", "Install the engine.", multitool_install_part=True
            ),
            "content/migration/_index.md": markdown(
                "Migrate", "Check architecture-specific code."
            ),
        }
    )
    sources = LearnSources(None)
    sources.repositories = {
        "learning_paths": repo,
    }
    monkeypatch.setattr(sources.public, "discovered_sources", lambda: [])
    monkeypatch.setattr(gc, "learn_sources", sources)
    monkeypatch.setattr(
        gc.http_session, "get", lambda *_args, **_kw: pytest.fail("Network fetch")
    )
    gc.discover_learn_sources()
    assert len(gc.all_sources) == 3
    assert next(s for s in gc.all_sources if "cross-platform" in s["url"])[
        "keywords"
    ].endswith("CI-CD")
    docs = repo.documents("https://learn.arm.com/learning-paths/cross-platform/demo/")
    assert len(docs) == 2
    assert "Build native binaries." in "\n".join(
        block.text for section in docs[0].sections for block in section.blocks
    )
    chunks = gc.create_chunks_for_source(
        "https://learn.arm.com/install-guides/docker/", "Docker", "Install Guides", ""
    )
    assert {c.url for c in chunks} == {
        "https://learn.arm.com/install-guides/docker/",
        "https://learn.arm.com/install-guides/docker/engine/",
    }
    assert gc.create_chunks_for_source(
        "https://learn.arm.com/migration", "Migrate", "Documentation", ""
    )


def test_hugo_shortcodes_preserve_tabs_notices_quizzes_and_references():
    body = """### Install
{{% notice Note %}}
Use a native compiler.
{{% /notice %}}
{{< tabpane language="bash" >}}
{{< tab header="Linux" >}}
clang -O3 main.c
{{< /tab >}}
{{< tab header="Windows" language="powershell" >}}
clang.exe main.c
{{< /tab >}}
{{< /tabpane >}}
[Guide]({{< relref "other.md" >}})
{{< knowledge-check question="Which compiler?" >}}
- [x] Native Arm compiler
- [ ] x86 compiler :: This targets a different architecture.
{{< /knowledge-check >}}
{{< knowledge-check-completion >}}Congratulations!{{< /knowledge-check-completion >}}
"""
    repo = repository(
        {
            "content/install-guides/demo.md": markdown("Demo", body),
            "content/install-guides/other.md": markdown("Other", "Use this guide."),
        }
    )
    doc = repo.documents("https://learn.arm.com/install-guides/demo/")[0]
    blocks = [b for s in doc.sections for b in s.blocks]
    text = "\n".join(b.text for b in blocks)
    assert "{{" not in text and "Congratulations" not in text
    assert "Correct answer: Native Arm compiler" in text
    assert "Incorrect answer: x86 compiler" in text
    assert "https://learn.arm.com/install-guides/other/" in text
    assert "Linux:" in text and "Windows:" in text
    assert [b.text for b in blocks if b.kind == "code"] == [
        "```\nclang -O3 main.c\n```",
        "```\nclang.exe main.c\n```",
    ]


def test_repository_markdown_and_html_produce_the_same_instructional_blocks():
    source = """## Install {#install}
Use Arm **Performance** Libraries and the [guide](../guide/).

![layout-hint#center](https://assets.example/opaque-id.png "Build settings")

| Setting | Value |
| --- | --- |
| Target | `aarch64` |

```sh
clang -O3 main.c
```
"""
    rendered = """<h2 id="install">Install</h2>
<p>Use Arm <strong>Performance</strong> Libraries and the <a href="../guide/">guide</a>.</p>
<p>Build settings</p>
<table><tr><th>Setting</th><th>Value</th></tr><tr><td>Target</td><td><code>aarch64</code></td></tr></table>
<pre><code>clang -O3 main.c</code></pre>"""
    url = "https://learn.arm.com/install-guides/example/"
    actual = parse_repository_markdown(source, url, "source.md", "Example")
    expected = parse_html(rendered, url, "source.html", "Example")
    assert actual.sections == expected.sections
    assert actual.content_type == "markdown"
    text = "\n".join(b.text for s in actual.sections for b in s.blocks)
    assert "Arm Performance Libraries" in text
    assert "Build settings" in text and "opaque-id" not in text
    assert "https://learn.arm.com/install-guides/guide/" in text


def test_unknown_shortcode_and_missing_source_fail_closed():
    repo = repository({"content/demo.md": markdown("Demo", "{{< new-component >}}")})
    with pytest.raises(ValueError, match="unsupported Hugo shortcode"):
        repo.documents("https://learn.arm.com/demo/")
    with pytest.raises(ValueError, match="missing or unpublished"):
        repo.documents("https://learn.arm.com/missing/")


def test_drafts_future_expired_and_nonrendered_pages_are_excluded():
    files = {
        "content/install-guides/ok.md": markdown("Published", "OK", tool_install=True)
    }
    for name, fields in {
        "draft": {"draft": True},
        "future": {"publishDate": "2030-01-01"},
        "expired": {"expiryDate": "2020-01-01"},
        "hidden": {"_build": {"render": "never"}},
    }.items():
        files[f"content/install-guides/{name}.md"] = markdown(
            name, "Unavailable", tool_install=True, **fields
        )
    repo = repository(files)
    assert len(repo.pages) == 1 and len(list(repo.discovered_sources())) == 1


def test_ambiguous_legacy_aliases_do_not_shadow_canonical_urls():
    repo = repository(
        {
            "content/first.md": markdown("First", "A", aliases=["/old/", "/second/"]),
            "content/second.md": markdown("Second", "B", aliases=["/old/"]),
        }
    )
    assert repo.documents("https://learn.arm.com/second/")[0].display_title == "Second"
    with pytest.raises(ValueError):
        repo.documents("https://learn.arm.com/old/")


def archive_bytes(files):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:gz") as archive:
        for name, value in files.items():
            info = tarfile.TarInfo("repo-sha/" + name)
            data = value.encode()
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return result.getvalue()


def test_acquisition_resolves_one_commit_and_downloads_sources_only(monkeypatch):
    calls = []
    archive = archive_bytes(
        {
            "content/learning-paths/demo/_index.md": markdown("Demo", "Body"),
            "content/install-guides/demo.md": markdown("Guide", "Body"),
            "static/asset.png": "ignore",
            "data/insights/demo.json": "{}",
        }
    )

    class Response:
        raw = io.BytesIO(archive)

        def raise_for_status(self):
            pass

        def json(self):
            return {"sha": SHA}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setenv("LEARN_LEARNING_PATHS_REF", "production")
    repo = acquire_repository("learning_paths", SimpleNamespace(get=get))
    assert len(calls) == 2
    assert calls[0][0].endswith("/commits/production")
    assert calls[1][0].endswith("/tarball/" + SHA)
    assert all("Authorization" not in kwargs["headers"] for _, kwargs in calls)
    assert set(repo.files) == {
        "content/learning-paths/demo/_index.md",
        "content/install-guides/demo.md",
    }


def test_archive_rejects_links_in_place_of_content():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("repo/content/demo.md")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        archive.addfile(info)
    with pytest.raises(ValueError, match="Invalid Learn source archive member"):
        read_archive(io.BytesIO(buffer.getvalue()))


def test_snapshot_is_reused_for_discovery_and_chunking(monkeypatch):
    calls = []
    repo = repository(
        {"content/install-guides/demo.md": markdown("Demo", "Body", tool_install=True)}
    )

    def acquire(kind, *_):
        calls.append(kind)
        return repo if kind == "learning_paths" else repository({})

    monkeypatch.setattr("learn_repository.acquire_repository", acquire)
    sources = LearnSources(None)
    monkeypatch.setattr(sources.public, "discovered_sources", lambda: [])
    list(sources.discovered_sources())
    sources.documents("https://learn.arm.com/install-guides/demo/")
    sources.documents("https://learn.arm.com/install-guides/demo")
    assert calls == ["learning_paths"]


def test_heading_anchors_skip_code_and_number_duplicate_headings():
    text = heading_anchors(
        "## Build `aarch64`\n## Build `aarch64`\n```sh\n# a comment\n```\n## Explicit {#custom}"
    )
    assert "{#build-aarch64}" in text and "{#build-aarch64-1}" in text
    assert "# a comment\n" in text and "{#a-comment}" not in text
    assert "{#custom}" in text


def test_generated_routes_match_hugo_casing_without_changing_source_paths():
    path = "content/learning-paths/laptops-and-desktops/Implementing-a-Voice-Translation-Pipeline/_index.md"
    repo = repository({
        path: markdown("Voice translation", "Build it."),
        "content/install-guides/Tool.md": markdown("Tool", "Install.", slug="My-Tool"),
        "content/install-guides/explicit.md": markdown("Explicit", "Read.", url="/Custom-URL/"),
    })
    url = "https://learn.arm.com/learning-paths/laptops-and-desktops/implementing-a-voice-translation-pipeline/"
    document = repo.documents(url)[0]
    assert document.source_url == url
    assert document.resolved_url.endswith(path)
    assert repo.documents("https://learn.arm.com/install-guides/my-tool/")
    assert repo.documents("https://learn.arm.com/Custom-URL/")


def test_heading_ids_match_hugo_raw_source_and_global_collisions():
    # Expected IDs verified against Hugo's default Goldmark renderer.
    source = "\n".join([
        "### Replace `std::complex<double>` with raw double arithmetic",
        "## [Link](url)", "## Build &amp; run", "## Build  again",
        "## Explicit {#custom}", "## Explicit", "## custom",
        "## foo", "## foo-1", "## foo",
    ])
    import re

    assert re.findall(r"\{#([^}]+)\}", heading_anchors(source)) == [
        "replace-stdcomplexdouble-with-raw-double-arithmetic",
        "linkurl", "build-amp-run", "build--again", "custom", "explicit", "custom-1",
        "foo", "foo-1", "foo-2",
    ]


def test_learning_path_title_and_hugo_heading_attributes_keep_public_anchors():
    repo = repository(
        {
            "content/learning-paths/cross-platform/demo/_index.md": markdown(
                "Demo", "Course overview."
            ),
            "content/learning-paths/cross-platform/demo/start.md": markdown(
                "Start here",
                "Introduction.\n\n### Procedure {.section}\n\nRun the command.\n\n"
                "### Next {.section #explicit}\n\nCheck the result.",
            )
        }
    )
    document = repo.documents(
        "https://learn.arm.com/learning-paths/cross-platform/demo/start/"
    )[0]
    chunks = chunk_parsed_document(document, "Learning Paths", [])
    assert [chunk["url"].split("#")[1] for chunk in chunks] == [
        "learning-path-title", "procedure", "explicit"
    ]
    assert chunks[1]["heading_path"] == ["Procedure"]
    assert all(".section" not in chunk["content"] for chunk in chunks)
    overview = repo.documents("https://learn.arm.com/learning-paths/cross-platform/demo/")[0]
    assert chunk_parsed_document(overview, "Learning Paths", [])[0]["url"] == (
        "https://learn.arm.com/learning-paths/cross-platform/demo/#about-marker"
    )


def test_learning_path_frontmatter_keeps_separate_sections_and_faq_answers():
    repo = repository({
        "content/learning-paths/cross-platform/demo/_index.md": markdown(
            "Demo", who_is_this_for="Embedded developers.",
            prerequisites=["Install a compiler."],
            generated_summary_faq={
                "summary": "Build the application.",
                "faqs": [
                    {"question": "How do I build?", "answer": "Run the compiler."},
                    {"question": "How do I debug?", "answer": "Start the debugger."},
                ],
            },
        )
    })
    doc = repo.documents("https://learn.arm.com/learning-paths/cross-platform/demo/")[0]
    chunks = chunk_parsed_document(doc, "Learning Paths", [])
    prerequisites = next(c for c in chunks if c["heading"] == "Prerequisites")
    assert prerequisites["url"].endswith("#about-marker")
    assert "Install a compiler." in prerequisites["content"]
    build = next(c for c in chunks if c["heading"] == "How do I build?")
    debug = next(c for c in chunks if c["heading"] == "How do I debug?")
    assert build["url"].endswith("#generated-summary-faq")
    assert "Run the compiler." in build["content"]
    assert "Start the debugger." not in build["content"]
    assert "Start the debugger." in debug["content"]


@pytest.mark.parametrize("tags", [None, {"doc_type": ["learning"], "product": ["arm"],
                                       "platform": ["linux", "windows"]}])
def test_learn_transcript_never_fetches_html(gc, monkeypatch, tags):
    sources = LearnSources(None)
    sources.repositories["learning_paths"] = repository(
        {"content/demo.md": markdown("Transcript", "Instructions.")}
    )
    monkeypatch.setattr(gc, "learn_sources", sources)
    monkeypatch.setattr(gc, "fetch_with_logging", lambda *_: pytest.fail("HTML fetch"))
    chunks = gc.create_chunks_for_source(
        "https://example.com/video",
        "Video",
        "Video",
        "Arm",
        "https://learn.arm.com/demo/",
        metadata_overrides=tags,
    )
    assert chunks and chunks[0].url == "https://example.com/video"
    assert all(chunk.toDict().get("filter_metadata", {}) == (tags or {"doc_type": [], "product": [], "platform": []}) for chunk in chunks)


def test_reconciliation_omits_retired_pages_without_expanding_skip_discovery(
    gc, monkeypatch, capsys
):
    repo = repository(
        {
            "content/install-guides/kept.md": markdown(
                "Kept", "Install.", tool_install=True
            ),
            "content/install-guides/new.md": markdown(
                "New", "Install.", tool_install=True
            ),
            "content/install-guides/draft.md": markdown(
                "Draft", "Unavailable.", draft=True
            ),
        }
    )
    sources = LearnSources(None)
    sources.repositories["learning_paths"] = repo
    monkeypatch.setattr(gc, "learn_sources", sources)
    for name in ("kept", "draft", "deleted"):
        gc.register_source(
            "Install Guides",
            "CC4.0",
            name,
            f"https://learn.arm.com/install-guides/{name}/",
            ["curated"],
        )
    gc.reconcile_learn_sources(discover=False)
    assert len(gc.all_sources) == 1
    assert gc.all_sources[0]["keywords"] == "curated"
    assert capsys.readouterr().out.count("[LEARN OMITTED SOURCE]") == 2


def test_draft_cascade_hides_descendants():
    repo = repository(
        {
            "content/courses/example/_index.md": markdown(
                "Draft course", draft=True, cascade={"draft": True}
            ),
            "content/courses/example/module/lesson.md": markdown(
                "Lesson", "Not published."
            ),
        }
    )
    assert not repo.pages


def test_leading_blank_lines_do_not_hide_hugo_frontmatter():
    repo = repository(
        {
            "content/install-guides/rust.md": "\n \r\n" + markdown(
                "Install Rust", "## Install\n\nUse rustup.", tool_install=True
            ),
            "content/install-guides/draft.md": "\n" + markdown(
                "Draft", "Do not publish.", draft=True
            ),
        }
    )
    sources = list(repo.discovered_sources())
    assert len(sources) == 1
    assert sources[0]["display_name"] == "Install Guide - Install Rust"
    doc = repo.documents("https://learn.arm.com/install-guides/rust/")[0]
    assert doc.display_title == "Install Rust"
    assert doc.sections[0].heading_path == ["Install"]
    assert "title:" not in doc.sections[0].blocks[0].text


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("transcript", [False, True])
def test_source_validation_failure_preserves_existing_csv_and_chunks(
    gc, monkeypatch, tmp_path, wrapped, transcript
):
    csv_path = tmp_path / "sources.csv"
    url = "https://learn.arm.com/insights/sve/"
    if wrapped:
        url = "chrome-extension://reader/" + url.replace("https://", "https:/")
    source_url = "https://example.com/video" if transcript else url
    original = (
        "Site Name,License Type,Display Name,URL,Keywords,Transcript Source URL\n"
        f"Insights,CC4.0,SVE,{source_url},SVE,{url if transcript else ''}\n"
    )
    csv_path.write_text(original)
    output = tmp_path / "yaml_data"
    output.mkdir()
    (output / "chunk_existing.yaml").write_text("existing")
    sources = LearnSources(SimpleNamespace(get=lambda *_a, **_kw: SimpleNamespace(
        raise_for_status=lambda: None, url="https://learn.arm.com/insights/sve/",
        content=b"<main><h1>SVE</h1></main>",
    )))
    monkeypatch.setattr(gc, "learn_sources", sources)
    monkeypatch.setattr(gc, "yaml_dir", str(output))
    monkeypatch.setattr(gc, "prepare_intrinsic_chunks", lambda: None)
    monkeypatch.setattr(gc, "reconcile_ecosystem_sources", lambda **_: None)
    monkeypatch.setattr("sys.argv", ["generate-chunks.py", str(csv_path)])
    monkeypatch.setenv("SKIP_DISCOVERY", "1")
    with pytest.raises(ValueError, match="No published Insights answers"):
        gc.main()
    assert csv_path.read_text() == original
    assert (output / "chunk_existing.yaml").read_text() == "existing"


def test_acquisition_failure_does_not_log_redirect_details():
    import requests

    def get(*_args, **_kwargs):
        raise requests.HTTPError("https://example.com/?token=DO-NOT-LOG")

    with pytest.raises(ValueError, match="public repository") as error:
        acquire_repository("learning_paths", SimpleNamespace(get=get))
    assert "DO-NOT-LOG" not in str(error.value)


def test_frontmatter_knowledge_and_code_examples_survive():
    repo = repository(
        {
            "content/install-guides/demo.md": markdown(
                "Demo",
                '{{< godbolt mode="output" opt="-O3" src="int main() {\\nreturn 0;\\n}" >}}',
                generated_summary_faq={
                    "summary": "Use Arm.",
                    "faqs": [
                        {"question": "How to build?", "answer": "Compile natively."}
                    ],
                },
                further_reading=[
                    {
                        "resource": {
                            "title": "Reference",
                            "link": "https://example.com/reference",
                        }
                    }
                ],
            )
        }
    )
    doc = repo.documents("https://learn.arm.com/install-guides/demo/")[0]
    text = "\n".join(block.text for section in doc.sections for block in section.blocks)
    assert "Compile natively." in text and "https://example.com/reference" in text
    assert "int main() {\nreturn 0;\n}" in text and "-O3" in text


@pytest.mark.parametrize("child_first", [False, True])
@pytest.mark.parametrize("parent_tags,child_tags,expected", [
    ({}, {}, {}),
    ({"product": ["arm"]}, {"platform": ["linux"]}, {"product": ["arm"], "platform": ["linux"]}),
    ({"doc_type": []}, {"product": ["arm"]}, {"doc_type": [], "product": ["arm"]}),
    ({"platform": ["linux", "windows"]}, {"platform": ["windows", "linux"]}, {"platform": ["linux", "windows"]}),
    ({"platform": ["linux", "windows"]}, {"platform": ["linux"]}, {"platform": ["linux"]}),
    ({"platform": ["linux"]}, {"platform": ["windows"]}, {"platform": ["windows"]}),
    ({"platform": []}, {"platform": ["linux"]}, {"platform": ["linux"]}),
    ({"platform": ["linux"]}, {}, {"platform": ["linux"]}),
    ({"platform": ["linux"]}, {"platform": []}, {"platform": []}),
    ({"platform": ["linux", "windows"], "product": ["arm"]},
     {"platform": ["linux"], "product": [], "doc_type": ["guide"]},
     {"platform": ["linux"], "product": [], "doc_type": ["guide"]}),
])
def test_parent_and_child_rows_do_not_emit_duplicate_chunks(
    gc, learn_build, tmp_path, child_first, parent_tags, child_tags, expected
):
    import yaml

    csv_path = tmp_path / "sources.csv"
    rows = [
        ["Install Guides", "CC4.0", "Docker", "https://learn.arm.com/install-guides/docker/", "containers"],
        ["Install Guides", "CC4.0", "Engine", "https://learn.arm.com/install-guides/docker/engine/", "systemd daemon control; containers"],
    ]
    for row, tags in zip(rows, (parent_tags, child_tags)):
        row.append("")
        row.extend(gc.format_metadata_override(tags.get(field)) for field in gc.METADATA_COLUMNS.values())
    if child_first:
        rows.reverse()
    with csv_path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Site Name", "License Type", "Display Name", "URL", "Keywords", "Transcript Source URL", *gc.METADATA_COLUMNS])
        writer.writerows(rows)
    learn_build.repositories["learning_paths"] = repository(
        {
            "content/install-guides/docker/_index.md": markdown(
                "Docker", "Choose a runtime."
            ),
            "content/install-guides/docker/engine.md": markdown(
                "Engine", "Install the engine.",
                url="/install-guides/container-engine/",
                aliases=["/install-guides/docker/engine/"],
            ),
        }
    )
    original_rows = list(csv.DictReader(io.StringIO(csv_path.read_text())))
    gc.main()
    assert list(csv.DictReader(io.StringIO(csv_path.read_text()))) == original_rows
    saved = [yaml.safe_load(path.read_text()) for path in (tmp_path / "chunks").glob("*.yaml")]
    assert len(saved) == 2
    assert len({chunk["url"] for chunk in saved}) == 2
    defaults = {"doc_type": ["guide"], "product": ["arm"], "platform": []}
    expected = defaults | expected
    parent_tags = defaults | parent_tags
    child = next(chunk for chunk in saved if chunk["url"].endswith("/container-engine/"))
    assert {k: set(v) for k, v in child.get("filter_metadata", {}).items()} == {k: set(v) for k, v in expected.items()}
    assert set(gc.parse_keywords(child["keywords"])) == {
        "containers", "docker", "engine", "systemd daemon control"
    }
    parent = next(chunk for chunk in saved if chunk["url"].endswith("/docker/"))
    assert parent.get("filter_metadata", {}) == parent_tags
    assert "systemd daemon control" not in parent["keywords"]


@pytest.mark.parametrize("alias_first", [False, True])
@pytest.mark.parametrize("alias_tags", [["windows"], []])
def test_equal_authority_alias_conflict_preserves_previous_outputs(
    gc, learn_build, tmp_path, alias_first, alias_tags
):
    csv_path = tmp_path / "sources.csv"
    rows = [
        ["Install Guides", "CC4.0", "Engine", "https://learn.arm.com/install-guides/engine/", "engine", "linux"],
        ["Install Guides", "CC4.0", "Legacy Engine", "https://learn.arm.com/install-guides/legacy/", "containers", json.dumps(alias_tags)],
    ]
    if alias_first:
        rows.reverse()
    with csv_path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Site Name", "License Type", "Display Name", "URL", "Keywords", "Platform"])
        writer.writerows(rows)
    original = csv_path.read_bytes()
    output = tmp_path / "chunks"
    output.mkdir()
    (output / "chunk_existing.yaml").write_text("previous chunk")
    details = tmp_path / "details.csv"
    details.write_text("previous details")
    learn_build.repositories["learning_paths"] = repository({
        "content/install-guides/engine.md": markdown(
            "Engine", "Install the engine.", aliases=["/install-guides/legacy/"]
        ),
    })
    with pytest.raises(ValueError, match="Conflicting platform tags"):
        gc.main()
    assert csv_path.read_bytes() == original
    assert (output / "chunk_existing.yaml").read_text() == "previous chunk"
    assert details.read_text() == "previous details"


def test_main_resolves_learn_transcript_metadata_by_document_identity(gc, learn_build, monkeypatch, tmp_path, capsys):
    import yaml

    csv_path = tmp_path / "sources.csv"
    csv_path.write_text(
        "Site Name,License Type,Display Name,URL,Keywords,Transcript Source URL,Platform,Product\n"
        "Install Guides,CC4.0,Docker,https://learn.arm.com/install-guides/docker/,containers,,\"[\"\"linux\"\",\"\"windows\"\"]\",arm\n"
        "Video,CC4.0,Engine,https://example.com/video,engine,https://learn.arm.com/install-guides/docker/engine/,linux,\n"
    )
    learn_build.repositories["learning_paths"] = repository({
        # A bodyless parent still defines a broader scope than its only child.
        "content/install-guides/docker/_index.md": markdown("Docker"),
        "content/install-guides/docker/engine.md": markdown("Engine", "## Setup\nInstall the engine."),
    })
    monkeypatch.setattr(gc, "fetch_with_logging", lambda *_: pytest.fail("HTML fetch"))
    gc.main()
    output = capsys.readouterr().out
    assert "[METADATA GAP] https://example.com/video: doc_type" in output
    assert "[METADATA COVERAGE] 2 source chunks" in output
    assert output.count("[SOURCE CHUNKS]") == 2
    assert " === Engine" not in output
    saved = [yaml.safe_load(path.read_text()) for path in (tmp_path / "chunks").glob("*.yaml")]
    assert len(saved) == 2
    transcript = next(chunk for chunk in saved if chunk["url"] == "https://example.com/video")
    assert transcript["document_context"]["url"] == "https://learn.arm.com/install-guides/docker/engine/"
    for chunk in saved:
        assert chunk["filter_metadata"] == {
            "doc_type": [] if chunk["url"] == "https://example.com/video" else ["guide"],
            "platform": ["linux"], "product": ["arm"],
        }


def test_comments_are_removed_without_changing_code_literals():
    body = '''Inline `print("<!--inline-->")` and `` ` <!--wide--> ` ``.
<!-- unpublished {{< unsupported >}} `example` -->
```python
print("<!--fenced-->")
```
~~~html
<!--tilde-->
~~~

    print("<!--indented-->")

Visible text. <!--hidden--> More text.
'''
    repo = repository({"content/install-guides/demo.md": markdown("Demo", body)})
    doc = repo.documents("https://learn.arm.com/install-guides/demo/")[0]
    text = "\n".join(c["content"] for c in chunk_parsed_document(doc, "Guide", []))
    for literal in ("inline", "wide", "fenced", "tilde", "indented"):
        assert f"<!--{literal}-->" in text
    assert "unpublished" not in text and "hidden" not in text
    assert "Visible text." in text and "More text." in text


@pytest.mark.parametrize(
    "pane,code",
    [("tabpane code=true", True), ("tabpane-normal", False),
     ('tabpane-normal language="python"', False)],
)
def test_language_less_tabs_keep_their_content_type(pane, code):
    body = f'''## Setup
{{{{< {pane} >}}}}
{{{{< tab header="Linux" >}}}}
# Install the package
sudo apt install example
{{{{< /tab >}}}}
{{{{< /{pane.split()[0]} >}}}}
'''
    repo = repository({"content/install-guides/demo.md": markdown("Demo", body)})
    doc = repo.documents("https://learn.arm.com/install-guides/demo/")[0]
    chunks = chunk_parsed_document(doc, "Guide", [])
    assert any(block.kind == "code" for section in doc.sections for block in section.blocks) == code
    if code:
        assert all(chunk["url"].endswith("#setup") for chunk in chunks)
        assert "# Install the package\nsudo apt install example" in chunks[0]["content"]
    else:
        assert any(chunk["url"].endswith("#install-the-package") for chunk in chunks)
