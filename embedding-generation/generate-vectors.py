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

import argparse
import json
import os
import re
import csv

from bs4 import BeautifulSoup
import requests
from urllib.parse import quote
from dataclasses import dataclass
from typing import Any, Dict, Optional
from playwright.async_api import async_playwright
import asyncio

from document_chunking import (
    chunk_parsed_document,
    parse_document_content,
)

from generate_common import (
    Chunk,
    createChunk,
    chunkSaveAndTrack,
    fetch_with_logging,
    register_source,
    save_sources_csv,
    load_existing_sources,
    get_number_of_sources,
    ensure_intrinsic_chunks_from_s3,
    yaml_dir,
    details_file,
    http_session
)


@dataclass
class CapturedSearchRequest:
    url: str
    method: str
    headers: Dict[str, str]
    post_data: Optional[str]
    response_json: Dict[str, Any]

async def capture_DeveloperArmComSearch(page_url: str) -> CapturedSearchRequest:
    apicount = 0
    def is_search_response(resp) -> bool:
        nonlocal apicount
        if "coveo.com/rest/search/v2" in resp.url and "querySuggest" not in resp.url:
            apicount += 1
            return (
                resp.request.method.upper() == "POST"
                and resp.request.post_data is not None
                and resp.status == 200
                and apicount > 1
            )
        else:
            return False

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

        if not(isinstance(data, dict) and "results" in data):
            raise RuntimeError("No search API response was captured. ")
        else:
            return CapturedSearchRequest(
                url=response.url,
                method=response.request.method,
                headers=dict(response.request.headers),
                post_data=response.request.post_data,
                response_json=data,
            )

def replay_DeveloperArmComSearch(
    captured: CapturedSearchRequest,
    query: str,
    first_result: int = 0,
    number_of_results: int = 48,
) -> Dict[str, Any]:

    def _merge_headers(base_headers: Dict[str, str]) -> Dict[str, str]:
        keep = {}
        drop = {"host", "content-length", "accept-encoding", "connection", "origin", "referer", "cookie"}
        for k, v in base_headers.items():
            if k.lower() not in drop:
                keep[k] = v
        keep.setdefault("accept", "application/json, text/plain, */*")
        keep.setdefault("content-type", "application/json")
        keep.setdefault("user-agent", "Mozilla/5.0")
        return keep

    if not captured.post_data:
        raise RuntimeError("Captured request had no POST body to replay.")

    body = json.loads(captured.post_data)
    body["q"] = query
    body["firstResult"] = first_result
    body["numberOfResults"] = number_of_results
    headers = _merge_headers(captured.headers)

    r = requests.post(captured.url, headers=headers, json=body, timeout=60)
    r.raise_for_status()
    return r.json()

def getDeveloperArmComSearchResults(searchterm: str, searchurl: str, maxitems: int = 20000):

    def extract_result(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "title": item.get("title") or item.get("raw", {}).get("title"),
            "url": item.get("clickUri") or item.get("uri") or item.get("url"),
            "type": item.get("raw", {}).get("navigationhierarchiescontenttype"),
            "author": item.get("raw", {}).get("author") or item.get("raw", {}).get("sysauthor"),
            "products": item.get("raw", {}).get("navigationhierarchiesproducts"),
            "objecttype": item.get("raw", {}).get("objecttype"),
            "keywords": item.get("raw", {}).get("navigationhierarchiestopics")
        }

    print('Searching developer.arm.com for "'+searchterm+'"')
    captured = asyncio.run(capture_DeveloperArmComSearch(searchurl))

    all_rows = []
    finished = False
    page_size = 48
    start = 0
    while (len(all_rows) < maxitems) and not finished:
        payload = replay_DeveloperArmComSearch(
            captured,
            query=searchterm,
            first_result=start,
            number_of_results=page_size,
        )

        items = [extract_result(x) for x in payload["results"]]
        all_rows.extend(items)
        finished = len(payload["results"]) < page_size
        start += page_size
    print("Found "+str(len(all_rows))+" results")
    return all_rows

