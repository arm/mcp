# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""MCP presentation helpers and a fixed, offline Learning Path catalog."""

import re
from typing import Any

MAX_CHARS = 80000
_ROOT = re.compile(r"^(https://learn\.arm\.com/learning-paths/[^/?#]+/[^/?#]+/)")
_FENCES = re.compile(r"```.*?```", re.DOTALL)
_SHELL_LINE = re.compile(r"^\s*(?:sudo |export |\$ ).*$", re.MULTILINE)
_NAV_FRAGMENTS = ("learning-path-step-active", "learning-path-title", "ads-masthead-title")
_NAV_HEADINGS = {"what you've accomplished", "what you’ve accomplished", "share", "give feedback",
                 "continue learning", "frequently asked questions"}
_NOTE = "Cite page URLs exactly as shown. Content derived from arm.com materials and subject to the source terms."
_HINT = "pass the learning_path field from a knowledge_base_search result"


def _page_identity(url: str) -> str:
    return url.split("#", 1)[0].split("?", 1)[0].rstrip("/")


def learning_path_root(url: str, *, normalize_missing_slash: bool = False) -> str | None:
    """Resolve only anchored HTTPS Learning Paths, never query/fragment contents."""
    clean = url.split("#", 1)[0].split("?", 1)[0]
    match = _ROOT.match(clean.rstrip("/") + "/" if normalize_missing_slash else clean)
    return match.group(1) if match else None


def strip_snippet_prefix(snippet: str) -> str:
    lines = snippet.split("\n")
    i = 0
    while i < len(lines) and (lines[i].startswith("Document Title:")
                             or lines[i].startswith("Heading Path:") or not lines[i].strip()):
        i += 1
    return "\n".join(lines[i:]).strip()


def lean_result(item: dict[str, Any]) -> dict[str, Any]:
    """Copy presentation fields without mutating shared search results or ranking."""
    result = {key: value for key, value in item.items()
              if key not in {"disclaimer", "url_tracking_instruction", "distance"}}
    if "snippet" in result:
        result["snippet"] = strip_snippet_prefix(result["snippet"])
    root = learning_path_root(item.get("url") or "")
    if root:
        result["learning_path"] = root
    return result


def _headings(row: dict) -> list[str]:
    return row.get("heading_path") or []


def _is_nav(row: dict) -> bool:
    headings = [heading.lower() for heading in _headings(row)]
    fragment = row["url"].partition("#")[2]
    return (any(marker in fragment for marker in _NAV_FRAGMENTS)
            or headings == ["about this learning path"]
            or bool(headings and headings[-1] in _NAV_HEADINGS)
            or _page_identity(row["url"]).endswith("/_next-steps"))


def _order_field(row: dict, name: str):
    context = row.get("document_context") or {}
    value = context.get(name, row.get(name))
    return value if type(value) is int and value >= 0 else None


def _chunk_key(row: dict) -> tuple:
    position = _order_field(row, "chunk_index")
    headings = _headings(row)
    heuristic = (" > ".join(headings[:1]), len(headings), " > ".join(headings))
    return (0, position, heuristic) if position is not None else (1, 0, heuristic)


def _commands(text: str) -> str:
    """Keep fenced blocks intact; scan shell lines only outside those blocks."""
    parts = []
    start = 0
    for match in _FENCES.finditer(text):
        parts.extend(line.group().strip("\n") for line in _SHELL_LINE.finditer(text[start:match.start()]))
        parts.append(match.group())
        start = match.end()
    parts.extend(line.group().strip("\n") for line in _SHELL_LINE.finditer(text[start:]))
    return "\n".join(parts)


