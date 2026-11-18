"""Source-level platform overrides must survive discovery and CSV round trips."""

import csv
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

FIELDS = [
    "Site Name",
    "License Type",
    "Display Name",
    "URL",
    "Keywords",
    "Transcript Source URL",
]
SOURCE = "https://example.com/guide"
SOURCES_FILE = Path(__file__).resolve().parents[1] / "vector-db-sources.csv"


def source_rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


SOURCE_TYPES = sorted({row["Site Name"] for row in source_rows(SOURCES_FILE)})


def platform_values(config):
    return [row.get("platform") for row in config["metadata_overrides"]]


def write_sources(tmp_path, cells, *, platform_column=True, site="Learning Paths"):
    path = tmp_path / "sources.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(FIELDS + (["Platform"] if platform_column else []))
        for index, cell in enumerate(cells):
            row = [
                site,
                "CC4.0",
                "Example, guide",
                SOURCE + str(index),
                "one; two",
                "https://example.com/transcript",
            ]
            writer.writerow(row + ([cell] if platform_column else []))
    return path


@pytest.mark.parametrize(
    "cell,expected",
    [
        (" Linux ", ["linux"]),
        (" CME ", ["cme"]),
        (" Mali ", ["mali"]),
        (" Google-Colab ", ["google-colab"]),
        (" Cortex-M ", ["cortex-m"]),
        ('["Cortex-M", "Windows", "cortex-m"]', ["cortex-m", "windows"]),
        ('["google-colab", "Linux", "GOOGLE-COLAB"]', ["google-colab", "linux"]),
        ('["Android", "MALI", "mali"]', ["android", "mali"]),
        ('["Neon", "SVE", "sve2", "SME", "SME2", "Helium"]',
         ["neon", "sve", "sve2", "sme", "sme2", "helium"]),
        ('["linux", "SVE", "sve"]', ["linux", "sve"]),
        ('["Windows", "linux", "WINDOWS", "macOS"]', ["windows", "linux", "macos"]),
        (
            '["Android", "Bare metal", "bare-metal", "RTOS", "ChromeOS", "FreeBSD"]',
            ["android", "baremetal", "rtos", "chromeos", "freebsd"],
        ),
        ("", None),
        ("   ", None),
        ("[]", []),
    ],
)
def test_platform_override_survives_discovery_and_csv_roundtrip(
    gc, tmp_path, cell, expected
):
    path = write_sources(tmp_path, [cell])
    config, count = gc.readInCSV(path)
    assert count == 1
    assert platform_values(config) == [expected]
    gc.load_existing_sources(path)
    gc.register_source(
        "Learning Paths", "CC4.0", "Discovered", "https://example.com/new", "new"
    )
    # Rediscovery must not replace a contributor's override, including [].
    assert not gc.register_source(
        "Learning Paths", "CC4.0", "Changed", SOURCE + "0", "changed"
    )
    gc.save_sources_csv(path)
    config, count = gc.readInCSV(path)
    assert count == 2
    assert platform_values(config) == [expected, None]
    assert config["transcript_urls"] == ["https://example.com/transcript", ""]
    assert config["source_names"] == ["Example, guide", "Discovered"]
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert "Platform" in rows[0]
    assert rows[1]["Platform"] == ""
    if expected == []:
        assert rows[0]["Platform"] == "[]"
    elif expected is None:
        assert rows[0]["Platform"] == ""


def test_legacy_csv_has_no_platform_override_or_added_column(gc, tmp_path):
    path = write_sources(tmp_path, [None], platform_column=False)
    assert platform_values(gc.readInCSV(path)[0]) == [None]
    gc.load_existing_sources(path)
    gc.save_sources_csv(path)
    with path.open(newline="", encoding="utf-8") as stream:
        assert next(csv.reader(stream)) == FIELDS


