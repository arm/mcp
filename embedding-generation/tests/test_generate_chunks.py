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

"""Unit tests for generate-chunks.py.

The `gc` fixture is provided by conftest.py and gives access to the
generate_chunks module with reset global state between tests.
"""

import base64
import csv
import json
from types import SimpleNamespace

import pytest


def _arm_api_response(title, html):
    return json.dumps(
        {
            "title": title,
            "topic": {
                "content": base64.b64encode(html.encode("utf-8")).decode("ascii"),
            },
        }
    ).encode("utf-8")


class TestChunkClass:
    """Tests for the Chunk class."""

    def test_chunk_creation(self, gc):
        """Test basic Chunk creation."""
        chunk = gc.Chunk(
            title="Test Title",
            url="https://example.com",
            uuid="test-uuid-123",
            keywords=["python", "testing"],
            content="This is test content."
        )
        
        assert chunk.title == "Test Title"
        assert chunk.url == "https://example.com"
        assert chunk.uuid == "test-uuid-123"
        assert chunk.content == "This is test content."

    def test_chunk_keywords_formatting(self, gc):
        """Test that keywords are properly formatted to lowercase comma-separated string."""
        chunk = gc.Chunk(
            title="Test",
            url="https://example.com",
            uuid="uuid",
            keywords=["Python", "TESTING", "Arm"],
            content="content"
        )
        
        assert chunk.keywords == "python, testing, arm"

    def test_chunk_keywords_with_spaces(self, gc):
        """Test keywords with leading/trailing spaces are trimmed."""
        chunk = gc.Chunk(
            title="Test",
            url="https://example.com",
            uuid="uuid",
            keywords=["  python  ", "testing  "],
            content="content"
        )
        
        # Each keyword should be stripped individually before joining
        assert chunk.keywords == "python, testing"

    def test_chunk_to_dict(self, gc):
        """Test toDict method returns correct dictionary."""
        chunk = gc.Chunk(
            title="Test Title",
            url="https://example.com",
            uuid="test-uuid",
            keywords=["key1", "key2"],
            content="Test content",
            heading="Install",
            heading_path=["Guide", "Install"],
            doc_type="Tutorial",
            product="Ampere",
            version="2025",
            resolved_url="https://example.com/resolved",
            content_type="markdown",
        )
        
        result = chunk.toDict()
        
        assert result["title"] == "Test Title"
        assert result["url"] == "https://example.com"
        assert result["uuid"] == "test-uuid"
        assert result["keywords"] == "key1, key2"
        assert result["content"] == "Test content"
        assert result["heading"] == "Install"
        assert result["heading_path"] == ["Guide", "Install"]
        assert result["doc_type"] == "Tutorial"
        assert result["product"] == "Ampere"
        assert result["version"] == "2025"
        assert result["resolved_url"] == "https://example.com/resolved"
        assert result["content_type"] == "markdown"

    def test_chunk_empty_keywords(self, gc):
        """Test Chunk with empty keywords list."""
        chunk = gc.Chunk(
            title="Test",
            url="https://example.com",
            uuid="uuid",
            keywords=[],
            content="content"
        )
        
        assert chunk.keywords == ""


