# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Match descriptive intrinsic operations and signature constraints."""
import re

TYPE = r"(?:sv)?(?:u?int|float|poly|bfloat)\d+(?:x\d+)*_t|svbool_t"
WIDTH = r"\b(8|16|32|64|128)\s*[- ]\s*bit\b"
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "eight": 8, "sixteen": 16}
OPERATIONS = {
    'add': '\\b(?:add|adds|adding|addition|sum|sums)\\b',
    'subtract': '\\b(?:subtract|subtracts|subtracting|subtraction)\\b',
    'multiply': '\\b(?:multiply|multiplies|multiplying|multiplication|product|products)\\b',
    'divide': '\\b(?:divide|divides|division|quotient|quotients)\\b',
    'absolute_difference': '\\babsolute differences?\\b',
    'absolute': '\\babsolute value\\b',
    'narrow': '\\b(?:narrow|narrows|narrowing)\\b',
    'widen': '\\b(?:widen|widens|widening)\\b',
    'load': '\\b(?:load|loads|loading)\\b',
    'store': '\\b(?:store|stores|storing)\\b',
    'gather': '\\bgather(?:s|ing)?\\b',
    'scatter': '\\bscatter(?:s|ing)?\\b',
    'shift': '\\bshift(?:s|ing)?\\b',
    'insert': '\\binsert(?:s|ing|ion)?\\b',
    'pairwise': '\\bpairwise\\b|\\badjacent pairs\\b',
    'accumulate': '\\baccumulat(?:e|es|ing|ion|or)\\b',
    'zip': '\\bzip\\b|\\binterleav(?:e|es|ing)\\b',
    'unzip': '\\bunzip\\b|\\bde-?interleav(?:e|es|ing)\\b',
    'transpose': '\\btranspos(?:e|es|ing|ition)\\b',
    'tuple_create': '\\b(?:create|construct|combine)\\b.{0,45}\\btuple\\b|\\bcreate vector tuple\\b',
    'tuple_extract': '\\bextract vector from tuple\\b',
    'compact': '\\bconcatenate active elements\\b|\\bcompact(?:s|ing|ion)?\\b|\\bpack(?:s|ing)? active\\b',
    'count_elements': '\\bcount elements\\b|\\bcount(?:s|ing)?\\b.{0,35}\\belements\\b|\\bruntime loop increment\\b',
    'count_active': '\\bcount active elements\\b|\\bcount(?:s|ing)?\\b.{0,20}\\b(?:true|active)\\b',
    'count_leading_zeros': '\\b(?:count leading zeros|leading zero)\\b',
    'count_leading_sign': '\\b(?:count leading sign|leading sign)\\b',
    'predicate_compare': '\\bwhile counter meets condition\\b|\\b(?:predicate|mask)\\b.{0,80}\\b(?:bound|counter|index|indexes|indices|comparison)\\b',
    'compare': '\\b(?:compare|compares|comparison|greater than|less than|equal to)\\b',
    'broadcast': '\\bset all lanes to the same value\\b|\\bbroadcast\\b',
    'extract_lane': '\\bextract one element from vector\\b|\\bextract(?:s|ing)?\\b.{0,20}\\blane\\b',
    'last_active': '\\blast active element\\b|\\blast active\\b',
    'table_lookup': '\\btable lookup\\b|\\blookup\\b.{0,12}\\btable\\b',
    'bit_select': '\\bbitwise select\\b|\\bselect(?:s|ing)? bits\\b|\\bbit mask\\b.{0,30}\\bselect\\b',
    'reinterpret': '\\breinterpret\\b|\\breinterpretation\\b',
    'reverse_bits': '\\breverse bits\\b|\\brevers(?:e|es|ing)\\b.{0,15}\\bbits\\b',
    'reverse_elements': '\\breverse elements\\b|\\brevers(?:e|es|ing)\\b.{0,15}\\b(?:byte|bytes|element|elements)\\b',
    'reciprocal': '\\breciprocal\\b',
    'square_root': '\\bsquare[- ]root\\b',
    'maximum': '\\b(?:maximum|largest)\\b',
    'minimum': '\\b(?:minimum|smallest)\\b',
    'negate': '\\b(?:negate|negation)\\b',
    'complex': '\\bcomplex\\b',
}