@pytest.mark.parametrize(
    "cell",
    [
        '["linux",',
        '["linux", null]',
        '["linux", 4]',
        '["linux", ["windows"]]',
        '["linux", ""]',
        '["linux", "  "]',
        '{"platform":"linux"}',
        "null",
        "true",
        "42",
        "unknown",
        "other",
        "all",
        "linux,windows",
        "linxu",
    ],
)
@pytest.mark.parametrize("reader", ["readInCSV", "load_existing_sources"])
def test_invalid_platform_override_rejected_with_source_context(
    gc, tmp_path, cell, reader
):
    path = write_sources(tmp_path, [cell])
    original = path.read_bytes()
    with pytest.raises(ValueError, match="Platform") as error:
        getattr(gc, reader)(path)
    assert SOURCE + "0" in str(error.value)
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "cell,expected",
    [("[]", []), ('["linux", "windows"]', ["linux", "windows"]), ("", None)],
)
@pytest.mark.parametrize("discover", [False, True])
def test_dashboard_reconciliation_keeps_platform_override(
    gc, monkeypatch, tmp_path, cell, expected, discover
):
    path = write_sources(tmp_path, [cell], site="Ecosystem Dashboard")
    gc.load_existing_sources(path)
    package = SimpleNamespace(
        keywords=["package"], document=SimpleNamespace(display_title="Package")
    )
    monkeypatch.setattr(
        gc, "build_ecosystem_dashboard_entries", lambda: {SOURCE + "0": [package]}
    )
    gc.reconcile_ecosystem_sources(discover=discover)
    gc.save_sources_csv(path)
    assert platform_values(gc.readInCSV(path)[0]) == [expected]


def test_conflicting_dashboard_overrides_are_not_silently_combined(
    gc, monkeypatch, tmp_path
):
    path = write_sources(tmp_path, ["linux", "windows"], site="Ecosystem Dashboard")
    text = path.read_text().replace(SOURCE + "1", SOURCE + "0")
    path.write_text(text)
    gc.load_existing_sources(path)
    package = SimpleNamespace(
        keywords=[], document=SimpleNamespace(display_title="Package")
    )
    monkeypatch.setattr(
        gc, "build_ecosystem_dashboard_entries", lambda: {SOURCE + "0": [package]}
    )
    with pytest.raises(ValueError, match="Platform") as error:
        gc.reconcile_ecosystem_sources()
    assert SOURCE + "0" in str(error.value)
    assert path.read_text() == text


def test_header_only_csv_keeps_platform_column(gc, tmp_path):
    path = write_sources(tmp_path, [])
    gc.load_existing_sources(path)
    gc.save_sources_csv(path)
    with path.open(newline="", encoding="utf-8") as stream:
        assert next(csv.reader(stream)) == FIELDS + ["Platform"]


@pytest.mark.parametrize(
    "cells,expected",
    [
        (["", "[]"], []),
        (['["linux", "windows"]', '["Windows", "Linux"]'], ["linux", "windows"]),
    ],
)
def test_dashboard_duplicate_equivalent_overrides_keep_one_assignment(
    gc, monkeypatch, tmp_path, cells, expected
):
    path = write_sources(tmp_path, cells, site="Ecosystem Dashboard")
    path.write_text(path.read_text().replace(SOURCE + "1", SOURCE + "0"))
    gc.load_existing_sources(path)
    package = SimpleNamespace(
        keywords=[], document=SimpleNamespace(display_title="Package")
    )
    monkeypatch.setattr(
        gc, "build_ecosystem_dashboard_entries", lambda: {SOURCE + "0": [package]}
    )
    gc.reconcile_ecosystem_sources()
    gc.save_sources_csv(path)
    assert platform_values(gc.readInCSV(path)[0]) == [expected]


@pytest.mark.parametrize("reader", ["readInCSV", "load_existing_sources"])
def test_unquoted_platform_alternatives_do_not_silently_drop_a_value(
    gc, tmp_path, reader
):
    path = write_sources(tmp_path, ["linux"])
    path.write_text(path.read_text().rstrip() + ",windows\n")
    with pytest.raises(ValueError, match="Platform") as error:
        getattr(gc, reader)(path)
    assert SOURCE + "0" in str(error.value)


