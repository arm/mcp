# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fail closed when a generated CSV loses contributor tags."""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

from source_metadata import (
    METADATA_COLUMNS,
    read_metadata_overrides,
    validate_metadata_columns,
)


def read_sources(path):
    by_url = defaultdict(set)
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        if "URL" not in columns:
            raise ValueError(f"{path}: missing URL column")
        validate_metadata_columns(columns, str(path))
        for row in reader:
            url = (row.get("URL") or "").strip()
            tags = read_metadata_overrides(row, url)
            if url:
                # None (inherit) and () (explicit clear) must remain distinct.
                values = tuple(
                    None if tags.get(field) is None else tuple(sorted(tags[field]))
                    for field in METADATA_COLUMNS.values()
                )
                by_url[url].add(values)
    return set(columns) & METADATA_COLUMNS.keys(), by_url


def assignment_sets(rows):
    # Dashboard reconciliation combines duplicate rows field by field. Ignore
    # inherited blanks, but retain every explicit assignment, including [].
    return tuple(
        {tags[index] for tags in rows if tags[index] is not None}
        for index in range(len(METADATA_COLUMNS))
    )


def validate(expected, actual):
    expected_columns, expected_sources = read_sources(expected)
    actual_columns, actual_sources = read_sources(actual)
    missing = expected_columns - actual_columns
    if missing:
        raise ValueError(f"Generated CSV lost metadata columns: {', '.join(sorted(missing))}")
    for url, tags in expected_sources.items():
        if url not in actual_sources:
            print(f"Removed source: {url}")
            continue
        if assignment_sets(actual_sources[url]) != assignment_sets(tags):
            raise ValueError(f"Generated CSV lost a source or changed metadata for {url}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    args = parser.parse_args()
    try:
        validate(args.expected, args.actual)
    except (ValueError, OSError) as error:
        print(f"Source metadata validation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
