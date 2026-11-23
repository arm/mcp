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

from typing import Any, Dict, List
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


ARM_CONTENT_DISCLAIMER = (
    "This information is derived from materials available on an arm.com subdomain and is subject to the "
    "terms and conditions applicable to the original source content. You should refer to the original "
    "materials for the full terms of use. Except where expressly stated in those terms or in a separate "
    "current and valid license from Arm to the information described, no license to any intellectual "
    "property rights is granted by Arm to use or implement this information."
)

UTM_SOURCE_PRESERVATION_NOTE = (
    "When sharing this result, use the URL exactly as returned. Preserve the `utm_source` query parameter "
    "and any URL fragment; do not remove, normalize, shorten, or rewrite the URL."
)


def is_arm_domain_url(url: str | None) -> bool:
    if not url:
        return False

    hostname = urlparse(url).hostname
    if not hostname:
        return False

    hostname = hostname.lower().rstrip(".")
    return hostname == "arm.com" or hostname.endswith(".arm.com")


def add_disclaimer_to_arm_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {**item, "disclaimer": ARM_CONTENT_DISCLAIMER} if is_arm_domain_url(item.get("url")) else item
        for item in results
    ]


def add_utm_source_to_url(url: str | None, utm_source: str | None) -> str | None:
    if not url or not utm_source:
        return url

    parsed = urlparse(url)
    query_params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "utm_source"
    ]
    query_params.append(("utm_source", utm_source))
    return urlunparse(parsed._replace(query=urlencode(query_params)))


def add_utm_source_to_results(
    results: List[Dict[str, Any]],
    utm_source: str | None,
) -> List[Dict[str, Any]]:
    if not utm_source:
        return results

    return [
        {
            **item,
            "url": add_utm_source_to_url(item.get("url"), utm_source),
            "url_tracking_instruction": UTM_SOURCE_PRESERVATION_NOTE,
        }
        if item.get("url")
        else item
        for item in results
    ]


def _split_snippet_prefix(snippet: str, title: Any, heading: Any) -> tuple[str, str | None]:
    """Strip a complete generated header only when result metadata agrees."""
    if not isinstance(title, str) or not title:
        return snippet, None
    lines = snippet.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    header = lines[i:i + 3]
    if (len(header) != 3 or header[0].rstrip("\r") != f"Document Title: {title}"
            or not header[1].startswith("Heading Path:") or header[2].strip()):
        return snippet, None
    heading_path = header[1].removeprefix("Heading Path:").strip()
    if not heading_path or (isinstance(heading, str) and heading
            and heading_path != heading and not heading_path.endswith(" > " + heading)):
        return snippet, None
    return "\n".join(lines[i + 3:]).strip(), heading_path


def lean_result(item: dict[str, Any]) -> dict[str, Any]:
    """Copy presentation fields without mutating shared search results or ranking."""
    result = {key: value for key, value in item.items()
              if key not in {"disclaimer", "url_tracking_instruction", "distance"}}
    if "snippet" in result:
        heading = result.get("heading")
        if isinstance(heading, list) and all(isinstance(part, str) for part in heading):
            heading = " > ".join(heading)
        result["snippet"], heading_path = _split_snippet_prefix(
            result["snippet"], result.get("title"), heading)
        if heading_path and heading_path != heading:
            result.setdefault("heading_path", heading_path)
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
