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

"""Build a validated intrinsic snapshot from the current public Arm catalog."""

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

from document_chunking import prepare_intrinsic_chunk

REFERENCE_URL = "https://developer.arm.com/architectures/instruction-sets/intrinsics/"
CATALOG_URL = REFERENCE_URL + "data/intrinsics.json"
OPERATIONS_URL = REFERENCE_URL + "data/operations.json"
_FAMILIES = {"neon": "Neon", "sve": "SVE", "sve2": "SVE2", "helium": "Helium",
             "sme and sme2": "SME and SME2"}
_HEADERS = {"Neon": "arm_neon.h", "SVE": "arm_sve.h", "SVE2": "arm_sve.h",
            "SME and SME2": "arm_sme.h", "Helium": "arm_mve.h"}


def _text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text().strip()


def _validate_catalog(catalog: list) -> None:
    if not isinstance(catalog, list) or not catalog:
        raise ValueError("Empty or invalid intrinsic catalog")
    names = set()
    for row in catalog:
        if (not isinstance(row, dict) or not isinstance(row.get("name"), str)
                or not row["name"].strip() or row["name"] in names
                or not isinstance(row.get("return_type"), dict)
                or not isinstance(row["return_type"].get("value"), str)
                or not row["return_type"]["value"].strip()
                or not isinstance(row.get("arguments"), list)
                or not all(isinstance(arg, str) for arg in row["arguments"])
                or not isinstance(row.get("description"), str)
                or not isinstance(row.get("instruction_group"), str)
                or not isinstance(row.get("Architectures"), list)
                or not all(isinstance(arch, str) for arch in row["Architectures"])
                or not isinstance(row.get("SIMD_ISA"), (str, list))
                or (isinstance(row["SIMD_ISA"], list)
                    and not all(isinstance(isa, str) for isa in row["SIMD_ISA"]))):
            raise ValueError(f"Invalid or duplicate intrinsic catalog record: {row.get('name') if isinstance(row, dict) else row}")
        names.add(row["name"])


def build_intrinsic_chunk(row: dict, operations: dict[str, str]) -> dict:
    """Reuse the reference-text and prepared-description format for every family."""
    name = row["name"]
    families = row["SIMD_ISA"]
    if isinstance(families, str):
        families = [families]
    families = [_FAMILIES.get(isa.lower(), isa) for isa in families]
    if unknown := set(families) - _HEADERS.keys():
        raise ValueError(f"Unsupported intrinsic families: {sorted(unknown)}")
    isa = " / ".join(families) or "ACLE"
    description = _text(row["description"])
    signature = f"{row['return_type']['value']} {name} ({', '.join(row['arguments'])});"
    content = f"The `{name}` intrinsic is part of the {isa} instruction set architecture."
    if not families:
        content = f"The `{name}` intrinsic is part of the Arm C Language Extensions (ACLE)."
    content += f" Here is a brief intrinsic description: {description}\n\n"
    content += f"The signature for this intrinsic function is as follows:\n`{signature}`\n\n"
    content += "Architectures: " + ", ".join(row["Architectures"]) + ".\n"
    headers = sorted({_HEADERS[family] for family in families if family in _HEADERS})
    if not families:
        headers = ["arm_acle.h"]
    if set(families) == {"Neon", "SVE"}:
        headers = ["arm_neon_sve_bridge.h"]
    if headers:
        content += "Header declarations: " + ", ".join(f"`#include <{header}>`" for header in headers) + ".\n"
    for field in ("required_features", "required_streaming_features", "required_non_streaming_features"):
        requirement = row.get(field)
        if isinstance(requirement, dict):
            content += " ".join(_text(requirement[key]) for key in ("title", "intro", "features")
                                if isinstance(requirement.get(key), str)) + "\n"
    if row.get("sme_modes"):
        content += "Function attributes: " + ", ".join(row["sme_modes"]) + ".\n"
    if row.get("Operation"):
        operation = operations.get(row["Operation"])
        if not operation:
            raise ValueError(f"Missing operation {row['Operation']} for intrinsic {name}")
        soup = BeautifulSoup(operation, "html.parser")
        for heading in soup.find_all(re.compile("^h[1-6]$")):
            if heading.get_text().strip() == "Operation":
                heading.decompose()
        for pre in soup.find_all("pre"):
            pre.replace_with("`" + pre.get_text() + "`")
        content += f"\nThis is the pseudocode for how the {name} intrinsic operates:\n" + soup.get_text()
    for group in row.get("instructions", []):
        content += "\n" + _text(group.get("preamble", "Instructions:")) + "\n"
        for instruction in group.get("list", []):
            content += f"`{instruction.get('base_instruction', '')} {instruction.get('operands', '')}`\n"
            if instruction.get("url"):
                content += instruction["url"] + "\n"
    url = REFERENCE_URL + "#q=" + name
    return prepare_intrinsic_chunk({
        "title": f"Arm Intrinsics - {name}", "url": url, "product": isa,
        "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, url)),
        "keywords": ", ".join([name, *families, row["instruction_group"].replace("|", ", ")]),
        "content": content,
    })


