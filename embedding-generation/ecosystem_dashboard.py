"""Convert Ecosystem Dashboard frontmatter into shared documents.

Acquisition and dashboard URL/slug resolution belong to the caller. This module
has no network access and does not change the production ingestion route.
"""

import yaml

from document_chunking import ParsedDocument, Section, parse_markdown, split_frontmatter


def parse_ecosystem_package(
    markdown: str, *, platform: str, source_url: str, resolved_url: str
) -> ParsedDocument:
    """Parse one package, reporting invalid metadata with its source location.

    BaseLoader preserves version strings such as 3.10 and dates verbatim. We
    validate scalar types and support booleans explicitly instead of letting
    YAML's implicit numeric/date conversions change package facts. The caller
    supplies platform (linux/windows) from the source directory.
    """

    def invalid(message):
        return ValueError(f"{resolved_url}: {message}")

    platforms = {
        "linux": ("Linux", "Arm Linux"),
        "windows": ("Windows on Arm", "Windows on Arm"),
    }
    if platform not in platforms:
        raise invalid("platform must be linux or windows")
    platform_title, platform_label = platforms[platform]

    frontmatter, body = split_frontmatter(markdown)
    if frontmatter is None:
        raise invalid("expected YAML frontmatter with closing --- delimiter")
    try:
        metadata = yaml.load(frontmatter, Loader=yaml.BaseLoader)
    except yaml.YAMLError as error:
        raise invalid(f"invalid YAML frontmatter: {error}") from error
    if not isinstance(metadata, dict):
        raise invalid("frontmatter must be a mapping")

    def field(path):
        value = metadata
        for key in path.split("."):
            if value in (None, "", "null", "~"):
                return None
            if not isinstance(value, dict):
                raise invalid(f"{path}: expected a mapping before {key}")
            value = value.get(key)
        return value

    def text(path):
        value = field(path)
        if value is None:
            return ""
        if not isinstance(value, str):
            raise invalid(f"{path}: expected text")
        return "" if value.strip().lower() in ("null", "~") else value.strip()

    name = text("name")
    if not name:
        raise invalid("name is required")
    support = text("works_on_arm").lower()
    if support not in ("", "true", "false"):
        raise invalid("works_on_arm must be true, false, or empty")

    paragraphs = [f"Package: {name}. Platform: {platform_label}."]

    def add(label, value):
        if value:
            paragraphs.append(f"{label}: {value}")

    for key, label in (
        ("description", "Description"),
        ("category", "Category"),
        ("vendor", "Vendor"),
    ):
        add(label, text(key))
    add(
        f"{platform_label} support",
        {"true": "Supported", "false": "Not supported", "": "Unknown"}[support],
    )
    for key, label in (
        ("supported_minimum_version.version_number", "Minimum supported version"),
        (
            "supported_minimum_version.release_date",
            "Minimum supported version release date",
        ),
        ("release_date_on_arm", "Available on Arm since"),
        (
            "optional_info.arm_recommended_minimum_version.version_number",
            "Arm-recommended minimum version",
        ),
        (
            "optional_info.arm_recommended_minimum_version.release_date",
            "Recommended version release date",
        ),
        (
            "optional_info.arm_recommended_minimum_version.rationale",
            "Recommendation rationale",
        ),
        ("optional_info.support_caveats", "Support caveats"),
        ("optional_info.alternative_options", "Alternatives"),
    ):
        add(label, text(key))

    seen_urls = set()

    def add_link(label, url):
        if url and url not in seen_urls:
            paragraphs.append(f"[{label}]({url})")
            seen_urls.add(url)

    for key, label in (
        ("download_url", "Download"),
        ("product_url", "Product page"),
        ("optional_info.homepage_url", "Homepage"),
        (
            "optional_info.arm_recommended_minimum_version.reference_content",
            "Recommendation reference",
        ),
        (
            "optional_info.getting_started_resources.official_docs",
            "Official documentation",
        ),
        ("optional_info.getting_started_resources.arm_content", "Arm guide"),
        (
            "optional_info.getting_started_resources.vendor_announcement",
            "Vendor announcement",
        ),
    ):
        add_link(label, text(key))
    partners = field("optional_info.getting_started_resources.partner_content")
    if partners not in (None, "", "null", "~"):
        if not isinstance(partners, list):
            raise invalid("partner_content must be a list")
        for partner in partners:
            if not isinstance(partner, dict) or not all(
                isinstance(partner.get(key), str) and partner[key].strip()
                for key in ("display_name", "url")
            ):
                raise invalid("partner_content entries need display_name and url")
            add_link(f"{partner['display_name']} guide", partner["url"])

    title = f"Ecosystem Dashboard — {platform_title} — {name}"
    # Resolve relative source links against the Markdown file, while keeping
    # dashboard URLs as the user-facing destination. Reuse Markdown parsing.
    parsed = parse_markdown("\n\n".join(paragraphs), resolved_url, resolved_url, title)
    sections = [
        Section(
            [platform_title, name],
            [block for section in parsed.sections for block in section.blocks],
        )
    ]
    if body.strip():
        extra = parse_markdown(body, resolved_url, resolved_url, title)
        sections.extend(
            Section([platform_title, name, *section.heading_path], section.blocks)
            for section in extra.sections
        )
    return ParsedDocument(
        source_url=source_url,
        resolved_url=resolved_url,
        display_title=title,
        content_type="markdown",
        sections=sections,
        product="",  # Do not confuse software package identity with product taxonomy.
        version="",  # Minimum and recommended versions are distinct content facts.
    )
