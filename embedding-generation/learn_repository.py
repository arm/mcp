"""Read Learn's published source repositories without fetching rendered pages.

Each repository is resolved once per acquisition. Only Markdown and Insights
JSON are retained from its commit-pinned archive; assets are streamed past.
"""

import datetime as dt
import html
import json
import os
import posixpath
import re
import shlex
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urljoin, urlsplit

import requests
import yaml
from markdown_it import MarkdownIt

from document_chunking import parse_html, split_frontmatter

SITE = "https://learn.arm.com"
REPOSITORIES = {
    "learning_paths": "ArmDeveloperEcosystem/arm-learning-paths",
    "courses": "ArmDeveloperEcosystem/courses",
    "insights": "ArmDeveloperEcosystem/insights",
}
SHORTCODE = re.compile(r"\{\{[<%]\s*(.*?)\s*[>%]\}\}", re.S)
TAGS = (
    "subjects",
    "armips",
    "operatingsystems",
    "tools_software_languages",
    "skilllevels",
    "tags",
    "additional_search_terms",
)


def _image_caption(tokens, index, options, env):
    # Hugo displays the optional image title as its caption. Asset URLs and
    # layout hints in alt text are not instructional prose or citation links.
    return html.escape(tokens[index].attrGet("title") or "")


_MARKDOWN = MarkdownIt("commonmark", {"html": True}).enable("table")
_MARKDOWN.renderer.rules["image"] = _image_caption


def parse_repository_markdown(markdown, source_url, resolved_url, title):
    """Use the shared content parser on locally rendered source Markdown.

    Rendering is entirely in memory: no website or image requests are made.
    This keeps paragraphs, lists, links, tables and code consistent with HTML
    acquisition instead of embedding Markdown syntax and image addresses.
    """
    tokens = _MARKDOWN.parse(markdown)
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        inline = tokens[index + 1]
        anchor = re.search(r"\s+\{#([^}]+)\}\s*$", inline.content)
        if anchor:
            token.attrSet("id", anchor[1])
            inline.content = inline.content[: anchor.start()]
            inline.children = _MARKDOWN.parseInline(inline.content)[0].children
    document = parse_html(
        _MARKDOWN.renderer.render(tokens, _MARKDOWN.options, {}),
        source_url,
        resolved_url,
        title,
        use_heading_levels=True,
    )
    document.content_type = "markdown"
    return document


def is_learn_url(url):
    return urlsplit(url).hostname == "learn.arm.com"


def public_url(path):
    parsed = urlsplit(urljoin(SITE + "/", path))
    if parsed.scheme not in {"http", "https"} or parsed.netloc != "learn.arm.com":
        raise ValueError(f"Not a Learn page URL: {path}")
    return SITE + quote(unquote(parsed.path).rstrip("/") + "/", safe="/-._~")


def read_archive(stream):
    """Read source bytes without extracting archive paths to the filesystem."""
    files = {}
    with tarfile.open(fileobj=stream, mode="r|gz") as archive:
        for member in archive:
            path = member.name.partition("/")[2]
            if not (
                (path.startswith("content/") and path.endswith(".md"))
                or (path.startswith("data/insights/") and path.endswith(".json"))
                or path == "layouts/shortcodes/comparison-results-table.html"
            ):
                continue
            if not member.isfile() or ".." in PurePosixPath(path).parts:
                raise ValueError(f"Invalid Learn source archive member: {path}")
            if member.size > 16 * 1024 * 1024 or path in files:
                raise ValueError(f"Oversized or duplicate Learn source: {path}")
            files[path] = archive.extractfile(member).read().decode("utf-8-sig")
    if not files:
        raise ValueError("Learn repository archive contains no source content")
    return files


