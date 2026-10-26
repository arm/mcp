# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
"""Build a reusable name index offline from final metadata and explicit aliases.

Run ``python -m arm_kb_search.build_names --help``. Source metadata and vectors
remain unchanged; deploy the saved index with the metadata used to build it.
"""
import argparse
import json
from pathlib import Path
import sys
import time

from .names import NameIndex
from .prepared_names import write_json_atomic


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Prepared name index JSON")
    parser.add_argument("--aliases", type=Path, help="Optional explicit alias groups with labels and provenance")
    parser.add_argument("--report", type=Path, help="Optional build and coverage report")
    args = parser.parse_args(argv)
    paths = [path.resolve() for path in (args.metadata, args.output, args.aliases, args.report)
             if path is not None]
    if len(set(paths)) != len(paths):
        parser.error("Input and output paths must be distinct")
    start = time.perf_counter()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    if not isinstance(metadata, list) or any(not isinstance(row, dict) for row in metadata):
        parser.error("Metadata must be a JSON list of chunk objects")
    aliases = json.loads(args.aliases.read_text(encoding="utf-8")) if args.aliases else ()
    stats = NameIndex.precompute(metadata, args.output, aliases)
    # Verify through the production loader before reporting success.
    index = NameIndex.load_precomputed(metadata, args.output)
    report = {"build": {**stats, "seconds": time.perf_counter() - start}, "coverage": index.report()}
    if args.report:
        write_json_atomic(args.report, report)
    rejected = report["coverage"]["aliases"]["rejected"]
    for rejection in rejected:
        group = rejection.get("group", {})
        label = group.get("canonical") or rejection.get("canonical")
        detail = group.get("labels") or rejection.get("alias")
        action = ("check labels against exact corpus package labels; omit the group if optional"
                  if rejection["reason"] == "no_exact_source_label"
                  else "review conflicting canonical names, aliases and source labels")
        print(f"Rejected alias {label!r} ({detail!r}): {rejection['reason']}; {action}", file=sys.stderr)
    print(json.dumps({**report["build"], "rejected_aliases": len(rejected)}, sort_keys=True))


if __name__ == "__main__":
    main()
