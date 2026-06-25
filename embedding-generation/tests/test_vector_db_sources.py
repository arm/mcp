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

"""Validation tests for vector-db-sources.csv."""

import csv
from pathlib import Path
from urllib.parse import urlparse


SOURCES_FILE = Path(__file__).resolve().parents[1] / "vector-db-sources.csv"
EXPECTED_COLUMNS = [
    "Site Name",
    "License Type",
    "Display Name",
    "URL",
    "Keywords",
    "Transcript Source URL",
]
URL_COLUMNS = ("URL", "Transcript Source URL")


def is_http_url(value):
    parsed = urlparse(value)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and not any(character.isspace() for character in value)
    )


def test_vector_db_sources_header_matches_schema():
    """The sources CSV must keep the expected six-column schema."""
    with SOURCES_FILE.open(newline="", encoding="utf-8") as sources:
        reader = csv.reader(sources)
        header = next(reader)

    assert header == EXPECTED_COLUMNS


def test_vector_db_sources_have_no_extra_fields():
    """Rows must not have extra unnamed fields, which usually means bad comma quoting."""
    extra_field_rows = []
    with SOURCES_FILE.open(newline="", encoding="utf-8") as sources:
        reader = csv.DictReader(sources)
        for line_number, row in enumerate(reader, start=2):
            extra_fields = row.get(None)
            if extra_fields:
                extra_field_rows.append(f"line {line_number}: {extra_fields}")

    assert not extra_field_rows, (
        "Rows in vector-db-sources.csv have extra unnamed fields:\n"
        + "\n".join(extra_field_rows)
    )


def test_vector_db_source_urls_are_http_urls():
    """Source URL fields must be valid HTTP(S) URLs when present."""
    invalid_urls = []
    with SOURCES_FILE.open(newline="", encoding="utf-8") as sources:
        reader = csv.DictReader(sources)
        for line_number, row in enumerate(reader, start=2):
            for column in URL_COLUMNS:
                value = (row.get(column) or "").strip()
                if value and not is_http_url(value):
                    invalid_urls.append(f"line {line_number}, {column}: {value}")

    assert not invalid_urls, (
        "Rows in vector-db-sources.csv have invalid URL values:\n"
        + "\n".join(invalid_urls)
    )


def test_vector_db_sources_have_keywords():
    """Every document source row must include keywords for lexical retrieval."""
    with SOURCES_FILE.open(newline="", encoding="utf-8") as sources:
        reader = csv.DictReader(sources)
        rows_without_keywords = [
            f"line {line_number}: {row.get('Display Name', '').strip()} ({(row.get('URL') or '').strip()})"
            for line_number, row in enumerate(reader, start=2)
            if (row.get("URL") or "").strip() and not (row.get("Keywords") or "").strip()
        ]

    assert not rows_without_keywords, (
        "Rows in vector-db-sources.csv must include Keywords:\n"
        + "\n".join(rows_without_keywords)
    )