def operation_tags(text: str) -> set:
    tags = {key for key, pattern in OPERATIONS.items() if re.search(pattern, text.lower())}
    for specific, general in [("absolute_difference", "subtract"), ("count_active", "count_elements"),
                              ("reverse_bits", "reverse_elements")]:
        if specific in tags:
            tags.discard(general)
    return tags


def query_roles(text: str) -> dict | None:
    q = text.lower()
    isas = set(re.findall(r"\b(?:neon|sve2?|sme2?)\b", q))
    if len(isas) > 1 or isas & {"sme", "sme2"} or re.search(r"\b(?:install|compiler flags|benchmark|compare.*(?:sve|neon))\b", q):
        return None
    if not (re.search(r"\bintrinsics?\b", q) or (isas and re.search(
        r"\b(?:which|what)\b.{0,50}\b(?:function|operation|load|store)\b|"
        r"\b(?:create|construct|generate)\b.{0,45}\b(?:predicate|mask|tuple)\b", q))):
        return None
    tags = operation_tags(q)
    excluded = {tag for tag, pattern in OPERATIONS.items() for m in re.finditer(pattern, q)
                if re.search(r"\b(?:without|not|no)\s+(?:any\s+)?$", q[max(0, m.start()-18):m.start()])}
    tags -= excluded
    for kind in ["zero", "sign"]:
        if re.search(rf"\b{kind}[- ]extend", q):
            tags.add(kind + "_extend")
    if not tags:
        return None
    roles = []
    for match in re.finditer(WIDTH, q):
        before, after = q[max(0, match.start()-30):match.start()], q[match.end():match.end()+35]
        if re.match(r"\s*(?:loop )?(?:bound|counter|index|indexes|indices|scalar)", after):
            roles.append(("scalar_bits", int(match[1])))
        elif re.match(r"\s*(?:lanes|elements|data)", after):
            roles.append(("predicate_bits" if "predicate_compare" in tags else "element_bits", int(match[1])))
        elif "predicate" in before[-15:]:
            roles.append(("predicate_bits", int(match[1])))
    for match in re.finditer(rf"\b({TYPE})\b", q):
        before = q[max(0, match.start()-35):match.start()]
        if "load" in tags and re.search(r"\b(?:reads?|loads?|from)\s*$", before):
            roles.append(("memory_type", match[0].removeprefix("sv")))
        elif re.search(r"\b(?:into|returns?|result(?:ing)?)\s*$", before):
            roles.append(("return_type", match[0].removeprefix("sv")))
    if "gather" in q or "scatter" in q:
        roles.append(("addressing", "gather" if "gather" in q else "scatter"))
    elif tags & {"load", "store"} and re.search(r"\b(?:consecutive|contiguous|directly)\b", q):
        roles.append(("addressing", "contiguous"))
    widths = {int(x) for x in re.findall(WIDTH, q)}
    for pattern, bits in [(r"\b(?:fp32|single[- ]precision|float(?!\d|\w))\b", 32), (r"\b(?:fp64|double[- ]precision)\b", 64)]:
        if re.search(pattern, q):
            roles.extend([("element_bits", bits), ("element_kind", "float")])
    for match in re.finditer(r"\b(one|two|three|four|eight|sixteen|\d+)\s+(?:(?:signed|unsigned|floating-point|single-precision)\s+)?(?:lanes|elements|floats|triples|pairs|quadruples)\b", q):
        roles.append(("lanes", int(match[1]) if match[1].isdigit() else NUMBERS[match[1]]))
    saturating = None if not re.search(r"\bsaturat", q) else not bool(re.search(r"\b(?:without\s+(?:a\s+)?|non[- ])saturat", q))
    return {"isa": next(iter(isas)) if isas else None, "types": set(re.findall(TYPE, q)), "widths": widths,
            "operations": tags, "excluded": excluded, "saturating": saturating, "roles": roles}