def refresh_catalog(existing_dir: Path, output_dir: Path, tokenizer) -> dict:
    """Validate the full replacement before writing; retain existing names and IDs."""
    if output_dir.exists():
        raise ValueError(f"Output directory must not already exist: {output_dir}")
    hashes = {}

    def load(filename, url):
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        content = response.content
        hashes[filename] = hashlib.sha256(content).hexdigest()
        return json.loads(content)

    catalog = load("intrinsics.json", CATALOG_URL)
    _validate_catalog(catalog)
    records = load("operations.json", OPERATIONS_URL)
    operations = {row["item"]["id"]: row["item"]["content"] for row in records}
    if len(operations) != len(records) or not all(isinstance(v, str) for v in operations.values()):
        raise ValueError("Invalid or duplicate intrinsic operations")
    existing = {}
    for path in sorted(existing_dir.glob("*.yaml")):
        chunk = yaml.safe_load(path.read_text())
        url = chunk["url"]
        if not url.startswith(REFERENCE_URL + "#q="):
            raise ValueError(f"Invalid intrinsic URL in {path}")
        name = url.split("#q=", 1)[1]
        if name in existing or not chunk.get("uuid"):
            raise ValueError(f"Duplicate intrinsic name or missing ID in {path}")
        existing[name] = (path.name, chunk)
    if not existing:
        raise ValueError("The pinned intrinsic snapshot is empty")
    missing = existing.keys() - {row["name"] for row in catalog}
    if missing:
        raise ValueError(f"Catalog is missing {len(missing)} existing intrinsics; review before replacing the snapshot")

    chunks, updated, max_tokens = {}, 0, 0
    for row in catalog:
        chunk = build_intrinsic_chunk(row, operations)
        if row["name"] in existing:
            filename, previous = existing[row["name"]]
            chunk.update(uuid=previous["uuid"], url=previous["url"])
            updated += chunk != prepare_intrinsic_chunk(previous)
        else:
            filename = f"catalog_{chunk['uuid']}.yaml"
        tokens = len(tokenizer(chunk["embedding_text"], add_special_tokens=True, truncation=False)["input_ids"])
        if tokens > 500:
            raise ValueError(f"Intrinsic {row['name']} exceeds 500 embedding tokens: {tokens}")
        max_tokens = max(max_tokens, tokens)
        if filename in chunks:
            raise ValueError(f"Duplicate intrinsic filename: {filename}")
        chunks[filename] = chunk
    if len({c["uuid"] for c in chunks.values()}) != len(chunks):
        raise ValueError("Duplicate intrinsic IDs")
    report = {"records": len(chunks), "added": len(chunks) - len(existing),
              "updated": updated, "max_embedding_tokens": max_tokens, "source_sha256": hashes}
    output_dir.mkdir(parents=True)
    for filename, chunk in sorted(chunks.items()):
        (output_dir / filename).write_text(yaml.safe_dump(chunk, sort_keys=False))
    (output_dir / "catalog-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    from transformers import AutoTokenizer

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path", required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, local_files_only=True, trust_remote_code=False)
    tokenizer.model_max_length = 512
    report = refresh_catalog(args.existing, args.output, tokenizer)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
