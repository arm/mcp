"""Offline acquisition and integration tests using real adapter/chunker output."""

import csv
import io
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from ecosystem_dashboard import (
    DASHBOARD_URL,
    REPOSITORY,
    acquire_catalog,
    package_slug,
    parse_catalog,
)

REVISION = "a" * 40
FIXTURES = Path(__file__).parent / "fixtures/ecosystem_dashboard"
LINUX = "content/linux/opensource_packages/dot-net.md"
WINDOWS = "content/windows/all_packages/dotnet-CLI.md"


def archive(files=None):
    files = files or {
        LINUX: (FIXTURES / "dot-net.md").read_text(),
        WINDOWS: (FIXTURES / "dotnet-CLI.md").read_text(),
    }
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        for path, content in files.items():
            encoded = content.encode()
            entry = tarfile.TarInfo(f"snapshot/{path}")
            entry.size = len(encoded)
            tar.addfile(entry, io.BytesIO(encoded))
    return output.getvalue()


@pytest.mark.parametrize(
    "name,slug",
    [
        (".NET", ".net"),
        ("5G RAL (RAN Acceleration library)", "5g-ral-ran-acceleration-library"),
        ("Authzed/SpiceDB", "authzed__spicedb"),
        ("Wazuh (Agent & Manager)", "wazuh-agent-and-manager"),
        ("Xerces-C++", "xerces-c++"),
        ("  Example - Name  ", "example-name"),
        ("Café", "caf%C3%A9"),
    ],
)
def test_dashboard_slug_matches_hugo_examples(name, slug):
    assert package_slug(name) == slug


@pytest.mark.parametrize(
    "name,encoded_slug",
    [("Café", "caf%C3%A9"), ("Xerces-C++", "xerces-c%2B%2B")],
)
def test_catalog_package_urls_encode_once(name, encoded_slug):
    package = f"---\nname: {name}\n---\n"
    catalog = parse_catalog(archive({LINUX: package, WINDOWS: package}), REVISION)

    assert set(catalog) == {
        f"{DASHBOARD_URL}/{platform}?package={encoded_slug}"
        for platform in ("linux", "windows")
    }


@pytest.mark.parametrize("sentinel", ["null", "~", "NULL", '" Null "'])
def test_catalog_keywords_exclude_null_metadata(sentinel):
    package = (
        f"---\nname: Example\ncategory: {sentinel}\nvendor: {sentinel}\n---\n"
    )
    catalog = parse_catalog(archive({LINUX: package, WINDOWS: package}), REVISION)

    assert catalog[f"{DASHBOARD_URL}/linux?package=example"][0].keywords == [
        "Example", "linux", "open-source"
    ]
    assert catalog[f"{DASHBOARD_URL}/windows?package=example"][0].keywords == [
        "Example", "windows"
    ]


def test_commit_resolved_once_and_all_sources_share_revision():
    session = Mock()
    session.get.side_effect = [
        Mock(json=lambda: {"sha": REVISION}),
        Mock(content=archive()),
    ]
    catalog = acquire_catalog(session)
    assert session.get.call_count == 2
    assert session.get.call_args_list[1].args[0].endswith(f"/tar.gz/{REVISION}")
    assert len(catalog) == 2
    for packages in catalog.values():
        assert f"/{REVISION}/content/" in packages[0].document.resolved_url
        assert packages[0].document.product == ""
        assert packages[0].document.version == ""


def test_explicit_revision_and_fetch_failure():
    session = Mock()
    session.get.return_value.content = archive()
    acquire_catalog(session, REVISION)
    assert session.get.call_count == 1
    assert (
        session.get.call_args.args[0]
        == f"https://codeload.github.com/{REPOSITORY}/tar.gz/{REVISION}"
    )
    session.get.return_value.raise_for_status.side_effect = requests.HTTPError(
        "unavailable"
    )
    with pytest.raises(requests.HTTPError):
        acquire_catalog(session, REVISION)
    with pytest.raises(ValueError, match="full Git commit SHA"):
        acquire_catalog(session, "main")


