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

"""Expand ranked hits using stored document identities and acquisition order only."""

from typing import Any


CONTEXT_SCOPES = {"chunks", "page", "parent_resource"}


def _document_key(row: dict, url: str) -> tuple:
    # Keep versioned documents and query/fragment identities distinct.
    return (url, *(row.get(field, "") for field in ("platform", "edition", "version")))


def _unavailable(url: str, reason: str) -> ValueError:
    return ValueError(
        f"Cannot expand stored context for {url}: {reason}. "
        "Regenerate chunks and the KB artifacts with complete document-order metadata; "
        "scope='chunks' remains available."
    )


def _prepare(validate, *args):
    """Retain a validation failure without blocking unrelated documents."""
    try:
        return validate(*args)
    except ValueError as exc:
        return ValueError(str(exc))


def _require(value):
    if isinstance(value, ValueError):
        raise ValueError(str(value))
    return value


def _ordered_chunks(key: tuple, rows: list[dict], resources, split_positions: dict) -> tuple[dict, ...]:
    chunks: dict[int, dict] = {}
    expected_count = None
    split_fields = ("parent_uuid", "parent_chunk_uuid", "source_start", "source_end", "source_part", "source_parts")
    for row in rows:
        context = row.get("document_context")
        if not isinstance(context, dict) or not isinstance(context.get("url"), str) or not context["url"]:
            raise _unavailable(key[0], "a same-document record is missing document-order metadata")
        index, count = context.get("chunk_index"), context.get("chunk_count")
        if (context.get("format") != 1 or type(index) is not int or type(count) is not int
                or count < 1 or not 0 <= index < count):
            raise _unavailable(key[0], "invalid chunk ordering metadata")
        if expected_count is not None and count != expected_count:
            raise _unavailable(key[0], "conflicting document revisions")
        expected_count = count
        if any(field in row for field in split_fields):
            parent = (row.get("parent_uuid"), row.get("parent_chunk_uuid"))
            if not all(isinstance(value, str) and value for value in parent):
                raise _unavailable(key[0], "a split chunk is missing parent identifiers")
            if parent not in resources._parent_texts:
                raise _unavailable(key[0], "an original chunk has missing or invalid embedding pieces")
            if split_positions.get(parent) != (key, index):
                raise _unavailable(key[0], "a split chunk has conflicting or missing document positions")
        # Collapse embedding pieces/import copies by logical position. A copy
        # acquired through its parent can supply a missing navigation manifest.
        if index in chunks:
            previous = chunks[index]
            previous_context = previous["document_context"]
            old_pages, new_pages = (c.get("learning_path_pages") for c in (previous_context, context))
            if (any(previous.get(f) != row.get(f) for f in ("url", "heading", "title"))
                    or resources.snippet_for(previous) != resources.snippet_for(row)
                    or {k: v for k, v in previous_context.items() if k != "learning_path_pages"}
                    != {k: v for k, v in context.items() if k != "learning_path_pages"}
                    or (old_pages is not None and new_pages is not None and old_pages != new_pages)):
                raise _unavailable(key[0], "conflicting chunks at the same position")
            if old_pages is None and new_pages is not None:
                chunks[index] = row
        else:
            chunks[index] = row
    if len(chunks) != expected_count:
        raise _unavailable(key[0], "one or more chunks are missing")
    return tuple(chunks[index] for index in range(expected_count))


def _parent_url(key: tuple, document, known_parents: set[str]) -> str | None:
    chunks = _require(document)
    root = chunks[0]["document_context"].get("parent_page_url")
    if root is not None and (not isinstance(root, str) or not root):
        raise _unavailable(key[0], "invalid parent identity")
    if (any(chunk["document_context"].get("parent_page_url") != root for chunk in chunks)
            or (known_parents and known_parents != {root})):
        raise _unavailable(key[0], "inconsistent parent identity across chunks")
    if root is None and any("learning_path_pages" in chunk["document_context"] for chunk in chunks):
        raise _unavailable(key[0], "parent manifest has no parent identity")
    return root


def _unique_key(url: str, keys_by_url: dict) -> tuple:
    keys = keys_by_url.get(url, [])
    if len(keys) != 1:
        raise _unavailable(url, "document is missing" if not keys else "ambiguous document variants")
    return keys[0]