def processDeveloperArmCom(url, title, type, keywords, emit_chunks=True):

    def chunkizeLearningPath(url, title, keywords):
        if not emit_chunks:
            return

        response = fetch_with_logging(url)
        if response is None:
            return
        parsed_document = parse_document_content(
            source_url=url,
            resolved_url=url,
            response_content=response.content,
            content_type=response.headers.get("content-type", "text/html"),
            fallback_title=title,
        )
        chunk_payloads = chunk_parsed_document(
            parsed_document,
            doc_type=type,
            keywords=keywords,
        )

        # 5) Create chunks for each snippet by adding metadata
        for payload in chunk_payloads:
            chunk = createChunk(
                payload["content"],
                url,
                keywords,
                payload["title"],
                heading=payload["heading"],
                heading_path=payload["heading_path"],
                doc_type=payload["doc_type"],
                product=payload["product"],
                version=payload["version"],
                resolved_url=payload["resolved_url"],
                content_type=payload["content_type"],
            )
            chunkSaveAndTrack(url,chunk)


    response = http_session.get(url, timeout=60)
    soup = BeautifulSoup(response.text, 'html.parser')

    itemtitle = 'Arm '+type+' - '+(blogtitle.get_text() if (blogtitle := soup.find(id='blog-title')) else title)
    itemdate = blogdate.get_text() if (blogdate := soup.find(id='blog-date')) else ''

    # Register this learning path as a source
    register_source(
        site_name='Arm Developer',
        license_type='Arm Proprietary',
        display_name=itemtitle,
        url=url,
        keywords=keywords
    )
    chunkizeLearningPath(url,itemtitle,keywords)

def item_is_relevant(item) -> bool:
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
                    "Predication"
            }

        case "Programmer's Guide":
            for pattern in {
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
                r"/Matrix-Multiply-Unit"
            }:
                if item.get("url") and re.search(pattern, item["url"]):
                    return True
            return False

        case "Blog Post":
            title = item.get("title") or ""
            author = item.get("author") or ""
            if author in {"Zenon_Xiu", "KhalidS"} and title.startswith("Part") and "SME" in title:
                return True
            if author == "mweidmann" and title.startswith("Introducing the Scalable Matrix Extension"):
                return True
            return False

        case _:
            return False

def createDeveloperArmComChunks(emit_chunks=True):
    search_base = "https://developer.arm.com/search#numberOfResults=48&f-navigationhierarchiescontenttype="
    content_types = [
        "Blog Post",
        "Guide",
        "Programmer's Guide"
    ]

    search_url = search_base+",".join([quote(x) for x in content_types])+"&q="
    for searchterm in ["SME"]:
        pages = getDeveloperArmComSearchResults(searchterm, search_url+searchterm)
        relevant = 0
        for page in pages:
            if item_is_relevant(page):
                keywords =  list(set( [searchterm] +
                                    [key for key_list in (page["keywords"] or []) for key in key_list.split(sep="|")] +
                                    [key for key_list in (page["products"] or []) for key in key_list.split(sep="|")[2:]]))
                processDeveloperArmCom(page["url"], page["title"], page["type"], keywords, emit_chunks=emit_chunks)
                relevant += 1
        print("Keeping "+str(relevant)+" relevant items out of "+str(len(pages)))

def main():
    skip_discovery = os.getenv("SKIP_DISCOVERY", "").lower() in {"1", "true", "yes"}

    # Ensure intrinsic_chunks folder and files from S3 are present
    ensure_intrinsic_chunks_from_s3()

    # Argparse inputs
    parser = argparse.ArgumentParser(
        description="Generates list of Arm documentation sources for vector database ingestion. "
                    "Discovers developer.arm.com entries, "
                    "then updates the sources CSV with any new entries found."
    )
    parser.add_argument(
        "sources_file",
        help="Path to vector-db-sources.csv. This file is read for existing sources "
             "(to avoid duplicates) and WILL BE OVERWRITTEN with the combined list "
             "of existing + newly discovered sources."
    )
    args = parser.parse_args()
    sources_file = args.sources_file

    # Load existing sources from vector-db-sources.csv (for deduplication)
    load_existing_sources(sources_file)

    # 0) Initialize files
    os.makedirs(yaml_dir, exist_ok=True) # create if doesn't exist
    details_dir = os.path.dirname(details_file)
    if details_dir:
        os.makedirs(details_dir, exist_ok=True)
    for filename in os.listdir(yaml_dir):
        if filename.startswith('chunk_') and filename.endswith('.yaml'):
            os.remove(os.path.join(yaml_dir, filename))
    with open(details_file, mode='w', newline='') as file:
        writer = csv.writer(file)        
        writer.writerow(['URL','Date', 'Number of Words', 'Number of Chunks','Chunk IDs'])

    # 0) Obtain full database information:
    # a) Learning Paths & Install Guides
    if not skip_discovery:
        # Developer.Arm.Com
        createDeveloperArmComChunks(emit_chunks=False)

    # Save updated sources CSV with all discovered sources
    save_sources_csv(sources_file)
    print(f"\n=== Source tracking complete ===")
    print(f"Total sources in {sources_file}: {get_number_of_sources()}")

if __name__ == "__main__":
    main()