def _signature_fields(signature: str, name: str) -> dict:
    """Extract sets of known facts directly, without a general C-type model."""
    fields = {key: set() for key in ["types", "widths", "scalar_bits", "element_bits", "element_kind",
                                    "lanes", "memory_type", "return_type", "predicate_bits"]}
    parts = signature.split("(", 1)
    if len(parts) != 2 or not parts[0].strip().endswith(name):
        return fields
    for position, raw in enumerate([parts[0][:-len(name)]] + parts[1].rstrip(");").split(",")):
        match = re.search(r"\b((sv)?(u?int|float|poly|bfloat)(\d+)(?:x(\d+))?(?:x\d+)?_t|svbool_t)\b", raw)
        if not match:
            if raw.strip() and raw.strip() != "void" and not re.fullmatch(r"\s*[\w\s]+\s+\w+\s*", raw):
                return {}
            continue
        full, scalable, kind, bits, lanes = match.groups()
        fields["types"].add(full)
        if not bits:
            continue
        bits, lanes = int(bits), int(lanes) if lanes else None
        element = f"{kind}{bits}_t"
        fields["widths"].add(bits)
        if position == 0:
            fields["return_type"].update([full.removeprefix("sv"), element])
        if "*" in raw:
            fields["memory_type"].add(element)
        elif scalable or lanes:
            fields["types"].add(element)
            fields["element_bits"].add(bits)
            fields["element_kind"].add(kind)
            if lanes and not scalable:
                fields["lanes"].add(lanes)
                fields["widths"].add(bits * lanes)
        elif position:
            fields["scalar_bits"].add(bits)
    fields["predicate_bits"] = {int(x) for x in re.findall(r"(?:_|\[)b(8|16|32|64)(?=$|_|\]|\[)", name)}
    fields["widths"] |= fields["predicate_bits"]
    return fields


def match_bonus(query: dict | None, metadata: dict) -> float:
    if not query or metadata.get("doc_type") != "Intrinsic":
        return 0.0
    isa, name = str(metadata.get("product") or "").lower(), str(metadata.get("heading") or "")
    text, categories = str(metadata.get("original_text") or ""), str(metadata.get("keywords") or "").lower()
    signature = re.search(r"follows:\s*`([^`]+)`", text)
    if not name or isa not in {"neon", "sve", "sve2"} or not signature:
        return 0.0
    fields = _signature_fields(signature[1], name)
    if not fields or not fields["types"]:
        return 0.0
    if query["isa"] and isa != query["isa"] and not (query["isa"] == "sve" and isa == "sve2"):
        return -0.6
    fields["addressing"] = {next((value for key, value in [("gather", "gather"), ("scatter", "scatter"),
                             ("consecutive", "contiguous")] if key in categories), None)} - {None}
    tags = operation_tags(categories)
    for tag, pattern in [("unzip", r"\bde-interleav"), ("zero_extend", r"\bzero extension\b|\bzero-extend"),
                         ("sign_extend", r"\bsign extension\b|\bsign-extend")]:
        if re.search(pattern, text, re.I):
            tags.add(tag)
    fields["widths"] |= {int(x) for x in re.findall(r"number of (8|16|32|64)[- ]bit (?:data )?elements", text, re.I)}
    saturated = True if re.search(r"\bsaturat", categories) else None
    if re.search(r"\b(?:without|non[- ])\s*saturat", text, re.I):
        saturated = False
    constraints = [(value in fields[key], bool(fields[key]), weight)
                   for key, weight in [("types", 1.0), ("widths", 0.7)] for value in query[key]]
    constraints += [(tag in tags, bool(tags), 1.2) for tag in query["operations"]]
    constraints += [(False, True, 1.2) for tag in query["excluded"] & tags]
    if query["saturating"] is not None:
        constraints.append((query["saturating"] == saturated, saturated is not None, 1.2))
    possible = sum(weight for _, _, weight in constraints)
    earned = sum((weight if matched else -0.35 * weight) for matched, known, weight in constraints if known)
    earned, possible = earned / possible if possible else 0.0, 1.0
    for key, wanted in query["roles"]:
        possible += 0.7
        if fields[key]:
            earned += 0.7 if wanted in fields[key] else -0.7
    return 0.6 * earned / possible
