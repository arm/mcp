# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared lexical analysis with explicit, resource-local product synonyms."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Sequence

_DELIMITERS = re.compile(r"[_\-.]+")
_PROSE_COMPOUND = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+[.]?")
_RAW_TOKEN = re.compile(r"(?:_+)?[a-z0-9][a-z0-9_\-+.]*", re.IGNORECASE)
# Keep identifier punctuation; a terminal prose colon is a phrase boundary.
_TOKEN = re.compile(
    r"(?:[._]+)?[a-z0-9](?:[a-z0-9_\-+.#\[\]]|:(?=[a-z0-9_\-+.#:\[\]]))*\(?|[^\w\s]",
    re.IGNORECASE,
)
# Inline and reference link labels are prose; attached identifier brackets stay protected.
_LINK_LABEL = re.compile(
    r"(?<![\w\\.\]\)])\[([^\[\]\\\n]+)\](?:"
    r"(?=\([^\n)]*\))|\[[^\[\]\\\n]*\])"
)
_REFERENCE_DEFINITION = re.compile(r"^ {0,3}\[([^\[\]\\\n]+)\]:[ \t]*\S", re.MULTILINE)
_SHORTCUT_LABEL = re.compile(r"(?<![\w\\.\[\]\)])\[([^\[\]\\\n]+)\](?![\[(:])")
_FORM = re.compile(r"[a-z0-9]+(?:[ \t_\-.]+[a-z0-9]+)*", re.IGNORECASE)
_CODE_PART = re.compile(r"^(?:(?:sv)?(?:u?int|float|poly|bfloat|mfloat|[subfp]|bf|mf)?\d+|[a-z])$")


def basic_tokens(text: str) -> list[str]:
    text = text or ""
    if "](" in text or "][" in text:
        text = _LINK_LABEL.sub(r"[ \1 ]", text)
    if "]:" in text:
        # A bare [name] is prose only when a matching reference is defined.
        definitions = {" ".join(label.lower().split()) for label in _REFERENCE_DEFINITION.findall(text)}
        if definitions:
            text = _SHORTCUT_LABEL.sub(
                lambda match: f"[ {match[1]} ]" if " ".join(match[1].lower().split()) in definitions else match[0],
                text,
            )
    return [token.lower() for token in _TOKEN.findall(text)]


def delimit(token: str) -> list[str]:
    """Retain whole terms while exposing prose parts, excluding lane/type fragments."""
    if token.isalnum() or token.startswith(("_", ".")):
        return [token]
    parts = [part for part in _DELIMITERS.split(token) if part]
    if len(parts) < 2 or any(_CODE_PART.fullmatch(part) for part in parts):
        return [token]
    return list(dict.fromkeys([token, *parts]))


@lru_cache(maxsize=8192)
def _literal_tokens(token: str, expand: bool) -> tuple[str, ...]:
    return tuple(part for word in _RAW_TOKEN.findall(token)
                 for part in (delimit(word) if expand else [word]))


