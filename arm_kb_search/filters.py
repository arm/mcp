"""Metadata equality filters and reusable chunk eligibility lookups."""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any


FilterValue = str | list[str] | tuple[str, ...] | None


def normalize_filter_value(value: FilterValue) -> str | tuple[str, ...] | None:
    """Keep scalars compatible and copy alternatives into an immutable, unique tuple."""
    if value is None:
        return None
    scalar = isinstance(value, str)
    choices = [value] if scalar else value
    if (not isinstance(choices, (list, tuple)) or not choices
            or any(not isinstance(item, str) or not item.strip() for item in choices)):
        raise ValueError("Filter values must be a non-empty string, a non-empty list/tuple of non-empty strings, or null")
    normalized = tuple(dict.fromkeys(item.strip().casefold() for item in choices))
    return normalized[0] if scalar else normalized


@dataclass(frozen=True)
class SearchFilters:
    """Exact labels: OR within a field, AND across fields; lists normalize to tuples."""

    doc_type: FilterValue = None
    product: FilterValue = None
    platform: FilterValue = None
    edition: FilterValue = None

    def __post_init__(self) -> None:
        for field in fields(self):
            object.__setattr__(self, field.name, normalize_filter_value(getattr(self, field.name)))

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
        postings = []
        for name, values in self._postings.items():
            value = getattr(filters, name)
            if value is None:
                continue
            # Union alternatives before intersecting fields. Scalar lookups keep
            # their existing fast path; neither operation mutates the index.
            postings.append(values.get(value, set()) if isinstance(value, str) else
                            set().union(*(values.get(label, set()) for label in value)))
        if not postings:
            return None
        postings.sort(key=len)
        # Never mutate the shared lookup tables during a request.
        eligible = postings[0].intersection(*postings[1:])
        return tuple(sorted(eligible))
