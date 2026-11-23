"""Metadata equality filters and reusable chunk eligibility lookups."""

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

FilterValue = str | Annotated[tuple[str, ...], Field(min_length=1)] | None


def metadata_filter_value(item: Mapping[str, Any], name: str) -> list[str]:
    """Return independent arrays for public tags and legacy scalar defaults."""
    public = item.get("filter_metadata")
    value = public[name] if isinstance(public, Mapping) and name in public else item.get(name, "")
    choices = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [label for label in choices if isinstance(label, str) and label.strip()]


class SearchFilters(BaseModel):
    """Exact labels: OR within a field, AND across fields; lists normalize to tuples."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    doc_type: FilterValue = Field(default=None, description=(
        "Content type: learning (tutorials and courses); guide (installation, configuration, migration, "
        "troubleshooting and tuning); reference (manuals, specifications, intrinsics and Insights FAQs); "
        "article (overviews, white papers and benchmark analysis); compatibility (software/OS/version "
        "support catalogs). Legacy corpora may use labels such as 'Learning Paths'; prefer observed "
        "labels and omit when unsure."))
    product: FilterValue = Field(default=None, description=(
        "Document publisher: arm, aws, google or ampere. Identifies who published the document, "
        "not the software or hardware discussed. An AWS workload does not by itself require product='aws'."))
    platform: FilterValue = Field(default=None, description=(
        "Verified execution environment: linux, windows, macos, android, baremetal (no OS), rtos, "
        "chromeos, freebsd, google-colab. Intrinsic family or ISA taught: neon, sve, sve2, sme, sme2, "
        "helium (MVE). Architecture or hardware: cme, mali (including NX), cortex-m, agi-cpu "
        "(Arm AGI CPU). Tags do not imply other OS, ISA or hardware support. "
        "Values in a list mean OR: ['linux', 'windows'] matches either. For Linux with SVE, "
        "filter one tag, keep the other in the query, and verify both in the evidence."))

    @field_validator("doc_type", "product", "platform", mode="before")
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
                value = metadata_filter_value(item, name)
                labels = {label.strip().casefold() for label in value}
                # Preserve old document-type queries without exposing detailed
                # labels as public tags. Empty/invalid public tags suppress aliases.
                legacy = item.get(name)
                if name == "doc_type" and labels and isinstance(legacy, str) and legacy.strip():
                    labels.add(legacy.strip().casefold())
                for label in labels:
                    values.setdefault(label, set()).add(row_id)

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