class LearningPathIndex:
    """Group and prepare shipped metadata once; requests only read the snapshot."""

    def __init__(self, resources):
        grouped: dict[str, list[dict]] = {}
        for row in resources.metadata:
            types = row.get("doc_type", [])
            if isinstance(types, str):
                types = [types]
            root = learning_path_root(row.get("url") or "")
            if root and "Learning Paths" in types:
                grouped.setdefault(root, []).append(row)
        self.paths = {}
        for root, rows in grouped.items():
            manifest = {}
            for row in rows:
                context = row.get("document_context") or {}
                pages = context.get("learning_path_pages", row.get("learning_path_pages"))
                if isinstance(pages, list):
                    for i, url in enumerate(pages):
                        if isinstance(url, str):
                            manifest.setdefault(_page_identity(url), i)
            pages = {}
            seen = set()
            for row in rows:
                if _is_nav(row):
                    continue
                identity = _page_identity(row["url"])
                text = resources.snippet_for(row)
                parent = (row.get("parent_uuid"), row.get("parent_chunk_uuid"))
                if all(parent):
                    key = (identity, "parent", parent, text)
                else:
                    key = (identity, "chunk", row.get("chunk_uuid"), _order_field(row, "chunk_index"),
                           tuple(_headings(row)), text)
                if key in seen:
                    continue
                seen.add(key)
                page = pages.setdefault(identity, {"row": row, "chunks": []})
                page["chunks"].append((row, text))
            def page_key(item, root=root, manifest=manifest):
                identity, page = item
                if identity == root.rstrip("/"):
                    return (0, 0, "")
                row = page["row"]
                stored = manifest.get(identity)
                if stored is None:
                    stored = _order_field(row, "page_index")
                if stored is not None:
                    return (1, stored, identity)
                try:
                    step = int(row.get("version", ""))
                except (ValueError, TypeError):
                    step = 500
                return (1, step, identity)
            prepared = []
            for _, page in sorted(pages.items(), key=page_key):
                row = page["row"]
                prepared.append({"url": row["url"].split("#", 1)[0], "title": row.get("title", ""),
                                 "chunks": sorted(page["chunks"], key=lambda pair: _chunk_key(pair[0]))})
            root_row = next((row for row in rows if _page_identity(row["url"]) == root.rstrip("/")), rows[0])
            self.paths[root] = (root_row.get("title", ""), prepared)

    def get(self, url: str, mode: str = "full", page: str | None = None) -> dict:
        root = learning_path_root(url, normalize_missing_slash=True)
        if not root or root not in self.paths:
            return {"error": f"no Learning Path found for {url}", "hint": _HINT}
        if mode not in {"full", "commands", "outline"}:
            return {"error": f"invalid mode: {mode}", "hint": "use full, commands, or outline"}
        if page is None and _page_identity(url) != root.rstrip("/"):
            page = url
        title, pages = self.paths[root]
        if page is not None:
            pages = [item for item in pages if _page_identity(item["url"]) == _page_identity(page)]
        if not pages:
            return {"error": f"no Learning Path found for {page or url}", "hint": _HINT}
        outline = "\n".join(f"- Page {i}: {item['title']} — {item['url']} "
                            f"({sum(len(text) for _, text in item['chunks'])} chars)"
                            for i, item in enumerate(pages, 1))
        note = _NOTE
        if mode == "outline":
            text = outline
        elif mode == "commands":
            text = "\n".join(commands for item in pages for _, source in item["chunks"]
                             if (commands := _commands(strip_snippet_prefix(source))))
            note += " Page URLs: " + ", ".join(item["url"] for item in pages)
        else:
            blocks = [f"# {title}\n{root}"]
            for i, item in enumerate(pages, 1):
                blocks.append(f"## Page {i}: {item['title']}\n{item['url']}")
                for row, source in item["chunks"]:
                    blocks.append(f"### {' > '.join(_headings(row))}\n{strip_snippet_prefix(source)}")
            text = "\n\n".join(blocks)
        if len(text) > MAX_CHARS:
            text = outline
            mode = "outline"
            note = _NOTE + f" Requested text exceeds {MAX_CHARS} chars; call get_learning_path again with page=<url> from this outline."
        return {"learning_path": root, "mode": mode, "page": page, "chars": len(text), "text": text, "note": note}
