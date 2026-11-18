# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fail closed when a pinned generator or generated CSV loses contributor tags."""

import argparse
import csv
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from source_metadata import (
    METADATA_COLUMNS,
    read_metadata_overrides,
    validate_metadata_columns,
)


def read_sources(path):
    by_url = defaultdict(Counter)
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
                by_url[url][values] += 1
    return set(columns) & METADATA_COLUMNS.keys(), by_url


def assignment_sets(rows):
    # Dashboard reconciliation combines duplicate rows field by field. Ignore
    # inherited blanks, but retain every explicit assignment, including [].
    return tuple(
        {tags[index] for tags in rows if tags[index] is not None}
        for index in range(len(METADATA_COLUMNS))
    )


def validate(expected, actual, *, strict_roundtrip=False):
    expected_columns, expected_sources = read_sources(expected)
    actual_columns, actual_sources = read_sources(actual)
    missing = expected_columns - actual_columns
    if missing:
        raise ValueError(f"Generated CSV lost metadata columns: {', '.join(sorted(missing))}")
    for url, tags in expected_sources.items():
        if strict_roundtrip:
            matches = actual_sources.get(url) == tags
        elif url not in actual_sources:
            print(f"Removed source: {url}")
            continue
        else:
            matches = assignment_sets(actual_sources[url]) == assignment_sets(tags)
        if not matches:
            raise ValueError(f"Generated CSV lost a source or changed metadata for {url}")


def check_generator(expected, generator):
    with tempfile.TemporaryDirectory() as directory:
        roundtrip = Path(directory) / "sources.csv"
        roundtrip.write_bytes(Path(expected).read_bytes())
        # Use the image's own imports, never the checkout's metadata implementation.
        subprocess.run(
            [sys.executable, "-I", "-c",
             "import runpy, sys; from pathlib import Path; "
             "sys.path.insert(0, str(Path(sys.argv[1]).resolve().parent)); "
             "module = runpy.run_path(sys.argv[1]); "
             "module['load_existing_sources'](sys.argv[2]); "
             "module['save_sources_csv'](sys.argv[2])",
             str(Path(generator).resolve()), str(roundtrip)],
            check=True,
        )
        validate(expected, roundtrip, strict_roundtrip=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path, nargs="?")
    parser.add_argument("--generator", type=Path)
    args = parser.parse_args()
    if bool(args.actual) == bool(args.generator):
        parser.error("supply either a generated CSV or --generator")
    try:
        if args.generator:
            check_generator(args.expected, args.generator)
        else:
            validate(args.expected, args.actual)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Source metadata validation failed: {error}", file=sys.stderr)
        if args.generator:
            print("Build and review a compatible generator image, then update "
                  "pipeline-inputs.lock.json before running acquisition.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
