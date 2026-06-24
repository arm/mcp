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


SOURCES_FILE = Path(__file__).resolve().parents[1] / "vector-db-sources.csv"
REQUIRED_COLUMNS = {"Display Name", "Keywords", "URL"}


def test_vector_db_sources_have_keywords():
    """Every document source row must include keywords for lexical retrieval."""
    with SOURCES_FILE.open(newline="", encoding="utf-8") as sources:
        reader = csv.DictReader(sources)

        missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        assert not missing_columns, (
            f"{SOURCES_FILE.name} is missing required columns: "
            f"{', '.join(sorted(missing_columns))}"
        )

        rows_without_keywords = [
            f"line {line_number}: {row.get('Display Name', '').strip()} ({(row.get('URL') or '').strip()})"
            for line_number, row in enumerate(reader, start=2)
            if (row.get("URL") or "").strip() and not (row.get("Keywords") or "").strip()
        ]

    assert not rows_without_keywords, (
        "Rows in vector-db-sources.csv must include Keywords:\n"
        + "\n".join(rows_without_keywords)
    )
