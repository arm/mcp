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

import requests
from bs4 import BeautifulSoup
import argparse
import sys, os
import re
import uuid
import yaml
import csv
import datetime
import json

# Boto3 for S3 operations
import boto3
from botocore.exceptions import NoCredentialsError, ClientError


def ensure_intrinsic_chunks_from_s3(local_folder='intrinsic_chunks',
                                    s3_bucket='arm-github-copilot-extension',
                                    s3_prefix='embedding_data/intrinsic_chunks/'):
    """
    Ensure the local 'intrinsic_chunks' folder exists and is populated with files from S3.
    If the folder does not exist, create it and download all files from the S3 prefix.
    """
    import os
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


yaml_dir = 'yaml_data'
details_file = 'info/chunk_details.csv'

chunk_index = 1

# Global var to prevent duplication entries from cross platform learning paths
cross_platform_lps_dont_duplicate = []


# Increase the file size limit, which defaults to '131,072'
csv.field_size_limit(10**9) #1,000,000,000 (1 billion), smaller than 64-bit space but avoids 'python overflowerror'

class Chunk:
    def __init__(self, title, url, uuid, keywords, content):
        self.title = title
        self.url = url
        self.uuid = uuid
        self.content = content

        # Translate keyword list into comma-seperated string, and add similar words to keywords.
        self.keywords = self.formatKeywords(keywords)
    

    def formatKeywords(self,keywords):
        return ', '.join(keywords).lower().strip()

    # Used to dump into a yaml file without difficulty
    def toDict(self):
        return {
            'title': self.title,
            'url': self.url,
            'uuid': self.uuid,
            'keywords': self.keywords,
            'content': self.content
        }

    def __repr__(self):
        return f"Chunk(title={self.title}, focus={self.focus}, url={self.url}, uuid={self.uuid}, display_name={self.display_name}, content={self.content})"

def createEcosystemDashboardChunks():
    ''' Format of Chunk text_snippet:
    .NET works on Arm Linux servers starting from version 5 released in November 2020.

    [Download .NET here.](https://dotnet.microsoft.com/en-us/download/dotnet)

    To get started quickly, here are some helpful guides from different sources:
    - [Arm guide](https://learn.arm.com/install-guides/dotnet/)
    - [CSP guide](https://aws.amazon.com/blogs/dotnet/powering-net-8-with-aws-graviton3-benchmarks/)
    - [Official documentation](https://learn.microsoft.com/en-us/dotnet/core/install/linux-ubuntu)
    '''

    def createTextSnippet(main_row):
        package_name = row.get('data-title')
        download_url = row.find('a', class_='download-icon-a').get('href')    

        # Get the support statement
        next_row = main_row.find_next_sibling('tr')
        works_on_arm_div = next_row.find('div', class_='description')

        arm_support_statement = works_on_arm_div.get_text().replace('\n',' ')

        # Get individual links to help
        quick_start_links_div = works_on_arm_div.parent.find_next_sibling('section').find('div', class_='description')
        li_elements = quick_start_links_div.find_all('li')
        get_started_text = ""
        if li_elements:
            get_started_text = "\n\nTo get started quickly, here are some helpful guides from different sources:\n"
            for li in quick_start_links_div.find_all('li'):
                get_started_text = get_started_text + f"- [{li.find('a').get_text()}]({li.find('a').get('href')})\n"
        
        

        text_snippet = f"{arm_support_statement}\n\n[Download {package_name} here.]({download_url}){get_started_text}"
        return text_snippet

    # Obtain all
    url = "https://www.arm.com/developer-hub/ecosystem-dashboard/"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    rows = soup.find_all('tr', class_=['main-sw-row']) 
    for row in rows:
        # Obtain details for text snippet
        text_snippet = createTextSnippet(row)
        package_name = row.get('data-title')
        package_name_urlized = row.get('data-title-urlized')

        # Keywords
        keywords=[package_name]
        for c in row.get('class'):
            if 'tag-' in c:
                keywords.append(c.replace('tag-license-','').replace('tag-category-',''))


        chunk = Chunk(
            title        = f"Ecosystem Dashboard - {package_name}",
            url          = f"{url}?package={package_name_urlized}",
            uuid         = str(uuid.uuid4()),
            keywords     = keywords,
            content      = text_snippet
        )

        chunkSaveAndTrack(url,chunk) 

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