class TestSourceTracking:
    """Tests for source tracking functions.
    
    Note: The gc fixture (from conftest.py) automatically resets
    known_source_urls and all_sources before and after each test.
    """

    def test_register_source_new(self, gc):
        """Test registering a new source."""
        result = gc.register_source(
            site_name="Test Site",
            license_type="MIT",
            display_name="Test Display",
            url="https://example.com/test",
            keywords=["test", "example"]
        )
        
        assert result is True
        assert "https://example.com/test" in gc.known_source_urls
        assert len(gc.all_sources) == 1
        assert gc.all_sources[0]['url'] == "https://example.com/test"
        assert gc.all_sources[0]['keywords'] == "test; example"

    def test_register_source_duplicate(self, gc):
        """Test that duplicate URLs are rejected."""
        gc.register_source(
            site_name="Test Site",
            license_type="MIT",
            display_name="Test Display",
            url="https://example.com/test",
            keywords="test"
        )
        
        result = gc.register_source(
            site_name="Test Site 2",
            license_type="Apache",
            display_name="Different Display",
            url="https://example.com/test",
            keywords="different"
        )
        
        assert result is False
        assert len(gc.all_sources) == 1

    def test_register_source_inserts_after_matching_site_group(self, gc):
        """Test that new sources stay grouped with existing sources from the same site."""
        gc.all_sources = [
            {
                'site_name': 'Google Cloud',
                'license_type': 'CC4.0',
                'display_name': 'Google 1',
                'url': 'https://example.com/google-1',
                'keywords': 'g1'
            },
            {
                'site_name': 'Ecosystem Dashboard',
                'license_type': 'Arm Proprietary',
                'display_name': 'Dashboard 1',
                'url': 'https://example.com/dashboard-1',
                'keywords': 'd1'
            },
            {
                'site_name': 'Ecosystem Dashboard',
                'license_type': 'Arm Proprietary',
                'display_name': 'Dashboard 2',
                'url': 'https://example.com/dashboard-2',
                'keywords': 'd2'
            },
            {
                'site_name': 'AWS Graviton',
                'license_type': 'Apache-2.0',
                'display_name': 'Graviton 1',
                'url': 'https://example.com/graviton-1',
                'keywords': 'a1'
            },
        ]
        gc.known_source_urls = {source['url'] for source in gc.all_sources}

        result = gc.register_source(
            site_name="Ecosystem Dashboard",
            license_type="Arm Proprietary",
            display_name="Dashboard 3",
            url="https://example.com/dashboard-3",
            keywords=["d3"]
        )

        assert result is True
        assert [source['display_name'] for source in gc.all_sources] == [
            'Google 1',
            'Dashboard 1',
            'Dashboard 2',
            'Dashboard 3',
            'Graviton 1',
        ]

    def test_register_source_url_normalization(self, gc):
        """Test that URLs are stripped of whitespace."""
        gc.register_source(
            site_name="Test",
            license_type="MIT",
            display_name="Test",
            url="  https://example.com/test  ",
            keywords="test"
        )
        
        assert "https://example.com/test" in gc.known_source_urls

    def test_register_source_string_keywords(self, gc):
        """Test that string keywords are preserved as-is."""
        gc.register_source(
            site_name="Test",
            license_type="MIT",
            display_name="Test",
            url="https://example.com",
            keywords="already; formatted; string"
        )
        
        assert gc.all_sources[0]['keywords'] == "already; formatted; string"

    def test_load_existing_sources_file_not_exists(self, gc, tmp_path):
        """Test loading from non-existent file."""
        gc.load_existing_sources(str(tmp_path / "nonexistent.csv"))
        
        assert len(gc.all_sources) == 0
        assert len(gc.known_source_urls) == 0

    def test_load_existing_sources(self, gc, tmp_path):
        """Test loading sources from CSV file."""
        csv_file = tmp_path / "sources.csv"
        csv_file.write_text(
            "Site Name,License Type,Display Name,URL,Keywords\n"
            "Test Site,MIT,Test Display,https://example.com/1,key1; key2\n"
            "Another Site,Apache,Another Display,https://example.com/2,key3\n"
        )
        
        gc.load_existing_sources(str(csv_file))
        
        assert len(gc.all_sources) == 2
        assert "https://example.com/1" in gc.known_source_urls
        assert "https://example.com/2" in gc.known_source_urls
        assert gc.all_sources[0]['site_name'] == "Test Site"
        assert gc.all_sources[1]['display_name'] == "Another Display"

    def test_save_sources_csv(self, gc, tmp_path):
        """Test saving sources to CSV file."""
        gc.all_sources = [
            {
                'site_name': 'Site 1',
                'license_type': 'MIT',
                'display_name': 'Display 1',
                'url': 'https://example.com/1',
                'keywords': 'key1; key2'
            },
            {
                'site_name': 'Site 2',
                'license_type': 'Apache',
                'display_name': 'Display 2',
                'url': 'https://example.com/2',
                'keywords': 'key3'
            }
        ]
        
        csv_file = tmp_path / "output.csv"
        gc.save_sources_csv(str(csv_file))
        
        # Read and verify
        with open(csv_file, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)
        
        assert rows[0] == ['Site Name', 'License Type', 'Display Name', 'URL', 'Keywords']
        assert rows[1] == ['Site 1', 'MIT', 'Display 1', 'https://example.com/1', 'key1; key2']
        assert rows[2] == ['Site 2', 'Apache', 'Display 2', 'https://example.com/2', 'key3']

    def test_load_and_save_roundtrip(self, gc, tmp_path):
        """Test that loading and saving preserves data."""
        csv_file = tmp_path / "sources.csv"
        original_content = (
            "Site Name,License Type,Display Name,URL,Keywords\n"
            "Test Site,MIT,Test Display,https://example.com/test,keyword1; keyword2\n"
        )
        csv_file.write_text(original_content)
        
        # Load
        gc.load_existing_sources(str(csv_file))
        
        # Add a new source
        gc.register_source(
            site_name="New Site",
            license_type="Apache",
            display_name="New Display",
            url="https://new.example.com",
            keywords=["new", "keywords"]
        )
        
        # Save
        gc.save_sources_csv(str(csv_file))
        
        # Verify
        gc.known_source_urls = set()
        gc.all_sources = []
        gc.load_existing_sources(str(csv_file))
        
        assert len(gc.all_sources) == 2
        assert "https://example.com/test" in gc.known_source_urls
        assert "https://new.example.com" in gc.known_source_urls