def acquire_repository(kind, session, token=""):
    repository = REPOSITORIES[kind]
    ref = os.getenv(f"LEARN_{kind.upper()}_REF", "production")
    # Keep credentials on GitHub API requests only. requests removes the header
    # on cross-host redirects to the archive download URL.
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    api = f"https://api.github.com/repos/{repository}"
    try:
        response = session.get(
            f"{api}/commits/{quote(ref, safe='')}", headers=headers, timeout=60
        )
        response.raise_for_status()
        revision = response.json()["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError(f"Invalid Learn repository revision: {repository}")
        with session.get(
            f"{api}/tarball/{revision}", headers=headers, timeout=(30, 180), stream=True
        ) as archive:
            archive.raise_for_status()
            files = read_archive(archive.raw)
    except (requests.RequestException, KeyError):
        # Do not expose signed redirect URLs or credentials in build logs.
        raise ValueError(
            f"Cannot acquire {repository} at {ref}; check LEARN_GITHUB_TOKEN read access and the ref"
        ) from None
    print(f"[LEARN SOURCE] {repository}@{revision}: {len(files)} source files")
    snapshot = Repository(repository, revision, files)
    families = (
        ("learning-paths", "install-guides") if kind == "learning_paths" else (kind,)
    )
    for family in families:
        if not any(path.startswith(f"content/{family}/") for path in snapshot.pages):
            raise ValueError(
                f"Learn snapshot has no published {family} pages: {repository}@{revision}"
            )
    return snapshot


@dataclass
class Page:
    path: str
    url: str
    metadata: dict
    body: str

    @property
    def title(self):
        return self.metadata.get("title") or PurePosixPath(self.path).stem

    @property
    def keywords(self):
        result = [self.title]
        for tag in TAGS:
            values = self.metadata.get(tag, [])
            result.extend(values if isinstance(values, list) else [values])
        return list(dict.fromkeys(str(v) for v in result if v))


def is_published(metadata, now):
    if str(metadata.get("draft", "")).lower() == "true":
        return False
    if metadata.get("_build", {}).get("render") == "never":
        return False
    publication = metadata.get(
        "publishdate", metadata.get("publishDate", metadata.get("date"))
    )
    expiry = metadata.get("expirydate", metadata.get("expiryDate"))
    for key, value in (("publishdate", publication), ("expirydate", expiry)):
        if not value:
            continue
        try:
            date = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            # Hugo also accepts RFC 822 dates; don't silently publish unknown dates.
            raise ValueError(f"Unsupported Learn publication date: {value}") from None
        date = date.replace(tzinfo=date.tzinfo or dt.timezone.utc)
        if (key.lower() == "expirydate" and date <= now) or (
            key.lower() != "expirydate" and date > now
        ):
            return False
    return True


class Repository:
    def __init__(self, repository, revision, files, *, now=None):
        self.repository, self.revision, self.files = repository, revision, files
        self.pages = {}
        self.by_url = {}
        now = now or dt.datetime.now(dt.timezone.utc)
        parsed = {}
        for path, source in sorted(files.items()):
            if not path.startswith("content/") or not path.endswith(".md"):
                continue
            # Hugo accepts leading blank lines before YAML frontmatter. Keep
            # that tolerance local to repository pages; otherwise a title (or
            # draft flag) can be mistaken for instructional Markdown.
            source = re.sub(r"\A(?:[ \t]*\r?\n)+", "", source.lstrip("\ufeff"))
            frontmatter, body = split_frontmatter(source)
            metadata = (
                yaml.load(frontmatter, Loader=yaml.BaseLoader) if frontmatter else {}
            )
            if not isinstance(metadata, dict):
                raise ValueError(f"{path}: expected frontmatter mapping")
            parsed[path] = (metadata, body)
        for path, (metadata, body) in parsed.items():
            inherited = {}
            for parent in reversed(PurePosixPath(path).parents):
                ancestor = parsed.get(str(parent / "_index.md"))
                if ancestor and isinstance(ancestor[0].get("cascade"), dict):
                    inherited.update(ancestor[0]["cascade"])
            metadata = inherited | metadata
            if not is_published(metadata, now):
                continue
            relative = path.removeprefix("content/")
            filename = PurePosixPath(relative).name
            route = relative[:-3]
            if filename in {"_index.md", "index.md"}:
                route = str(PurePosixPath(relative).parent)
                if route == ".":
                    route = ""
            elif metadata.get("slug"):
                route = posixpath.join(posixpath.dirname(route), metadata["slug"])
            url = public_url(metadata.get("url") or "/" + route + "/")
            page = Page(path, url, metadata, body)
            self.pages[path] = page
            if url in self.by_url:
                raise ValueError(f"Duplicate canonical Learn URL: {url}")
            self.by_url[url] = page
        # Some authored legacy aliases conflict with each other. They must not
        # shadow canonical URLs or choose an arbitrary page on lookup.
        self.ambiguous_aliases = set()
        aliases = {}
        for page in self.pages.values():
            for alias in page.metadata.get("aliases", []):
                alias = public_url(alias)
                if alias in self.by_url:
                    continue
                if alias in aliases and aliases[alias].path != page.path:
                    self.ambiguous_aliases.add(alias)
                aliases[alias] = page
        self.by_url.update(
            {
                url: page
                for url, page in aliases.items()
                if url not in self.ambiguous_aliases
            }
        )

    def resolved_url(self, path):
        return f"https://raw.githubusercontent.com/{self.repository}/{self.revision}/{quote(path)}"

    def selected_pages(self, url):
        page = self.by_url.get(public_url(url))
        if page is None:
            raise ValueError(
                f"Learn source is missing or unpublished in {self.repository}@{self.revision}: {url}"
            )
        if PurePosixPath(page.path).name != "_index.md":
            return [page]
        prefix = page.path.removesuffix("_index.md")
        descendants = [p for p in self.pages.values() if p.path.startswith(prefix)]
        # Directory ancestry, not URL shape, defines course/module membership.
        return sorted(descendants, key=lambda p: (p.path != page.path, p.path))

    def ref_url(self, page, target):
        path, _, fragment = target.partition("#")
        candidates = [
            "content/" + path.lstrip("/"),
            posixpath.normpath(posixpath.join(posixpath.dirname(page.path), path)),
        ]
        for candidate in candidates:
            for possible in (
                candidate,
                candidate + ".md",
                candidate.rstrip("/") + "/_index.md",
            ):
                if possible in self.pages:
                    return self.pages[possible].url + (
                        "#" + fragment if fragment else ""
                    )
        raise ValueError(f"{page.path}: unresolved Hugo reference {target}")

    def markdown(self, page, body):
        """Retain callout text, code tabs, links and embedded example source."""
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        body = re.sub(
            r"\{\{[<%]\s*knowledge-check-completion\s*[>%]\}\}.*?\{\{[<%]\s*/knowledge-check-completion\s*[>%]\}\}",
            "",
            body,
            flags=re.S,
        )
        # Mark quiz alternatives explicitly so incorrect choices aren't ingested
        # as standalone recommendations.
        body = re.sub(
            r"^[-*] \[([xX ])\] (.+)$",
            lambda m: (
                "- "
                + ("Correct answer: " if m[1].lower() == "x" else "Incorrect answer: ")
                + m[2]
            ),
            body,
            flags=re.M,
        )
        tab_languages = []
        code_tabs = []

        def shortcode(match):
            raw = match[1].strip()
            if raw.startswith("/*") and raw.endswith("*/"):
                return match[0].replace("/*", "", 1).replace("*/", "", 1)
            closing = raw.startswith("/")
            parts = shlex.split(raw.lstrip("/").strip())
            if not parts:
                return ""
            name = parts[0]
            args = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
            if name in {"relref", "ref"}:
                return self.ref_url(page, parts[1])
            if name == "knowledge-check":
                return (
                    "\n\n" if closing else "\n\nQuestion: " + args["question"] + "\n\n"
                )
            if name == "course-survey":
                return ""
            if name == "comparison-results-table":
                template = self.files.get(
                    "layouts/shortcodes/comparison-results-table.html", ""
                )
                rows = re.findall(
                    r'\(dict "area" "([^"\n]+)" "decision" "([^"\n]+)"\)', template
                )
                if not rows:
                    raise ValueError(
                        f"{page.path}: unsupported comparison table source format"
                    )
                return (
                    "\n\n| Investigation area | What it helps you decide |\n| --- | --- |\n"
                    + "\n".join(f"| {area} | {decision} |" for area, decision in rows)
                    + "\n\n"
                )
            if name == "notice":
                return "\n\n" if closing else "\n\n" + " ".join(parts[1:]) + ":\n\n"
            if name in {"tabpane", "tabpane-normal"}:
                if closing:
                    tab_languages.pop()
                else:
                    tab_languages.append(args.get("language", ""))
                return "\n\n"
            if name == "tab":
                language = args.get(
                    "language", tab_languages[-1] if tab_languages else ""
                )
                if closing:
                    return "\n```\n\n" if code_tabs.pop() else "\n\n"
                code_tabs.append(bool(language))
                title = args.get("header", args.get("title", ""))
                return (
                    "\n\n"
                    + (title + ":\n\n" if title else "")
                    + ("```" + language + "\n" if language else "")
                )
            if name == "godbolt":
                source = args.get("src", "").replace("\\n", "\n")
                options = " ".join(
                    args.get(k, "") for k in ("opt", "lopt", "ropt")
                ).strip()
                return f"\n\nCompiler Explorer options: {options}\n\n```c\n{source}\n```\n\n"
            if name == "youtube-nocookie":
                return f"[Video](https://www.youtube.com/watch?v={parts[1]})"
            raise ValueError(f"{page.path}: unsupported Hugo shortcode {name}")

        body = SHORTCODE.sub(shortcode, body)
        # Only authored headings receive anchors; frontmatter summaries below
        # remain linked to the page rather than invented HTML element IDs.
        return heading_anchors(body)

    def documents(self, url):
        documents = []
        for page in self.selected_pages(url):
            if page.metadata.get("dataset"):
                documents.extend(self.insight_documents(page))
                continue
            body = self.markdown(page, page.body)
            introduction = (
                page.path.startswith("content/learning-paths/")
                and PurePosixPath(page.path).name == "_index.md"
            )
            overview = []
            for key, label in (
                ("description", "Description"),
                ("who_is_this_for", "Audience"),
                ("target_audience", "Audience"),
                ("what_youll_build", "What you'll build"),
                ("learning_objectives", "Learning objectives"),
                ("outcomes", "Outcomes"),
                ("prerequisites", "Prerequisites"),
            ):
                value = page.metadata.get(key)
                if value:
                    rendered = (
                        "\n".join(f"- {item}" for item in value)
                        if isinstance(value, list)
                        else value
                    )
                    if introduction:
                        label = {
                            "Audience": "Who is this for?",
                            "Learning objectives": "What will you learn?",
                        }.get(label, label)
                        overview.append(f"### {label}\n\n{rendered}")
                    else:
                        overview.append(f"{label}:\n{rendered}")
            faq = page.metadata.get("generated_summary_faq") or {}
            if faq.get("summary"):
                heading = (
                    "### Summary {#generated-summary-faq}\n\n"
                    if introduction
                    else "Summary: "
                )
                overview.append(heading + faq["summary"])
            if introduction and faq.get("faqs"):
                overview.append(
                    "### Frequently asked questions {#generated-summary-faq}"
                )
            for entry in faq.get("faqs", []):
                if introduction:
                    question = re.sub(r"\s+", " ", entry["question"]).strip()
                    overview.append(f"#### {question}\n\n{entry['answer']}")
                else:
                    overview.append(f"Question: {entry['question']}\n\n{entry['answer']}")
            for entry in page.metadata.get("further_reading", []):
                resource = entry.get("resource", {})
                if (
                    isinstance(resource, dict)
                    and resource.get("title")
                    and resource.get("link")
                ):
                    heading = (
                        "### Further reading {#about-marker}\n\n"
                        if introduction else "Further reading: "
                    )
                    overview.append(heading + f"[{resource['title']}]({resource['link']})")
            if introduction and body.strip() and overview:
                body = "## About this Learning Path {#about-marker}\n\n" + body
            text = "\n\n".join([*overview, body]).strip()
            if not text:
                continue
            if introduction:
                # Match the published introduction sections and anchor targets.
                # Do not combine all prerequisites, summary and FAQ answers into
                # one broad retrieval passage, or invent anchors for questions.
                text = "## About this Learning Path {#about-marker}\n\n" + text
            document = parse_repository_markdown(
                text, page.url, self.resolved_url(page.path), page.title
            )
            document.display_title = page.title
            if (
                page.path.startswith("content/learning-paths/")
                and PurePosixPath(page.path).name != "_index.md"
            ):
                # Hugo renders the page title outside .Content. Introductory
                # sections still cite that public heading, as HTML parsing did.
                for section in document.sections:
                    if not section.url_fragment:
                        section.url_fragment = "learning-path-title"
            documents.append(document)
        return documents

    def insight_documents(self, page):
        path = f"data/insights/{page.metadata['dataset']}.json"
        if path not in self.files:
            raise ValueError(f"Missing Insights dataset: {path}")
        dataset = json.loads(self.files[path])
        if dataset.get("schema_version") != 1 or not isinstance(
            dataset.get("entries"), list
        ):
            raise ValueError(f"Unsupported Insights dataset schema: {path}")
        documents, seen = [], set()
        for entry in dataset["entries"]:
            anchor = entry.get("slug") or entry.get("id")
            if not isinstance(anchor, str) or not anchor or anchor in seen:
                raise ValueError(f"Missing or duplicate Insights answer anchor: {path}")
            seen.add(anchor)
            question, answer = entry.get("question"), entry.get("answer")
            if (
                not isinstance(question, str)
                or not question.strip()
                or not isinstance(answer, str)
                or not answer.strip()
            ):
                raise ValueError(f"Invalid Insights question/answer: {path}#{anchor}")
            document = parse_repository_markdown(
                answer, page.url, self.resolved_url(path), page.title
            )
            document.display_title = page.title
            # Each answer is separate, even when two questions share headings.
            # Point all its chunks at the public accordion, not inner headings.
            for section in document.sections:
                section.heading_path.insert(0, question)
                section.url_fragment = anchor
            documents.append(document)
        overview = dataset.get("fundamentals", {}).get("paragraphs", [])
        if overview:
            document = parse_repository_markdown(
                "\n\n".join(overview), page.url, self.resolved_url(path), page.title
            )
            for section in document.sections:
                section.url_fragment = "insight-overview-title"
            documents.insert(0, document)
        return documents

    def discovered_sources(self):
        for page in self.pages.values():
            parts = PurePosixPath(page.path).parts
            family = parts[1] if len(parts) > 1 else ""
            if (
                family == "learning-paths"
                and len(parts) == 5
                and parts[-1] == "_index.md"
            ):
                site, label = "Learning Paths", "Learning Path"
            elif family == "install-guides" and (
                str(page.metadata.get("tool_install", "")).lower() == "true"
                or str(page.metadata.get("multitool_install_part", "")).lower()
                == "true"
            ):
                site, label = "Install Guides", "Install Guide"
            elif family == "courses" and len(parts) == 4 and parts[-1] == "_index.md":
                site = label = "Educational Course"
            elif family == "insights" and len(parts) == 4 and parts[-1] == "_index.md":
                site = label = "Insights"
            else:
                continue
            yield dict(
                site_name=site,
                license_type=page.metadata.get("license")
                or ("CC-BY-SA-4.0" if family == "insights" else "CC4.0"),
                display_name=f"{label} - {page.title}",
                url=page.url,
                keywords=page.keywords
                + (
                    ["install", "build", "download"]
                    if family == "install-guides"
                    else []
                ),
            )


def heading_anchors(markdown):
    """Goldmark's default heading IDs, with duplicate suffixes; leave code alone."""
    seen, lines = {}, []
    fence = None
    for line in markdown.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif fence == marker[1][0]:
                fence = None
        heading = (
            re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line) if fence is None else None
        )
        if heading:
            title = heading[2]
            attributes = re.search(r"\s+\{([^{}]*)\}\s*$", title)
            explicit_id = None
            if attributes and re.match(r"[#.]|[\w-]+=", attributes[1]):
                identifier = re.search(r"(?:^|\s)#([^\s]+)", attributes[1])
                explicit_id = identifier[1] if identifier else None
                title = title[: attributes.start()].rstrip()
            plain_title = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", title)
            plain_title = html.unescape(re.sub(r"<[^>]*>", "", plain_title))
            slug = "".join(
                c.lower() for c in plain_title if c.isalnum() or c in "-_" or c.isspace()
            )
            slug = re.sub(r"\s", "-", slug) or "heading"
            count = seen.get(slug, 0)
            seen[slug] = count + 1
            anchor = explicit_id or slug + ("-" + str(count) if count else "")
            line = f"{heading[1]} {title} {{#{anchor}}}"
        lines.append(line)
    return "\n".join(lines)


class LearnSources:
    def __init__(self, session, token=None):
        self.session = session
        self.token = os.getenv("LEARN_GITHUB_TOKEN", "") if token is None else token
        if token is None and not self.token and os.getenv("LEARN_GITHUB_TOKEN_FILE"):
            self.token = Path(os.environ["LEARN_GITHUB_TOKEN_FILE"]).read_text().strip()
        self.repositories = {}
        self._documents = {}

    def repository(self, kind):
        if kind not in self.repositories:
            self.repositories[kind] = acquire_repository(kind, self.session, self.token)
        return self.repositories[kind]

    def repository_for_url(self, url):
        family = urlsplit(url).path.strip("/").split("/")[0]
        kind = family if family in {"courses", "insights"} else "learning_paths"
        return self.repository(kind)

    def has_page(self, url):
        return public_url(url) in self.repository_for_url(url).by_url

    def documents(self, url):
        key = public_url(url)
        if key not in self._documents:
            self._documents[key] = self.repository_for_url(url).documents(url)
        return self._documents[key]

    def discovered_sources(self):
        for kind in REPOSITORIES:
            yield from self.repository(kind).discovered_sources()