def processLearningPath(url,type):
    github_raw_link = "https://raw.githubusercontent.com/ArmDeveloperEcosystem/arm-learning-paths/refs/heads/production/content"
    site_link = "https://learn.arm.com"

    def chunkizeLearningPath(relative_url, title, keywords):
        if relative_url.endswith('/'):
            relative_url = relative_url[:-1]
        MARKDOWN_url = github_raw_link + relative_url + '.md'
        WEBSITE_url = site_link + relative_url


        # 3) Extract markdown, skipping those that are 404ing
        if not URLIsValidCheck(MARKDOWN_url):
            return 
        markdown = obtainMarkdownContentFromGitHubMDFile(MARKDOWN_url)

        # 4) Get sized text snippets the markdown
        text_snippets = obtainTextSnippets__Markdown(markdown)

        # 5) Create chunks for each snippet by adding metadata 
        for text_snippet in text_snippets:
            chunk = createChunk(text_snippet, WEBSITE_url, keywords, title)

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



        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
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
        igs_response = requests.get(site_link+url)
        igs_soup = BeautifulSoup(igs_response.text, 'html.parser')
        for ig_card in igs_soup.find_all(class_="tool-card"):
            ig_rel_url = ig_card.get('link')
            ig_url = site_link + ig_rel_url

            
            
            ig_response = requests.get(ig_url)
            ig_soup = BeautifulSoup(ig_response.text, 'html.parser')
            
            # obtain title of Install Guide
            title = 'Install Guide - '+ ig_soup.find(id='install-guide-title').get_text()
            

            # Obtain keywords of learning path
            keywords = [ig_soup.find(id='install-guide-title').get_text(), 'install','build', 'download']
            
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