class TestGetMarkdownGitHubURLsFromPage:
    """Tests for getMarkdownGitHubURLsFromPage function."""

    def test_migration_url(self, gc):
        """Test handling of migration page URL."""
        gh_urls, site_urls = gc.getMarkdownGitHubURLsFromPage("https://learn.arm.com/migration")
        
        assert len(gh_urls) == 1
        assert len(site_urls) == 1
        assert "raw.githubusercontent.com" in gh_urls[0]
        assert "migration/_index.md" in gh_urls[0]
        assert site_urls[0] == "https://learn.arm.com/migration"

    def test_graviton_url(self, gc):
        """Test handling of Graviton getting started URL."""
        url = "https://github.com/aws/aws-graviton-getting-started/blob/main/README.md"
        gh_urls, site_urls = gc.getMarkdownGitHubURLsFromPage(url)
        
        assert len(gh_urls) == 1
        assert len(site_urls) == 1
        assert "raw.githubusercontent.com/aws/aws-graviton-getting-started" in gh_urls[0]
        assert "README.md" in gh_urls[0]

    def test_graviton_nested_url(self, gc):
        """Test handling of nested Graviton URL."""
        url = "https://github.com/aws/aws-graviton-getting-started/blob/main/machinelearning/pytorch.md"
        gh_urls, site_urls = gc.getMarkdownGitHubURLsFromPage(url)
        
        assert len(gh_urls) == 1
        assert "machinelearning/pytorch.md" in gh_urls[0]

    def test_unknown_url_returns_empty(self, gc, capsys):
        """Test that unknown URLs return empty lists and print warning."""
        gh_urls, site_urls = gc.getMarkdownGitHubURLsFromPage("https://unknown.com/page")
        
        assert gh_urls == []
        assert site_urls == []
        
        captured = capsys.readouterr()
        assert "doesnt match expected format" in captured.out


