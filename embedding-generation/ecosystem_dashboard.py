"""Acquire the Ecosystem Dashboard catalog and convert it into shared documents."""

import re
import tarfile
import unicodedata
import warnings
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import quote, urlencode

import yaml

from document_chunking import ParsedDocument, Section, parse_markdown, split_frontmatter

REPOSITORY = "ArmDeveloperEcosystem/ecosystem-dashboard-for-arm"
DASHBOARD_URL = "https://developer.arm.com/ecosystem-dashboard"
PACKAGE_DIRECTORIES = {
    "content/linux/opensource_packages": ("linux", "open-source"),
    "content/linux/commercial_packages": ("linux", "commercial"),
    "content/windows/all_packages": ("windows", ""),
}


def _read_package_frontmatter(markdown: str, source_url: str) -> tuple[dict, str]:
    """Read source metadata without YAML's numeric/date coercion."""
    frontmatter, body = split_frontmatter(markdown)
    if frontmatter is None:
        raise ValueError(
            f"{source_url}: expected YAML frontmatter with closing --- delimiter"
        )
    try:
        metadata = yaml.load(frontmatter, Loader=yaml.BaseLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"{source_url}: invalid YAML frontmatter: {error}") from error
    if not isinstance(metadata, dict):
        raise ValueError(f"{source_url}: frontmatter must be a mapping")
    return metadata, body


def parse_ecosystem_package(
    markdown: str, *, platform: str, source_url: str, resolved_url: str
) -> ParsedDocument:
    """Parse one package, reporting invalid metadata with its source location.

    BaseLoader preserves version strings such as 3.10 and dates verbatim. We
    validate scalar types and support booleans explicitly instead of letting
    YAML's implicit numeric/date conversions change package facts. The caller
    supplies platform (linux/windows) from the source directory.
    """
    metadata, body = _read_package_frontmatter(markdown, resolved_url)
    return _package_document(
        metadata,
        body,
        platform=platform,
        source_url=source_url,
        resolved_url=resolved_url,
    )


def _package_document(
    metadata: dict, body: str, *, platform: str, source_url: str, resolved_url: str
) -> ParsedDocument:
    """Validate package fields and render them with the shared Markdown parser."""

    def invalid(message):
        return ValueError(f"{resolved_url}: {message}")

    platforms = {
        "linux": ("Linux", "Arm Linux"),
        "windows": ("Windows on Arm", "Windows on Arm"),
    }
    if platform not in platforms:
        raise invalid("platform must be linux or windows")
    platform_title, platform_label = platforms[platform]

    for key in ("getting_started_resources", "arm_recommended_minimum_version"):
        if key in metadata:
            raise invalid(f"{key} must be nested under optional_info")

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
        platform=platform,
    )


def package_slug(name: str) -> str:
    """Match the dashboard's urlize_custom.html and Hugo path sanitization.

    Filenames are not dashboard slugs: dot-net.md links to ?package=.net.
    Keep punctuation Hugo permits, remove other punctuation, and turn internal
    whitespace into hyphens. The dashboard additionally replaces / and &.
    """
    name = name.lower().replace("/", "__").replace("&", "and")
    result = ""
    pending_hyphen = False
    for index, char in enumerate(name):
        allowed = (
            unicodedata.category(char)[0] in "LM"
            or unicodedata.category(char) == "Nd"
            or char in ".\\_#+~-@"
            or (char == "%" and re.match(r"[0-9a-f]{2}", name[index + 1 : index + 3]))
        )
        if allowed:
            if pending_hyphen and char != "-":
                result += "-"
            result += char
            pending_hyphen = False
        elif result and not result.endswith("-") and char.isspace():
            pending_hyphen = True
    return quote(result, safe=".%_#+~-@")


@dataclass
class DashboardPackage:
    document: ParsedDocument
    keywords: list[str]


def parse_catalog(archive: bytes, revision: str) -> dict[str, list[DashboardPackage]]:
    """Skip invalid records with source-specific warnings; retain valid variants.

    Read archive members in memory, never extract paths to disk. resolved_url
    identifies the platform, catalog/edition, and source file within the commit.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Dashboard revision must be a full Git commit SHA")
    catalog = {}
    errors = []
    platforms = set()
    with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as source:
        for member in sorted(source.getmembers(), key=lambda item: item.name):
            path = member.name.partition("/")[2]
            directory, _, filename = path.rpartition("/")
            if (
                directory not in PACKAGE_DIRECTORIES
                or not filename.endswith(".md")
                or filename == "_index.md"
            ):
                continue
            resolved_url = f"https://raw.githubusercontent.com/{REPOSITORY}/{revision}/{quote(path)}"
            try:
                if not member.isfile():
                    raise ValueError(f"{path}: expected a regular package file")
                markdown = source.extractfile(member).read().decode("utf-8-sig")
                platform, edition = PACKAGE_DIRECTORIES[directory]
                metadata, body = _read_package_frontmatter(markdown, resolved_url)
                document = _package_document(
                    metadata,
                    body,
                    platform=platform,
                    source_url="",
                    resolved_url=resolved_url,
                )
                slug = package_slug(metadata["name"].strip())
                if not slug:
                    raise ValueError(f"{path}: package name produces an empty slug")
                document.source_url = (
                    f"{DASHBOARD_URL}/{platform}?{urlencode({'package': slug})}"
                )
                document.edition = edition
                if edition:
                    document.display_title += (
                        f" — {edition.replace('-', ' ').capitalize()}"
                    )
                keywords = [metadata["name"].strip(), platform]
                keywords.extend(
                    value.strip()
                    for value in (
                        edition,
                        metadata.get("category", ""),
                        metadata.get("vendor", ""),
                    )
                    if value.strip()
                )
                catalog.setdefault(document.source_url, []).append(
                    DashboardPackage(document, keywords)
                )
                platforms.add(platform)
            except ValueError as error:
                errors.append(str(error))
    if errors:
        warnings.warn(
            f"Skipped {len(errors)} invalid Ecosystem Dashboard records:\n"
            + "\n".join(errors),
            stacklevel=2,
        )
    if platforms != {"linux", "windows"}:
        raise ValueError("Dashboard snapshot must contain Linux and Windows packages")
    return catalog


def acquire_catalog(session, revision: str = "") -> dict[str, list[DashboardPackage]]:
    """Resolve main once, then fetch every source from that immutable revision."""
    if not revision:
        response = session.get(
            f"https://api.github.com/repos/{REPOSITORY}/commits/main", timeout=60
        )
        response.raise_for_status()
        revision = response.json()["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Dashboard revision must be a full Git commit SHA")
    response = session.get(
        f"https://codeload.github.com/{REPOSITORY}/tar.gz/{revision}", timeout=120
    )
    response.raise_for_status()
    catalog = parse_catalog(response.content, revision)
    count = sum(len(packages) for packages in catalog.values())
    print(
        f"[ECOSYSTEM SNAPSHOT] {revision}: {count} records, {len(catalog)} dashboard URLs"
    )
    for url, packages in catalog.items():
        if len(packages) > 1:
            print(
                f"[ECOSYSTEM SHARED URL] {url}: "
                + ", ".join(p.document.resolved_url for p in packages)
            )
    return catalog
