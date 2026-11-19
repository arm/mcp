"""Validated contributor tags, kept separate from source routing and identity."""

import json
import warnings
from collections.abc import Iterable

METADATA_COLUMNS = {
    "Doc Type": "doc_type",
    "Product": "product",
    "Platform": "platform",
}
DOC_TYPES = frozenset({"learning", "guide", "reference", "article", "compatibility"})
PRODUCTS = frozenset({"arm", "aws", "google", "ampere"})
PLATFORMS = frozenset(
    {
        "linux",
        "windows",
        "macos",
        "android",
        "baremetal",
        "rtos",
        "chromeos",
        "freebsd",
        "neon",
        "sve",
        "sve2",
        "sme",
        "sme2",
        "helium",
        "cme",
        "mali",
        "cortex-m",
        "agi-cpu",
        "google-colab",
    }
)
PLATFORM_ALIASES = {"bare metal": "baremetal", "bare-metal": "baremetal"}

# Site Name is the acquisition adapter, not necessarily the public document type.
# Mixed-purpose adapters still need a contributor-supplied Doc Type.
SITE_DOC_TYPES = {
    "Learning Paths": "learning", "Install Guides": "guide",
    "Educational Course": "learning", "Educational Resource": "learning",
    "Ecosystem Dashboard": "compatibility", "Insights": "reference",
    "Tuning Guide": "guide", "Workload Brief": "article",
}
SITE_PUBLISHERS = {
    "Arm Developer": "arm", "Arm Documentation": "arm", "Learning Paths": "arm",
    "Install Guides": "arm", "Educational Course": "arm", "Educational Resource": "arm",
    "Ecosystem Dashboard": "arm", "Insights": "arm",
    "Google Cloud Documentation": "google", "Graviton Getting Started Guide": "aws",
    "Reference Architecture": "ampere", "Tuning Guide": "ampere",
    "Tutorial": "ampere", "Workload Brief": "ampere",
}
LEARN_PLATFORM_TAGS = {
    "operatingsystems": {name: name for name in (
        "linux", "windows", "macos", "android", "baremetal", "rtos", "chromeos", "freebsd",
    )},
    "armips": {"cortex-m": "cortex-m", "cortex-m55": "cortex-m", "mali": "mali"},
    "tools_software_languages": {name: name for name in (
        "neon", "sve", "sve2", "sme", "sme2", "helium",
    )},
    "platforms": {"arm agi cpu": "agi-cpu"},
}


def source_metadata_defaults(site: str) -> dict[str, list[str]]:
    """Verified adapter defaults; unknown fields suppress legacy heuristic tags."""
    return {
        "doc_type": [SITE_DOC_TYPES[site]] if site in SITE_DOC_TYPES else [],
        "product": [SITE_PUBLISHERS[site]] if site in SITE_PUBLISHERS else [],
        "platform": [],
    }


def learn_platform_tags(metadata: dict, source_url: str) -> list[str]:
    """Use exact authored taxonomy values, never incidental body/keyword matches."""
    result = []
    for field, mapping in LEARN_PLATFORM_TAGS.items():
        values = metadata.get(field) or []
        for value in [values] if isinstance(values, str) else values:
            normalized = value.strip().casefold() if isinstance(value, str) else ""
            tag = mapping.get(normalized)
            if tag and tag not in result:
                result.append(tag)
            elif not tag and field == "operatingsystems":
                warnings.warn(f"{source_url}: unmapped operatingsystems value {value!r}; no tag inferred", stacklevel=2)
    return result


def _requires_array(value: str) -> bool:
    """Keep commas and JSON-looking labels unambiguous when serializing."""
    if value.startswith(("[", "{", '"')) or "," in value:
        return True
    try:
        json.loads(value)
    except json.JSONDecodeError:
        return False
    return True


def parse_metadata_override(
    value: str | None, column: str, source_url: str
) -> list[str] | None:
    """Return None for inheritance, [] for explicit clear, or normalized tags."""
    if value is None or not value.strip():
        return None
    cell = value.strip()
    context = f"{column} for {source_url}"
    if _requires_array(cell):
        try:
            labels = json.loads(cell)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"{context}: expected a label or valid JSON array"
            ) from error
        if not isinstance(labels, list):
            raise ValueError(f"{context}: expected a label or JSON array of labels")
    else:
        labels = [cell]
    allowed = {"Doc Type": DOC_TYPES, "Product": PRODUCTS, "Platform": PLATFORMS}.get(column)
    result = []
    for label in labels:
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"{context}: expected nonempty string labels")
        normalized = label.strip().casefold()
        if column == "Platform":
            normalized = PLATFORM_ALIASES.get(normalized, normalized)
        if allowed is not None and normalized not in allowed:
            kind = "publisher" if column == "Product" else "label"
            raise ValueError(
                f"{context}: unsupported {kind} {label!r}; "
                f"use one of {', '.join(sorted(allowed))} or a JSON array of them; "
                "leave blank to inherit, or use [] to clear"
            )
        if normalized not in result:
            result.append(normalized)
    return result


def validate_metadata_columns(columns: Iterable[str], source: str) -> None:
    """Reject retired columns even when a contributor CSV has no data rows."""
    columns = list(columns)
    if any(isinstance(column, str) and column.strip().casefold() == "edition" for column in columns):
        raise ValueError(
            f"Edition for {source}: this filter was removed; remove the Edition CSV column"
        )
    aliases = {column.casefold().replace(" ", ""): column for column in METADATA_COLUMNS}
    for column in columns:
        if not isinstance(column, str):
            continue
        canonical = aliases.get(column.strip().casefold().replace("_", "").replace(" ", "").removesuffix("s"))
        if canonical and column != canonical:
            raise ValueError(f"{column} for {source}: use the exact CSV header {canonical!r}")
        if column in METADATA_COLUMNS and columns.count(column) > 1:
            raise ValueError(f"{column} for {source}: duplicate metadata column")


def validate_metadata_overrides(overrides: dict | None, source_url: str) -> dict[str, list[str]]:
    """Validate programmatic callers as strictly as CSV contributors."""
    columns = {field: column for column, field in METADATA_COLUMNS.items()}
    result = {}
    for field, tags in (overrides or {}).items():
        if field not in columns:
            raise ValueError(f"{field} for {source_url}: unsupported metadata field")
        if tags is None:
            continue
        if not isinstance(tags, list):
            raise ValueError(f"{field} for {source_url}: expected a list of labels")
        result[field] = parse_metadata_override(json.dumps(tags), columns[field], source_url)
    return result


def read_metadata_overrides(row: dict, source_url: str) -> dict[str, list[str] | None]:
    """Read present tag columns, rejecting unquoted extra CSV cells."""
    validate_metadata_columns(row, source_url)
    columns = [column for column in METADATA_COLUMNS if column in row]
    if columns and None in row:
        raise ValueError(
            f"{', '.join(columns)} for {source_url}: extra CSV cells; quote JSON arrays"
        )
    return {
        METADATA_COLUMNS[column]: parse_metadata_override(
            row[column], column, source_url
        )
        for column in columns
    }


def format_metadata_override(value: list[str] | None) -> str:
    """Serialize validated tags without conflating explicit empty with absent."""
    if value is None:
        return ""
    if len(value) == 1 and not _requires_array(value[0]):
        return value[0]
    return json.dumps(value, separators=(",", ":"))
