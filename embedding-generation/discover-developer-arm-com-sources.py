# Copyright © 2025, Arm Limited and Contributors. All rights reserved.
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

"""Discover relevant developer.arm.com pages and add them to vector-db-sources.csv.

See README.md in this directory for usage guidance.
"""

import argparse
import asyncio
import csv
import json
import re
from dataclasses import dataclass
from typing import Any, Dict
from urllib.parse import quote

import requests
from playwright.async_api import async_playwright

SEARCH_TERMS = ["SME"]
CONTENT_TYPES = ["Blog Post", "Guide", "Programmer's Guide"]
PAGE_SIZE = 48


@dataclass
class CapturedSearchRequest:
    """A real Coveo search request captured from the browser, replayable with new queries."""
    url: str
    headers: Dict[str, str]
    post_data: str


async def capture_search_request(page_url: str) -> CapturedSearchRequest:
    """Load the developer.arm.com search page and capture its Coveo search API request.

    The Coveo API needs an auth token that is only available inside the page, so we
    capture one live request and replay it later with modified queries.
    """
    search_response_count = 0

    def is_search_response(resp) -> bool:
        nonlocal search_response_count
        if "coveo.com/rest/search/v2" not in resp.url or "querySuggest" in resp.url:
            return False
        search_response_count += 1
        # Skip the first search request: it fires before the page applies the
        # content-type facets, so only the second one carries the full payload.
        return (
            resp.request.method.upper() == "POST"
            and resp.request.post_data is not None
            and resp.status == 200
            and search_response_count > 1
        )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            async with page.expect_response(is_search_response, timeout=30_000) as response_info:
                await page.goto(page_url, wait_until="domcontentloaded")
            response = await response_info.value
            data = await response.json()
        finally:
            await browser.close()

    if not (isinstance(data, dict) and "results" in data):
        raise RuntimeError("No search API response was captured.")
    return CapturedSearchRequest(
        url=response.url,
        headers=dict(response.request.headers),
        post_data=response.request.post_data,
    )


def replay_search(captured: CapturedSearchRequest, query: str, first_result: int) -> Dict[str, Any]:
    """Replay the captured search request with a new query and result offset."""
    drop = {"host", "content-length", "accept-encoding", "connection", "origin", "referer", "cookie"}
    headers = {k: v for k, v in captured.headers.items() if k.lower() not in drop}
    headers.setdefault("accept", "application/json, text/plain, */*")
    headers.setdefault("content-type", "application/json")
    headers.setdefault("user-agent", "Mozilla/5.0")

    body = json.loads(captured.post_data)
    body["q"] = query
    body["firstResult"] = first_result
    body["numberOfResults"] = PAGE_SIZE

    response = requests.post(captured.url, headers=headers, json=body, timeout=60)
    response.raise_for_status()
    return response.json()


def search_developer_arm_com(searchterm: str, search_url: str) -> list:
    """Run a developer.arm.com search and return all result items."""

    def extract_result(item: Dict[str, Any]) -> Dict[str, Any]:
        raw = item.get("raw", {})
        return {
            "title": item.get("title") or raw.get("title"),
            "url": item.get("clickUri") or item.get("uri"),
            "type": raw.get("navigationhierarchiescontenttype"),
            "author": raw.get("author") or raw.get("sysauthor"),
            "products": raw.get("navigationhierarchiesproducts"),
            "keywords": raw.get("navigationhierarchiestopics"),
        }

    print(f'Searching developer.arm.com for "{searchterm}"')
    captured = asyncio.run(capture_search_request(search_url))

    results = []
    start = 0
    while True:
        payload = replay_search(captured, query=searchterm, first_result=start)
        results.extend(extract_result(x) for x in payload["results"])
        if len(payload["results"]) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    print(f"Found {len(results)} results")
    return results


def item_is_relevant(item: Dict[str, Any]) -> bool:
    """Editorial filter: keep only the SME-related pages we want in the vector DB."""
    if not item.get("url"):
        return False
    match item["type"]:
        case "Guide":
            return item["title"] in {
                "What is SME/SME2?",
                "Overview of SME",
                "Assembly code",
                "Streaming SVE",
                "Load and Store",
                "Z registers",
                "Real world examples",
                "ZA storage",
                "Predication",
            }
        case "Programmer's Guide":
            return any(
                re.search(pattern, item["url"])
                for pattern in (
                    r"/SME-Overview/",
                    r"/CME",
                    r"/matmul-fp32",
                    r"/lut-gemv-rm-int8",
                    r"/matmul-int8",
                    r"/gemv-cm-int8.+/",
                    r"/109246/.*/Introduction(\?|/The.+/)",
                    r"/Introduction-to-CME",
                    r"/Toolchains-and-model-support/(?!Quick-start)",
                    r"/Memory-access.(?!Implications)",
                    r"/Performance-monitoring",
                    r"/Matrix-Multiply-Unit",
                )
            )
        case "Blog Post":
            title = item.get("title") or ""
            author = item.get("author") or ""
            if author in {"Zenon_Xiu", "KhalidS"} and title.startswith("Part") and "SME" in title:
                return True
            return author == "mweidmann" and title.startswith("Introducing the Scalable Matrix Extension")
        case _:
            return False


def item_keywords(item: Dict[str, Any], searchterm: str) -> list:
    """Build a deduplicated keyword list from the search term and result metadata."""
    keywords = [searchterm]
    for key_list in item["keywords"] or []:
        keywords.extend(key_list.split("|"))
    for key_list in item["products"] or []:
        keywords.extend(key_list.split("|")[2:])
    return list(dict.fromkeys(keywords))


def main():
    parser = argparse.ArgumentParser(
        description="Discover relevant developer.arm.com pages and append any new "
                    "URLs to the sources CSV. Existing rows are preserved unchanged."
    )
    parser.add_argument("sources_file", help="Path to vector-db-sources.csv.")
    args = parser.parse_args()

    # Read the CSV verbatim so unrelated rows and columns round-trip untouched.
    with open(args.sources_file, "r", newline="", encoding="utf-8") as file:
        rows = list(csv.reader(file))
    header, existing_rows = rows[0], rows[1:]
    url_column = header.index("URL")
    known_urls = {row[url_column].strip() for row in existing_rows if len(row) > url_column}

    search_base = "https://developer.arm.com/search#numberOfResults=48&f-navigationhierarchiescontenttype="
    search_url = search_base + ",".join(quote(x) for x in CONTENT_TYPES) + "&q="

    new_rows = []
    for searchterm in SEARCH_TERMS:
        items = search_developer_arm_com(searchterm, search_url + searchterm)
        relevant = 0
        for item in items:
            if not item_is_relevant(item):
                continue
            relevant += 1
            if item["url"].strip() in known_urls:
                continue
            known_urls.add(item["url"].strip())
            display_name = f"Arm {item['type']} - {item['title']}"
            row = [
                "Arm Developer",
                "Arm Proprietary",
                display_name,
                item["url"],
                "; ".join(item_keywords(item, searchterm)),
            ]
            new_rows.append(row + [""] * (len(header) - len(row)))
            print(f"[NEW SOURCE] {display_name}: {item['url']}")
        print(f"Keeping {relevant} relevant items out of {len(items)}")

    if new_rows:
        with open(args.sources_file, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerows(rows + new_rows)

    print(f"\nAdded {len(new_rows)} new sources to {args.sources_file} "
          f"({len(existing_rows) + len(new_rows)} total).")
    if new_rows:
        print("Next: add questions with expected URLs for the new sources to eval_questions.json.")


if __name__ == "__main__":
    main()
