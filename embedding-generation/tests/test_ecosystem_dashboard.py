"""Exercise the adapter with the real parser and chunker, without network mocks."""

from pathlib import Path

import pytest

from document_chunking import chunk_parsed_document, parse_markdown, split_frontmatter
from ecosystem_dashboard import parse_ecosystem_package

FIXTURES = Path(__file__).parent / "fixtures" / "ecosystem_dashboard"
SOURCE = "https://developer.arm.com/ecosystem-dashboard/linux?package=.net"
RESOLVED = "https://raw.githubusercontent.com/example/repo/123/content/dot-net.md"


def chunks(markdown, *, platform="linux", **options):
    document = parse_ecosystem_package(
        markdown, platform=platform, source_url=SOURCE, resolved_url=RESOLVED
    )
    return chunk_parsed_document(document, "Ecosystem Dashboard", [".NET"], **options)


def test_dotnet_retains_discovery_support_and_resource_information():
    result = chunks((FIXTURES / "dot-net.md").read_text())
    content = "\n".join(chunk["content"] for chunk in result)
    for expected in (
        "cross-platform framework",
        "Category: Runtimes",
        "Arm Linux support: Supported",
        "Minimum supported version: 5.0",
        "Arm-recommended minimum version: 8.0",
        "Recommendation rationale:",
        "conditional comparison",
        "Amazon AWS guide",
        "https://learn.arm.com/install-guides/dotnet/",
        "https://learn.microsoft.com/en-us/dotnet/core/install/linux-ubuntu",
        "https://devblogs.microsoft.com/dotnet/this-arm64-performance-in-dotnet-8/",
    ):
        assert expected in content
    assert "optional_hidden_info" not in content
    assert (
        "https://learn.microsoft.com/en-us/dotnet/core/whats-new/dotnet-5"
        not in content
    )
    for chunk in result:
        assert chunk["url"] == SOURCE
        assert chunk["resolved_url"] == RESOLVED
        assert chunk["version"] == ""  # Neither the commit number nor minimum version.
        assert chunk["product"] == ""
        assert chunk["doc_type"] == "Ecosystem Dashboard"


def test_commercial_package_preserves_vendor_date_and_deduplicates_homepage():
    content = "\n".join(
        c["content"] for c in chunks((FIXTURES / "bloombase-storesafe.md").read_text())
    )
    assert "intelligent storage firewall" in content
    assert "Vendor: Bloombase" in content
    assert "Available on Arm since: 2021/03/10" in content
    assert "https://supportal.bloombase.com" in content
    assert (
        content.count("[Product page](https://www.bloombase.com/products/storesafe)")
        == 1
    )
    assert "[Homepage]" not in content
    assert "Minimum supported version:" not in content
    assert "Support caveats:" not in content


@pytest.mark.parametrize(
    "value,expected", [("false", "Not supported"), ("null", "Unknown"), ("", "Unknown")]
)
def test_support_status_and_version_spelling(value, expected):
    content = chunks(f"""---
name: Example
works_on_arm: {value}
supported_minimum_version:
  version_number: 3.10
optional_info:
  support_caveats: Requires [extra libraries](./requirements.md).
  alternative_options: Another package
---
""")[0]["content"]
    assert f"Arm Linux support: {expected}" in content
    assert "Minimum supported version: 3.10" in content
    assert "Alternatives: Another package" in content
    assert (
        "https://raw.githubusercontent.com/example/repo/123/content/requirements.md"
        in content
    )


@pytest.mark.parametrize(
    "metadata,reason",
    [
        ("name: [broken", "invalid YAML frontmatter"),
        ("- item", "frontmatter must be a mapping"),
        ("description: No name", "name is required"),
        (
            "name: Example\nworks_on_arm: maybe",
            "works_on_arm must be true, false, or empty",
        ),
        ("name: Example\noptional_info: []", "expected a mapping"),
    ],
)
def test_invalid_metadata_reports_source_and_reason(metadata, reason):
    with pytest.raises(ValueError) as error:
        chunks(f"---\n{metadata}\n---\n")
    assert RESOLVED in str(error.value)
    assert reason in str(error.value)


@pytest.mark.parametrize(
    "platform,label", [("linux", "Linux"), ("windows", "Windows on Arm")]
)
def test_long_content_keeps_identity_and_body_links_without_fake_dashboard_anchors(
    platform, label
):
    result = chunks(
        "---\nname: Example\ndescription: "
        + "Useful database capability. " * 120
        + "\n---\n## Setup {#setup}\nRead [guide](./guide.md).",
        platform=platform,
        min_tokens=30,
        max_tokens=80,
        overlap_tokens=10,
    )
    assert len(result) > 2
    assert all(
        c["url"] == SOURCE and "Example" in c["content"] and label in c["content"]
        for c in result
    )
    assert any(
        "https://raw.githubusercontent.com/example/repo/123/content/guide.md"
        in c["content"]
        for c in result
    )


def test_windows_fixture_preserves_platform_and_package_guidance():
    source_url = (
        "https://developer.arm.com/ecosystem-dashboard/windows?package=dotnet-cli"
    )
    resolved_url = "https://raw.githubusercontent.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/f7341f1e34cc51e3822b16dd7659a6ee2dfd3ea0/content/windows/all_packages/dotnet-CLI.md"
    document = parse_ecosystem_package(
        (FIXTURES / "dotnet-CLI.md").read_text(),
        platform="windows",
        source_url=source_url,
        resolved_url=resolved_url,
    )
    result = chunk_parsed_document(document, "Ecosystem Dashboard", ["dotnet CLI"])
    content = "\n".join(c["content"] for c in result)
    assert (
        "Command-line interface for building and managing .NET applications." in content
    )
    assert "Category: Miscellaneous" in content
    assert "Windows on Arm support: Supported" in content
    assert "Minimum supported version: 5.0.100" in content
    assert "https://learn.microsoft.com/dotnet/core/tools/" in content
    assert "Linux" not in content
    assert "Arm-recommended minimum version:" not in content
    for chunk in result:
        assert chunk["url"] == source_url
        assert chunk["resolved_url"] == resolved_url
        assert chunk["heading_path"] == ["Windows on Arm", "dotnet CLI"]
        assert chunk["doc_type"] == "Ecosystem Dashboard"


def test_unknown_platform_is_rejected_instead_of_mislabeled():
    with pytest.raises(ValueError, match="platform must be linux or windows"):
        chunks("---\nname: Example\n---\n", platform="macos")


def test_frontmatter_split_and_generic_metadata_inference_remain_independent():
    markdown = "\ufeff---\r\nname: Hidden\r\n---\r\n# Guide v2.0\r\nUseful guidance."
    frontmatter, body = split_frontmatter(markdown)
    assert frontmatter == "name: Hidden"
    assert body.startswith("# Guide")
    parsed = parse_markdown(
        markdown,
        "https://developer.arm.com/guide",
        "https://developer.arm.com/guide",
        "Guide",
    )
    result = chunk_parsed_document(parsed, "Guide", [])
    assert result[0]["product"] == "Arm"
    assert result[0]["version"] == "v2.0"
    assert "Hidden" not in result[0]["content"]
    assert split_frontmatter("---\nnot closed")[0] is None
    parsed.product = "Explicit product"
    parsed.version = ""
    overridden = chunk_parsed_document(parsed, "Guide", [])[0]
    assert overridden["product"] == "Explicit product"
    assert overridden["version"] == ""
