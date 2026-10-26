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

"""Corpus-evidenced, whole-name formatting equivalence and raw-field postings.

This module deliberately depends only on the standard library. Explicit labels
supply component boundaries; ordinary prose and URLs never create new names.
"""

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping, Optional


_MAX_COMPONENTS = 8
_MAX_LABEL_LENGTH = 80
_CONNECTORS = frozenset({"for", "on", "with", "using", "and", "or", "from", "to", "in"})
_LABEL = re.compile(r"[A-Za-z]+(?:(?:[ \t]+|[ \t]*[-_.][ \t]*)[A-Za-z]+)*")
# Starts exclude adjacent identifiers, meaningful symbols and namespaces.
_LEFT_BOUNDARY = r"(?<![\w.:+#-])"


@dataclass(frozen=True)
class NameMatch:
    """A recognized whole name and its half-open offsets in the original text."""

    key: str
    start: int
    end: int


@dataclass(frozen=True)
class NameEntry:
    """One non-conflicting component signature with all original provenance."""

    key: str
    components: tuple[str, ...]
    sources: tuple[dict[str, Any], ...]


class _TrieNode:
    __slots__ = ("children", "terminal")

    def __init__(self):
        self.children: dict[str, "_TrieNode"] = {}
        self.terminal: Optional[tuple[str, int]] = None


def _valid_right_boundary(text: str, end: int) -> bool:
    if end == len(text):
        return True
    char = text[end]
    if char.isalnum() or char in "_+#-:([":
        return False
    if char == "." and end + 1 < len(text):
        following = text[end + 1]
        if following.isalnum() or following in "_.+#-":
            return False
    return True


def _doc_type(row: Mapping[str, Any]) -> str:
    return str(row.get("doc_type") or "").strip().lower()


def _alias_parts(text):
    if (
        not isinstance(text, str)
        or len(text) > _MAX_LABEL_LENGTH
        or not _LABEL.fullmatch(text.strip())
        or re.search(r"(?:^|\s)\.[A-Za-z]", text)
    ):
        return ()
    parts = tuple(re.findall("[a-z]+", text.lower()))
    return parts if len(parts) <= _MAX_COMPONENTS else ()


def _explicit_label(row):
    kind = _doc_type(row)
    if kind == "ecosystem dashboard":
        path = row.get("heading_path")
        if (
            isinstance(path, (list, tuple))
            and len(path) > 1
            and isinstance(path[1], str)
            and path[1].strip()
        ):
            return "heading_path[1]", path[1]
        return "heading", row.get("heading")
    if kind in {"install guide", "install guides"}:
        return "title", row.get("title")
    return "", None


