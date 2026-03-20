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
import os
import re
import uuid
import yaml
import csv
import datetime

import boto3
from botocore.exceptions import NoCredentialsError, ClientError
from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import parse_qs, urlparse

from document_chunking import (
    chunk_parsed_document,
    derive_product,
    derive_version,
    normalize_source_url,
    parse_document_content,
    source_to_fetch_url,
)


# Create a session with retry logic for resilient HTTP requests
def create_retry_session(retries=5, backoff_factor=1, status_forcelist=(500, 502, 503, 504)):
    """Create a requests session with automatic retry on failures."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# Global session for all HTTP requests
http_session = create_retry_session()


def ensure_intrinsic_chunks_from_s3(local_folder='intrinsic_chunks',
                                    s3_bucket='arm-github-copilot-extension',
                                    s3_prefix='embedding_data/intrinsic_chunks/'):
    """
    Ensure the local 'intrinsic_chunks' folder exists and is populated with files from S3.
    If the folder does not exist, create it and download all files from the S3 prefix.
    """
    if not os.path.exists(local_folder):
        os.makedirs(local_folder, exist_ok=True)
        print(f"Created local folder: {local_folder}")
        s3 = boto3.client('s3')
        try:
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=s3_bucket, Prefix=s3_prefix):
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    if key.endswith('/'):
                        continue  # skip folders
                    filename = os.path.basename(key)
                    local_path = os.path.join(local_folder, filename)
                    print(f"Downloading {key} to {local_path}")
                    s3.download_file(s3_bucket, key, local_path)
        except NoCredentialsError:
            print("AWS credentials not found. Please configure them.")
        except ClientError as e:
            print(f"S3 ClientError: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")
    else:
        print(f"Folder '{local_folder}' already exists. Skipping S3 download.")

'''
To fix:
1. Prevent multiple learning paths from being used (compare URLs to existing chunks OR delete overlaps)
2. Learning Path titles must come from index page...send through function along with Graviton.
'''

yaml_dir = os.getenv('YAML_OUTPUT_DIR', 'yaml_data')
details_file = os.getenv('CHUNK_DETAILS_FILE', 'info/chunk_details.csv')

chunk_index = 1

# Global var to prevent duplication entries from cross platform learning paths
cross_platform_lps_dont_duplicate = []

# Cache the ecosystem dashboard page so package entries do not re-fetch the same
# multi-megabyte HTML document for every source row.
ecosystem_dashboard_entries = None

# Global tracking for vector-db-sources.csv
# Set of URLs already in the CSV (for deduplication)
known_source_urls = set()
# List of all source entries (including existing and new)
# Each entry is a dict: {site_name, license_type, display_name, url, keywords}
all_sources = []

# Increase the file size limit, which defaults to '131,072'
csv.field_size_limit(10**9) #1,000,000,000 (1 billion), smaller than 64-bit space but avoids 'python overflowerror'


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
    
    with open(csv_file, 'r', newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            url = row.get('URL', '').strip()
            if url:
                known_source_urls.add(url)
                all_sources.append({
                    'site_name': row.get('Site Name', ''),
                    'license_type': row.get('License Type', ''),
                    'display_name': row.get('Display Name', ''),
                    'url': url,
                    'keywords': row.get('Keywords', '')
                })
    
    print(f"Loaded {len(all_sources)} existing sources from '{csv_file}'")


def register_source(site_name, license_type, display_name, url, keywords):
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
    all_sources.append({
        'site_name': site_name,
        'license_type': license_type,
        'display_name': display_name,
        'url': url,
        'keywords': keywords if isinstance(keywords, str) else '; '.join(keywords)
    })
    print(f"[NEW SOURCE] {display_name}: {url}")
    return True


def save_sources_csv(csv_file):
    """
    Write all sources (existing + new) to vector-db-sources.csv.
    """
    with open(csv_file, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['Site Name', 'License Type', 'Display Name', 'URL', 'Keywords'])
        for source in all_sources:
            writer.writerow([
                source['site_name'],
                source['license_type'],
                source['display_name'],
                source['url'],
                source['keywords']
            ])
    
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

        # Translate keyword list into comma-separated string, and add similar words to keywords.
        self.keywords = self.formatKeywords(keywords)

    def formatKeywords(self, keywords):
        """Format keywords list into a lowercase, comma-separated string."""
        return ', '.join(k.strip() for k in keywords).lower()

    # Used to dump into a yaml file without difficulty
    def toDict(self):
        return {
            'title': self.title,
            'url': self.url,
            'uuid': self.uuid,
            'keywords': self.keywords,
            'content': self.content,
            'heading': self.heading,
            'heading_path': self.heading_path,
            'doc_type': self.doc_type,
            'product': self.product,
            'version': self.version,
            'resolved_url': self.resolved_url,
            'content_type': self.content_type,
        }

    def __repr__(self):
        return f"Chunk(title={self.title}, url={self.url}, uuid={self.uuid}, heading={self.heading})"

def build_ecosystem_dashboard_entries():
    """Load and cache package-level snippets from the ecosystem dashboard."""
    global ecosystem_dashboard_entries
    if ecosystem_dashboard_entries is not None:
        return ecosystem_dashboard_entries

    def create_text_snippet(main_row):
        package_name = main_row.get('data-title')
        download_link = main_row.find('a', class_='download-icon-a')
        download_url = download_link.get('href') if download_link else None

        next_row = main_row.find_next_sibling('tr')
        works_on_arm_div = next_row.find('div', class_='description') if next_row else None
        arm_support_statement = ""
        if works_on_arm_div:
            arm_support_statement = works_on_arm_div.get_text(" ", strip=True)

        quick_start_section = None
        if works_on_arm_div and works_on_arm_div.parent:
            next_section = works_on_arm_div.parent.find_next_sibling('section')
            if next_section:
                quick_start_section = next_section.find('div', class_='description')

        quick_start_lines = []
        if quick_start_section:
            for li in quick_start_section.find_all('li'):
                link = li.find('a')
                if not link:
                    continue
                link_text = link.get_text(" ", strip=True)
                link_href = link.get('href')
                if link_text and link_href:
                    quick_start_lines.append(f"- [{link_text}]({link_href})")

        snippet_parts = []
        if arm_support_statement:
            snippet_parts.append(arm_support_statement)
        if download_url:
            snippet_parts.append(f"[Download {package_name} here.]({download_url})")
        if quick_start_lines:
            snippet_parts.append(
                "To get started quickly, here are some helpful guides from different sources:\n"
                + "\n".join(quick_start_lines)
            )
        return "\n\n".join(part for part in snippet_parts if part)

    url = "https://www.arm.com/developer-hub/ecosystem-dashboard/"
    response = http_session.get(url, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    rows = soup.find_all('tr', class_=['main-sw-row'])
    entries = {}
    for row in rows:
        package_name = row.get('data-title')
        package_slug = row.get('data-title-urlized')
        if not package_name or not package_slug:
            continue

        keywords = [package_name]
        for c in row.get('class', []):
            if 'tag-' in c:
                keywords.append(c.replace('tag-license-','').replace('tag-category-',''))

        package_url = f"{url}?package={package_slug}"
        entries[package_slug] = {
            "display_name": f"Ecosystem Dashboard - {package_name}",
            "package_name": package_name,
            "keywords": keywords,
            "url": package_url,
            "resolved_url": response.url + f"?package={package_slug}",
            "content": create_text_snippet(row),
        }

    ecosystem_dashboard_entries = entries
    return ecosystem_dashboard_entries


def ecosystem_dashboard_slug_from_url(source_url):
    query = parse_qs(urlparse(source_url).query)
    values = query.get("package", [])
    if values:
        return values[0].strip()
    return ""


def create_ecosystem_dashboard_chunk(source_url, source_name, keywords_value):
    package_slug = ecosystem_dashboard_slug_from_url(source_url)
    if not package_slug:
        return []

    entry = build_ecosystem_dashboard_entries().get(package_slug)
    if not entry or not entry["content"]:
        return []

    keywords = parse_keywords(keywords_value, entry["package_name"])
    return [
        createChunk(
            text_snippet=entry["content"],
            WEBSITE_url=normalize_source_url(source_url),
            keywords=keywords,
            title=entry["display_name"],
            heading=entry["package_name"],
            heading_path=[entry["package_name"]],
            doc_type="Ecosystem Dashboard",
            product=derive_product(entry["display_name"], source_url, "Ecosystem Dashboard", keywords),
            version=derive_version(entry["display_name"], entry["resolved_url"], entry["content"]),
            resolved_url=entry["resolved_url"],
            content_type="html",
        )
    ]


def createEcosystemDashboardChunks(emit_chunks=True):
    for entry in build_ecosystem_dashboard_entries().values():
        register_source(
            site_name='Ecosystem Dashboard',
            license_type='Arm Proprietary',
            display_name=entry["display_name"],
            url=entry["url"],
            keywords=entry["keywords"]
        )
        if not emit_chunks:
            continue

        chunk = Chunk(
            title=entry["display_name"],
            url=entry["url"],
            uuid=str(uuid.uuid4()),
            keywords=entry["keywords"],
            content=entry["content"],
            heading=entry["package_name"],
            heading_path=[entry["package_name"]],
            doc_type="Ecosystem Dashboard",
            product=derive_product(entry["display_name"], entry["url"], "Ecosystem Dashboard", entry["keywords"]),
            version=derive_version(entry["display_name"], entry["resolved_url"], entry["content"]),
            resolved_url=entry["resolved_url"],
            content_type="html",
        )

        chunkSaveAndTrack(entry["url"], chunk)

    return


def createIntrinsicsDatabaseChunks():
    def htmlToMarkdown(html_string):
        # Step 0: Remove '<h4>Operation</h4>' as it isn't needed
        html_string = re.sub(r'^<h4>Operation</h4>', '', html_string)

        # Step 1: Replace <pre> tags with backticks for code block
        html_string = re.sub(r'<pre>(.*?)</pre>', r'`\1`', html_string, flags=re.DOTALL)
        
        # Step 2: Add newline after headers (like <h1>, <h2>, <h3>, etc.)
        html_string = re.sub(r'<h[1-6]>(.*?)</h[1-6]>', r'\1\n', html_string)
        
        # Step 3: Remove all other HTML tags
        html_string = re.sub(r'<.*?>', '', html_string)
        
        return html_string



    # What devs care about:
    #    What is this?              Description
    #    Signature (code)           int8x8_t vadd_s8 (int8x8_t a, int8x8_t b);      Inputs and outputs
    #    How to use it?             Add header file & compiler flag
    #    Sudocode of how it works   'Operation' ID to then operation.json           
    #    URL to get more info       https://developer.arm.com/architectures/instruction-sets/intrinsics/#q=vadd_s8   


    # Read in .json files
    intrinsics_directory_path = os.getenv('INTRINSICS_DATAPATH')
    with open(intrinsics_directory_path+'/intrinsics.json', 'r') as file:
        intrinsics = json.load(file)
    with open(intrinsics_directory_path+'/operations.json', 'r') as file:
        operations = json.load(file)

    for intrinsic in intrinsics:
        intrinsic_content = f"The `{intrinsic['name']}` intrinsic is part of the {intrinsic['SIMD_ISA']} instruction set architecture."

        # Only include aarch64 intrinsics
        if 'A64' in intrinsic['Architectures']:
            description = intrinsic['description']
            # Exclude descriptions that don't exist or are simply 'Add' or 'Vector move'
            if (len(description.split(' ')) > 5):
                intrinsic_content += f" Here is a brief intrinsic description: {description}\n\n"

            # Define signature:
            signature = f"{intrinsic['return_type']['value']} {intrinsic['name']} ({', '.join(intrinsic['arguments'])});"
            intrinsic_content += f"The signature for this intrinsic function is as follows:\n`{signature}`\n\n"

            # Tell how to use:
            intrinsic_content += f"To use this {intrinsic['SIMD_ISA']} intrinsic, add the following to your C/C++ project:\n"
            intrinsic_content += f"1. Add compiler flags to ensure architecture-specific optimizations are present (for both GCC and ArmClang):\n"
            if (intrinsic['SIMD_ISA'] == 'Neon'):
                intrinsic_content += f'`-march=armv8-a+simd`'
            elif (intrinsic['SIMD_ISA'] == 'sve'):
                intrinsic_content += f'`-march=armv8-a+sve`'
            elif (intrinsic['SIMD_ISA'] == 'sve2'):
                intrinsic_content += f'`-march=armv8-a+sve2`'
            else:
                print('Intrinsic processing issue. resolve and run script again. Intrinsic SIMD_ISA: ',intrinsic['SIMD_ISA'])
                sys.exit(0)
            intrinsic_content += f'\n2. Add the now included .h header file containing the intrinsic:\n'
            if ({intrinsic['SIMD_ISA']} == 'Neon'):
                intrinsic_content += f'`#include <arm_neon.h>`'
            else:
                intrinsic_content += f'`#include <arm_sve.h>`'
            intrinsic_content += "\nYou can enable more specific microarchitectural optimizations (such as instruction scheduling, vectorization, and cache usage patterns) using the -mcpu flag and specifying the CPU in your machine.\n\n"

            # Sudocode if present
            if 'Operation' in intrinsic:
                op_id = intrinsic['Operation']
                operation_text = next((item["item"]["content"] for item in operations if item["item"]["id"] == op_id), None)
                if operation_text:
                    intrinsic_content += f'This is the sudocode for how the {intrinsic["name"]} intrinsic operates:\n'
                    intrinsic_content += htmlToMarkdown(operation_text)
                else:
                    print('Operation matching issue. Resolve and run script again. Operation ID: ',op_id)
                    sys.exit(0)


            keywords = [intrinsic['name'], intrinsic['SIMD_ISA'], intrinsic['instruction_group'].replace('|',', '), 'Intrinsic', 'SSE', 'AVX', 'Streaming SIMD Extension']

            url = "https://developer.arm.com/architectures/instruction-sets/intrinsics/"
            
            
            chunk = Chunk(
                title        = f"Arm Intrinsics - {intrinsic['name']}",
                url          = f"{url}#q={intrinsic['name']}",
                uuid         = str(uuid.uuid4()),
                keywords     = keywords,
                content      = intrinsic_content
            )

            chunkSaveAndTrack(url,chunk) 
    
    '''
    content:
        <description> if more than 5 words...otherwise leave out.
    SIGNATURE
        The signature for this inrinsic function is as follows:
        <return_type[value]> <name> (<'arguments' as comma seperated list>);
        
    HOW TO USE
        To use this <SIMD_ISA> intrinsic, do the following:
        1. Add the now included .h header file containing the intrinsic:
        `#include <arm_neon.h>`
        `#include <arm_sve.h>`

        2. Add compiler flags to ensure architecture-specific optimizations are present (for both GCC and ArmClang)
        `-march=armv8-a+simd`
        `-march=armv8-a+sve`
        `-march=armv8-a+sve+sve2`
        You can enable more specific microarchitectural optimizations (such as instruction scheduling, vectorization, and cache usage patterns) using the -mcpu flag and specifying your machine's CPU.

    SUDOCODE
        This is the sudocode for how the <name> intrinsic operates.
        <sudocode>
    '''


def processLearningPath(url, type, emit_chunks=True):
    github_raw_link = "https://raw.githubusercontent.com/ArmDeveloperEcosystem/arm-learning-paths/refs/heads/production/content"
    site_link = "https://learn.arm.com"

    def chunkizeLearningPath(relative_url, title, keywords):
        if not emit_chunks:
            return
        if relative_url.endswith('/'):
            relative_url = relative_url[:-1]
        MARKDOWN_url = github_raw_link + relative_url + '.md'
        WEBSITE_url = site_link + relative_url

        response = fetch_with_logging(MARKDOWN_url)
        if response is None:
            return
        parsed_document = parse_document_content(
            source_url=WEBSITE_url,
            resolved_url=response.url,
            response_content=response.content,
            content_type=response.headers.get("content-type", "text/markdown"),
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
                WEBSITE_url,
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
            chunkSaveAndTrack(WEBSITE_url,chunk)


    if type == 'Learning Path':
        # Prevent duplicate logging of cross-platform learningpaths via a local list. Check if URL is already in list. If so, move past URL. If not, add it and continue processing.
        if 'cross-platform' in url:
            if url in cross_platform_lps_dont_duplicate:
                print('NOT PROCESSING ',url,' already in list')
                # Don't process URL
                return
            else:
                print('Cross platform URL being added to list: ',url)
                cross_platform_lps_dont_duplicate.append(url)



        response = http_session.get(url, timeout=60)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Get learning path title and keywords once for registration
        lp_title_elem = soup.find(id='learning-path-title')
        if lp_title_elem:
            lp_title = lp_title_elem.get_text()
            ads_tags = soup.findAll('ads-tag')
            lp_keywords = []
            for tag in ads_tags:
                keyword = tag.get_text().strip()
                if keyword not in lp_keywords:
                    lp_keywords.append(keyword)
            
            # Register this learning path as a source
            register_source(
                site_name='Learning Paths',
                license_type='CC4.0',
                display_name=f'Learning Path - {lp_title}',
                url=url,
                keywords=lp_keywords
            )
        
        for link in soup.find_all(class_='inner-learning-path-navbar-element'):
            #Ignore mobile links
            if 'content-individual-a-mobile' not in link.get('class', []): 
                href = link.get('href')

                # Ignore the index file
                if '0-weight' in link.get('class', []): # Ignore index
                    continue
                #Ignore links that start with _   (index, demo, next_steps, review)
                if href.split('/')[-1].startswith('_'):
                    continue

                # Obtain title of learning path
                title = 'Arm Learning Path - '+soup.find(id='learning-path-title').get_text()

                # Obtain keywords of learning path
                ads_tags = soup.findAll('ads-tag')
                keywords = []
                for tag in ads_tags:
                    keyword = tag.get_text().strip()
                    if keyword not in keywords:
                        keywords.append(keyword)


                chunkizeLearningPath(href,title,keywords)
    
    
    elif type == "Install Guide":
        igs_response = http_session.get(site_link+url, timeout=60)
        igs_soup = BeautifulSoup(igs_response.text, 'html.parser')
        for ig_card in igs_soup.find_all(class_="tool-card"):
            ig_rel_url = ig_card.get('link')
            ig_url = site_link + ig_rel_url

            
            
            ig_response = http_session.get(ig_url, timeout=60)
            ig_soup = BeautifulSoup(ig_response.text, 'html.parser')
            
            # obtain title of Install Guide
            ig_title_elem = ig_soup.find(id='install-guide-title')
            if not ig_title_elem:
                continue
            ig_title = ig_title_elem.get_text()
            title = 'Install Guide - '+ ig_title
            

            # Obtain keywords of learning path
            keywords = [ig_title, 'install','build', 'download']
            
            # Register this install guide as a source
            register_source(
                site_name='Install Guides',
                license_type='CC4.0',
                display_name=title,
                url=ig_url,
                keywords=keywords
            )
            
            # Processing to check for multi-install
            multi_install_guides = ig_soup.find_all(class_='multi-install-card')
            if multi_install_guides:    
                for guide in multi_install_guides:
                    # Extend keywords
                    keywords.append(guide.find(class_='multi-tool-selection-title').get_text(strip=True))

                for guide in multi_install_guides:
                    sub_ig_rel_url = guide.get('link')

                    chunkizeLearningPath(sub_ig_rel_url,title, keywords)
            # If not multi-install (most cases)
            else:
                chunkizeLearningPath(ig_rel_url,title, keywords)


def createLearningPathChunks(emit_chunks=True):
    # Find all categories to iterate over
    learn_url = "https://learn.arm.com/"
    response = http_session.get(learn_url, timeout=60)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Process Install Guides separately (directly from /install-guides page)
    processLearningPath("/install-guides", "Install Guide", emit_chunks=emit_chunks)
    
    # Find category links - main-topic-card elements are now wrapped in <a> tags
    # Look for <a> tags that contain main-topic-card divs
    for a_tag in soup.find_all('a', href=True):
        card = a_tag.find(class_='main-topic-card')
        if card:
            cat_rel_path = a_tag.get('href')
            if cat_rel_path is None or cat_rel_path.startswith('http'):
                continue
            # Skip non-learning-path links (like /tag/ml/ or install guides button)
            if not cat_rel_path.startswith('/learning-paths/'):
                continue
            
            cat_response = http_session.get(learn_url.rstrip('/') + cat_rel_path, timeout=60)
            cat_soup = BeautifulSoup(cat_response.text, 'html.parser')
            for lp_card in cat_soup.find_all(class_="path-card"):
                lp_link = lp_card.get('link')
                if lp_link is None:
                    continue
                lp_url = learn_url.rstrip('/') + lp_link
                # Chunking step
                processLearningPath(lp_url, "Learning Path", emit_chunks=emit_chunks)


def readInCSV(csv_file):
    """Read sources CSV file and return dict of lists for processing.
    
    Uses csv.DictReader to properly handle quoted fields containing commas.
    Returns empty results if the file doesn't exist.
    """
    csv_dict = {
        'urls': [],
        'focus': [],
        'source_names': [],
        'site_names': [],
        'license_types': [],
    }
    
    if not os.path.exists(csv_file):
        return csv_dict, 0
    
    with open(csv_file, 'r', newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            csv_dict['urls'].append(normalize_source_url(row.get('URL', '')))
            csv_dict['focus'].append(row.get('Keywords', ''))
            csv_dict['source_names'].append(row.get('Display Name', ''))
            csv_dict['site_names'].append(row.get('Site Name', ''))
            csv_dict['license_types'].append(row.get('License Type', ''))
    
    return csv_dict, len(csv_dict['urls'])


def getMarkdownGitHubURLsFromPage(url):
    GH_urls = []
    SITE_urls = []

    fetch_url = source_to_fetch_url(url)
    if fetch_url != normalize_source_url(url):
        SITE_urls.append(normalize_source_url(url))
        GH_urls.append(fetch_url)
    else:
        print('url doesnt match expected format. Check function and try again.')
        print('URL: ',url)

    return GH_urls, SITE_urls


def URLIsValidCheck(url):
    try:
        response = http_session.get(url, timeout=60)
        response.raise_for_status()  # Ensure we got a valid response
        return True
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        with open('info/errors.csv', 'a', newline='') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow([url,str(http_err)])
        return False


def fetch_with_logging(url):
    try:
        response = http_session.get(url, timeout=60)
        response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        with open('info/errors.csv', 'a', newline='') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow([url, str(http_err)])
        return None
    except Exception as err:
        print(f"Other error occurred: {err}")
        with open('info/errors.csv', 'a', newline='') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow([url, str(err)])
        return None
    except Exception as err:
        print(f"Other error occurred: {err}")
        with open('info/errors.csv', 'a', newline='') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow([url,str(err)])
        return False


def obtainMarkdownContentFromGitHubMDFile(gh_url):
    response = http_session.get(gh_url, timeout=60)
    response.raise_for_status()  # Ensure we got a valid response
    md_content = response.text

    return md_content


def obtainTextSnippets__Markdown(content, min_words=300, max_words=500, min_final_words=200):
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


def createChunk(
    text_snippet,
    WEBSITE_url,
    keywords,
    title,
    heading="",
    heading_path=None,
    doc_type="",
    product="",
    version="",
    resolved_url="",
    content_type="",
):
    chunk = Chunk(
        title        = title,
        url          = WEBSITE_url,
        uuid         = str(uuid.uuid4()),
        keywords     = keywords,
        content      = text_snippet,
        heading      = heading,
        heading_path = heading_path or [],
        doc_type     = doc_type,
        product      = product,
        version      = version,
        resolved_url = resolved_url,
        content_type = content_type,
    )

    return chunk


def printChunks(chunks):
    for chunk_dict in chunks:
        print('='*100)
        print("Title:", chunk_dict['title'])
        print("Keywords:", chunk_dict['keywords'])
        print("URL:", chunk_dict['url'])
        print("Unique ID:", chunk_dict['uuid'])
        print("Content:", chunk_dict['content'])
        print('='*100)


def parse_keywords(keywords_value, title=""):
    keywords = [keyword.strip() for keyword in re.split(r"[;,]", keywords_value or "") if keyword.strip()]
    if title and title not in keywords:
        keywords.append(title)
    return keywords


def create_chunks_for_source(source_url, source_name, doc_type, keywords_value):
    if doc_type == "Ecosystem Dashboard":
        return create_ecosystem_dashboard_chunk(source_url, source_name, keywords_value)

    fetch_url = source_to_fetch_url(source_url)
    response = fetch_with_logging(fetch_url)
    if response is None:
        print('not valid, ', fetch_url)
        return []
    parsed_document = parse_document_content(
        source_url=normalize_source_url(source_url),
        resolved_url=response.url,
        response_content=response.content,
        content_type=response.headers.get("content-type", ""),
        fallback_title=source_name,
    )
    keywords = parse_keywords(keywords_value, source_name)
    return [
        createChunk(
            text_snippet=payload["content"],
            WEBSITE_url=payload["url"],
            keywords=keywords,
            title=payload["title"],
            heading=payload["heading"],
            heading_path=payload["heading_path"],
            doc_type=payload["doc_type"],
            product=payload["product"],
            version=payload["version"],
            resolved_url=payload["resolved_url"],
            content_type=payload["content_type"],
        )
        for payload in chunk_parsed_document(parsed_document, doc_type=doc_type or "Documentation", keywords=keywords)
    ]


def chunkSaveAndTrack(url,chunk):

    def addNewRow(current_date,chunk_words,chunk_id):
        return [url,current_date,chunk_words,'1',chunk_id]
    
    def addToExistingRow(row,chunk_words,chunk_id):
        url = row[0] # same URL
        date = row[1] # same date
        words = str(int(row[2]) + chunk_words) # update words
        chunks = row[3] = str(int(row[3]) + 1) # update number of chunks
        ids = row[4]+ f", {chunk_id}" # update chunk IDs
        return [url,date,words,chunks,ids]


    def recordChunk():
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        chunk_words  = len(chunk.content.split())    
        chunk_id     = f'chunk_{chunk.uuid}'

        new_rows = []

        with open(details_file, mode='r', newline='', encoding='utf-8') as file:
            csv_reader = csv.reader(file)
            try:
                headers = next(csv_reader)  
                new_rows.append(headers) # keep in memory
            except StopIteration:
                pass

            url_found = False  # Track if the URL is found in any row
            
            # Loop through all the rows after the header
            for row in csv_reader:
                if row[0] == url:
                    new_rows.append(addToExistingRow(row, chunk_words, chunk_id))  # Modify and append the row
                    url_found = True  # Mark that the URL was found
                else:
                    new_rows.append(row)  # Append the row without modification
            
            # If the URL was not found, append a new row
            if not url_found:
                new_rows.append(addNewRow(current_date, chunk_words, chunk_id))


        # Overwrite csv with new info
        with open(details_file, mode='w', newline='') as file:
            csv_writer = csv.writer(file, delimiter=',')
            csv_writer.writerows(new_rows) 

    # Save chunk
    file_name = f"{yaml_dir}/chunk_{chunk.uuid}.yaml"
    with open(file_name, 'w') as file:
        yaml.dump(chunk.toDict(), file, default_flow_style=False, sort_keys=False)

    # Record chunk
    recordChunk()
    print(f"{file_name} === {chunk.title}")


def main():
    skip_discovery = os.getenv("SKIP_DISCOVERY", "").lower() in {"1", "true", "yes"}

    # Ensure intrinsic_chunks folder and files from S3 are present
    ensure_intrinsic_chunks_from_s3()

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
        createLearningPathChunks(emit_chunks=False)

        # b) Ecosystem Dashboard
        createEcosystemDashboardChunks(emit_chunks=False)

    # c) Intrinsics
    #createIntrinsicsDatabaseChunks()

    # 1) Get URLs and details from CSV
    csv_dict, csv_length = readInCSV(sources_file)

    print(f'Starting to loop over CSV file {sources_file} ......')
    for i in range(csv_length):
        url = csv_dict['urls'][i]
        source_name = csv_dict['source_names'][i]
        doc_type = csv_dict['site_names'][i]
        keywords_value = csv_dict['focus'][i]

        for chunk in create_chunks_for_source(url, source_name, doc_type, keywords_value):
            chunkSaveAndTrack(url, chunk)

    # Save updated sources CSV with all discovered sources
    save_sources_csv(sources_file)
    print(f"\n=== Source tracking complete ===")
    print(f"Total sources in {sources_file}: {len(all_sources)}")


if __name__ == "__main__":
    main()