def createLearningPathChunks():
    # Find all categories to iterate over
    learn_url = "https://learn.arm.com/"
    response = requests.get(learn_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    for card in soup.find_all(class_='main-topic-card'):
        if 'tool-install' == card.get('id'): 
            ig_rel_path = card.get('link')
            processLearningPath(ig_rel_path,"Install Guide")
            
        else:         
            cat_rel_path = card.get('link')
            cat_response = requests.get(learn_url+cat_rel_path)
            cat_soup = BeautifulSoup(cat_response.text, 'html.parser')
            for lp_card in cat_soup.find_all(class_="path-card"):
                lp_url = learn_url + lp_card.get('link')
                # Chunking step
                processLearningPath(lp_url, "Learning Path")


def readInCSV(csv_file):
    csv_length = 0
    csv_dict = {
        'urls': [],
        'focus': [],
        'source_names': []
    }
    with open(csv_file, 'r') as file:
        next(file)  # Skip the header row
        for line in file:

            source_name = line.strip().split(',')[2]  # Get the URL from column A
            focus = line.strip().split(',')[4]  # Get the URL from column B
            url = line.strip().split(',')[3]  # Get the URL from column C

            csv_dict['urls'].append(url)
            csv_dict['focus'].append(focus)
            csv_dict['source_names'].append(source_name)

            csv_length += 1

    return csv_dict, csv_length

def getMarkdownGitHubURLsFromPage(url):
    GH_urls = []
    SITE_urls = []

    if url == 'https://learn.arm.com/migration':
        github_raw_link = "https://raw.githubusercontent.com/ArmDeveloperEcosystem/arm-learning-paths/refs/heads/main/content"               
        github_md_link = github_raw_link + '/migration/_index.md'

        SITE_urls.append(url)
        GH_urls.append(github_md_link)

    elif '/github.com/aws/aws-graviton-getting-started/' in url:
        github_raw_link = "https://raw.githubusercontent.com/aws/aws-graviton-getting-started/refs/heads/main/"
        
        # Rip off part of the URL after '/main/'
        specific_content = url.split('/main/')[1]

        github_md_link = github_raw_link + specific_content

        SITE_urls.append(url)
        GH_urls.append(github_md_link)

    else:
        print('url doesnt match expected format. Check function and try again.')
        print('URL: ',url)


    
    return GH_urls, SITE_urls


def URLIsValidCheck(url):
    try:
        response = requests.get(url)
        response.raise_for_status()  # Ensure we got a valid response
        return True
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        with open('info/errors.csv', 'a', newline='') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow([url,str(http_err)])
        return False
    except Exception as err:
        print(f"Other error occurred: {err}")
        with open('info/errors.csv', 'a', newline='') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow([url,str(err)])
        return False


def obtainMarkdownContentFromGitHubMDFile(gh_url):
    response = requests.get(gh_url)
    response.raise_for_status()  # Ensure we got a valid response
    md_content = response.text


    # Remove frontmatter bounded by '---'
    md_content = md_content[md_content.find('---', 3)  + 3:].strip()  # +3 to remove the '---' and strip to remove leading/trailing whitespace

    return md_content

def obtainTextSnippets__Markdown(content, min_words=300, max_words=500, min_final_words=200):
    """Split content into chunks based on headers and word count constraints."""

    # Helper function to count words
    def word_count(text):
        return len(text.split())

    # Helper function to split content by a given heading level (e.g., h2, h3, h4)
    def split_by_heading(content, heading_level):
        pattern = re.compile(rf'(?<=\n)({heading_level} .+)', re.IGNORECASE)
        return pattern.split(content)

        # Helper function to chunk content
    def create_chunks(content_pieces, heading_level='##'):
        """
        Create chunks from content pieces based on the word count limits.
        """
        chunks = []
        current_chunk = ""
        current_word_count = 0

        for piece in content_pieces:
            piece_word_count = word_count(piece)

            # Check if the current piece starts with the heading level, indicating the start of a new section
            if re.match(rf'^{heading_level} ', piece.strip()):
                # If the current chunk has enough words, finalize it and start a new chunk
                if current_word_count >= min_words:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                    current_word_count = 0

            # Add the piece to the current chunk
            if current_word_count + piece_word_count > max_words and current_word_count >= min_words:
                # If adding this piece exceeds max_words, finalize the current chunk
                chunks.append(current_chunk.strip())
                current_chunk = piece.strip()
                current_word_count = piece_word_count
            else:
                current_chunk += piece + "\n"
                current_word_count += piece_word_count

        # Handle the last chunk
        if current_chunk.strip():
            if current_word_count < min_final_words and chunks:
                # If the last chunk is too small, merge it with the previous chunk
                chunks[-1] += "\n" + current_chunk.strip()
            else:
                # Otherwise, add it as a separate chunk
                chunks.append(current_chunk.strip())

        return chunks

    # 1. Split by h2 headings
    content_pieces = split_by_heading(content, '##')
    chunks = create_chunks(content_pieces)

    # 2. Further split large chunks by h3 if they exceed max_words
    final_chunks = []
    for chunk in chunks:
        if word_count(chunk) > max_words:
            sub_pieces = split_by_heading(chunk, '###')
            sub_chunks = create_chunks(sub_pieces,'###')
            
            # 3. Further split large sub-chunks by h4 if they exceed max_words
            for sub_chunk in sub_chunks:
                if word_count(sub_chunk) > max_words:
                    sub_sub_pieces = split_by_heading(sub_chunk, '####')
                    sub_sub_chunks = create_chunks(sub_sub_pieces,'####')
                    
                    # 4. If still too large, split by paragraph
                    for sub_sub_chunk in sub_sub_chunks:
                        if word_count(sub_sub_chunk) > max_words:
                            paragraphs = sub_sub_chunk.split('\n\n')
                            paragraph_chunks = create_chunks(paragraphs)
                            final_chunks.extend(paragraph_chunks)
                        else:
                            final_chunks.append(sub_sub_chunk)
                else:
                    final_chunks.append(sub_chunk)
        else:
            final_chunks.append(chunk)

    return final_chunks


def createChunk(text_snippet,WEBSITE_url,keywords,title):
    chunk = Chunk(
        title        = title,
        url          = WEBSITE_url,
        uuid         = str(uuid.uuid4()),
        keywords     = keywords,
        content      = text_snippet
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



def main():
    

    # Ensure intrinsic_chunks folder and files from S3 are present
    ensure_intrinsic_chunks_from_s3()

    # Argparse inputs
    parser = argparse.ArgumentParser(description="Turn a Learning Path URL into suburls in GitHub")
    parser.add_argument("csv_file", help="Path to the CSV file that lists all Learning Paths to chunk.")
    args = parser.parse_args()

    # 0) Initialize files
    os.makedirs(yaml_dir, exist_ok=True) # create if doesn't exist
    os.makedirs('info', exist_ok=True)   # create if doesn't exist
    with open(details_file, mode='w', newline='') as file:
        writer = csv.writer(file)        
        writer.writerow(['URL','Date', 'Number of Words', 'Number of Chunks','Chunk IDs'])

    # 0) Obtain full database information:
    # a) Learning Paths & Install Guides
    createLearningPathChunks()

    # b) Ecosystem Dashboard
    createEcosystemDashboardChunks()

    # c) Intrinsics
    #createIntrinsicsDatabaseChunks()

    # 1) Get URLs and details from CSV
    csv_dict, csv_length = readInCSV(args.csv_file)

    print(f'Starting to loop over CSV file {args.csv_file} ......')
    for i in range(csv_length):
        url = csv_dict['urls'][i]
        source_name = csv_dict['source_names'][i]

        # 2) Translate a URL into all it's individual page URLs, if applicable, as their raw GitHub MD files -->       https://raw.githubusercontent.com/ArmDeveloperEcosystem/arm-learning-paths/refs/heads/main/content/learning-paths/servers-and-cloud-computing/llama-cpu/llama-chatbot.md
        MARKDOWN_urls, WEBSITE_urls = getMarkdownGitHubURLsFromPage(url)
        for j in range(len(MARKDOWN_urls)):
            MARKDOWN_url = MARKDOWN_urls[j]
            WEBSITE_url = WEBSITE_urls[j]

            # 3) Extract markdown, skipping those that are 404ing
            if not URLIsValidCheck(MARKDOWN_url):
                print('not valid, ',MARKDOWN_url)
                continue 
            markdown = obtainMarkdownContentFromGitHubMDFile(MARKDOWN_url)

            # 4) Get keywords (removing -)
            keywords = [source_name.replace(" - ", " ").replace(" ", ", ")]

            # 4) Get sized text snippets the markdown
            text_snippets = obtainTextSnippets__Markdown(markdown)

            # 5) Create chunks for each snippet by adding metadata 
            for text_snippet in text_snippets:
                chunk = createChunk(text_snippet, WEBSITE_url, keywords, source_name)
                chunkSaveAndTrack(url,chunk) 



if __name__ == "__main__":
    main()