def _texts(value: Any) -> Iterable[str]:
    """Yield independent field/list values without introducing fake boundaries."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str):
                yield item


class NameIndex:
    """Inventory explicit names once, then match and retrieve without query caches.

    ``inventory`` maps joined lower-case keys to :class:`NameEntry` instances.
    Single-component entries are provenance only; an explicit segmented source
    must authorize matching and optional separators for a joined spelling.
    """

    def __init__(self, metadata: Iterable[Mapping[str, Any]], aliases=()):
        rows = list(metadata)
        labels: dict[str, list[tuple[tuple[str, ...], dict[str, Any]]]] = {}
        self._excluded: list[dict[str, Any]] = []
        self._label_count = 0
        self._intrinsic_count = 0
        self._explicit_labels = []
        for row_id, row in enumerate(rows):
            kind = _doc_type(row)
            if kind == "intrinsic":
                self._intrinsic_count += 1
                continue
            field, label = _explicit_label(row)
            if not isinstance(label, str) or not label.strip():
                continue
            self._label_count += 1
            self._explicit_labels.append((row_id, field, label))
            source = {"label": label, "row_id": row_id, "chunk_uuid": row.get("chunk_uuid"),
                      "url": row.get("url"), "field": field}
            stripped = label.strip(" \t")
            reason = None
            if len(stripped) > _MAX_LABEL_LENGTH:
                reason = "label_too_long"
            elif not _LABEL.fullmatch(stripped):
                reason = "unsupported_syntax"
            else:
                components = tuple(part.lower() for part in re.findall(r"[A-Za-z]+", stripped))
                if len(components) > _MAX_COMPONENTS:
                    reason = "too_many_components"
                elif field == "title" and _CONNECTORS.intersection(components):
                    reason = "prose_connector"
            if reason:
                self._excluded.append({"reason": reason, "source": source})
                continue
            key = "".join(components)
            labels.setdefault(key, []).append((components, source))

        self.inventory: dict[str, NameEntry] = {}
        for key, observations in labels.items():
            signatures = {components for components, _ in observations if len(components) > 1}
            if len(signatures) > 1:
                self._excluded.extend({"reason": "conflicting_component_signatures", "source": source}
                                      for _, source in observations)
                continue
            components = next(iter(signatures)) if signatures else (key,)
            self.inventory[key] = NameEntry(key, components, tuple(source for _, source in observations))

        self._alias_report, alias_specs, literal_specs = self._resolve_aliases(rows, aliases)
        active = [entry for entry in self.inventory.values() if len(entry.components) > 1]
        self._matcher_specs = [(entry.key, entry.components, entry.key) for entry in active] + alias_specs
        self._literal_specs = literal_specs
        self._build_matcher()

        self._postings: dict[str, dict[int, int]] = {entry.key: {} for entry in active}
        for row_id, row in enumerate(rows):
            if _doc_type(row) == "intrinsic":
                continue
            body = row.get("original_text")
            if not isinstance(body, str):
                body = row.get("content")
            # Flattened search_text has no recoverable field boundaries.
            fields = ((0, row.get("title")), (1, row.get("heading")),
                      (1, row.get("heading_path")), (2, row.get("keywords")),
                      (2, row.get("product")), (3, body))
            for priority, value in fields:
                for text in _texts(value):
                    for key in self.keys(text):
                        postings = self._postings[key]
                        postings[row_id] = min(postings.get(row_id, priority), priority)

    def _resolve_aliases(self, rows, groups):
        """Bind explicit build inputs to corpus labels; never discover aliases."""
        if not isinstance(groups, (list, tuple)):
            raise ValueError("Aliases must be a list of explicit groups")
        candidates, rejected = [], []
        labels = {row_id: label for row_id, _, label in self._explicit_labels}
        for group in groups:
            if not isinstance(group, Mapping):
                raise ValueError("Each alias group must be an object")
            canonical = _alias_parts(group.get("canonical"))
            aliases, selectors = group.get("aliases"), group.get("labels")
            provenance = group.get("provenance")
            if (len(canonical) < 2
                    or not isinstance(aliases, (list, tuple)) or not aliases
                    or not isinstance(selectors, (list, tuple)) or not selectors
                    or any(not isinstance(label, str) or not label.strip() for label in selectors)
                    or not isinstance(provenance, str) or not provenance.strip()):
                raise ValueError("Alias groups require a complete canonical name, aliases, labels and provenance")
            signatures = [_alias_parts(alias) for alias in aliases]
            if any(not parts or len("".join(parts)) < 3 for parts in signatures):
                raise ValueError("Aliases must be supported names of at least three letters")
            selected = {" ".join(label.split()).casefold() for label in selectors}
            sources = [
                dict(label=label, field=field, row_id=row_id,
                     chunk_uuid=rows[row_id].get("chunk_uuid"), url=rows[row_id].get("url"),
                     provenance=provenance)
                for row_id, field, label in self._explicit_labels
                if " ".join(label.split()).casefold() in selected
            ]
            if not sources:
                rejected.append({"reason": "no_exact_source_label", "group": dict(group)})
            for source in sources:
                bound = {"label": source["label"], "sources": [source]}
                for signature in signatures:
                    candidates.append(("".join(canonical), canonical, "".join(signature),
                                       signature, bound, source["row_id"]))
        canonical_keys = set(self.inventory) | {item[0] for item in candidates}
        owners, signatures, canonical_signatures, source_owners = {}, {}, {}, {}
        for label in labels.values():
            signature = _alias_parts(label)
            if signature:
                # Excluded conflicting names still reserve their identity.
                canonical_keys.add("".join(signature))
            if len(signature) > 1:
                canonical_signatures.setdefault("".join(signature), set()).add(signature)
        for key, canonical, _, _, _, _ in candidates:
            canonical_signatures.setdefault(key, set()).add(canonical)
        for key, _, alias, signature, group, _ in candidates:
            source_label = " ".join(group["label"].split()).casefold()
            source_owners.setdefault(source_label, set()).add(key)
            owners.setdefault(alias, set()).add(key)
            if len(signature) > 1:
                signatures.setdefault(alias, set()).add(signature)
        resolved, literal_keys = {}, {}
        for key, canonical, alias, signature, group, row_id in candidates:
            if len(canonical_signatures[key]) > 1:
                reason = "conflicting_canonical_component_signatures"
            elif len(source_owners[" ".join(group["label"].split()).casefold()]) > 1:
                reason = "conflicting_source_label_owners"
            elif alias == key and len(signature) > 1 and signature != canonical:
                reason = "alias_conflicts_with_canonical_signature"
            elif len(owners[alias]) > 1:
                reason = "ambiguous_alias"
            elif alias in canonical_keys and alias != key:
                reason = "alias_conflicts_with_canonical"
            elif len(signatures.get(alias, ())) > 1:
                reason = "conflicting_alias_component_signatures"
            else:
                reason = None
            if reason:
                rejected.append({"reason": reason, "alias": alias, "canonical": key,
                                 "sources": group["sources"], "row_id": row_id})
                continue
            entry = self.inventory.get(key)
            sources = list(entry.sources) if entry else []
            for source in group["sources"]:
                if source not in sources:
                    sources.append(source)
            self.inventory[key] = NameEntry(key, canonical, tuple(sources))
            # A redundant joined spelling cannot erase the canonical boundaries.
            alias_components = canonical if alias == key else (
                next(iter(signatures[alias])) if signatures.get(alias) else signature)
            resolved[alias] = (alias_components, key)
            # Consume the complete original parenthetical label as one identity.
            if "(" in group["label"]:
                literal_keys[group["label"]] = (key, canonical)
        # Complete unsupported labels mask nested known names. Restrict blockers
        # to names newly granted aliases, preserving legacy segmented behavior.
        gap = r"[ \t]*(?:[-_.][ \t]*)?"
        canonical_patterns = [(re.compile(r"(?ai)^" + gap.join(self.inventory[key].components) + r"(?=[ \t]*\()"),
                               self.inventory[key].components)
                              for key in set(key for _, key in resolved.values())]
        for _, _, label in self._explicit_labels:
            if label in literal_keys or "(" not in label:
                continue
            for pattern, components in canonical_patterns:
                if pattern.search(label):
                    literal_keys[label] = (None, components)
                    break
        specs = [(alias, signature, key) for alias, (signature, key) in sorted(resolved.items())]
        literals = []
        for label, (key, components) in sorted(literal_keys.items()):
            prefix = gap.join(components)
            matched = re.match(r"(?ai)^" + prefix, label)
            suffix = label[matched.end():] if matched else label
            literal = r"[ \t]+".join(re.escape(part) for part in re.split(r"[ \t]+", suffix))
            # Keep the identifier lookbehind Unicode-aware, as in the trie.
            pattern = _LEFT_BOUNDARY + "(?ai:" + (prefix if matched else "") + literal + ")"
            literals.append((pattern, key))
        return {"accepted": [{"alias_key": alias, "components": list(signature), "canonical_key": key}
                             for alias, signature, key in specs], "rejected": rejected}, specs, literals

    def _build_matcher(self):
        """Build query matcher from persisted, resolved component signatures."""
        self._trie = _TrieNode()
        for spelling, components, canonical_key in self._matcher_specs:
            node = self._trie
            for letter in spelling:
                node = node.children.setdefault(letter, _TrieNode())
            boundary_mask = letters = 0
            for component in components[:-1]:
                letters += len(component)
                boundary_mask |= 1 << letters
            node.terminal = (canonical_key, boundary_mask)
        starts = "".join(sorted(self._trie.children))
        self._starts = re.compile(_LEFT_BOUNDARY + f"(?ai:[{starts}])") if starts else None
        self._literals = [(re.compile(pattern), key) for pattern, key in self._literal_specs]

    @staticmethod
    def precompute(metadata, path, aliases=()):
        from .prepared_names import write_artifact
        return write_artifact(metadata, path, aliases)

    @staticmethod
    def load_precomputed(metadata, path):
        from .prepared_names import PreparedNameIndex
        return PreparedNameIndex(metadata, path)

    @staticmethod
    def atom(key: str) -> str:
        """Return the stable indivisible field-scoring unit for a joined key."""
        return f"__name_{key}"

    def _trie_match(self, text: str) -> tuple[NameMatch, ...]:
        """Return candidates from complete component signatures."""
        if not text or self._starts is None:
            return ()
        matches = []
        consumed_until = 0
        length = len(text)
        for start_match in self._starts.finditer(text):
            start = start_match.start()
            if start < consumed_until:
                continue
            node = self._trie
            position, letters, gap_mask = start, 0, 0
            best = None
            while position < length:
                letter = text[position]
                if not ("a" <= letter <= "z" or "A" <= letter <= "Z"):
                    break
                node = node.children.get(letter.lower())
                if node is None:
                    break
                position += 1
                letters += 1
                if node.terminal is not None:
                    key, boundary_mask = node.terminal
                    if not gap_mask & ~boundary_mask and _valid_right_boundary(text, position):
                        best = NameMatch(key, start, position)
                if position >= length:
                    break
                next_char = text[position]
                if "a" <= next_char <= "z" or "A" <= next_char <= "Z":
                    continue
                # Consume one evidenced separator candidate. Its validity for a
                # particular signature is checked only at that terminal above.
                gap_start = position
                while position < length and text[position] in " \t":
                    position += 1
                if position < length and text[position] in "-_.":
                    position += 1
                    while position < length and text[position] in " \t":
                        position += 1
                if position == gap_start:
                    break
                gap_mask |= 1 << letters
            if best is not None:
                matches.append(best)
                consumed_until = best.end
        return tuple(matches)

    def match(self, text: str) -> tuple[NameMatch, ...]:
        """Select longest complete labels before projecting aliases or blockers."""
        candidates = [(m.start, m.end, m.key) for m in self._trie_match(text)]
        for pattern, key in self._literals:
            candidates.extend((m.start(), m.end(), key) for m in pattern.finditer(text)
                              if _valid_right_boundary(text, m.end()))
        matches, consumed = [], 0
        for start, end, key in sorted(candidates, key=lambda m: (m[0], -m[1])):
            if start < consumed:
                continue
            consumed = end
            if key is not None:
                matches.append(NameMatch(key, start, end))
        return tuple(matches)

    def keys(self, text: str) -> frozenset[str]:
        """Return each complete name at most once regardless of repetition."""
        return frozenset(matched.key for matched in self.match(text))

    def project(self, text: str, keys: Optional[Iterable[str]] = None) -> str:
        """Replace complete spans, optionally selecting keys after overlap masking.

        Matching always uses the full inventory so selecting a shorter key cannot
        expose a nested span hidden inside a longer recognized name.
        """
        selected = None if keys is None else frozenset(keys)
        pieces = []
        cursor = 0
        for matched in self.match(text):
            if selected is not None and matched.key not in selected:
                continue
            pieces.extend((text[cursor:matched.start], self.atom(matched.key)))
            cursor = matched.end
        pieces.append(text[cursor:])
        return "".join(pieces)

    def candidates(self, query: str, eligible_ids: Optional[Iterable[int]] = None,
                   limit: int = 100) -> list[int]:
        """Return filtered row IDs ordered by field prominence and stable row ID."""
        if limit <= 0:
            return []
        eligible = None if eligible_ids is None else frozenset(eligible_ids)
        priorities: dict[int, int] = {}
        for key in self.keys(query):
            for row_id, priority in self._postings[key].items():
                if eligible is None or row_id in eligible:
                    priorities[row_id] = min(priorities.get(row_id, priority), priority)
        return sorted(priorities, key=lambda row_id: (priorities[row_id], row_id))[:limit]

    def report(self) -> dict[str, Any]:
        """Return JSON-safe coverage counts and every rejected label's provenance."""
        return {"counts": {"labels": self._label_count, "names": len(self.inventory),
                           "segmented_names": len(self._postings),
                           "joined_only_names": len(self.inventory) - len(self._postings),
                           "excluded_labels": len(self._excluded), "intrinsic_records": self._intrinsic_count,
                           "postings": sum(len(postings) for postings in self._postings.values())},
                "excluded": [{"reason": item["reason"], "source": dict(item["source"])} for item in self._excluded],
                "joined_only": [{"key": entry.key, "reason": "no_evidenced_component_boundary",
                                 "sources": [dict(source) for source in entry.sources]}
                                for entry in sorted(self.inventory.values(), key=lambda entry: entry.key)
                                if len(entry.components) == 1],
                "aliases": self._alias_report,
                "inventory": [{"key": entry.key, "components": list(entry.components),
                               "sources": [dict(source) for source in entry.sources]}
                              for entry in sorted(self.inventory.values(), key=lambda entry: entry.key)]}