def _parent_pages(root: str, members: set[tuple], keys_by_url: dict, documents: dict, parents: dict) -> tuple:
    root_chunks = _require(documents[_unique_key(root, keys_by_url)])
    pages = root_chunks[0]["document_context"].get("learning_path_pages")
    if (not isinstance(pages, list) or not pages
            or any(not isinstance(url, str) or not url for url in pages)
            or pages[0] != root or len(set(pages)) != len(pages)):
        raise _unavailable(root, "the parent resource page order is absent or invalid")
    keys = tuple(_unique_key(url, keys_by_url) for url in pages)
    if not members.issubset(keys):
        raise _unavailable(root, "inconsistent parent resource manifests: a stored sibling is omitted")
    for key in keys:
        chunks = _require(documents[key])
        if (_require(parents[key]) != root
                or any(chunk["document_context"].get("learning_path_pages") != pages for chunk in chunks)):
            raise _unavailable(root, "inconsistent parent resource manifests")
    return keys


class DocumentContextIndex:
    """Prepare a fixed snapshot once; expansion only reads validated catalog entries."""

    def __init__(self, metadata: list[dict[str, Any]], resources):
        rows_by_document: dict[tuple, list[dict]] = {}
        known_parents: dict[tuple, set[str]] = {}
        members: dict[str, set[tuple]] = {}
        keys_by_url: dict[str, list[tuple]] = {}
        split_positions: dict[tuple, tuple | None] = {}
        for row in metadata:
            position = None
            context = row.get("document_context")
            if isinstance(context, dict) and "learning_path_url" in context:
                context = dict(context)
                context.setdefault("parent_page_url", context.pop("learning_path_url"))
                row = {**row, "document_context": context}
            context_url = context.get("url") if isinstance(context, dict) else None
            url = context_url if isinstance(context_url, str) and context_url else row.get("page_url")
            if isinstance(url, str) and url:
                key = _document_key(row, url)
                rows_by_document.setdefault(key, []).append(row)
                if isinstance(context_url, str) and context_url:
                    position = (key, context.get("chunk_index"))
                roots = known_parents.setdefault(key, set())
                for root in (context.get("parent_page_url") if isinstance(context, dict) else None,
                             row.get("parent_page_url", row.get("learning_path_url"))):
                    if isinstance(root, str) and root:
                        roots.add(root)
                        members.setdefault(root, set()).add(key)
            parent = (row.get("parent_uuid"), row.get("parent_chunk_uuid"))
            if all(isinstance(value, str) and value for value in parent):
                if parent not in split_positions:
                    split_positions[parent] = position
                elif split_positions[parent] != position:
                    split_positions[parent] = None
        for key in rows_by_document:
            keys_by_url.setdefault(key[0], []).append(key)

        # Record errors at the narrowest scope: a bad parent need not prevent
        # reading a valid page, and a bad page need not block another document.
        self.documents = {key: _prepare(_ordered_chunks, key, rows, resources, split_positions)
                          for key, rows in rows_by_document.items()}
        self.document_parents = {key: _prepare(_parent_url, key, document, known_parents[key])
                                 for key, document in self.documents.items()}
        self.parents = {root: _prepare(_parent_pages, root, keys, keys_by_url, self.documents, self.document_parents)
                        for root, keys in members.items()}

    def expand(self, seeds: list[dict], scope: str) -> list[dict]:
        output = []
        seen = set()
        for seed in seeds:
            row = seed["metadata"]
            context = row.get("document_context")
            if not isinstance(context, dict) or not isinstance(context.get("url"), str) or not context["url"]:
                raise _unavailable(row.get("url", ""), "document metadata is absent")
            key = _document_key(row, context["url"])
            _require(self.documents.get(key, _unavailable(key[0], "document is missing")))
            root = _require(self.document_parents[key]) if scope == "parent_resource" else None
            pages = _require(self.parents[root]) if root else (key,)
            for page_index, page_key in enumerate(pages):
                if page_key in seen:
                    continue
                seen.add(page_key)
                chunks = _require(self.documents[page_key])
                for chunk in chunks:
                    output.append({"metadata": chunk, "context": {
                        "scope": "parent_resource" if root else "page",
                        "page_url": page_key[0],
                        "chunk_index": chunk["document_context"]["chunk_index"],
                        "chunk_count": len(chunks),
                        **({"parent_page_url": root, "page_index": page_index,
                            "page_count": len(pages)} if root else {}),
                    }})
        return output
