"""Repository acquisition, Hugo source handling and Learn pipeline routing."""

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
COURSE = "https://learn.arm.com/courses/example/"


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


def test_nested_course_uses_frontmatter_urls_and_retains_code(gc, monkeypatch):
    repo = repository(
        {
            "content/courses/example/_index.md": markdown(
                "Example course", description="Deploy on Arm."
            ),
            "content/courses/example/module/_index.md": markdown(
                "Module", url="/courses/example/deployment/"
            ),
            "content/courses/example/module/section/lesson.md": markdown(
                "Deploy model",
                "### Run\n\n```python\nmodel.forward(inputs)\n```\n\n### Inspect\n\nCheck outputs.",
                url="/courses/example/deployment/run/",
                aliases=["/courses/old/run/"],
            ),
            "content/courses/other/_index.md": markdown(
                "Unrelated course", "Not part of example."
            ),
        },
        "courses",
    )
    sources = LearnSources(None)
    sources.repositories["courses"] = repo
    monkeypatch.setattr(gc, "learn_sources", sources)
    monkeypatch.setattr(gc, "fetch_with_logging", lambda *_: pytest.fail("HTML fetch"))
    chunks = gc.create_chunks_for_source(
        COURSE, "Example course", "Educational Course", "Arm"
    )
    run = next(c for c in chunks if c.url.endswith("/run/#run"))
    assert "model.forward(inputs)" in run.content
    assert run.title == "Deploy model"
    assert run.resolved_url.endswith(
        f"/{SHA}/content/courses/example/module/section/lesson.md"
    )
    assert all("Unrelated" not in c.content for c in chunks)
    inspect = next(c for c in chunks if c.url.endswith("#inspect"))
    assert "Run" not in inspect.heading_path  # skipped heading levels stay siblings
    alias = repo.documents("https://learn.arm.com/courses/old/run/")
    assert len(alias) == 1 and alias[0].source_url.endswith("/deployment/run/")


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
        "courses": repository({}),
        "insights": repository({}),
    }
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


def test_insights_keep_all_answers_separate_and_use_dataset_anchors():
    dataset = {
        "schema_version": 1,
        "entries": [
            {
                "id": "q1",
                "slug": "tail-handling",
                "question": "How do I handle the tail?",
                "answer": "Use predication.\n\n## Example\n\n```c\nsvwhilelt_b32(i, n);\n```",
            },
            {
                "id": "q2",
                "question": "How do I choose vector length?",
                "answer": "Query the vector length at runtime.\n\n## Example\n\nUse svcntw().",
            },
        ],
    }
    repo = repository(
        {
            "content/insights/sve/_index.md": markdown("SVE Insights", dataset="sve"),
            "data/insights/sve.json": json.dumps(dataset),
        },
        "insights",
    )
    docs = repo.documents("https://learn.arm.com/insights/sve/")
    assert len(docs) == 2
    chunks = [
        c
        for d in docs
        for c in chunk_parsed_document(d, doc_type="Insights", keywords=["SVE"])
    ]
    first = [c for c in chunks if c["url"].endswith("#tail-handling")]
    assert first and all(
        c["heading_path"][0] == "How do I handle the tail?" for c in first
    )
    assert all("choose vector length" not in c["content"] for c in first)
    assert {c["url"].split("#")[1] for c in chunks} == {"tail-handling", "q2"}
    assert all(
        c["resolved_url"].endswith(f"/{SHA}/data/insights/sve.json") for c in chunks
    )


@pytest.mark.parametrize(
    "entries",
    [
        [{"id": "q", "question": "Question", "answer": ""}],
        [{"id": "q", "question": "Question", "answer": "Answer"}] * 2,
    ],
)
def test_invalid_insights_fail_instead_of_dropping_answers(entries):
    repo = repository(
        {
            "content/insights/sve/_index.md": markdown("SVE", dataset="sve"),
            "data/insights/sve.json": json.dumps(
                {"schema_version": 1, "entries": entries}
            ),
        }
    )
    with pytest.raises(ValueError):
        repo.documents("https://learn.arm.com/insights/sve/")


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
            "content/courses/demo/_index.md": markdown("Demo", "Body"),
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

    monkeypatch.setenv("LEARN_COURSES_REF", "production")
    repo = acquire_repository("courses", SimpleNamespace(get=get), "test-secret")
    assert len(calls) == 2
    assert calls[0][0].endswith("/commits/production")
    assert calls[1][0].endswith("/tarball/" + SHA)
    assert calls[1][1]["headers"]["Authorization"] == "Bearer test-secret"
    assert set(repo.files) == {
        "content/courses/demo/_index.md",
        "data/insights/demo.json",
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
    list(sources.discovered_sources())
    sources.documents("https://learn.arm.com/install-guides/demo/")
    sources.documents("https://learn.arm.com/install-guides/demo")
    assert calls == ["learning_paths", "courses", "insights"]


def test_heading_anchors_skip_code_and_number_duplicate_headings():
    text = heading_anchors(
        "## Build `aarch64`\n## Build `aarch64`\n```sh\n# a comment\n```\n## Explicit {#custom}"
    )
    assert "{#build-aarch64}" in text and "{#build-aarch64-1}" in text
    assert "# a comment\n" in text and "{#a-comment}" not in text
    assert "{#custom}" in text


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


def test_learn_transcript_never_fetches_html(gc, monkeypatch):
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
    )
    assert chunks and chunks[0].url == "https://example.com/video"


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


