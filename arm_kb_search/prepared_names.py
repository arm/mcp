"""Versioned, corpus-bound whole-name evidence computed without embeddings."""

from collections import Counter
import os
import tempfile
from typing import Any
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

from .names import NameEntry, NameIndex

SCHEMA = 3
FIELDS = (
    "title",
    "heading",
    "heading_path",
    "keywords",
    "product",
    "doc_type",
    "version",
    "original_text",
    "content",
    "url",
    "resolved_url",
)
BODY_FIELDS = (
    "title",
    "heading_path",
    "heading",
    "doc_type",
    "product",
    "version",
    "keywords",
)


def corpus_fingerprint(metadata: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in metadata:
        digest.update(
            json.dumps(
                row, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        )
        digest.update(b"\n")
    return digest.hexdigest()


def write_json_atomic(path: str | Path, payload: Any) -> None:
    """Publish a complete JSON file; ASCII escaping avoids wide decode buffers."""
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"))
            stream.write("\n")
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _checksum(payload: dict) -> str:
    # Detect damaged/partial sidecars, not authenticate untrusted artifacts.
    data = {key: value for key, value in payload.items() if key != "checksum"}
    return hashlib.sha256(
        json.dumps(
            data, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        ).encode("ascii")
    ).hexdigest()


def _row_ids(metadata: list[dict]) -> dict[str, int]:
    keys = [row.get("chunk_uuid") for row in metadata]
    if any(not isinstance(key, str) or not key for key in keys) or len(
        set(keys)
    ) != len(keys):
        raise ValueError(
            "Name artifact requires unique, nonempty corpus chunk_uuid values"
        )
    return {key: number for number, key in enumerate(keys)}


def _load_payload(metadata: list[dict], path: str | Path) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
            raise ValueError("Unsupported name artifact schema; rebuild the artifact")
        if payload.get("checksum") != _checksum(payload):
            raise ValueError("Name artifact checksum mismatch; rebuild the artifact")
        if payload.get("corpus") != corpus_fingerprint(metadata) or len(
            payload["rows"]
        ) != len(metadata):
            raise ValueError("Name artifact does not match corpus content/order")
        names = payload["names"]
        if (
            not isinstance(names, list)
            or names != sorted(set(names))
            or any(not isinstance(key, str) or not key for key in names)
            or set(payload["postings"]) != set(names)
        ):
            raise ValueError("Invalid name artifact inventory")
        for pairs in payload["postings"].values():
            seen = set()
            for row_id, priority in pairs:
                if (
                    type(row_id) is not int
                    or not 0 <= row_id < len(metadata)
                    or type(priority) is not int
                    or priority not in range(4)
                    or row_id in seen
                ):
                    raise ValueError("Invalid name artifact posting")
                seen.add(row_id)
        for spelling, components, key in payload["matcher_specs"]:
            if key not in names or not components or "".join(components) != spelling:
                raise ValueError("Invalid name artifact matcher")
        for _, key in payload["literal_specs"]:
            # None consumes an unsupported complete label without name credit.
            if key is not None and key not in names:
                raise ValueError("Invalid name artifact literal")
        if not isinstance(payload["urls"], dict) or not isinstance(
            payload["report"], dict
        ):
            raise ValueError("Invalid name artifact fields")
        return payload
    except (KeyError, TypeError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid name artifact; rebuild the artifact") from exc


def _items(row, field):
    value = row.get(field)
    for number, item in enumerate(value if isinstance(value, list) else [value]):
        if item:
            yield number, str(item)


def _delta(before, after):
    return [
        [token, after.get(token, 0) - before.get(token, 0)]
        for token in sorted(before.keys() | after.keys())
        if before.get(token, 0) != after.get(token, 0)
    ]


def _project(text, spans, keys, names):
    pieces = []
    end = 0
    for name_id, start, stop in spans:
        key = names[name_id]
        if key in keys:
            pieces.extend((text[end:start], NameIndex.atom(key)))
            end = stop
    if not pieces:
        return text
    pieces.append(text[end:])
    return "".join(pieces)


def write_artifact(metadata: list[dict[str, Any]], path: str | Path, aliases=()) -> dict[str, int]:
    """Write resolved spans, sparse token patches and auditable name provenance."""
    from .search import _bm25_tokens, _separate_name_punctuation, tokenize_for_search

    _row_ids(metadata)
    index = NameIndex(metadata, aliases)
    names = sorted(index._postings)
    ids = {key: number for number, key in enumerate(names)}
    records = []
    urls = {}
    for row in metadata:
        spans = {}
        for field in FIELDS:
            found = {}
            for number, text in _items(row, field):
                matches = [[ids[m.key], m.start, m.end] for m in index.match(text)]
                if matches:
                    found[str(number)] = matches
            if found:
                spans[field] = found
        for field in ("url", "resolved_url"):
            url = str(row.get(field) or "")
            if url and url not in urls:
                parsed = urlparse(url)
                matches = [
                    [[ids[m.key], m.start, m.end] for m in index.match(part)]
                    for part in (parsed.path, parsed.query, parsed.fragment)
                ]
                if any(matches):
                    urls[url] = matches
        body_field = (
            "original_text" if isinstance(row.get("original_text"), str) else "content"
        )
        body_parts = [
            (field, number, text)
            for field in (*BODY_FIELDS, body_field)
            for number, text in _items(row, field)
        ]
        base = Counter(tokenize_for_search(" ".join(text for _, _, text in body_parts)))
        bm25 = Counter(_bm25_tokens(row.get("search_text", "")))
        body_ids = {
            m[0]
            for field, number, _ in body_parts
            for m in spans.get(field, {}).get(str(number), [])
        }
        patches = {}
        for name_id in sorted(body_ids):
            key = names[name_id]
            projected = " ".join(
                _separate_name_punctuation(
                    _project(
                        text,
                        spans.get(field, {}).get(str(number), []),
                        {key},
                        names,
                    )
                )
                for field, number, text in body_parts
            )
            patches[str(name_id)] = _delta(
                base, Counter(tokenize_for_search(projected))
            )
        base_delta = _delta(bm25, base)
        records.append(
            {"spans": spans, "base": base_delta, "names": patches}
            if spans or base_delta or patches
            else None
        )
    payload = {
        "schema": SCHEMA,
        "corpus": corpus_fingerprint(metadata),
        "names": names,
        "report": index.report(),
        "matcher_specs": index._matcher_specs,
        "literal_specs": index._literal_specs,
        "postings": {key: list(rows.items()) for key, rows in index._postings.items()},
        "rows": records,
        "urls": urls,
    }
    payload["checksum"] = _checksum(payload)
    write_json_atomic(path, payload)
    return {
        "rows": len(records),
        "names": len(names),
        "bytes": Path(path).stat().st_size,
        "span_fields": sum(len(record["spans"]) for record in records if record),
        "base_token_adjustments": sum(
            len(record["base"]) for record in records if record
        ),
        "name_token_adjustments": sum(
            len(delta)
            for record in records
            if record
            for delta in record["names"].values()
        ),
    }


class PreparedNameIndex(NameIndex):
    """Load precomputed document evidence; only query matching walks the trie."""

    def __init__(self, metadata: list[dict[str, Any]], path: str | Path):
        self._row_ids = _row_ids(metadata)
        payload = _load_payload(metadata, path)
        self._report = payload["report"]
        self._names = tuple(map(sys.intern, payload["names"]))
        self.inventory = {
            entry["key"]: NameEntry(
                entry["key"], tuple(entry["components"]), tuple(entry["sources"])
            )
            for entry in self._report["inventory"]
        }
        self._postings = {
            key: dict(pairs) for key, pairs in payload["postings"].items()
        }
        self._rows = payload["rows"]
        self._urls = payload["urls"]
        for record in self._rows:
            if record is None:
                continue
            record["base"] = tuple(
                (sys.intern(token), count) for token, count in record["base"]
            )
            record["names"] = {
                self._names[int(name_id)]: tuple(
                    (sys.intern(token), count) for token, count in delta
                )
                for name_id, delta in record["names"].items()
            }
        # Alias spellings and full-label masks were resolved at build time.
        self._matcher_specs = payload["matcher_specs"]
        self._literal_specs = payload["literal_specs"]
        self._build_matcher()

    def report(self):
        return self._report

    def project_field(self, metadata, field, item_number, text, keys):
        row_id = self._row_ids.get(metadata.get("chunk_uuid"))
        if row_id is None:
            return self.project(text, keys)
        record = self._rows[row_id]
        if record is None:
            return text
        spans = record["spans"].get(field, {}).get(str(item_number), ())
        return _project(text, spans, keys, self._names)

    def project_url_parts(self, metadata, url, keys):
        parsed = urlparse(url or "")
        parts = (parsed.path, parsed.query, parsed.fragment)
        if metadata.get("chunk_uuid") not in self._row_ids:
            return tuple(self.project(part, keys) for part in parts)
        matches = self._urls.get(url, ((), (), ()))
        return tuple(
            _project(part, spans, keys, self._names)
            for part, spans in zip(parts, matches)
        )

    def body_tokens(self, row_id, frequencies, keys):
        if not keys:
            return frequencies.keys()
        record = self._rows[row_id]
        if record is None:
            return frequencies.keys()
        changes = Counter(dict(record["base"]))
        for key in keys:
            for token, delta in record["names"].get(key, ()):
                changes[token] += delta
        if not changes:
            return frequencies.keys()
        tokens = set(frequencies)
        for token, delta in changes.items():
            if frequencies.get(token, 0) + delta > 0:
                tokens.add(token)
            else:
                tokens.discard(token)
        return tokens