class TestObtainTextSnippetsMarkdown:
    """Tests for obtainTextSnippets__Markdown function."""

    def test_single_short_content(self, gc):
        """Test content shorter than min_words stays as one chunk."""
        content = "This is a short piece of content with only a few words."
        
        chunks = gc.obtainTextSnippets__Markdown(content, min_words=10, max_words=50)
        
        assert len(chunks) == 1

    def test_split_by_h2(self, gc):
        """Test that content is split by h2 headings."""
        content = """
## Section One
""" + "word " * 350 + """

## Section Two
""" + "word " * 350
        
        chunks = gc.obtainTextSnippets__Markdown(content, min_words=300, max_words=500)
        
        assert len(chunks) >= 2

    def test_split_by_h3_when_h2_too_large(self, gc):
        """Test that large h2 sections are split by h3."""
        content = """
## Large Section
""" + "word " * 200 + """
### Subsection One
""" + "word " * 350 + """
### Subsection Two
""" + "word " * 350
        
        chunks = gc.obtainTextSnippets__Markdown(content, min_words=300, max_words=500)
        
        # Should have multiple chunks due to h3 splitting
        assert len(chunks) >= 2

    def test_small_final_chunk_merged(self, gc):
        """Test that small final chunks are merged with previous."""
        content = "word " * 400 + "\n\n" + "short ending"
        
        chunks = gc.obtainTextSnippets__Markdown(content, min_words=300, max_words=500, min_final_words=50)
        
        # The small ending should be merged
        assert len(chunks) == 1
        assert "short ending" in chunks[0]

    def test_empty_content(self, gc):
        """Test handling of empty content."""
        chunks = gc.obtainTextSnippets__Markdown("")
        
        assert chunks == [] or chunks == ['']

    def test_respects_max_words(self, gc):
        """Test that chunks don't significantly exceed max_words when headers are present."""
        # Create content with h2 headers to enable splitting
        content = """
## Section One
""" + "word " * 400 + """

## Section Two
""" + "word " * 400 + """

## Section Three
""" + "word " * 400
        
        chunks = gc.obtainTextSnippets__Markdown(content, min_words=100, max_words=200, min_final_words=50)
        
        # With headers, content should be split into multiple chunks
        assert len(chunks) >= 2

    def test_prepends_document_title_and_heading_path(self, gc):
        """Structured chunks should carry the document title and heading path prefix."""
        content = """
# Deployment Guide

## Install
""" + "word " * 350

        chunks = gc.obtainTextSnippets__Markdown(content, min_words=150, max_words=400)

        assert len(chunks) >= 1
        assert chunks[0].startswith("Document Title: Deployment Guide")
        assert "Heading Path: Install" in chunks[0]

    def test_keeps_code_with_neighboring_explanation(self, gc):
        """Code blocks should remain grouped with nearby explanatory text."""
        content = """
# Example Guide

## Build
First install dependencies and verify the environment is ready for compilation.

```bash
make build
make test
```

Use the generated binary to verify the expected output and continue with setup.
""" + ("\n\nAdditional context. " * 120)

        chunks = gc.obtainTextSnippets__Markdown(content, min_words=100, max_words=250)

        matching = [chunk for chunk in chunks if "make build" in chunk]
        assert matching
        assert "First install dependencies" in matching[0]
        assert "Use the generated binary" in matching[0]


