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
import csv
import datetime
import json
import os
import re
import uuid
from pathlib import Path

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from document_chunking import (
    arm_service_url_to_developer_url,
    chunk_parsed_document,
    is_arm_developer_documentation_url,
    normalize_source_url,
    parse_arm_documentation_api_json,
    parse_document_content,
    prepare_intrinsic_chunk,
    source_to_fetch_url,
)
from ecosystem_dashboard import acquire_catalog
from learn_repository import LearnSources, is_learn_url


# Create a session with retry logic for resilient HTTP requests
def create_retry_session(
    retries=5, backoff_factor=1, status_forcelist=(500, 502, 503, 504)
):
    """Create a requests session with automatic retry on failures."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["HEAD", "GET", "OPTIONS"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# Global session for all HTTP requests
http_session = create_retry_session()


"""
To fix:
1. Prevent multiple learning paths from being used (compare URLs to existing chunks OR delete overlaps)
2. Learning Path titles must come from index page...send through function along with Graviton.
"""

yaml_dir = os.getenv("YAML_OUTPUT_DIR", "yaml_data")
details_file = os.getenv("CHUNK_DETAILS_FILE", "info/chunk_details.csv")

chunk_index = 1

# Reuse the same pinned source snapshots for discovery and chunking.
learn_sources = LearnSources(http_session)

# Reuse one validated source revision for dashboard discovery and chunking.
ecosystem_dashboard_entries = None

# Global tracking for vector-db-sources.csv
# Set of URLs already in the CSV (for deduplication)
known_source_urls = set()
# List of all source entries (including existing and new)
# Each entry is a dict: {site_name, license_type, display_name, url, keywords}
all_sources = []

# Increase the file size limit, which defaults to '131,072'
csv.field_size_limit(
    10**9
)  # 1,000,000,000 (1 billion), smaller than 64-bit space but avoids 'python overflowerror'


def load_existing_sources(csv_file):
    """
    Load existing sources from vector-db-sources.csv into memory.
    Populates known_source_urls set and all_sources list.
    """
    global known_source_urls, all_sources
    known_source_urls = set()
    all_sources = []

    if not os.path.exists(csv_file):
        print(f"Sources file '{csv_file}' does not exist. Starting fresh.")
        return

    with open(csv_file, "r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            url = row.get("URL", "").strip()
            if url:
                known_source_urls.add(url)
                all_sources.append(
                    {
                        "site_name": row.get("Site Name", ""),
                        "license_type": row.get("License Type", ""),
                        "display_name": row.get("Display Name", ""),
                        "url": url,
                        "keywords": row.get("Keywords", ""),
                        "transcript_source_url": (
                            row.get("Transcript Source URL", "") or ""
                        ).strip(),
                    }
                )

    print(f"Loaded {len(all_sources)} existing sources from '{csv_file}'")


def register_source(
    site_name, license_type, display_name, url, keywords, transcript_source_url=""
):
    """
    Register a new source URL. If the URL already exists, skip it.
    Returns True if the source was added, False if it was a duplicate.
    """
    global known_source_urls, all_sources

    # Normalize URL for comparison
    url = url.strip()

    if url in known_source_urls:
        return False

    known_source_urls.add(url)
    source_entry = {
        "site_name": site_name,
        "license_type": license_type,
        "display_name": display_name,
        "url": url,
        "keywords": keywords if isinstance(keywords, str) else "; ".join(keywords),
        "transcript_source_url": (transcript_source_url or "").strip(),
    }

    # Keep discovered sources grouped with their existing site section instead of
    # appending them to the very end of the CSV and fragmenting that block.
    insert_at = None
    for index, existing_source in enumerate(all_sources):
        if existing_source.get("site_name") == site_name:
            insert_at = index + 1

    if insert_at is None:
        all_sources.append(source_entry)
    else:
        all_sources.insert(insert_at, source_entry)

    print(f"[NEW SOURCE] {display_name}: {url}")
    return True


def save_sources_csv(csv_file):
    """
    Write all sources (existing + new) to vector-db-sources.csv.
    """
    with open(csv_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "Site Name",
                "License Type",
                "Display Name",
                "URL",
                "Keywords",
                "Transcript Source URL",
            ]
        )
        for source in all_sources:
            writer.writerow(
                [
                    source["site_name"],
                    source["license_type"],
                    source["display_name"],
                    source["url"],
                    source["keywords"],
                    source.get("transcript_source_url", ""),
                ]
            )

    print(f"Saved {len(all_sources)} sources to '{csv_file}'")


class Chunk:
    def __init__(
        self,
        title,
        url,
        uuid,
        keywords,
        content,
        heading="",
        heading_path=None,
        doc_type="",
        product="",
        version="",
        resolved_url="",
        content_type="",
        platform="",
        edition="",
    ):
        self.title = title
        self.url = url
        self.uuid = uuid
        self.content = content
        self.heading = heading
        self.heading_path = heading_path or []
        self.doc_type = doc_type
        self.product = product
        self.version = version
        self.resolved_url = resolved_url
        self.content_type = content_type
        self.platform = platform
        self.edition = edition

        # Translate keyword list into comma-separated string, and add similar words to keywords.
        self.keywords = self.formatKeywords(keywords)

    def formatKeywords(self, keywords):
        """Format keywords list into a lowercase, comma-separated string."""
        return ", ".join(k.strip() for k in keywords).lower()

    # Used to dump into a yaml file without difficulty
    def toDict(self):
        return {
            "title": self.title,
            "url": self.url,
            "uuid": self.uuid,
            "keywords": self.keywords,
            "content": self.content,
            "heading": self.heading,
            "heading_path": self.heading_path,
            "doc_type": self.doc_type,
            "product": self.product,
            "version": self.version,
            "resolved_url": self.resolved_url,
            "content_type": self.content_type,
            "platform": self.platform,
            "edition": self.edition,
        }

    def __repr__(self):
        return f"Chunk(title={self.title}, url={self.url}, uuid={self.uuid}, heading={self.heading})"


def build_ecosystem_dashboard_entries():
    """Acquire and validate the dashboard once per run."""
    global ecosystem_dashboard_entries
    if ecosystem_dashboard_entries is None:
        ecosystem_dashboard_entries = acquire_catalog(
            http_session, os.getenv("ECOSYSTEM_DASHBOARD_REVISION", "")
        )
    return ecosystem_dashboard_entries


def create_ecosystem_dashboard_chunk(source_url, keywords_value):
    packages = build_ecosystem_dashboard_entries().get(source_url)
    if not packages:
        print(f"[ECOSYSTEM OMITTED SOURCE] Missing or invalid in snapshot: {source_url}")
        return []
    # CSV rows represent public URLs, which may cover multiple editions. Keep
    # each record's own catalog/category keywords instead of mixing editions.
    generated = {word.casefold() for package in packages for word in package.keywords}
    curated = [
        word
        for word in parse_keywords(keywords_value)
        if word.casefold() not in generated
    ]
    chunks = []
    for package in packages:
        keywords = list(dict.fromkeys(package.keywords + curated))
        chunks.extend(
            chunk_from_payload(payload, keywords)
            for payload in chunk_parsed_document(
                package.document, "Ecosystem Dashboard", keywords
            )
        )
    return chunks


def reconcile_ecosystem_sources(discover=True):
    """Replace only dashboard rows, keeping curated keywords and one row per URL.

    Discovery reconciles the complete catalog, including removed/skipped entries.
    With SKIP_DISCOVERY, only existing rows are retained; the requested source
    subset never expands. Missing records are reported and omitted in both modes.
    """
    global all_sources, known_source_urls
    existing = [row for row in all_sources if row["site_name"] == "Ecosystem Dashboard"]
    if not discover and not existing:
        return
    catalog = build_ecosystem_dashboard_entries()
    curated = {}
    for row in existing:
        curated.setdefault(row["url"], []).extend(parse_keywords(row["keywords"], ""))
    missing = curated.keys() - catalog.keys()
    for url in sorted(missing):
        print(f"[ECOSYSTEM OMITTED SOURCE] Missing or invalid in snapshot: {url}")
    replacements = []
    for url, packages in catalog.items():
        if not discover and url not in curated:
            continue
        keywords = list(
            dict.fromkeys(
                curated.get(url, [])
                + [word for package in packages for word in package.keywords]
            )
        )
        replacements.append(
            {
                "site_name": "Ecosystem Dashboard",
                "license_type": "Arm Proprietary",
                "display_name": packages[0].document.display_title,
                "url": url,
                "keywords": "; ".join(keywords),
                "transcript_source_url": "",
            }
        )
    position = next(
        (
            i
            for i, row in enumerate(all_sources)
            if row["site_name"] == "Ecosystem Dashboard"
        ),
        len(all_sources),
    )
    remaining = [
        row for row in all_sources if row["site_name"] != "Ecosystem Dashboard"
    ]
    all_sources = remaining[:position] + replacements + remaining[position:]
    known_source_urls = {row["url"] for row in all_sources}


def discover_learn_sources():
    for source in learn_sources.discovered_sources():
        register_source(**source)


def reconcile_learn_sources(discover=True):
    """Omit retired/unpublished rows, retaining curated metadata for live pages."""
    global all_sources, known_source_urls
    retained = []
    for source in all_sources:
        url = source["url"]
        if is_learn_url(url) and not learn_sources.has_page(url):
            print(f"[LEARN OMITTED SOURCE] Missing or unpublished in snapshot: {url}")
        else:
            retained.append(source)
    all_sources = retained
    known_source_urls = {source["url"] for source in all_sources}
    if discover:
        discover_learn_sources()


def create_learn_chunks(source_url, source_name, doc_type, keywords_value):
    keywords = parse_keywords(keywords_value, source_name)
    chunks = []
    for document in learn_sources.documents(source_url):
        for payload in chunk_parsed_document(
            document, doc_type=doc_type or "Documentation", keywords=keywords
        ):
            chunks.append(chunk_from_payload(payload, keywords))
    return chunks


def readInCSV(csv_file):
    """Read sources CSV file and return dict of lists for processing.

    Uses csv.DictReader to properly handle quoted fields containing commas.
    Returns empty results if the file doesn't exist.
    """
    csv_dict = {
        "urls": [],
        "focus": [],
        "source_names": [],
        "site_names": [],
        "license_types": [],
        "transcript_urls": [],
    }

    if not os.path.exists(csv_file):
        return csv_dict, 0

    with open(csv_file, "r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            csv_dict["urls"].append(normalize_source_url(row.get("URL", "")))
            csv_dict["focus"].append(row.get("Keywords", ""))
            csv_dict["source_names"].append(row.get("Display Name", ""))
            csv_dict["site_names"].append(row.get("Site Name", ""))
            csv_dict["license_types"].append(row.get("License Type", ""))
            csv_dict["transcript_urls"].append(
                (row.get("Transcript Source URL", "") or "").strip()
            )

    return csv_dict, len(csv_dict["urls"])


def getMarkdownGitHubURLsFromPage(url):
    GH_urls = []
    SITE_urls = []

    fetch_url = source_to_fetch_url(url)
    if fetch_url != normalize_source_url(url):
        SITE_urls.append(normalize_source_url(url))
        GH_urls.append(fetch_url)
    else:
        print("url doesnt match expected format. Check function and try again.")
        print("URL: ", url)

    return GH_urls, SITE_urls


def URLIsValidCheck(url):
    try:
        response = http_session.get(url, timeout=60)
        response.raise_for_status()  # Ensure we got a valid response
        return True
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        with open("info/errors.csv", "a", newline="") as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow([url, str(http_err)])
        return False


def fetch_with_logging(url):
    try:
        response = http_session.get(url, timeout=60)
        response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        with open("info/errors.csv", "a", newline="") as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow([url, str(http_err)])
        return None
    except Exception as err:
        print(f"Other error occurred: {err}")
        with open("info/errors.csv", "a", newline="") as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow([url, str(err)])
        return None


def obtainMarkdownContentFromGitHubMDFile(gh_url):
    response = http_session.get(gh_url, timeout=60)
    response.raise_for_status()  # Ensure we got a valid response
    md_content = response.text

    return md_content


def obtainTextSnippets__Markdown(
    content, min_words=300, max_words=500, min_final_words=200
):
    """Backward-compatible wrapper that now uses structured chunking."""
    if not content or not content.strip():
        return []
    parsed_document = parse_document_content(
        source_url="https://example.com",
        resolved_url="https://example.com/doc.md",
        response_content=content.encode("utf-8"),
        content_type="text/markdown",
        fallback_title="Document",
    )
    chunks = chunk_parsed_document(
        parsed_document,
        doc_type="Markdown",
        keywords=[],
        min_tokens=min_words,
        max_tokens=max_words,
        overlap_tokens=max(0, min_final_words // 4),
    )
    return [chunk["content"] for chunk in chunks]


def chunk_from_payload(payload, keywords, **overrides):
    """Serialize shared chunker output without repeating its metadata field list."""
    return Chunk(uuid=str(uuid.uuid4()), keywords=keywords, **(payload | overrides))


def printChunks(chunks):
    for chunk_dict in chunks:
        print("=" * 100)
        print("Title:", chunk_dict["title"])
        print("Keywords:", chunk_dict["keywords"])
        print("URL:", chunk_dict["url"])
        print("Unique ID:", chunk_dict["uuid"])
        print("Content:", chunk_dict["content"])
        print("=" * 100)


def parse_keywords(keywords_value, title=""):
    keywords = [
        keyword.strip()
        for keyword in re.split(r"[;,]", keywords_value or "")
        if keyword.strip()
    ]
    if title and title not in keywords:
        keywords.append(title)
    return keywords


def log_no_parsed_sections(parsed_document, source_url, source_name, transcript_url=""):
    if parsed_document.sections:
        return False

    context = f"source: {source_url}"
    if transcript_url:
        context += f"; transcript: {transcript_url}"
    print(
        "[NO CHUNKS] no parseable content for "
        f"{source_name or parsed_document.display_title} ({context}; "
        f"resolved: {parsed_document.resolved_url}; content_type: {parsed_document.content_type})"
    )
    return True


def create_transcript_chunks(
    source_url, transcript_url, source_name, doc_type, keywords_value
):
    """Chunk a transcript document on behalf of a primary source.

    Some sources (for example edX course videos) have no directly chunkable text
    at their primary URL. When a "Transcript Source URL" is provided in the CSV,
    we fetch and chunk that transcript document instead, but keep the primary
    ``source_url`` as the user-facing link so retrieval still points users at
    the original content.
    """
    if is_learn_url(transcript_url):
        chunks = create_learn_chunks(transcript_url, source_name, doc_type, keywords_value)
        for chunk in chunks:
            chunk.url = normalize_source_url(source_url)
        return chunks
    normalized_source_url = normalize_source_url(source_url)
    fetch_url = source_to_fetch_url(normalize_source_url(transcript_url))
    response = fetch_with_logging(fetch_url)
    if response is None:
        print(
            f"[TRANSCRIPT FETCH FAILED] for {normalized_source_url} (transcript: {transcript_url}): {fetch_url}"
        )
        return []

    keywords = parse_keywords(keywords_value, source_name)
    parsed_document = parse_document_content(
        source_url=normalize_source_url(transcript_url),
        resolved_url=response.url,
        response_content=response.content,
        content_type=response.headers.get("content-type", ""),
        fallback_title=source_name,
    )
    # Keep the primary URL as the user-facing link while still using the transcript
    # URL as the base for resolving any relative links inside the transcript content.
    parsed_document.source_url = normalized_source_url
    if log_no_parsed_sections(
        parsed_document, normalized_source_url, source_name, transcript_url
    ):
        return []

    chunks = []
    for payload in chunk_parsed_document(
        parsed_document, doc_type=doc_type or "Transcript", keywords=keywords
    ):
        chunks.append(
            chunk_from_payload(
                payload,
                keywords,
                url=normalized_source_url,
                title=payload["title"] or source_name,
                resolved_url=response.url,
            )
        )
    return chunks


def create_chunks_for_source(
    source_url, source_name, doc_type, keywords_value, transcript_url=""
):
    source_url = normalize_source_url(source_url)
    transcript_url = normalize_source_url(transcript_url)
    # When a transcript source is provided, chunk that document instead of
    # fetching the primary URL (which may be a video player or other non-text page),
    # while keeping the primary URL as the user-facing link for retrieval.
    if transcript_url and transcript_url.strip():
        return create_transcript_chunks(
            source_url, transcript_url, source_name, doc_type, keywords_value
        )
    if is_learn_url(source_url):
        return create_learn_chunks(source_url, source_name, doc_type, keywords_value)
    if doc_type == "Ecosystem Dashboard":
        return create_ecosystem_dashboard_chunk(source_url, keywords_value)
    if is_arm_developer_documentation_url(source_url):
        return create_arm_documentation_chunks(
            source_url, source_name, doc_type, keywords_value
        )

    normalized_source_url = normalize_source_url(source_url)
    fetch_url = source_to_fetch_url(normalized_source_url)
    response = fetch_with_logging(fetch_url)
    if response is None:
        print(f"Fetch failed for {normalized_source_url}: {fetch_url}")
        return []

    sources_to_parse = [(normalized_source_url, response)]

    keywords = parse_keywords(keywords_value, source_name)
    chunks = []
    for display_url, source_response in sources_to_parse:
        parsed_document = parse_document_content(
            source_url=display_url,
            resolved_url=source_response.url,
            response_content=source_response.content,
            content_type=source_response.headers.get("content-type", ""),
            fallback_title=source_name,
        )
        if log_no_parsed_sections(parsed_document, display_url, source_name):
            continue
        for payload in chunk_parsed_document(
            parsed_document, doc_type=doc_type or "Documentation", keywords=keywords
        ):
            chunks.append(chunk_from_payload(payload, keywords))
    return chunks


def _arm_topic_links(topic):
    links = []
    for child in topic.get("topics", []) or []:
        self_links = child.get("_links", {}).get("self", [])
        if self_links and self_links[0].get("href"):
            links.append(self_links[0]["href"])
        links.extend(_arm_topic_links(child))
    return links


def _arm_metadata_keywords(root_data, keywords_value, source_name):
    keywords = parse_keywords(keywords_value, source_name)
    for value in root_data.get("keywords", []) + root_data.get("products", []):
        if value and value not in keywords:
            keywords.append(value)
    return keywords


def create_arm_documentation_chunks(source_url, source_name, doc_type, keywords_value):
    root_response = fetch_with_logging(source_to_fetch_url(source_url))
    if root_response is None:
        return []

    root_data = json.loads(root_response.content.decode("utf-8", errors="ignore"))
    keywords = _arm_metadata_keywords(root_data, keywords_value, source_name)
    document_title = root_data.get("title") or source_name
    topic_links = _arm_topic_links(root_data.get("topic", {}))
    fetch_urls = topic_links or [root_response.url]

    chunks = []
    for fetch_url in fetch_urls:
        if fetch_url == root_response.url:
            response = root_response
        else:
            response = fetch_with_logging(fetch_url)
            if response is None:
                continue

        display_url = arm_service_url_to_developer_url(response.url, source_url)
        parsed_document = parse_arm_documentation_api_json(
            response_content=response.content,
            source_url=display_url,
            resolved_url=response.url,
            fallback_title=document_title,
        )
        if log_no_parsed_sections(parsed_document, display_url, document_title):
            continue
        for payload in chunk_parsed_document(
            parsed_document, doc_type=doc_type or "Documentation", keywords=keywords
        ):
            chunks.append(
                chunk_from_payload(
                    payload,
                    keywords,
                    version=root_data.get("versionLabel") or payload["version"],
                )
            )
    return chunks


def chunkSaveAndTrack(url, chunk):

    def addNewRow(current_date, chunk_words, chunk_id):
        return [url, current_date, chunk_words, "1", chunk_id]

    def addToExistingRow(row, chunk_words, chunk_id):
        url = row[0]  # same URL
        date = row[1]  # same date
        words = str(int(row[2]) + chunk_words)  # update words
        chunks = row[3] = str(int(row[3]) + 1)  # update number of chunks
        ids = row[4] + f", {chunk_id}"  # update chunk IDs
        return [url, date, words, chunks, ids]

    def recordChunk():
        current_date = datetime.date.today().strftime("%Y-%m-%d")
        chunk_words = len(chunk.content.split())
        chunk_id = f"chunk_{chunk.uuid}"

        new_rows = []

        with open(details_file, mode="r", newline="", encoding="utf-8") as file:
            csv_reader = csv.reader(file)
            try:
                headers = next(csv_reader)
                new_rows.append(headers)  # keep in memory
            except StopIteration:
                pass

            url_found = False  # Track if the URL is found in any row

            # Loop through all the rows after the header
            for row in csv_reader:
                if row[0] == url:
                    new_rows.append(
                        addToExistingRow(row, chunk_words, chunk_id)
                    )  # Modify and append the row
                    url_found = True  # Mark that the URL was found
                else:
                    new_rows.append(row)  # Append the row without modification

            # If the URL was not found, append a new row
            if not url_found:
                new_rows.append(addNewRow(current_date, chunk_words, chunk_id))

        # Overwrite csv with new info
        with open(details_file, mode="w", newline="") as file:
            csv_writer = csv.writer(file, delimiter=",")
            csv_writer.writerows(new_rows)

    # Save chunk
    file_name = f"{yaml_dir}/chunk_{chunk.uuid}.yaml"
    with open(file_name, "w") as file:
        yaml.dump(prepare_intrinsic_chunk(chunk.toDict()), file, default_flow_style=False, sort_keys=False)

    # Record chunk
    recordChunk()
    print(f"{file_name} === {chunk.title}")


def prepare_intrinsic_chunks():
    """Prepare copied intrinsic records before publishing the chunk artifact."""
    directory = Path(os.getenv("INTRINSIC_CHUNKS_DIR", "intrinsic_chunks"))
    for path in sorted(directory.glob("*.yaml")):
        chunk = prepare_intrinsic_chunk(yaml.safe_load(path.read_text()))
        path.write_text(yaml.safe_dump(chunk, sort_keys=False))


def main():
    skip_discovery = os.getenv("SKIP_DISCOVERY", "").lower() in {"1", "true", "yes"}

    # Argparse inputs
    parser = argparse.ArgumentParser(
        description="Generate text chunks from Arm documentation sources for vector database ingestion. "
        "Discovers learning paths, install guides, and ecosystem dashboard entries, "
        "then updates the sources CSV with any new entries found."
    )
    parser.add_argument(
        "sources_file",
        help="Path to vector-db-sources.csv. This file is read for existing sources "
        "(to avoid duplicates) and WILL BE OVERWRITTEN with the combined list "
        "of existing + newly discovered sources.",
    )
    args = parser.parse_args()
    sources_file = args.sources_file

    prepare_intrinsic_chunks()

    # Load existing sources from vector-db-sources.csv (for deduplication)
    load_existing_sources(sources_file)

    # 0) Obtain full database information:
    # a) All Learn content, including courses and Insights
    reconcile_learn_sources(discover=not skip_discovery)

    # b) Validate and reconcile the dashboard before writing any source changes.
    reconcile_ecosystem_sources(discover=not skip_discovery)
    # Validate Learn sources before modifying the CSV or deleting old chunks.
    # This also applies to SKIP_DISCOVERY and explicit transcript sources.
    for source in all_sources:
        url = source.get("transcript_source_url") or source["url"]
        if is_learn_url(url):
            learn_sources.documents(url)
    save_sources_csv(sources_file)

    # 0) Initialize files
    os.makedirs(yaml_dir, exist_ok=True)  # create if doesn't exist
    details_dir = os.path.dirname(details_file)
    if details_dir:
        os.makedirs(details_dir, exist_ok=True)
    for filename in os.listdir(yaml_dir):
        if filename.startswith("chunk_") and filename.endswith(".yaml"):
            os.remove(os.path.join(yaml_dir, filename))
    with open(details_file, mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            ["URL", "Date", "Number of Words", "Number of Chunks", "Chunk IDs"]
        )

    # 1) Get URLs and details from CSV
    csv_dict, csv_length = readInCSV(sources_file)

    seen_learn_chunks = set()
    print(f"Starting to loop over CSV file {sources_file} ......")
    for i in range(csv_length):
        url = csv_dict["urls"][i]
        source_name = csv_dict["source_names"][i]
        doc_type = csv_dict["site_names"][i]
        keywords_value = csv_dict["focus"][i]
        transcript_url = csv_dict["transcript_urls"][i]

        for chunk in create_chunks_for_source(
            url, source_name, doc_type, keywords_value, transcript_url
        ):
            if is_learn_url(url):
                # A parent guide and an explicitly listed child may overlap.
                identity = (chunk.url, chunk.resolved_url, chunk.content)
                if identity in seen_learn_chunks:
                    continue
                seen_learn_chunks.add(identity)
            chunkSaveAndTrack(url, chunk)

    # Save updated sources CSV with all discovered sources
    save_sources_csv(sources_file)
    print("\n=== Source tracking complete ===")
    print(f"Total sources in {sources_file}: {len(all_sources)}")


if __name__ == "__main__":
    main()