def test_source_validation_failure_preserves_existing_csv_and_chunks(
    gc, monkeypatch, tmp_path
):
    csv_path = tmp_path / "sources.csv"
    original = "Site Name,License Type,Display Name,URL,Keywords\nInsights,CC4.0,SVE,https://learn.arm.com/insights/sve/,SVE\n"
    csv_path.write_text(original)
    output = tmp_path / "yaml_data"
    output.mkdir()
    (output / "chunk_existing.yaml").write_text("existing")
    repo = repository(
        {"content/insights/sve/_index.md": markdown("SVE", dataset="missing")}
    )
    sources = LearnSources(None)
    sources.repositories["insights"] = repo
    monkeypatch.setattr(gc, "learn_sources", sources)
    monkeypatch.setattr(gc, "yaml_dir", str(output))
    monkeypatch.setattr(gc, "prepare_intrinsic_chunks", lambda: None)
    monkeypatch.setattr(gc, "reconcile_ecosystem_sources", lambda **_: None)
    monkeypatch.setattr("sys.argv", ["generate-chunks.py", str(csv_path)])
    monkeypatch.setenv("SKIP_DISCOVERY", "1")
    with pytest.raises(ValueError, match="Missing Insights dataset"):
        gc.main()
    assert csv_path.read_text() == original
    assert (output / "chunk_existing.yaml").read_text() == "existing"


def test_auth_failure_does_not_leak_credentials():
    import requests

    def get(*_args, **_kwargs):
        raise requests.HTTPError("https://example.com/?token=DO-NOT-LOG")

    with pytest.raises(ValueError, match="LEARN_GITHUB_TOKEN") as error:
        acquire_repository("courses", SimpleNamespace(get=get), "DO-NOT-LOG")
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


def test_parent_and_child_rows_do_not_emit_duplicate_chunks(gc, monkeypatch, tmp_path):
    csv_path = tmp_path / "sources.csv"
    csv_path.write_text(
        "Site Name,License Type,Display Name,URL,Keywords\n"
        "Install Guides,CC4.0,Docker,https://learn.arm.com/install-guides/docker/,containers\n"
        "Install Guides,CC4.0,Engine,https://learn.arm.com/install-guides/docker/engine/,containers\n"
    )
    sources = LearnSources(None)
    sources.repositories["learning_paths"] = repository(
        {
            "content/install-guides/docker/_index.md": markdown(
                "Docker", "Choose a runtime."
            ),
            "content/install-guides/docker/engine.md": markdown(
                "Engine", "Install the engine."
            ),
        }
    )
    monkeypatch.setattr(gc, "learn_sources", sources)
    monkeypatch.setattr(gc, "yaml_dir", str(tmp_path / "chunks"))
    monkeypatch.setattr(gc, "details_file", str(tmp_path / "details.csv"))
    monkeypatch.setattr(gc, "prepare_intrinsic_chunks", lambda: None)
    monkeypatch.setattr(gc, "reconcile_ecosystem_sources", lambda **_: None)
    saved = []
    monkeypatch.setattr(gc, "chunkSaveAndTrack", lambda _, chunk: saved.append(chunk))
    monkeypatch.setattr("sys.argv", ["generate-chunks.py", str(csv_path)])
    monkeypatch.setenv("SKIP_DISCOVERY", "1")
    gc.main()
    assert len(saved) == 2
    assert len({chunk.url for chunk in saved}) == 2


def test_token_can_be_read_from_buildkit_secret_file(monkeypatch, tmp_path):
    token_file = tmp_path / "secret"
    token_file.write_text("test-token\n")
    monkeypatch.delenv("LEARN_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("LEARN_GITHUB_TOKEN_FILE", str(token_file))
    assert LearnSources(None).token == "test-token"
