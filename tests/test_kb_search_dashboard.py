"""Dashboard identity must survive result deduplication and response formatting."""

import pytest
from arm_kb_search import resources
from arm_kb_search.search import deduplicate_urls


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


def test_dashboard_editions_survive_but_multiple_chunks_per_source_do_not():
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


def test_other_documents_and_legacy_dashboard_keep_url_deduplication():
    for doc_type, content_type in [
        ("Documentation", "markdown"),
        ("Ecosystem Dashboard", "html"),
    ]:
        first = result("https://example.com", "first", doc_type, content_type)
        second = result("https://example.com", "second", doc_type, content_type)
        assert deduplicate_urls([first, second]) == [first]
        assert deduplicate_urls([first, second], max_chunks_per_url=2) == [
            first,
            second,
        ]


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
    assert hits[0]["platform"] == "linux" and hits[0]["edition"] == "commercial"
    assert hits[1]["platform"] == hits[1]["edition"] == ""
