"""Utilities for parsing documentation sources into retrieval-friendly chunks."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import base64
import json
import math
import re
from typing import Dict, Iterable, List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from pypdf import PdfReader


TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
WORD_PATTERN = re.compile(r"\S+")
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
MARKDOWN_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
MARKDOWN_HEADING_ANCHOR_PATTERN = re.compile(r"^(.*?)\s*\{#([A-Za-z0-9_-]+)\}\s*$")
MARKDOWN_FENCE_PATTERN = re.compile(r"^(```|~~~)")
MARKDOWN_LINK_PATTERN = re.compile(r'(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
HTML_HEADING_TAGS = {f"h{level}" for level in range(1, 7)}
HTML_BLOCK_TAGS = HTML_HEADING_TAGS | {"p", "li", "pre", "code", "table"}
BOILERPLATE_LINE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^register\s*login$",
        r"^english\s*chinese$",
        r"^about\s*\|\s*contact us\s*\|\s*privacy\s*\|\s*sitemap$",
        r"^this site runs on ampere processors\.?$",
        r"^created at\s*:",
        r"^last updated at\s*:",
        r"^copy$",
        r"^table of contents$",
        r"^on this page$",
        r"^skip to content$",
        r"^sign in$",
        r"^sign up$",
        r"^all rights reserved\.?$",
        r"^ampere computing llc$",
        r"^products solutions developers support resources company$",
    )
]
ARM_DOCUMENTATION_SERVICE_HOST = "documentation-service.arm.com"
ARM_DEVELOPER_HOST = "developer.arm.com"


@dataclass
class Link:
    text: str
    url: str


@dataclass
class Block:
    kind: str
    text: str
    links: List[Link] | None = None


@dataclass
class Section:
    heading_path: List[str]
    blocks: List[Block]
    url_fragment: Optional[str] = None


@dataclass
class ParsedDocument:
    source_url: str
    resolved_url: str
    display_title: str
    content_type: str
    sections: List[Section]


def normalize_source_url(url: str) -> str:
    """Strip browser-extension wrappers and normalize trivial URL noise."""
    url = (url or "").strip()
    if url.startswith("chrome-extension://") and "https:/" in url:
        _, tail = url.split("https:/", 1)
        url = f"https://{tail.lstrip('/')}"
    return url


def is_learn_learning_path_url(url: str) -> bool:
    parsed = urlparse(normalize_source_url(url))
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.lower() == "learn.arm.com"
        and parsed.path.startswith("/learning-paths/")
    )


def learn_learning_path_step_urls(source_url: str, html: str | bytes) -> List[str]:
    source_url = normalize_source_url(source_url)
    if not is_learn_learning_path_url(source_url):
        return []

    source = urlparse(source_url)
    source_path = source.path.rstrip("/") + "/"
    soup = BeautifulSoup(html, "html.parser")
    step_urls: List[str] = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=True):
        candidate = normalize_source_url(urljoin(source_url, link.get("href", "")))
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "learn.arm.com":
            continue
        path = parsed.path.rstrip("/") + "/"
        if path == source_path or not path.startswith(source_path):
            continue
        step_url = urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
        if step_url not in seen:
            seen.add(step_url)
            step_urls.append(step_url)

    return step_urls


def is_arm_developer_documentation_url(url: str) -> bool:
    parsed = urlparse(normalize_source_url(url))
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == ARM_DEVELOPER_HOST and parsed.path.startswith("/documentation/")


def arm_developer_url_to_service_url(url: str) -> str:
    parsed = urlparse(normalize_source_url(url))
    return urlunparse(parsed._replace(scheme="https", netloc=ARM_DOCUMENTATION_SERVICE_HOST))


def arm_service_url_to_developer_url(service_url: str, source_url: str) -> str:
    service = urlparse(service_url)
    source = urlparse(normalize_source_url(source_url))
    path_parts = [part for part in service.path.split("/") if part]
    source_parts = [part for part in source.path.split("/") if part]

    if len(path_parts) >= 3 and path_parts[0] == "documentation":
        source_version = source_parts[2] if len(source_parts) >= 3 else path_parts[2]
        path_parts[2] = source_version

    filtered_query = urlencode(
        [(key, value) for key, value in parse_qsl(service.query, keep_blank_values=True) if key != "rev"]
    )
    return urlunparse(("https", ARM_DEVELOPER_HOST, "/" + "/".join(path_parts), "", filtered_query, service.fragment))


def source_to_fetch_url(url: str) -> str:
    """Resolve source URLs into directly fetchable content URLs."""
    url = normalize_source_url(url)
    if is_arm_developer_documentation_url(url):
        return arm_developer_url_to_service_url(url)
    if url == "https://learn.arm.com/migration":
        return (
            "https://raw.githubusercontent.com/ArmDeveloperEcosystem/"
            "arm-learning-paths/refs/heads/main/content/migration/_index.md"
        )
    if "/github.com/aws/aws-graviton-getting-started/" in url:
        specific_content = url.split("/main/", 1)[1]
        return (
            "https://raw.githubusercontent.com/aws/aws-graviton-getting-started/"
            f"refs/heads/main/{specific_content}"
        )
    if url.startswith("https://github.com/") and "/blob/" in url:
        owner_repo, path = url.split("/blob/", 1)
        branch, relative_path = path.split("/", 1)
        return owner_repo.replace("https://github.com/", "https://raw.githubusercontent.com/") + f"/{branch}/{relative_path}"
    return url


def estimate_tokens(text: str) -> int:
    """Cheap token estimator good enough for chunk sizing."""
    if not text:
        return 0
    return math.ceil(len(TOKEN_PATTERN.findall(text)) * 0.85)


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def tokenize_link_text(text: str) -> List[str]:
    return [token.lower() for token in re.findall(r"[a-z0-9][a-z0-9_\-+.]*", text or "", re.IGNORECASE)]


def resolve_link_url(base_url: str, href: str) -> str:
    href = clean_text(href)
    if not href or href.startswith(("mailto:", "tel:", "javascript:")):
        return ""
    return urljoin(base_url, href)


def extract_markdown_links(text: str, base_url: str) -> List[Link]:
    links: List[Link] = []
    for match in MARKDOWN_LINK_PATTERN.finditer(text or ""):
        link_text = clean_text(match.group(1))
        link_url = resolve_link_url(base_url, match.group(2))
        if link_text and link_url:
            links.append(Link(link_text, link_url))
    return links


def extract_html_links(tag, base_url: str) -> List[Link]:
    links: List[Link] = []
    for link in tag.find_all("a", href=True):
        link_text = clean_text(link.get_text(" ", strip=True))
        link_url = resolve_link_url(base_url, link.get("href", ""))
        if link_text and link_url:
            links.append(Link(link_text, link_url))
    return links


def link_text_with_urls(text: str, links: List[Link]) -> str:
    if not links:
        return text
    link_evidence = " ".join(f"{link.text} {link.url}" for link in links)
    return clean_text(f"{text}\n\nLinked references: {link_evidence}")


def is_meaningful_retrieval_link(link: Link) -> bool:
    parsed = urlparse(link.url)
    if parsed.scheme not in {"http", "https"}:
        return False
    stopwords = {"a", "an", "and", "for", "here", "in", "of", "or", "the", "this", "to"}
    tokens = [token for token in tokenize_link_text(link.text) if token not in stopwords]
    return bool(parsed.fragment) or len(tokens) >= 2


def is_boilerplate_line(line: str) -> bool:
    line = clean_text(line)
    if not line:
        return False
    if re.fullmatch(r"©\s*\d{4}.*", line):
        return True
    if re.fullmatch(r"\d+\s*/\s*\d+", line):
        return True
    if re.fullmatch(r"\d+", line):
        return True
    return any(pattern.match(line) for pattern in BOILERPLATE_LINE_PATTERNS)


def strip_frontmatter(markdown: str) -> str:
    markdown = markdown.lstrip("\ufeff")
    if markdown.startswith("---"):
        end = markdown.find("\n---", 3)
        if end != -1:
            return markdown[end + 4 :].lstrip()
    return markdown


def normalize_heading_path(title: str, heading_path: List[str]) -> List[str]:
    normalized = [clean_text(part) for part in heading_path if clean_text(part)]
    if normalized and clean_text(normalized[0]).lower() == clean_text(title).lower():
        normalized = normalized[1:]
    return normalized


def url_with_fragment(url: str, fragment: str | None) -> str:
    if not fragment:
        return url
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=fragment))


def parse_markdown(markdown: str, source_url: str, resolved_url: str, fallback_title: str) -> ParsedDocument:
    markdown = strip_frontmatter(markdown)
    lines = markdown.splitlines()
    heading_stack: List[str] = []
    heading_anchor_stack: List[Optional[str]] = []
    sections: List[Section] = []
    current_blocks: List[Block] = []
    current_paragraph: List[str] = []
    current_code: List[str] = []
    in_code_block = False
    document_title = fallback_title

    def flush_paragraph() -> None:
        nonlocal current_paragraph
        if not current_paragraph:
            return
        paragraph = clean_text("\n".join(current_paragraph))
        current_paragraph = []
        if paragraph and not is_boilerplate_line(paragraph):
            links = extract_markdown_links(paragraph, source_url)
            current_blocks.append(Block("paragraph", link_text_with_urls(paragraph, links), links))

    def flush_code() -> None:
        nonlocal current_code
        if not current_code:
            return
        code = "\n".join(current_code).strip()
        current_code = []
        if code:
            current_blocks.append(Block("code", code))

    def flush_section() -> None:
        if current_blocks:
            section_anchor = next((anchor for anchor in reversed(heading_anchor_stack) if anchor), None)
            sections.append(Section(list(heading_stack), list(current_blocks), section_anchor))
            current_blocks.clear()

    for line in lines:
        if MARKDOWN_FENCE_PATTERN.match(line.strip()):
            if in_code_block:
                current_code.append(line)
                flush_code()
                in_code_block = False
            else:
                flush_paragraph()
                in_code_block = True
                current_code = [line]
            continue
        if in_code_block:
            current_code.append(line)
            continue
        heading_match = MARKDOWN_HEADING_PATTERN.match(line.strip())
        if heading_match:
            flush_paragraph()
            flush_section()
            level = len(heading_match.group(1))
            heading_text = clean_text(heading_match.group(2))
            heading_anchor = None
            anchor_match = MARKDOWN_HEADING_ANCHOR_PATTERN.match(heading_text)
            if anchor_match:
                heading_text = clean_text(anchor_match.group(1))
                heading_anchor = clean_text(anchor_match.group(2))
            if level == 1 and fallback_title == document_title:
                document_title = heading_text
            while len(heading_stack) >= level:
                heading_stack.pop()
                heading_anchor_stack.pop()
            heading_stack.append(heading_text)
            heading_anchor_stack.append(heading_anchor)
            continue
        if not line.strip():
            flush_paragraph()
            continue
        current_paragraph.append(line)

    flush_paragraph()
    flush_code()
    flush_section()
    if not sections:
        sections.append(Section([], [Block("paragraph", clean_text(markdown))]))
    return ParsedDocument(
        source_url=source_url,
        resolved_url=resolved_url,
        display_title=document_title,
        content_type="markdown",
        sections=sections,
    )


def _select_html_root(soup: BeautifulSoup):
    for selector in ("main", "article", "[role='main']", ".article", ".content"):
        root = soup.select_one(selector)
        if root:
            return root
    return soup.body or soup


def _should_skip_html_tag(tag) -> bool:
    if tag.name not in HTML_BLOCK_TAGS:
        return True
    parent = tag.parent
    while parent is not None:
        if getattr(parent, "name", None) in HTML_BLOCK_TAGS:
            if tag.name == "code" and parent.name == "pre":
                return True
            if tag.name == "li" and parent.name not in {"ul", "ol"}:
                return True
            if tag.name not in {"li"}:
                return True
        parent = parent.parent
    return False


def parse_html(html: str, source_url: str, resolved_url: str, fallback_title: str) -> ParsedDocument:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg", "form"]):
        tag.decompose()
    root = _select_html_root(soup)
    title = fallback_title
    if soup.find("meta", attrs={"property": "og:title"}):
        title = clean_text(soup.find("meta", attrs={"property": "og:title"}).get("content", "")) or title
    elif soup.title:
        title = clean_text(soup.title.get_text(" ", strip=True)) or title

    heading_stack: List[str] = []
    heading_anchor_stack: List[Optional[str]] = []
    sections: List[Section] = []
    current_blocks: List[Block] = []
    first_h1_seen = False

    def flush_section() -> None:
        if current_blocks:
            section_anchor = next((anchor for anchor in reversed(heading_anchor_stack) if anchor), None)
            sections.append(Section(list(heading_stack), list(current_blocks), section_anchor))
            current_blocks.clear()

    for tag in root.find_all(list(HTML_BLOCK_TAGS)):
        if _should_skip_html_tag(tag):
            continue
        text = clean_text(tag.get_text("\n" if tag.name == "pre" else " ", strip=True))
        if not text or is_boilerplate_line(text):
            continue
        if tag.name in HTML_HEADING_TAGS:
            flush_section()
            level = int(tag.name[1])
            while len(heading_stack) >= level:
                heading_stack.pop()
                heading_anchor_stack.pop()
            heading_stack.append(text)
            heading_anchor_stack.append(clean_text(tag.get("id", "")) or None)
            if level == 1 and not first_h1_seen:
                title = text
                first_h1_seen = True
            continue
        links = extract_html_links(tag, source_url)
        if tag.name == "table":
            rows = []
            for row in tag.find_all("tr"):
                values = [clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
                values = [value for value in values if value]
                if values:
                    rows.append(" | ".join(values))
            text = "\n".join(rows)
        if tag.name in {"pre", "code"}:
            current_blocks.append(Block("code", f"```\n{text}\n```", links))
        elif tag.name == "li":
            current_blocks.append(Block("paragraph", link_text_with_urls(f"- {text}", links), links))
        else:
            current_blocks.append(Block("paragraph", link_text_with_urls(text, links), links))

    flush_section()
    if not sections:
        page_text = clean_text(root.get_text("\n", strip=True))
        if page_text:
            sections.append(Section([], [Block("paragraph", page_text)]))
    return ParsedDocument(
        source_url=source_url,
        resolved_url=resolved_url,
        display_title=title,
        content_type="html",
        sections=sections,
    )


def looks_like_heading(paragraph: str) -> bool:
    text = clean_text(paragraph)
    if not text or len(text) > 120:
        return False
    if text.endswith((".", "!", "?", ":")):
        return False
    if len(text.split()) > 12:
        return False
    return text == text.title() or text == text.upper()


def parse_pdf(pdf_bytes: bytes, source_url: str, resolved_url: str, fallback_title: str) -> ParsedDocument:
    reader = PdfReader(BytesIO(pdf_bytes))
    sections: List[Section] = []
    document_title = fallback_title
    for page_number, page in enumerate(reader.pages, start=1):
        raw_text = clean_text(page.extract_text() or "")
        if not raw_text:
            continue
        paragraphs = [clean_text(chunk) for chunk in re.split(r"\n\s*\n", raw_text) if clean_text(chunk)]
        heading_path = [f"Page {page_number}"]
        blocks: List[Block] = []
        for paragraph in paragraphs:
            if page_number == 1 and document_title == fallback_title and len(paragraph.split()) <= 12:
                document_title = paragraph
                continue
            if looks_like_heading(paragraph):
                heading_path = [f"Page {page_number}", paragraph]
                continue
            if is_boilerplate_line(paragraph):
                continue
            blocks.append(Block("paragraph", paragraph))
        if blocks:
            sections.append(Section(heading_path, blocks))
    if not sections:
        sections.append(Section([], [Block("paragraph", fallback_title)]))
    return ParsedDocument(
        source_url=source_url,
        resolved_url=resolved_url,
        display_title=document_title,
        content_type="pdf",
        sections=sections,
    )


def parse_document_content(
    source_url: str,
    resolved_url: str,
    response_content: bytes,
    content_type: str,
    fallback_title: str,
) -> ParsedDocument:
    content_type = (content_type or "").lower()
    if "pdf" in content_type or resolved_url.lower().endswith(".pdf"):
        return parse_pdf(response_content, source_url, resolved_url, fallback_title)
    decoded = response_content.decode("utf-8", errors="ignore")
    if "markdown" in content_type or resolved_url.lower().endswith(".md"):
        return parse_markdown(decoded, source_url, resolved_url, fallback_title)
    if "html" in content_type or "<html" in decoded.lower():
        return parse_html(decoded, source_url, resolved_url, fallback_title)
    return parse_markdown(decoded, source_url, resolved_url, fallback_title)


def parse_arm_documentation_api_json(
    response_content: bytes,
    source_url: str,
    resolved_url: str,
    fallback_title: str,
) -> ParsedDocument:
    data = json.loads(response_content.decode("utf-8", errors="ignore"))
    topic = data.get("topic", data)
    content = topic.get("content", "")
    if not content:
        return ParsedDocument(
            source_url=source_url,
            resolved_url=resolved_url,
            display_title=fallback_title,
            content_type="html",
            sections=[],
        )

    html = base64.b64decode(content).decode("utf-8", errors="ignore")
    title = data.get("title") or fallback_title
    return parse_html(html, source_url, resolved_url, title)


def merge_code_context(blocks: List[Block]) -> List[str]:
    merged: List[str] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block.kind == "code":
            parts = []
            if merged:
                previous = merged.pop()
                if estimate_tokens(previous) <= 180:
                    parts.append(previous)
                else:
                    merged.append(previous)
            parts.append(block.text)
            if i + 1 < len(blocks) and blocks[i + 1].kind != "code":
                if estimate_tokens(blocks[i + 1].text) <= 180:
                    parts.append(blocks[i + 1].text)
                    i += 1
            merged.append("\n\n".join(part for part in parts if part))
        else:
            merged.append(block.text)
        i += 1
    return [clean_text(item) for item in merged if clean_text(item)]


def split_text_recursively(text: str, max_tokens: int) -> List[str]:
    text = clean_text(text)
    if not text:
        return []
    if estimate_tokens(text) <= max_tokens:
        return [text]
    parts = [clean_text(part) for part in re.split(r"\n\s*\n", text) if clean_text(part)]
    if len(parts) > 1:
        flattened: List[str] = []
        for part in parts:
            flattened.extend(split_text_recursively(part, max_tokens))
        return flattened
    if "```" not in text:
        sentences = [clean_text(part) for part in SENTENCE_SPLIT_PATTERN.split(text) if clean_text(part)]
        if len(sentences) > 1:
            flattened = []
            for sentence in sentences:
                flattened.extend(split_text_recursively(sentence, max_tokens))
            return flattened
    words = WORD_PATTERN.findall(text)
    step = max(1, int(max_tokens / 0.85))
    return [" ".join(words[index : index + step]) for index in range(0, len(words), step)]


def overlap_tail(text: str, overlap_tokens: int) -> str:
    words = WORD_PATTERN.findall(text)
    if len(words) <= overlap_tokens:
        return text
    return " ".join(words[-overlap_tokens:])


def chunk_section_units(
    units: List[str],
    min_tokens: int,
    max_tokens: int,
    overlap_tokens: int,
) -> List[str]:
    normalized_units: List[str] = []
    for unit in units:
        normalized_units.extend(split_text_recursively(unit, max_tokens))

    chunks: List[str] = []
    current_units: List[str] = []
    current_tokens = 0
    for unit in normalized_units:
        unit_tokens = estimate_tokens(unit)
        if current_units and current_tokens + unit_tokens > max_tokens and current_tokens >= min_tokens:
            current_text = "\n\n".join(current_units)
            chunks.append(current_text.strip())
            tail = overlap_tail(current_text, overlap_tokens)
            current_units = [tail] if tail else []
            current_tokens = estimate_tokens(tail)
        current_units.append(unit)
        current_tokens += unit_tokens

    if current_units:
        current_text = "\n\n".join(current_units).strip()
        if chunks and estimate_tokens(current_text) < max(80, min_tokens // 2):
            chunks[-1] = f"{chunks[-1]}\n\n{current_text}".strip()
        else:
            chunks.append(current_text)
    return [chunk for chunk in chunks if clean_text(chunk)]



def build_chunk_text(title: str, heading_path: List[str], body: str) -> str:
    normalized_heading_path = normalize_heading_path(title, heading_path)
    heading_label = " > ".join(normalized_heading_path) if normalized_heading_path else title
    return clean_text(f"Document Title: {title}\nHeading Path: {heading_label}\n\n{body}")


def derive_version(title: str, source_url: str, content: str = "") -> str:
    haystack = " ".join([title, source_url, content[:4000]])
    match = re.search(r"\b(v?\d+(?:\.\d+){0,2})\b", haystack, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"\b(20\d{2})\b", haystack)
    if match:
        return match.group(1)
    return ""


def derive_product(title: str, source_url: str, doc_type: str, keywords: Iterable[str]) -> str:
    haystack = " ".join([title, source_url, doc_type, *keywords]).lower()
    if "graviton" in haystack:
        return "AWS Graviton"
    if "ampere" in haystack or "amperecomputing.com" in source_url:
        return "Ampere"
    if "learn.arm.com" in source_url or "developer.arm.com" in source_url or "/arm-" in source_url or " arm " in f" {haystack} ":
        return "Arm"
    return clean_text(doc_type) or "Documentation"


def chunk_parsed_document(
    parsed_document: ParsedDocument,
    doc_type: str,
    keywords: List[str],
    min_tokens: int = 300,
    max_tokens: int = 600,
    overlap_tokens: int = 50,
) -> List[Dict[str, str]]:
    chunks: List[Dict[str, str]] = []
    product = derive_product(parsed_document.display_title, parsed_document.source_url, doc_type, keywords)
    version = derive_version(parsed_document.display_title, parsed_document.resolved_url)
    for section in parsed_document.sections:
        heading_path = normalize_heading_path(parsed_document.display_title, section.heading_path)
        units = merge_code_context(section.blocks)
        if not units:
            continue
        heading = heading_path[-1] if heading_path else parsed_document.display_title
        for chunk_body in chunk_section_units(units, min_tokens, max_tokens, overlap_tokens):
            chunks.append(
                {
                    "title": parsed_document.display_title,
                    "url": url_with_fragment(parsed_document.source_url, section.url_fragment),
                    "resolved_url": parsed_document.resolved_url,
                    "heading": heading,
                    "heading_path": heading_path,
                    "doc_type": doc_type,
                    "product": product,
                    "version": version,
                    "content_type": parsed_document.content_type,
                    "content": build_chunk_text(parsed_document.display_title, heading_path, chunk_body),
                }
            )
    return chunks
