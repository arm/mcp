"""Extract the Arm AGI CPU brief without losing SKU/specification associations."""

import re
from urllib.parse import urlsplit

BRIEF_PATH = "/static/az/pdf/product-brief/arm-agi-cpu-product-brief.pdf"
SPEC_ROWS = (
    "SKU",
    "Processing Cores",
    "CPU Architecture",
    "System-Level Cache",
    "Max Frequency",
    "Base TDP*",
    "RDIMM Memory",
    "Memory Throughput/core",
    "PCIe/IO",
    "PCIe Control Lanes",
    "2-Socket Support",
    "2 DIMMS per channel",
)
HIGHLIGHTS = (
    "High-performance CPU",
    "High-memory bandwidth",
    "Advanced I/O and accelerator connectivity",
    "Enterprise security architecture",
)
RACK_HEADING = "BETTER RACK-LEVEL PERFORMANCE AND EFFICIENCY FOR AI DATA CENTERS"
REFERENCE_HEADING = "ACCELERATING DEPLOYMENT WITH REFERENCE PLATFORMS"


def is_agi_product_brief(url):
    parsed = urlsplit(url)
    return parsed.hostname in {"arm.com", "www.arm.com"} and parsed.path == BRIEF_PATH


def _text(value):
    return " ".join(value.split())


def _require(condition, message):
    if not condition:
        raise ValueError(f"Arm AGI CPU product brief: {message}")


def _prose(page, page_number):
    lines = []
    for line in (page.extract_text() or "").splitlines():
        line = line.strip()
        if line in {str(page_number), "Arm AGI CPU"} or re.fullmatch(
            r"\d*\s*PRODUCT BRIEF(?:\s*\d+)?", line
        ):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _split_sections(text, headings):
    """Split at authored headings and reject missing/reordered sections."""
    positions = []
    for heading in headings:
        matches = list(re.finditer(r"^" + re.escape(heading) + r"\s*$", text, re.M))
        _require(len(matches) == 1, f"missing or duplicate heading: {heading}")
        positions.append(matches[0])
    _require(
        [m.start() for m in positions] == sorted(m.start() for m in positions),
        "unexpected section order",
    )
    for index, match in enumerate(positions):
        end = positions[index + 1].start() if index + 1 < len(positions) else len(text)
        body = _text(text[match.end() : end])
        _require(body, f"empty section: {headings[index]}")
        yield headings[index], body


def _specifications(page):
    # Keep vertical spacing: some labels are centered beside multiline cells.
    # Blank lines delimit those rows; assigning text by label order would put
    # the first line of Processing Cores into the preceding SKU row.
    layout = page.extract_text(extraction_mode="layout")
    header = re.search(r"^.*\bSpecs\s{2,}Arm AGI CPU .*$", layout, re.M)
    _require(header is not None, "missing specification table header")
    variants = list(re.finditer(r"Arm AGI CPU \d+C\b", header[0]))
    _require(len(variants) >= 2, "expected multiple CPU variant columns")
    _require(
        len({m[0] for m in variants}) == len(variants), "duplicate variant columns"
    )
    # Layout extraction may place text one character left of its header.
    starts = [0, *(match.start() - 2 for match in variants)]

    def cells(block):
        columns = [[] for _ in starts]
        for line in block.splitlines():
            for index, start in enumerate(starts):
                end = starts[index + 1] if index + 1 < len(starts) else len(line)
                columns[index].append(line[start:end].strip())
        return [_text(" ".join(column)) for column in columns]

    footnote = re.search(r"^\s*(\*[^\n]+)", layout[header.end() :], re.M)
    _require(footnote is not None, "missing TDP qualification")
    table_end = header.end() + footnote.start()
    blocks = re.split(r"\n\s*\n", layout[header.start() : table_end].strip("\n"))
    names = cells(blocks[0])[1:]
    _require(
        all(name.startswith(match[0]) for name, match in zip(names, variants)),
        "invalid variant headers",
    )
    rows = {}
    for block in blocks[1:]:
        label, *values = cells(block)
        _require(
            label in SPEC_ROWS and label not in rows, f"unexpected table row: {label}"
        )
        _require(all(values), f"missing specification cell in {label}")
        rows[label] = values
    _require(set(rows) == set(SPEC_ROWS), "incomplete specification table")
    _require(len(set(rows["SKU"])) == len(names), "duplicate SKUs")
    for index, name in enumerate(names):
        sku = rows["SKU"][index]
        body = [f"{name}; SKU: {sku}."]
        body.extend(
            f"{label}: {rows[label][index]}" for label in SPEC_ROWS if label != "SKU"
        )
        body.append(_text(footnote[1]))
        yield ["Specifications", name, f"SKU {sku}"], "\n".join(body)


def extract_agi_product_brief(reader):
    """Return (heading path, text, page number), with values read from the PDF.

    Fail explicitly on an unfamiliar structure rather than emit an ambiguous
    table or silently omit a section. Page positions are discovered, not fixed.
    """
    sections, seen = [], set()
    for number, page in enumerate(reader.pages, 1):
        text = _prose(page, number)
        if re.search(r"^INTRODUCTION\s*$", text, re.M):
            kind = "introduction"
            text = re.sub(
                r"KEY FEATURES\s+AND BENEFITS", "Key features and benefits", text
            )
            parts = list(
                _split_sections(text, ("INTRODUCTION", "Key features and benefits"))
            )
            _require(
                re.search(r"\b1\s+Based on estimates\.", parts[1][1]),
                "missing performance qualification",
            )
            sections.extend(
                ([heading.capitalize()], body, number) for heading, body in parts
            )
        elif re.search(r"^HIGHLIGHTS\s*$", text, re.M):
            kind = "highlights"
            sections.extend(
                (["Highlights", heading], body, number)
                for heading, body in _split_sections(text, HIGHLIGHTS)
            )
        elif RACK_HEADING in text:
            kind = "specifications"
            overview = text.split(RACK_HEADING, 1)[1].split("Specs", 1)[0]
            _require(_text(overview), "missing rack-level overview")
            sections.append(
                (["Rack-level performance and efficiency"], _text(overview), number)
            )
            sections.extend(
                (heading, body, number) for heading, body in _specifications(page)
            )
        elif REFERENCE_HEADING in text:
            kind = "reference platforms"
            body = _text(text.split(REFERENCE_HEADING, 1)[1])
            _require(body, "missing reference platforms")
            sections.append((["Reference platforms"], body, number))
        else:
            raise ValueError(
                f"Arm AGI CPU product brief: unrecognized content on page {number}"
            )
        _require(kind not in seen, f"duplicate {kind} page")
        seen.add(kind)
    _require(
        seen == {"introduction", "highlights", "specifications", "reference platforms"},
        "incomplete product brief",
    )
    return sections
