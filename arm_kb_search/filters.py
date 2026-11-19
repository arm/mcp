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
        "Choose the kind of content needed: learning = tutorials, courses, lessons and worked exercises; "
        "guide = how-to instructions for installation, configuration, migration, troubleshooting or tuning; "
        "reference = technical manuals/specifications, instruction and intrinsic definitions, register "
        "behavior, and Insights technical FAQs; article = explanations, overviews, white papers and "
        "benchmark analysis; compatibility = software/OS/version support catalogs such as the ecosystem "
        "dashboard. For an intrinsic's definition use reference; for a lesson on using it use learning; "
        "for either use [\"reference\",\"learning\"]. "
        "Older KB snapshots still return detailed labels such as Learning Paths, Install Guides, "
        "Intrinsic, and Ecosystem Dashboard. Tagged records also accept their legacy document "
        "type as a query alias unless their public type was explicitly cleared. Omit this "
        "filter when unsure or when a general topic question could need several types of evidence."))
    product: FilterValue = Field(default=None, description=(
        "Exact publisher tag: arm, aws, google, or ampere; not the software name or ISA family. "
        "Older snapshots may return legacy labels such as Arm, AWS Graviton, Neon, SVE, or SVE2. "
        "Legacy ISA labels do not match records tagged with a publisher."))
    platform: FilterValue = Field(default=None, description=(
        "Exact platform tag: linux, windows, macos, android, baremetal, rtos, chromeos, or freebsd "
        "for a verified execution environment; neon, sve, sve2, sme, sme2, or helium (MVE) "
        "for an intrinsic family or an ISA taught by a document; cme for CME architecture, "
        "programming, and performance-monitoring documentation; mali for Mali GPU guidance, "
        "including neural-graphics guidance for Mali GPUs with a Neural Accelerator (NX). "
        "Use cortex-m for lessons or guidance explicitly targeting Cortex-M processors, "
        "including deployment, resource limits, and optimized kernels. "
        "Use agi-cpu for material explicitly targeting Arm AGI CPU hardware. "
        "Use google-colab for a documented Google Colab execution environment; it does not "
        "imply an OS, CPU architecture, GPU model, or Google as the document publisher. "
        "Hardware, architecture, and ISA tags do not imply OS compatibility, support for every "
        "hardware variant, or additional tags. Multiple values use OR: [linux, sve] matches "
        "Linux resources or SVE resources. "
        "Records missing the requested tag do not match."))

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