def test_catalog_retains_platform_and_same_url_editions():
    package = (
        "---\nname: Example\ndescription: Useful software\nworks_on_arm: true\n---\n"
    )
    catalog = parse_catalog(
        archive(
            {
                "content/linux/opensource_packages/example.md": package,
                "content/linux/commercial_packages/example.md": package
                + "Vendor guidance.",
                "content/windows/all_packages/example.md": package,
                "content/linux/opensource_packages/_index.md": "Not a package",
                "data/test-results/example.md": "Test output",
            }
        ),
        REVISION,
    )
    assert len(catalog) == 2
    linux = catalog[f"{DASHBOARD_URL}/linux?package=example"]
    assert len(linux) == 2
    assert len({p.document.resolved_url for p in linux}) == 2
    assert any("Commercial" in p.document.display_title for p in linux)
    assert any("Open source" in p.document.display_title for p in linux)


def test_catalog_warns_and_skips_individual_bad_records():
    files = {
        LINUX: (FIXTURES / "dot-net.md").read_text(),
        WINDOWS: (FIXTURES / "dotnet-CLI.md").read_text(),
        "content/linux/opensource_packages/bad.md": "---\nname: [bad\n---",
        "content/windows/all_packages/bad.md": "No frontmatter",
    }
    with pytest.warns(UserWarning, match="Skipped 2") as captured:
        catalog = parse_catalog(archive(files), REVISION)
    assert len(catalog) == 2
    assert "content/linux/opensource_packages/bad.md" in str(captured[0].message)
    assert "content/windows/all_packages/bad.md" in str(captured[0].message)


def test_catalog_rejects_incomplete_snapshot():
    with pytest.raises(ValueError, match="Linux and Windows"):
        parse_catalog(archive({LINUX: (FIXTURES / "dot-net.md").read_text()}), REVISION)


def test_bad_edition_does_not_discard_valid_record_with_same_url(gc):
    valid = "---\nname: Example\nworks_on_arm: true\ncategory: Databases\n---"
    invalid = "---\nname: Example\nworks_on_arm: maybe\n---"
    with pytest.warns(UserWarning, match="works_on_arm"):
        catalog = parse_catalog(
            archive(
                {
                    "content/linux/opensource_packages/example.md": valid,
                    "content/linux/commercial_packages/example.md": invalid,
                    WINDOWS: (FIXTURES / "dotnet-CLI.md").read_text(),
                }
            ),
            REVISION,
        )
    gc.ecosystem_dashboard_entries = catalog
    url = f"{DASHBOARD_URL}/linux?package=example"
    chunks = gc.create_ecosystem_dashboard_chunk(url, "custom keyword")
    assert len(chunks) == 1
    assert chunks[0].platform == "linux" and chunks[0].edition == "open-source"
    assert "custom keyword" in chunks[0].keywords


def source(url, keywords="curated", site="Ecosystem Dashboard"):
    return dict(
        site_name=site,
        license_type="Arm Proprietary",
        display_name="Original",
        url=url,
        keywords=keywords,
        transcript_source_url="",
    )


def test_discovery_reconciliation_is_idempotent_and_preserves_other_sources(
    gc, monkeypatch
):
    catalog = parse_catalog(archive(), REVISION)
    fetch = Mock(return_value=catalog)
    monkeypatch.setattr(gc, "acquire_catalog", fetch)
    other = source("https://example.com/guide", site="Documentation")
    gc.all_sources = [
        other,
        source(f"{DASHBOARD_URL}/linux?package=.net"),
        source(f"{DASHBOARD_URL}/linux?package=.net", "second keyword"),
        source(f"{DASHBOARD_URL}/linux?package=removed"),
    ]
    gc.reconcile_ecosystem_sources()
    first = list(gc.all_sources)
    gc.reconcile_ecosystem_sources()
    assert gc.all_sources == first
    assert gc.all_sources[0] == other
    assert len(gc.all_sources) == 3
    assert len(gc.known_source_urls) == 3
    dotnet = next(row for row in gc.all_sources if row["url"].endswith("package=.net"))
    assert "curated" in dotnet["keywords"] and "second keyword" in dotnet["keywords"]
    chunks = gc.create_chunks_for_source(
        dotnet["url"], dotnet["display_name"], dotnet["site_name"], dotnet["keywords"]
    )
    assert fetch.call_count == 1
    assert chunks and "cross-platform framework" in chunks[0].content
    assert chunks[0].product == chunks[0].version == ""
    assert chunks[0].content_type == "markdown"
    assert chunks[0].resolved_url.endswith(LINUX)


