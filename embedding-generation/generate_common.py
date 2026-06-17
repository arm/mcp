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

import os
import uuid
import yaml
import csv
import datetime

import boto3
from botocore.exceptions import NoCredentialsError, ClientError
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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


yaml_dir = os.getenv('YAML_OUTPUT_DIR', 'yaml_data')
details_file = os.getenv('CHUNK_DETAILS_FILE', 'info/chunk_details.csv')

# Global tracking for vector-db-sources.csv
# Set of URLs already in the CSV (for deduplication)
known_source_urls = set()
# List of all source entries (including existing and new)
# Each entry is a dict: {site_name, license_type, display_name, url, keywords}
all_sources = []


def get_number_of_sources():
    global all_sources
    return len(all_sources)


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
    source_entry = {
        'site_name': site_name,
        'license_type': license_type,
        'display_name': display_name,
        'url': url,
        'keywords': keywords if isinstance(keywords, str) else '; '.join(keywords)
    }

    # Keep discovered sources grouped with their existing site section instead of
    # appending them to the very end of the CSV and fragmenting that block.
    insert_at = None
    for index, existing_source in enumerate(all_sources):
        if existing_source.get('site_name') == site_name:
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