def canonical_key(name: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", name.lower()))


def atom(key: str) -> str:
    return "__name_" + key


@lru_cache(maxsize=8192)
def valid_form(form: str) -> bool:
    if form.isascii() and form.isalnum():
        return True
    return bool(_FORM.fullmatch(form)) and not re.search(r"(?:^|\s)\.[a-z]", form, re.IGNORECASE)


class Synonyms:
    """Declared names and aliases with equivalent component separators."""

    def __init__(self, rules: Mapping[str, Sequence[str]]):
        if not isinstance(rules, dict) or any(
            not isinstance(key, str) or not re.fullmatch(r"[a-z0-9]+", key)
            or not isinstance(forms, list) or not forms
            or any(not isinstance(form, str) or not valid_form(form) for form in forms)
            for key, forms in rules.items()
        ):
            raise ValueError("Synonym table must map lowercase alphanumeric keys to nonempty lists of name spellings")
        self.keys = frozenset(rules)
        self._single = {}
        self._gaps = {}
        self._prefixes = set()
        for canonical, forms in rules.items():
            for form in forms:
                joined, gaps = self._parts(form)
                owner = self._single.setdefault(joined, canonical)
                if owner != canonical:
                    raise ValueError(f"Synonym form {form!r} claimed by {owner!r} and {canonical!r}")
                self._gaps.setdefault(joined, set()).add(gaps)
                self._prefixes.update(joined[:position] for position in gaps)

    def __len__(self) -> int:
        return len(self.keys)

    @staticmethod
    @lru_cache(maxsize=8192)
    def _parts(text: str):
        if text.isalnum():
            return text.lower(), frozenset()
        parts = re.split(r"[ \t_\-.]+", text.lower())
        positions = set()
        end = 0
        for part in parts[:-1]:
            end += len(part)
            positions.add(end)
        return "".join(parts), frozenset(positions)

    def _match(self, tokens: Sequence[str], start: int):
        token = tokens[start].rstrip(".")
        if token.isalnum() and token not in self._single and token not in self._prefixes:
            return 0, None
        joined, gaps = "", set()
        best = (0, None)
        for end in range(start, len(tokens)):
            token = tokens[end].rstrip(".")
            if joined and tokens[end] in {"-", "_"}:
                continue
            if not valid_form(token):
                break
            part, positions = self._parts(token)
            offset = len(joined)
            if offset:
                gaps.add(offset)
            gaps.update(offset + position for position in positions)
            joined += part
            if joined in self._single and frozenset(gaps) in self._gaps[joined]:
                best = (end - start + 1, self._single[joined])
            # A period can end a complete name, but cannot join two sentences.
            if tokens[end].endswith(".") or joined not in self._prefixes:
                break
        return best

    @lru_cache(maxsize=8192)
    def _nested_names(self, tokens: tuple[str, ...]) -> tuple[str, ...]:
        # Only expand an already recognized name, never arbitrary identifier fragments.
        parts = re.split(r"[ \t_\-.]+", " ".join(tokens).rstrip("."))
        names = []
        for start in range(len(parts)):
            for end in range(start + 1, len(parts) + 1):
                size, key = self._match(parts[start:end], 0)
                if size == end - start:
                    names.append(atom(key))
        return tuple(dict.fromkeys(names))

    def apply(self, tokens: Sequence[str], *, replace_aliases: bool = False) -> list[str]:
        """Keep name words for documents and name-only queries; balance mixed queries."""
        out = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token.isascii() and token.isalnum() and token not in self._single and token not in self._prefixes:
                out.append(token)
                i += 1
                continue
            size, canonical = self._match(tokens, i)
            if not size:
                # Document parts support prose searches; query identifiers stay literal.
                # These parts never pass through synonym matching again.
                expand = not replace_aliases or bool(_PROSE_COMPOUND.fullmatch(token))
                out.extend(_literal_tokens(token, expand))
                i += 1
                continue
            alias = size == 1 and canonical_key(tokens[i]) != canonical
            words = [] if replace_aliases and (alias or size < len(tokens)) else [
                word for token in tokens[i:i + size] for word in delimit(token.rstrip("."))
                if word not in {canonical, "-", "_", "", "."}]
            nested = self._nested_names(tuple(tokens[i:i + size])) if not replace_aliases else ()
            out.extend(dict.fromkeys([*words, atom(canonical), *nested]))
            i += size
        return out

    @classmethod
    def load(cls, path: str | Path) -> "Synonyms":
        with open(path, encoding="utf-8") as stream:
            return cls(json.load(stream))


EMPTY = Synonyms({})


def analyze_tokens(tokens: Sequence[str], synonyms: Synonyms = EMPTY, *, query: bool = False) -> list[str]:
    return synonyms.apply(tokens, replace_aliases=query)


def analyze(text: str, synonyms: Synonyms = EMPTY, *, query: bool = False) -> list[str]:
    return analyze_tokens(basic_tokens(text), synonyms, query=query)


def name_keys(tokens: Iterable[str], synonyms: Synonyms = EMPTY) -> frozenset[str]:
    return frozenset(token[7:] for token in tokens if token.startswith("__name_") and token[7:] in synonyms.keys)
