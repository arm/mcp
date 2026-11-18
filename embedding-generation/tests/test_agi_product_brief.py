"""Exercise real PDF extraction with synthetic, independently authored pages."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from agi_product_brief import BRIEF_PATH
from document_chunking import chunk_parsed_document, parse_document_content

URL = "https://www.arm.com" + BRIEF_PATH
VARIANTS = ["Arm AGI CPU 136C", "Arm AGI CPU 128C", "Arm AGI CPU 64C"]
SKUS = ["SP113012", "SP113012S", "SP113012A"]


def brief_pdf(*, order=(0, 1, 2), damage=None, frequency="3.5GHz"):
    """Build a PDF with genuine columns and vertically centered row labels."""
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )

    def page(items):
        pdf_page = writer.add_blank_page(width=700, height=1000)
        pdf_page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        commands = []
        for x, y, text in items:
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"BT /F1 8 Tf 1 0 0 1 {x} {y} Tm ({escaped}) Tj ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("ascii"))
        pdf_page[NameObject("/Contents")] = writer._add_object(stream)

    page(
        [
            (20, 950, "PRODUCT BRIEF"),
            (20, 930, "Arm AGI CPU"),
            (220, 900, "INTRODUCTION"),
            (220, 880, "A processor for AI infrastructure."),
            (20, 800, "KEY FEATURES"),
            (20, 790, "AND BENEFITS"),
            (20, 770, "More than 2x performance per rack.1"),
            (220, 40, "1 Based on estimates."),
            (650, 20, "1"),
        ]
    )
    page(
        [
            (20, 950, "HIGHLIGHTS"),
            (20, 920, "High-performance CPU"),
            (20, 900, "Supports Armv9.2 and SVE2."),
            (20, 860, "High-memory bandwidth"),
            (20, 840, "Supports AI data throughput."),
            (20, 800, "Advanced I/O and accelerator connectivity"),
            (20, 780, "Connects accelerators."),
            (20, 740, "Enterprise security architecture"),
            (20, 720, "Includes runtime protection."),
            (20, 20, "PRODUCT BRIEF"),
            (650, 20, "2"),
        ]
    )
    rows = [
        ("SKU", SKUS),
        (
            "Processing Cores",
            [
                f"{cores} Neoverse V3\n2x 128 SVE\n2MB/core L2"
                for cores in (136, 128, 64)
            ],
        ),
        ("CPU Architecture", ["Armv9.2\nbfloat16 and\nINT8 AI instructions"] * 3),
        ("System-Level Cache", ["128MB"] * 3),
        ("Max Frequency", [frequency, "3.5GHz", "3.7GHz"]),
        ("Base TDP*", ["300W"] * 3),
        ("RDIMM Memory", ["12x DDR5 up to\n8800MT/s"] * 3),
        (
            "Memory Throughput/core",
            ["6GB/s per core", "6.3GB/s per core", "13GB/s per core"],
        ),
        ("PCIe/IO", ["96x lanes PCIe Gen6\nCXL 3.0 Type 3"] * 3),
        ("PCIe Control Lanes", ["6x 1 Gen4"] * 3),
        ("2-Socket Support", ["Yes"] * 3),
        ("2 DIMMS per channel", ["Yes"] * 3),
    ]
    table = [
        (20, 950, "BETTER RACK-LEVEL PERFORMANCE AND EFFICIENCY FOR AI DATA CENTERS"),
        (20, 930, "Efficient compute at rack scale."),
        (20, 850, "Specs"),
    ]
    purposes = ["(max core count)", "(TCO optimized)", "(max mem/core)"]
    for column, variant in enumerate(order):
        table.extend(
            [
                (210 + column * 155, 855, VARIANTS[variant]),
                (210 + column * 155, 845, purposes[variant]),
            ]
        )
    for row, (label, values) in enumerate(rows):
        if damage == "missing row" and label == "Max Frequency":
            continue
        y = 800 - row * 40
        table.append((20, y, label))
        for column, variant in enumerate(order):
            if damage == "missing cell" and label == "Max Frequency" and variant == 1:
                continue
            lines = values[variant].splitlines()
            for line, value in enumerate(lines):
                table.append(
                    (210 + column * 155, y + (len(lines) - 1) * 5 - line * 10, value)
                )
    if damage != "missing qualification":
        table.append(
            (
                20,
                300,
                "*Represents a preset TDP value within the configurable TDP range",
            )
        )
    table.extend([(20, 20, "PRODUCT BRIEF"), (650, 20, "3")])
    page(table)
    if damage != "missing page":
        page(
            [
                (20, 950, "ACCELERATING DEPLOYMENT WITH REFERENCE PLATFORMS"),
                (20, 930, "An OCP-compliant reference platform for deployment."),
                (20, 900, "1U2N dual node reference server."),
                (20, 880, "2U2P reference server."),
                (20, 20, "PRODUCT BRIEF"),
                (650, 20, "4"),
            ]
        )
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 0, 1)])
def test_pipeline_keeps_each_skus_specifications_and_qualifications(
    gc, monkeypatch, order
):
    monkeypatch.setattr(
        gc,
        "fetch_with_logging",
        lambda _: SimpleNamespace(
            content=brief_pdf(order=order, frequency="3.6GHz"),
            url=URL,
            headers={"content-type": "application/pdf"},
        ),
    )
    chunks = gc.create_chunks_for_source(
        URL, "Arm AGI CPU Product Brief", "Arm Documentation", "Arm AGI CPU; SVE2"
    )
    assert len(chunks) == 11
    specs = [c for c in chunks if c.heading_path[0] == "Specifications"]
    assert len(specs) == 3
    for index, (sku, frequency, bandwidth) in enumerate(
        zip(SKUS, ["3.6GHz", "3.5GHz", "3.7GHz"], ["6GB/s", "6.3GB/s", "13GB/s"])
    ):
        chunk = next(c for c in specs if c.heading == f"SKU {sku}")
        assert VARIANTS[index] in chunk.content
        assert f"Max Frequency: {frequency}" in chunk.content
        assert f"Memory Throughput/core: {bandwidth} per core" in chunk.content
        assert (
            "CPU Architecture: Armv9.2 bfloat16 and INT8 AI instructions"
            in chunk.content
        )
        assert "RDIMM Memory: 12x DDR5 up to 8800MT/s" in chunk.content
        assert "PCIe/IO: 96x lanes PCIe Gen6 CXL 3.0 Type 3" in chunk.content
        assert (
            "*Represents a preset TDP value within the configurable TDP range"
            in chunk.content
        )
        assert chunk.url == URL + "#page=3"
        assert chunk.resolved_url == URL
        assert chunk.keywords == "arm agi cpu, sve2, arm agi cpu product brief"
        assert chunk.content.count("SKU:") == 1
    benefits = next(c for c in chunks if c.heading == "Key features and benefits")
    assert (
        "2x performance" in benefits.content
        and "1 Based on estimates." in benefits.content
    )
    assert benefits.url.endswith("#page=1")
    highlights = [c for c in chunks if c.heading_path[0] == "Highlights"]
    assert len(highlights) == 4 and all(c.url.endswith("#page=2") for c in highlights)
    assert next(c for c in chunks if c.heading == "Reference platforms").url.endswith(
        "#page=4"
    )
    assert all("PRODUCT BRIEF" not in c.content for c in chunks)


@pytest.mark.parametrize(
    "damage", ["missing cell", "missing row", "missing qualification", "missing page"]
)
def test_incomplete_brief_is_rejected_instead_of_emitting_partial_specs(damage):
    with pytest.raises(ValueError, match="Arm AGI CPU product brief"):
        parse_document_content(
            URL, URL, brief_pdf(damage=damage), "application/pdf", "Brief"
        )


def test_query_string_and_binary_content_type_still_route_the_brief():
    url = URL + "?download=1"
    doc = parse_document_content(
        url, url, brief_pdf(), "application/octet-stream", "Brief"
    )
    chunks = chunk_parsed_document(doc, "Arm Documentation", [])
    assert len(chunks) == 11
    assert any(c["url"] == url + "#page=3" for c in chunks)


def test_other_pdfs_keep_generic_parsing_and_gain_page_citations():
    url = "https://example.com" + BRIEF_PATH
    # An incomplete brief at another host must not activate the custom adapter.
    doc = parse_document_content(
        url, url, brief_pdf(damage="missing page"), "application/pdf", "Brief"
    )
    chunks = chunk_parsed_document(doc, "Documentation", [])
    assert {c["url"] for c in chunks} == {url + f"#page={i}" for i in (1, 2, 3)}
    assert not any(c["heading_path"][0] == "Specifications" for c in chunks)


@pytest.mark.parametrize("damage", [None, "missing cell", "download failure"])
def test_main_validates_before_replacing_outputs_and_reuses_download(
    gc, monkeypatch, tmp_path, damage
):
    import yaml

    sources = tmp_path / "sources.csv"
    original = (
        "Site Name,License Type,Display Name,URL,Keywords\n"
        f"Arm Documentation,Arm Proprietary,Arm AGI CPU Product Brief,{URL},Arm AGI CPU\n"
    )
    sources.write_text(original)
    output = tmp_path / "chunks"
    output.mkdir()
    previous = output / "chunk_previous.yaml"
    previous.write_text("previous snapshot")
    details = tmp_path / "details.csv"
    details.write_text("previous details")
    monkeypatch.setattr(gc, "yaml_dir", str(output))
    monkeypatch.setattr(gc, "details_file", str(details))
    monkeypatch.setattr(gc, "prepare_intrinsic_chunks", lambda: None)
    monkeypatch.setattr(gc, "reconcile_ecosystem_sources", lambda **_: None)
    monkeypatch.setenv("SKIP_DISCOVERY", "1")
    monkeypatch.setattr("sys.argv", ["generate-chunks.py", str(sources)])
    requests = []

    def fetch(url):
        requests.append(url)
        if damage == "download failure":
            return None
        return SimpleNamespace(
            content=brief_pdf(damage=damage),
            url=URL,
            headers={"content-type": "application/pdf"},
        )

    monkeypatch.setattr(gc, "fetch_with_logging", fetch)
    if damage:
        with pytest.raises(ValueError, match="Arm AGI CPU product brief"):
            gc.main()
        assert sources.read_text() == original
        assert previous.read_text() == "previous snapshot"
        assert details.read_text() == "previous details"
    else:
        gc.main()
        saved = [yaml.safe_load(path.read_text()) for path in output.glob("*.yaml")]
        assert len(saved) == 11
        specs = [c for c in saved if c["heading_path"][0] == "Specifications"]
        assert {c["heading"] for c in specs} == {f"SKU {sku}" for sku in SKUS}
        assert all(c["url"] == URL + "#page=3" for c in specs)
    assert requests == [URL]