@pytest.mark.parametrize("site", SOURCE_TYPES)
def test_each_source_type_keeps_tags_and_original_columns(gc, tmp_path, site):
    path = write_sources(
        tmp_path, ["", "linux", '["linux","windows","macos","sme2","cme","mali","google-colab","cortex-m"]', "[]"], site=site
    )
    before = source_rows(path)
    gc.load_existing_sources(path)
    gc.register_source(site, "CC4.0", "New, source", SOURCE + "/new", "new")
    gc.save_sources_csv(path)

    after = source_rows(path)
    assert after[:-1] == before
    assert after[-1]["Platform"] == ""
    config, count = gc.readInCSV(path)
    assert count == 5
    assert platform_values(config) == [
        None,
        ["linux"],
        ["linux", "windows", "macos", "sme2", "cme", "mali", "google-colab", "cortex-m"],
        [],
        None,
    ]
    assert config["site_names"] == [site] * 5


def test_actual_source_csv_preserves_all_rows_and_legacy_inputs(gc, tmp_path):
    path = tmp_path / "sources.csv"
    path.write_bytes(SOURCES_FILE.read_bytes())
    rows = source_rows(path)
    legacy = tmp_path / "legacy.csv"
    with legacy.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    expected_config, expected_count = gc.readInCSV(legacy)
    expected_config.pop("metadata_overrides")
    gc.load_existing_sources(path)
    gc.save_sources_csv(path)
    assert source_rows(path) == rows
    config, count = gc.readInCSV(path)
    overrides = platform_values(config)
    config.pop("metadata_overrides")
    assert count == expected_count == len(rows)
    assert config == expected_config
    assert overrides == [
        json.loads(row["Platform"])
        if row["Platform"].startswith("[")
        else [row["Platform"]]
        if row["Platform"]
        else None
        for row in rows
    ]


def test_developer_discovery_preserves_real_csv_tags(gc, tmp_path, monkeypatch):
    # Browser acquisition is outside this test; exercise the real CSV writer
    # with controlled search results, including a rediscovered tagged source.
    playwright = ModuleType("playwright.async_api")

    def unexpected_browser_call():
        pytest.fail("CSV discovery test must not launch a browser")

    playwright.async_playwright = unexpected_browser_call
    monkeypatch.setitem(sys.modules, "playwright.async_api", playwright)
    script = SOURCES_FILE.with_name("discover-developer-arm-com-sources.py")
    spec = importlib.util.spec_from_file_location("developer_discovery", script)
    discovery = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, discovery)
    spec.loader.exec_module(discovery)

    path = tmp_path / "sources.csv"
    path.write_bytes(SOURCES_FILE.read_bytes())
    original = source_rows(path)
    tagged = next(row for row in original if row["Platform"].startswith("["))
    # Populate future tags only in this temporary copy to verify discovery
    # preserves all three fields, including an explicit empty publisher.
    tagged.update(
        {
            "Doc Type": '["learning","guide"]',
            "Product": "[]",
        }
    )
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(original[0]))
        writer.writeheader()
        writer.writerows(original)
    tagged_url = tagged["URL"]
    new_url = "https://developer.arm.com/documentation/test-platform-csv"
    items = [
        {
            "url": url,
            "title": "Overview of SME",
            "type": "Guide",
            "keywords": ["one|two"],
            "products": [],
        }
        for url in [tagged_url, new_url, new_url]
    ]
    monkeypatch.setattr(discovery, "search_developer_arm_com", lambda *_: items)
    monkeypatch.setattr(sys, "argv", [str(script), str(path)])
    discovery.main()
    after = source_rows(path)
    assert after[:-1] == original
    assert after[-1]["URL"] == new_url
    assert after[-1]["Platform"] == ""
    assert after[-1]["Transcript Source URL"] == ""
    assert None not in after[-1]
    gc.load_existing_sources(path)
    gc.save_sources_csv(path)
    assert source_rows(path) == after
    discovery.main()
    assert source_rows(path) == after
