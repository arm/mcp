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
    # Editions and versions at the same URL are separate documents. In particular,
    # preserve dashboard query parameters and intrinsic #q identities verbatim.
    return (url, *(row.get(field, "") for field in ("platform", "edition", "version")))


def _unavailable(url: str, reason: str) -> ValueError:
    return ValueError(
        f"Cannot expand stored context for {url}: {reason}. "
        "Regenerate chunks and the KB artifacts with complete document-order metadata; "
        "scope='chunks' remains available."
    )


class DocumentContextIndex:
    def __init__(self, metadata: list[dict[str, Any]]):
        self.documents: dict[tuple, list[dict]] = {}
        self.document_urls_by_parent: dict[str, set[str]] = {}
        self.split_chunk_positions: dict[tuple, tuple | None] = {}
        for row in metadata:
            position = None
            context = row.get("document_context")
            if isinstance(context, dict) and isinstance(context.get("url"), str):
                # Read earlier experimental artifacts without mutating the snapshot.
                if "learning_path_url" in context:
                    context = dict(context)
                    context.setdefault("parent_page_url", context.pop("learning_path_url"))
                    row = {**row, "document_context": context}
                key = _document_key(row, context["url"])
                position = (key, context.get("chunk_index"))
                self.documents.setdefault(key, []).append(row)
                parent_url = context.get("parent_page_url")
                if isinstance(parent_url, str) and parent_url:
                    self.document_urls_by_parent.setdefault(parent_url, set()).add(context["url"])
            parent = (row.get("parent_uuid"), row.get("parent_chunk_uuid"))
            if all(isinstance(value, str) and value for value in parent):
                # Every piece must identify the same original document position.
                if parent not in self.split_chunk_positions:
                    self.split_chunk_positions[parent] = position
                elif self.split_chunk_positions[parent] != position:
                    self.split_chunk_positions[parent] = None
        self.document_keys_by_url: dict[str, list[tuple]] = {}
        for key in self.documents:
            self.document_keys_by_url.setdefault(key[0], []).append(key)

    def ordered_chunks(self, key: tuple, resources) -> list[dict]:
        rows = self.documents.get(key, [])
        if not rows:
            raise _unavailable(key[0], "document is missing")
        chunks: dict[int, dict] = {}
        expected_count = None
        split_fields = ("parent_uuid", "parent_chunk_uuid", "source_start", "source_end", "source_part", "source_parts")
        for row in rows:
            context = row["document_context"]
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
                if self.split_chunk_positions.get(parent) != (key, index):
                    raise _unavailable(key[0], "a split chunk has conflicting or missing document positions")
            # A logical chunk can have many embedding pieces or duplicate imports.
            # Deduplicate by its stored position, never by URL (sections can share it).
            if index in chunks:
                previous = chunks[index]
                fields = ("url", "heading", "title")
                previous_context = previous["document_context"]
                old_pages, new_pages = (c.get("learning_path_pages") for c in (previous_context, context))
                if (any(previous.get(f) != row.get(f) for f in fields)
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
        return [chunks[index] for index in range(expected_count)]

    def expand(self, seeds: list[dict], resources, scope: str) -> list[dict]:
        output = []
        seen = set()
        for seed in seeds:
            row = seed["metadata"]
            context = row.get("document_context")
            if not isinstance(context, dict) or not context.get("url"):
                raise _unavailable(row.get("url", ""), "document metadata is absent")
            # A separately acquired copy of a step can lack a path manifest.
            # Use the verified copy from the same stored document when available.
            seed_key = _document_key(row, context["url"])
            seed_chunks = self.ordered_chunks(seed_key, resources)
            context = seed_chunks[0]["document_context"]
            root = context.get("parent_page_url")
            if scope == "parent_resource":
                if any(chunk["document_context"].get("parent_page_url") != root for chunk in seed_chunks):
                    raise _unavailable(context["url"], "inconsistent parent identity across chunks")
                if root is not None and (not isinstance(root, str) or not root):
                    raise _unavailable(context["url"], "invalid parent identity")
                if root is None and any("learning_path_pages" in chunk["document_context"] for chunk in seed_chunks):
                    raise _unavailable(context["url"], "parent manifest has no parent identity")
            pages = [context["url"]]
            resolved_scope = "page"
            if scope == "parent_resource" and root:
                pages = context.get("learning_path_pages")
                if (not isinstance(pages, list) or not pages
                        or any(not isinstance(url, str) or not url for url in pages)
                        or pages[0] != root or context["url"] not in pages
                        or len(set(pages)) != len(pages)):
                    raise _unavailable(root, "the parent resource page order is absent or invalid")
                # A seed's manifest must not hide other stored siblings. Listed
                # pages are checked for completeness and consistency below.
                if not self.document_urls_by_parent.get(root, set()).issubset(pages):
                    raise _unavailable(root, "inconsistent parent resource manifests: a stored sibling is omitted")
                resolved_scope = "parent_resource"
            for page_index, page_url in enumerate(pages):
                key = seed_key
                if resolved_scope == "parent_resource":
                    # URL-only manifests cannot disambiguate multiple stored variants.
                    # Each sibling can legitimately have its own version/edition/platform.
                    keys = self.document_keys_by_url.get(page_url, [])
                    if len(keys) != 1:
                        reason = "document is missing" if not keys else "ambiguous document variants"
                        raise _unavailable(page_url, reason)
                    key = keys[0]
                chunks = self.ordered_chunks(key, resources)
                if resolved_scope == "parent_resource" and any(
                    chunk["document_context"].get("learning_path_pages") != pages
                    or chunk["document_context"].get("parent_page_url") != root
                    for chunk in chunks
                ):
                    raise _unavailable(root, "inconsistent parent resource manifests")
                if key in seen:
                    continue
                seen.add(key)
                for chunk in chunks:
                    output.append({"metadata": chunk, "context": {
                        "scope": resolved_scope,
                        "page_url": page_url,
                        "chunk_index": chunk["document_context"]["chunk_index"],
                        "chunk_count": len(chunks),
                        **({"parent_page_url": root, "page_index": page_index,
                            "page_count": len(pages)} if resolved_scope == "parent_resource" else {}),
                    }})
        return output
