"""Contributor metadata must survive every source configuration writer."""

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

LEGACY_COLUMNS = [
    "Site Name",
    "License Type",
    "Display Name",
    "URL",
    "Keywords",
    "Transcript Source URL",
]
TAG_COLUMNS = ["Doc Type", "Product", "Platform"]
URL = "https://example.com/guide"
with (Path(__file__).resolve().parents[1] / "vector-db-sources.csv").open(
    newline="", encoding="utf-8"
) as sources:
    SOURCE_TYPES = sorted({row["Site Name"] for row in csv.DictReader(sources)})


def write_source(tmp_path, tags, *, site="Learning Paths"):
    path = tmp_path / "sources.csv"
    row = dict(
        zip(
            LEGACY_COLUMNS,
            [
                site,
                "CC4.0",
                "Guide, with examples",
                URL,
                "arm; linux",
                "https://example.com/transcript",
            ],
        )
    )
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=LEGACY_COLUMNS + list(tags))
        writer.writeheader()
        writer.writerow(row | tags)
    return path


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


@pytest.mark.parametrize("column,cell", [
    ("Product", "amr"), ("platform", "linux"), ("Platforms", "linux"),
    ("Doc Types", "learning"), ("product", "arm"),
])
@pytest.mark.parametrize("reader", ["readInCSV", "load_existing_sources"])
def test_mistyped_metadata_fails_before_csv_rewrite(gc, tmp_path, column, cell, reader):
    path = write_source(tmp_path, {column: cell})
    before = path.read_bytes()
    with pytest.raises(ValueError, match=column):
        getattr(gc, reader)(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("overrides", [
    {"edition": ["commercial"]}, {"platform": "linux"}, {"product": ["amr"]},
])
def test_chunk_entry_point_validates_tags_before_fetch(gc, monkeypatch, overrides):
    monkeypatch.setattr(gc, "_create_source_chunks", lambda *args: pytest.fail("Fetched invalid source"))
    with pytest.raises(ValueError):
        gc.create_chunks_for_source(URL, "Guide", "Install Guides", "", metadata_overrides=overrides)


@pytest.mark.parametrize("column,cell", [
    ("Doc Type", cell) for cell in ["tutorial", "learning paths", "bogus", '["guide","bogus"]']
] + [("Edition", "commercial"), ("Edition", "")])
@pytest.mark.parametrize("reader", ["readInCSV", "load_existing_sources"])
def test_unsupported_tag_fields_and_types_fail_before_ingestion(gc, tmp_path, column, cell, reader):
    path = write_source(tmp_path, {column: cell})
    before = path.read_bytes()
    with pytest.raises(ValueError, match=column) as error:
        getattr(gc, reader)(path)
    assert (str(path) if column == "Edition" else URL) in str(error.value)
    assert path.read_bytes() == before


@pytest.mark.parametrize("site", SOURCE_TYPES)
def test_all_filter_tags_roundtrip_without_changing_source_routing(gc, tmp_path, site):
    path = write_source(
        tmp_path,
        {
            "Doc Type": '[" Learning ","Guide","LEARNING"]',
            "Product": '["AWS","Arm"]',
            "Platform": '["Linux","Windows"]',
        },
        site=site,
    )
    expected = {
        "doc_type": ["learning", "guide"],
        "product": ["aws", "arm"],
        "platform": ["linux", "windows"],
    }
    config, count = gc.readInCSV(path)
    assert count == 1
    assert config.get("metadata_overrides") == [expected]
    assert config["site_names"] == [site]
    gc.load_existing_sources(path)
    assert not gc.register_source(site, "CC4.0", "Changed", URL, "new")
    gc.register_source("Arm Developer", "Arm Proprietary", "New", URL + "/new", "arm")
    gc.save_sources_csv(path)
    assert gc.readInCSV(path)[0]["metadata_overrides"] == [
        expected,
        {
            "doc_type": None,
            "product": None,
            "platform": None,
        },
    ]
    header, rows = read_rows(path)
    assert header == LEGACY_COLUMNS + TAG_COLUMNS
    assert rows[0]["License Type"] == "CC4.0"
    assert rows[0]["Transcript Source URL"] == "https://example.com/transcript"
    assert rows[1]["Platform"] == ""


@pytest.mark.parametrize(
    "column,field",
    [
        ("Doc Type", "doc_type"),
        ("Product", "product"),
        ("Platform", "platform"),
    ],
)
@pytest.mark.parametrize("cell,expected", [("", None), ("[]", [])])
def test_blank_and_explicit_clear_survive_for_every_field(
    gc, tmp_path, column, field, cell, expected
):
    path = write_source(tmp_path, {column: cell})
    gc.load_existing_sources(path)
    gc.save_sources_csv(path)
    assert gc.readInCSV(path)[0].get("metadata_overrides") == [{field: expected}]
    header, rows = read_rows(path)
    assert header == LEGACY_COLUMNS + [column]
    assert rows[0][column] == cell


@pytest.mark.parametrize("column", TAG_COLUMNS)
@pytest.mark.parametrize(
    "cell",
    [
        '["valid",',
        '["valid",null]',
        '["valid",4]',
        '["valid",[]]',
        '["valid",""]',
        '{"tag":"valid"}',
        '"valid"',
        "null",
        "true",
        "42",
        "unknown",
        "other",
        "all",
        "n/a",
        "none",
        "not applicable",
        "linux,windows",
    ],
)
@pytest.mark.parametrize("reader", ["readInCSV", "load_existing_sources"])
def test_invalid_tag_cells_fail_with_field_and_url(gc, tmp_path, column, cell, reader):
    path = write_source(tmp_path, {column: cell})
    before = path.read_bytes()
    with pytest.raises(ValueError) as error:
        getattr(gc, reader)(path)
    assert column in str(error.value)
    assert URL in str(error.value)
    assert path.read_bytes() == before


@pytest.mark.parametrize("discover", [False, True])
def test_dashboard_reconciliation_preserves_all_overrides(
    gc, tmp_path, monkeypatch, discover
):
    path = write_source(
        tmp_path,
        {
            "Doc Type": "Compatibility",
            "Product": "Arm",
            "Platform": '["linux","windows"]',
        },
        site="Ecosystem Dashboard",
    )
    package = SimpleNamespace(
        keywords=["jenkins"], document=SimpleNamespace(display_title="Jenkins")
    )
    monkeypatch.setattr(
        gc, "build_ecosystem_dashboard_entries", lambda: {URL: [package]}
    )
    gc.load_existing_sources(path)
    gc.reconcile_ecosystem_sources(discover=discover)
    gc.save_sources_csv(path)
    assert gc.readInCSV(path)[0].get("metadata_overrides") == [
        {
            "doc_type": ["compatibility"],
            "product": ["arm"],
            "platform": ["linux", "windows"],
        }
    ]


@pytest.mark.parametrize("column", TAG_COLUMNS)
def test_duplicate_dashboard_sources_reject_conflicts_in_any_field(
    gc, tmp_path, column
):
    first, second = {"Doc Type": ("guide", "reference"), "Product": ("arm", "aws"), "Platform": ("linux", "windows")}[column]
    path = write_source(tmp_path, {column: first}, site="Ecosystem Dashboard")
    header, rows = read_rows(path)
    with path.open("a", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=header).writerow(
            rows[0] | {column: second}
        )
    before = path.read_bytes()
    gc.load_existing_sources(path)
    # Catalog loading is not needed to detect an override conflict, but this
    # boundary prevents the reconciliation test from accessing the network.
    gc.ecosystem_dashboard_entries = {}
    with pytest.raises(ValueError) as error:
        gc.reconcile_ecosystem_sources()
    assert column in str(error.value)
    assert URL in str(error.value)
    assert path.read_bytes() == before


@pytest.mark.parametrize("cell", ['["Example, Product"]', '["42"]', '["[Example]"]'])
def test_unsupported_publishers_are_rejected_even_in_json(gc, tmp_path, cell):
    path = write_source(tmp_path, {"Product": cell})
    with pytest.raises(ValueError, match="unsupported publisher"):
        gc.load_existing_sources(path)


@pytest.mark.parametrize("retired_column", [False, True])
def test_header_only_file_keeps_all_tag_columns_in_original_order(
    gc, tmp_path, retired_column
):
    path = tmp_path / "sources.csv"
    header = LEGACY_COLUMNS + ["Platform", "Product", "Doc Type"]
    if retired_column:
        header.append("Edition")
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(header)
    if retired_column:
        for reader in (gc.load_existing_sources, gc.readInCSV):
            with pytest.raises(ValueError, match="remove the Edition CSV column"):
                reader(path)
        assert read_rows(path) == (header, [])
        return
    gc.load_existing_sources(path)
    gc.save_sources_csv(path)
    assert read_rows(path) == (header, [])
