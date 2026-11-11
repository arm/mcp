"""Acquire courses and Insights exclusively from published Learn HTML."""

import json
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from document_chunking import parse_html

SITE = "https://learn.arm.com"


def is_public_learn_url(url):
    parsed = urlsplit(url)
    return parsed.hostname == "learn.arm.com" and parsed.path.strip("/").split("/")[
        0
    ] in {"courses", "insights"}


def _page_url(base, target):
    parsed = urlsplit(urljoin(base, target))
    if parsed.scheme not in {"http", "https"} or not is_public_learn_url(
        parsed.geturl()
    ):
        return None
    return urlunsplit(("https", "learn.arm.com", parsed.path.rstrip("/") + "/", "", ""))


def _title(soup, fallback):
    heading = soup.select_one("h1")
    if heading:
        return heading.get_text(" ", strip=True)
    meta = soup.find("meta", property="og:title")
    return meta.get("content") if meta and meta.get("content") else fallback


def _preserve_quizzes(body):
    """Convert published quiz forms to labelled instructional text."""
    for quiz in body.select("[data-knowledge-check]"):
        legend = quiz.select_one("legend")
        if legend is None or not quiz.get("id"):
            raise ValueError("Missing published course quiz question or anchor")
        section = body.new_tag("section")
        heading = body.new_tag("h2", id=quiz["id"])
        heading.string = legend.get_text(" ", strip=True)
        section.append(heading)
        for option in quiz.select(".course-knowledge-check-option"):
            choice = option.select_one("input[data-correct]")
            answer = option.select_one(".course-knowledge-check-option-text")
            if (
                choice is None
                or answer is None
                or choice["data-correct"] not in {"true", "false"}
            ):
                raise ValueError("Invalid published course quiz answer")
            label = (
                "Correct answer: "
                if choice["data-correct"] == "true"
                else "Incorrect answer: "
            )
            paragraph = body.new_tag("p")
            paragraph.string = label + answer.get_text(" ", strip=True)
            section.append(paragraph)
            feedback = option.select_one(".course-knowledge-check-option-feedback")
            if feedback:
                paragraph = body.new_tag("p")
                paragraph.string = "Feedback: " + feedback.get_text(" ", strip=True)
                section.append(paragraph)
        quiz.replace_with(section)


class PublicLearnSources:
    def __init__(self, session):
        self.session = session
        self._pages = {}

    def page(self, url):
        if url not in self._pages:
            response = self.session.get(url, timeout=60)
            response.raise_for_status()
            resolved = _page_url(url, response.url)
            if resolved is None or urlsplit(resolved).path != urlsplit(url).path:
                raise ValueError(f"Unexpected public Learn redirect for {url}")
            soup = BeautifulSoup(response.content, "html.parser")
            if not soup.find("main"):
                raise ValueError(f"Missing public Learn page content: {url}")
            self._pages[url] = (soup, resolved)
        return self._pages[url]

    def discovered_sources(self):
        for family, label, selector in (
            ("courses", "Educational Course", "[data-course-card]"),
            ("insights", "Insights", ".insights-area-card"),
        ):
            listing = f"{SITE}/{family}/"
            soup, _ = self.page(listing)
            cards = soup.select(selector)
            if not cards:
                raise ValueError(f"No published {family} found at {listing}")
            seen = set()
            for card in cards:
                link = card if card.get("link") else card.select_one("[link], a[href]")
                target = (link.get("link") or link.get("href")) if link else ""
                url = _page_url(listing, target)
                parts = urlsplit(url).path.strip("/").split("/") if url else []
                if len(parts) != 2 or parts[0] != family:
                    raise ValueError(f"Invalid public {family} card at {listing}")
                if url in seen:
                    continue
                seen.add(url)
                heading = card.select_one("h2, h3")
                title = heading.get_text(" ", strip=True) if heading else url
                yield dict(
                    site_name=label,
                    license_type="CC-BY-SA-4.0",
                    display_name=f"{label} - {title}",
                    url=url,
                    keywords=[title],
                )

    def documents(self, url):
        soup, resolved = self.page(url)
        if urlsplit(url).path.startswith("/insights/"):
            return self.insight_documents(soup, resolved)
        documents = []
        pending, seen = [url], set()
        # Follow published navigation only within the requested course/module.
        # A lesson request cannot expand to siblings through its sidebar.
        while pending:
            page_url = pending.pop(0)
            if page_url in seen:
                continue
            seen.add(page_url)
            page, resolved = self.page(page_url)
            targets = [
                tag.get("href") or tag.get("link")
                for tag in page.select("a[href], [link]")
            ]
            for tag in page.select("[data-course-lesson-order]"):
                lessons = json.loads(tag["data-course-lesson-order"])
                targets.extend(lesson["url"] for lesson in lessons)
            for target in targets:
                candidate = _page_url(page_url, target)
                if (
                    candidate
                    and candidate.startswith(url)
                    and candidate not in seen
                    and "."
                    not in urlsplit(candidate).path.rstrip("/").rsplit("/", 1)[-1]
                ):
                    pending.append(candidate)
            body = page.select_one(".course-body") or page.find("main")
            # Work on a copy so cached navigation remains available on later calls.
            body = BeautifulSoup(str(body), "html.parser")
            _preserve_quizzes(body)
            for control in body.select(
                "nav, .course-module-pager, [data-course-completion-panel], "
                "[data-course-survey], #course-syllabus, #course-license"
            ):
                control.decompose()
            document = parse_html(
                str(body),
                page_url,
                resolved,
                _title(page, page_url),
                use_heading_levels=True,
            )
            if not document.sections:
                raise ValueError(
                    f"No instructional content on public course page: {page_url}"
                )
            documents.append(document)
        return documents

    def insight_documents(self, soup, url):
        entries = soup.select(".insight-entry")
        if not entries:
            raise ValueError(f"No published Insights answers at {url}")
        title = _title(soup, url)
        documents, seen = [], set()
        overview = soup.select_one(".insight-overview")
        if overview:
            documents.append(
                parse_html(str(overview), url, url, title, use_heading_levels=True)
            )
        for entry in entries:
            anchor = entry.get("id")
            question = entry.select_one(".insight-entry__question-text")
            answer = entry.select_one(".insight-entry__answer")
            if not anchor or anchor in seen or question is None or answer is None:
                raise ValueError(f"Invalid published Insights answer at {url}")
            seen.add(anchor)
            question = question.get_text(" ", strip=True)
            document = parse_html(str(answer), url, url, title, use_heading_levels=True)
            if not question or not document.sections:
                raise ValueError(f"Empty published Insights answer at {url}#{anchor}")
            document.display_title = title
            for section in document.sections:
                section.heading_path.insert(0, question)
                section.url_fragment = anchor
            documents.append(document)
        return documents