def test_skip_discovery_retains_selected_sources_and_reports_missing(gc, capsys):
    gc.ecosystem_dashboard_entries = parse_catalog(archive(), REVISION)
    gc.all_sources = [source(f"{DASHBOARD_URL}/linux?package=.net")]
    gc.reconcile_ecosystem_sources(discover=False)
    assert len(gc.all_sources) == 1
    assert gc.all_sources[0]["url"] == f"{DASHBOARD_URL}/linux?package=.net"
    gc.all_sources.append(source(f"{DASHBOARD_URL}/linux?package=missing"))
    gc.reconcile_ecosystem_sources(discover=False)
    assert len(gc.all_sources) == 1
    assert "[ECOSYSTEM OMITTED SOURCE]" in capsys.readouterr().out


def test_main_writes_dashboard_csv_and_yaml_without_html(gc, tmp_path, monkeypatch):
    import sys

    monkeypatch.setenv("SKIP_DISCOVERY", "1")
    monkeypatch.setattr(
        gc, "acquire_catalog", lambda *args: parse_catalog(archive(), REVISION)
    )
    sources = tmp_path / "sources.csv"
    gc.all_sources = [source(f"{DASHBOARD_URL}/linux?package=.net")]
    gc.save_sources_csv(sources)
    monkeypatch.setattr(gc, "yaml_dir", str(tmp_path / "chunks"))
    monkeypatch.setattr(gc, "details_file", str(tmp_path / "details.csv"))
    monkeypatch.setattr(sys, "argv", ["generate-chunks.py", str(sources)])
    gc.main()
    with sources.open() as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 1 and rows[0]["URL"] == f"{DASHBOARD_URL}/linux?package=.net"
    import yaml

    chunks = [
        yaml.safe_load(path.read_text())
        for path in (tmp_path / "chunks").glob("*.yaml")
    ]
    assert chunks and all(c["doc_type"] == "Ecosystem Dashboard" for c in chunks)
    assert all(c["product"] == c["version"] == "" for c in chunks)
    assert all(
        c["platform"] == "linux" and c["edition"] == "open-source" for c in chunks
    )
    assert all(f"/{REVISION}/" in c["resolved_url"] for c in chunks)


def test_validation_failure_keeps_previous_snapshot_and_csv(gc, tmp_path, monkeypatch):
    import sys

    sources = tmp_path / "sources.csv"
    gc.all_sources = [source(f"{DASHBOARD_URL}/linux?package=.net")]
    gc.save_sources_csv(sources)
    previous_csv = sources.read_bytes()
    chunks = tmp_path / "chunks"
    chunks.mkdir()
    previous = chunks / "chunk_previous.yaml"
    previous.write_text("previous snapshot")
    monkeypatch.setenv("SKIP_DISCOVERY", "1")
    monkeypatch.setattr(gc, "yaml_dir", str(chunks))
    monkeypatch.setattr(
        gc, "acquire_catalog", Mock(side_effect=ValueError("bad upstream"))
    )
    monkeypatch.setattr(sys, "argv", ["generate-chunks.py", str(sources)])
    with pytest.raises(ValueError, match="bad upstream"):
        gc.main()
    assert sources.read_bytes() == previous_csv
    assert previous.read_text() == "previous snapshot"


@pytest.mark.parametrize(
    "field", ["getting_started_resources", "arm_recommended_minimum_version"]
)
def test_misplaced_guidance_is_reported_instead_of_omitted(field):
    from ecosystem_dashboard import parse_ecosystem_package

    with pytest.raises(ValueError, match="nested under optional_info"):
        parse_ecosystem_package(
            f"---\nname: Example\n{field}: {{}}\n---",
            platform="windows",
            source_url="url",
            resolved_url="source",
        )
