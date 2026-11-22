# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Slim MCP response fields without changing shared retrieval behavior."""

from typing import Any

from arm_kb_search.response import ARM_CONTENT_DISCLAIMER, is_arm_domain_url


def strip_snippet_prefix(snippet: str) -> str:
    lines = snippet.split("\n")
    i = 0
    while i < len(lines) and (lines[i].startswith("Document Title:")
                             or lines[i].startswith("Heading Path:") or not lines[i].strip()):
        i += 1
    return "\n".join(lines[i:]).strip()


def lean_result(item: dict[str, Any]) -> dict[str, Any]:
    """Copy presentation fields without mutating shared search results or ranking."""
    result = {key: value for key, value in item.items()
              if key not in {"disclaimer", "url_tracking_instruction", "distance"}}
    if "snippet" in result:
        result["snippet"] = strip_snippet_prefix(result["snippet"])
    return result


def lean_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one scoped Arm notice in the response for clients that omit instructions."""
    results = [lean_result(item) for item in items]
    for item, result in zip(items, results):
        if item.get("disclaimer") and is_arm_domain_url(item.get("url")):
            result["disclaimer"] = (
                "For all results in this response sourced from arm.com or its subdomains: "
                + ARM_CONTENT_DISCLAIMER
            )
            break
    return results