class TestReadInCSV:
    """Tests for readInCSV function."""

    def test_read_csv_basic(self, gc, tmp_path):
        """Test reading a basic CSV file."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "Site Name,License Type,Display Name,URL,Keywords\n"
            "Site1,MIT,Display1,https://example.com/1,key1\n"
            "Site2,Apache,Display2,https://example.com/2,key2\n"
        )
        
        csv_dict, length = gc.readInCSV(str(csv_file))
        
        assert length == 2
        assert csv_dict['urls'] == ['https://example.com/1', 'https://example.com/2']
        assert csv_dict['source_names'] == ['Display1', 'Display2']
        assert csv_dict['focus'] == ['key1', 'key2']
        assert csv_dict['site_names'] == ['Site1', 'Site2']
        assert csv_dict['license_types'] == ['MIT', 'Apache']

    def test_read_csv_empty(self, gc, tmp_path):
        """Test reading an empty CSV (header only)."""
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("Site Name,License Type,Display Name,URL,Keywords\n")
        
        csv_dict, length = gc.readInCSV(str(csv_file))
        
        assert length == 0
        assert csv_dict['urls'] == []

    def test_read_csv_quoted_commas(self, gc, tmp_path):
        """Test that quoted fields containing commas are handled correctly."""
        csv_file = tmp_path / "quoted.csv"
        # Display name contains a comma inside quotes
        csv_file.write_text(
            'Site Name,License Type,Display Name,URL,Keywords\n'
            'Learning Paths,CC4.0,"Learning Path - Managed, self-hosted runners",https://example.com/runners,"github; actions, runners"\n'
        )
        
        csv_dict, length = gc.readInCSV(str(csv_file))
        
        assert length == 1
        assert csv_dict['source_names'] == ['Learning Path - Managed, self-hosted runners']
        assert csv_dict['urls'] == ['https://example.com/runners']
        assert csv_dict['focus'] == ['github; actions, runners']

    def test_read_csv_file_not_exists(self, gc, tmp_path):
        """Test that missing file returns empty results (not FileNotFoundError)."""
        csv_file = tmp_path / "nonexistent.csv"
        
        csv_dict, length = gc.readInCSV(str(csv_file))
        
        assert length == 0
        assert csv_dict['urls'] == []
        assert csv_dict['source_names'] == []
        assert csv_dict['focus'] == []


class TestCreateChunk:
    """Tests for createChunk function."""

    def test_create_chunk_basic(self, gc):
        """Test basic chunk creation."""
        chunk = gc.createChunk(
            text_snippet="Test content",
            WEBSITE_url="https://example.com",
            keywords=["key1", "key2"],
            title="Test Title"
        )
        
        assert chunk.title == "Test Title"
        assert chunk.url == "https://example.com"
        assert chunk.content == "Test content"
        assert chunk.keywords == "key1, key2"
        # UUID should be generated
        assert len(chunk.uuid) > 0

    def test_create_chunk_generates_unique_uuids(self, gc):
        """Test that each chunk gets a unique UUID."""
        chunk1 = gc.createChunk("content", "url", ["key"], "title")
        chunk2 = gc.createChunk("content", "url", ["key"], "title")
        
        assert chunk1.uuid != chunk2.uuid


class TestArmDocumentationParsing:
    """Tests for Arm developer documentation API parsing and chunk creation."""

    def test_is_arm_developer_documentation_url(self, gc):
        """Only developer.arm.com documentation pages should use the Arm API path."""
        assert gc.is_arm_developer_documentation_url(
            "https://developer.arm.com/documentation/102376/0100"
        )
        assert gc.is_arm_developer_documentation_url(
            " chrome-extension://reader/https:/developer.arm.com/documentation/102376/0100 "
        )

        assert not gc.is_arm_developer_documentation_url(
            "https://documentation-service.arm.com/documentation/102376/0100"
        )
        assert not gc.is_arm_developer_documentation_url("https://developer.arm.com/tools-and-software")
        assert not gc.is_arm_developer_documentation_url("https://learn.arm.com/migration")

    def test_parse_arm_documentation_api_json_decodes_html_topic(self, gc):
        """API JSON content should be base64-decoded and parsed as structured HTML."""
        response_content = _arm_api_response(
            "Fallback API Title",
            """
            <html>
              <head><title>Browser Title</title></head>
              <body>
                <main>
                  <h1>Arm API Reference</h1>
                  <h2>Install</h2>
                  <p>Install the package and configure the target platform.</p>
                  <pre>make build</pre>
                </main>
              </body>
            </html>
            """,
        )

        parsed = gc.parse_arm_documentation_api_json(
            response_content=response_content,
            source_url="https://developer.arm.com/documentation/102376/0100/install",
            resolved_url="https://documentation-service.arm.com/documentation/102376/0100/install",
            fallback_title="Fallback Title",
        )

        assert parsed.display_title == "Arm API Reference"
        assert parsed.content_type == "html"
        assert parsed.source_url == "https://developer.arm.com/documentation/102376/0100/install"
        assert parsed.resolved_url == "https://documentation-service.arm.com/documentation/102376/0100/install"
        assert len(parsed.sections) == 1
        assert parsed.sections[0].heading_path == ["Arm API Reference", "Install"]
        assert parsed.sections[0].blocks[0].text == "Install the package and configure the target platform."
        assert parsed.sections[0].blocks[1].kind == "code"
        assert "make build" in parsed.sections[0].blocks[1].text

    def test_parse_arm_documentation_api_json_empty_content(self, gc):
        """API topics without content should return an empty parsed document."""
        parsed = gc.parse_arm_documentation_api_json(
            response_content=json.dumps({"topic": {"content": ""}}).encode("utf-8"),
            source_url="https://developer.arm.com/documentation/102376/0100",
            resolved_url="https://documentation-service.arm.com/documentation/102376/0100",
            fallback_title="Fallback Title",
        )

        assert parsed.display_title == "Fallback Title"
        assert parsed.content_type == "html"
        assert parsed.sections == []

    def test_create_arm_documentation_chunks_fetches_topics_and_maps_metadata(self, gc, monkeypatch):
        """Arm docs should fetch API topic links and emit developer-facing chunks."""
        source_url = "https://developer.arm.com/documentation/102376/0100"
        root_fetch_url = "https://documentation-service.arm.com/documentation/102376/0100"
        overview_fetch_url = "https://documentation-service.arm.com/documentation/102376/0100/overview?rev=abc"
        install_fetch_url = "https://documentation-service.arm.com/documentation/102376/0100/install"
        responses = {
            root_fetch_url: SimpleNamespace(
                url=root_fetch_url,
                content=json.dumps(
                    {
                        "title": "Arm Reference Manual",
                        "versionLabel": "0100",
                        "keywords": ["SVE"],
                        "products": ["Cortex-A"],
                        "topic": {
                            "topics": [
                                {
                                    "_links": {
                                        "self": [
                                            {
                                                "href": overview_fetch_url,
                                            }
                                        ]
                                    }
                                },
                                {
                                    "topics": [
                                        {
                                            "_links": {
                                                "self": [
                                                    {
                                                        "href": install_fetch_url,
                                                    }
                                                ]
                                            }
                                        }
                                    ]
                                },
                            ]
                        },
                    }
                ).encode("utf-8"),
            ),
            overview_fetch_url: SimpleNamespace(
                url=overview_fetch_url,
                content=_arm_api_response(
                    "Overview Topic",
                    """
                    <main>
                      <h1>Arm Reference Manual</h1>
                      <h2>Overview</h2>
                      <p>This overview explains how Arm systems expose scalable vector extension features.</p>
                    </main>
                    """,
                ),
            ),
            install_fetch_url: SimpleNamespace(
                url=install_fetch_url,
                content=_arm_api_response(
                    "Install Topic",
                    """
                    <main>
                      <h1>Arm Reference Manual</h1>
                      <h2>Install</h2>
                      <p>Install the Arm compiler package and configure the target CPU for Cortex-A builds.</p>
                    </main>
                    """,
                ),
            ),
        }
        fetched_urls = []

        def fake_fetch(url):
            fetched_urls.append(url)
            return responses[url]

        monkeypatch.setattr(gc, "fetch_with_logging", fake_fetch)

        chunks = gc.create_arm_documentation_chunks(
            source_url=source_url,
            source_name="Arm Reference Manual",
            doc_type="Reference",
            keywords_value="architecture; compiler",
        )

        assert fetched_urls == [root_fetch_url, overview_fetch_url, install_fetch_url]
        assert len(chunks) == 2
        assert {chunk.heading for chunk in chunks} == {"Overview", "Install"}
        assert all(chunk.title == "Arm Reference Manual" for chunk in chunks)
        assert all(chunk.doc_type == "Reference" for chunk in chunks)
        assert all(chunk.product == "Arm" for chunk in chunks)
        assert all(chunk.version == "0100" for chunk in chunks)
        assert all(chunk.content_type == "html" for chunk in chunks)
        assert chunks[0].url == "https://developer.arm.com/documentation/102376/0100/overview"
        assert chunks[0].resolved_url == overview_fetch_url
        assert chunks[0].keywords == "architecture, compiler, arm reference manual, sve, cortex-a"
        assert "Document Title: Arm Reference Manual" in chunks[0].content
        assert "Heading Path: Overview" in chunks[0].content
        assert "scalable vector extension" in chunks[0].content
        assert chunks[1].url == "https://developer.arm.com/documentation/102376/0100/install"
        assert "target CPU for Cortex-A builds" in chunks[1].content


class TestCreateRetrySession:
    """Tests for create_retry_session function."""

    def test_creates_session(self, gc):
        """Test that a session is created."""
        session = gc.create_retry_session()
        
        assert session is not None
        # Check that adapters are mounted
        assert 'http://' in session.adapters
        assert 'https://' in session.adapters

    def test_custom_retry_settings(self, gc):
        """Test session with custom retry settings."""
        session = gc.create_retry_session(
            retries=3,
            backoff_factor=2,
            status_forcelist=(500, 503)
        )
        
        assert session is not None
