# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exclude Markdown link metadata without rewriting visible code identifiers."""

import re
from functools import lru_cache

from markdown_it import MarkdownIt
from markdown_it.rules_block import reference
from markdown_it.rules_inline import image, link

_ATTACHED = re.compile(r"[\w\\.\]\)]")
_REFERENCE_LINK = re.compile(r"\[([^\[\]\\\n]+)\]\[[^\[\]\\\n]*\]")


def _reference(state, start, end, silent):
    pos = state.bMarks[start] + state.tShift[start]
    # In the source corpus, GitHub footnotes contain visible explanatory prose.
    if state.src.startswith("[^", pos):
        return False
    return reference(state, start, end, silent)


def _link(state, silent, *, is_image=False):
    start = state.pos
    depth = state.env.get("search_link_depth", 0)
    if depth >= state.md.options["maxNesting"]:
        return False
    attached = not is_image and start and _ATTACHED.fullmatch(state.src[start - 1])
    bracket = start + int(is_image)
    if bracket >= state.posMax or state.src[bracket] != "[":
        return False
    label_end = state.md.helpers.parseLinkLabel(state, bracket, not is_image)
    if label_end < 0:
        return False
    if not (image if is_image else link)(state, True):
        # Chunks can retain a full/collapsed label without its definition.
        # Keep the established label behavior, never invent a shortcut link.
        match = _REFERENCE_LINK.match(state.src, bracket, state.posMax)
        if not match or attached:
            state.pos = start
            return False
        state.pos = match.end()
    if not silent:
        label = state.src[bracket + 1:label_end]
        if "](" in label or "][" in label:
            children = []
            state.md.inline.parse(label, state.md, {**state.env, "search_link_depth": depth + 1}, children)
            label = _inline_text(label, children)
        token = state.push("search_link", "", 0)
        token.content = "[" + label + "]" if attached else "[ " + label + " ]"
        token.meta = {"start": start, "end": state.pos}
    return True


def _image(state, silent):
    return _link(state, silent, is_image=True)


_MARKDOWN = MarkdownIt("commonmark", {"inline_definitions": True})
_MARKDOWN.block.ruler.at("reference", _reference)
_MARKDOWN.inline.ruler.at("link", _link)
_MARKDOWN.inline.ruler.at("image", _image)


def _inline_text(content, children):
    parts = []
    start = 0
    for child in children or ():
        if child.type == "search_link":
            parts.extend((content[start:child.meta["start"]], child.content))
            start = child.meta["end"]
    parts.append(content[start:])
    return "".join(parts)


@lru_cache(maxsize=2048)
def _markdown_text(text):
    lines = text.splitlines(keepends=True)
    parts = []
    for token in _MARKDOWN.parse(text):
        if token.type == "inline":
            parts.append(_inline_text(token.content, token.children))
        elif token.type in {"fence", "code_block", "html_block"}:
            # Keep code markers as well as their content: cleanup is idempotent,
            # and reference-like examples cannot become definitions on a second pass.
            parts.append("".join(lines[token.map[0]:token.map[1]]))
    return "\n\n".join(parts)


def searchable_text(text: str) -> str:
    """Share visible evidence between name recognition and phrase scoring."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if any(marker in text for marker in ("]:", "](", "][")):
        return _markdown_text(text)
    return text
