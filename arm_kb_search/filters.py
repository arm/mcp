"""Metadata equality filters and reusable chunk eligibility lookups."""

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

FilterValue = str | Annotated[tuple[str, ...], Field(min_length=1)] | None


class SearchFilters(BaseModel):
    """Exact labels: OR within a field, AND across fields; lists normalize to tuples."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    doc_type: FilterValue = Field(default=None, description=(
        "Exact document category, for example Learning Paths, Install Guides, Intrinsic, "
        "or Ecosystem Dashboard. Use labels present in returned metadata."))
    product: FilterValue = Field(default=None, description=(
        "Exact corpus product label, for example Arm, AWS Graviton, Neon, SVE, or SVE2. "
        "This is not generally the software name: Jenkins documentation may have product Arm."))
    platform: FilterValue = Field(default=None, description=(
        "Exact platform label, for example linux or windows. Mainly populated for ecosystem "
        "compatibility records; filtering on it excludes tutorials with missing platform metadata."))
    edition: FilterValue = Field(default=None, description=(
        "Exact edition label, for example commercial or open-source. Mainly populated for "
        "ecosystem compatibility records; missing metadata cannot match."))

    @field_validator("doc_type", "product", "platform", "edition", mode="before")
    @classmethod
    def normalize_value(cls, value: Any) -> str | tuple[str, ...] | None:
        """Copy alternatives into an immutable, normalized, unique tuple."""
        if value is None:
            return None
        scalar = isinstance(value, str)
        choices = [value] if scalar else value
        if (not isinstance(choices, (list, tuple)) or not choices
                or any(not isinstance(item, str) or not item.strip() for item in choices)):
            raise ValueError("Filter values must be a non-empty string, a non-empty list/tuple of non-empty strings, or null")
        normalized = tuple(dict.fromkeys(item.strip().casefold() for item in choices))
        return normalized[0] if scalar else normalized

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
        return cls.model_validate(dict(value))


class MetadataFilterIndex:
    """Snapshot of metadata values to row IDs; rebuild when replacing the corpus."""

    def __init__(self, metadata: list[dict[str, Any]]) -> None:
        self._postings: dict[str, dict[str, set[int]]] = {
            name: {} for name in SearchFilters.model_fields
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
