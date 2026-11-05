"""Metadata equality filters and reusable chunk eligibility lookups."""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class SearchFilters:
    """Optional scalar filters, combined with AND after strip/casefold normalization."""

    doc_type: str | None = None
    product: str | None = None
    platform: str | None = None
    edition: str | None = None

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Filter '{field.name}' must be a non-empty string or None")
            object.__setattr__(self, field.name, value.strip().casefold())

    @classmethod
    def parse(cls, value: "SearchFilters | Mapping[str, Any] | None") -> "SearchFilters":
        """Accept typed filters or a JSON-compatible object; reject unknown keys."""
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            # All invalid request filters use the same validation exception.
            raise ValueError("'filters' must be a SearchFilters instance, mapping, or None")  # noqa: TRY004
        allowed = {field.name for field in fields(cls)}
        if any(key not in allowed for key in value):
            raise ValueError(f"Unknown filter field; supported fields: {', '.join(sorted(allowed))}")
        return cls(**value)


class MetadataFilterIndex:
    """Snapshot of metadata values to row IDs; rebuild when replacing the corpus."""

    def __init__(self, metadata: list[dict[str, Any]]) -> None:
        self._postings: dict[str, dict[str, set[int]]] = {
            field.name: {} for field in fields(SearchFilters)
        }
        for row_id, item in enumerate(metadata):
            for name, values in self._postings.items():
                value = item.get(name)
                if isinstance(value, str) and value.strip():
                    values.setdefault(value.strip().casefold(), set()).add(row_id)

    def eligible_ids(self, filters: SearchFilters) -> tuple[int, ...] | None:
        """None means unrestricted; an empty tuple means no eligible chunks."""
        postings = [
            values.get(value, set())
            for name, values in self._postings.items()
            if (value := getattr(filters, name)) is not None
        ]
        if not postings:
            return None
        postings.sort(key=len)
        # Never mutate the shared lookup tables during a request.
        eligible = postings[0].intersection(*postings[1:])
        return tuple(sorted(eligible))
