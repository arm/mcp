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

"""Learning Path membership evidence must not manufacture complete context."""

from copy import deepcopy

import pytest

from arm_kb_search import SearchResources, resources, search


ROOT = "https://learn.arm.com/learning-paths/cross-platform/example/"
FIRST, EXTRA = ROOT + "first/", ROOT + "second/"


def ordered(url, pages=None, **extra):
    context = dict(format=1, url=url, chunk_index=0, chunk_count=1)
    if pages is not None:
        context.update(parent_page_url=pages[0], learning_path_pages=pages)
    return dict(url=url + "#section", chunk_uuid=url, original_text="Content: " + url,
                document_context=context, **extra)


def resource_snapshot(monkeypatch, rows, selected):
    monkeypatch.setattr(resources, "hybrid_search", lambda *args, **kwargs: [
        {"metadata": row, "distance": 0.1} for row in selected])
    return SearchResources(rows, None, None, None, include_disclaimers=False)


@pytest.mark.parametrize("identity", ["document_context", "page_url", "url", "resolved_url"])
@pytest.mark.parametrize("empty_parent", ["absent", None, ""])
def test_parent_rejects_url_only_sibling(monkeypatch, identity, empty_parent):
    pages = [ROOT, FIRST]
    sibling = dict(chunk_uuid=EXTRA, original_text="Stored sibling must not be omitted")
    if identity == "document_context":
        sibling[identity] = ordered(EXTRA)[identity]
    else:
        sibling[identity] = EXTRA + "?utm_source=import#section"
    if empty_parent != "absent":
        sibling.update(parent_page_url=empty_parent, learning_path_url=empty_parent)
        if identity == "document_context":
            sibling[identity].update(parent_page_url=empty_parent, learning_path_url=empty_parent)
    root, first = (ordered(url, pages) for url in pages)
    unrelated = ordered("https://example.org/unrelated/")
    rows, selected = [root, first, sibling, unrelated], [first]
    before = deepcopy(rows)
    for records in (rows, list(reversed(rows))):
        state = resource_snapshot(monkeypatch, records, selected)
        baseline = search("needle", state)
        assert len(baseline) == 1 and "context" not in baseline[0]
        assert len(search("needle", state, scope="page")) == 1
        with pytest.raises(ValueError, match="stored sibling is omitted"):
            search("needle", state, scope="parent_resource")
        assert search("needle", state) == baseline
        selected[:] = [unrelated]
        assert len(search("needle", state, scope="parent_resource")) == 1
        if identity == "document_context":
            selected[:] = [sibling]
            assert len(search("needle", state, scope="page")) == 1
            with pytest.raises(ValueError, match="Regenerate chunks"):
                search("needle", state, scope="parent_resource")
        selected[:] = [first]
    assert rows == before


@pytest.mark.parametrize("url,extra", [
    (ROOT.replace("example/", "example-other/") + "second/", {}),
    (ROOT.replace("learn.arm.com", "example.org") + "second/", {}),
    (ROOT.replace("learn.arm.com", "learn.arm.com.example.org") + "second/", {}),
    (ROOT.replace("/learning-paths/", "/install-guides/") + "second/", {}),
    (ROOT.replace("https:", "ftp:") + "second/", {}),
    ("https://[broken", {}),
    (EXTRA + "#q=intrinsic", {}),
    (EXTRA, {"doc_type": "Intrinsic"}),
])
def test_url_membership_does_not_capture_unrelated_identities(monkeypatch, url, extra):
    pages = [ROOT, FIRST]
    rows = [*(ordered(url, pages) for url in pages), ordered(url, **extra)]
    state = resource_snapshot(monkeypatch, rows, [rows[1]])
    result = search("needle", state, scope="parent_resource")
    assert [hit["context"]["page_url"] for hit in result] == pages
    assert all(hit["context"]["page_count"] == 2 for hit in result)


@pytest.mark.parametrize("url", [ROOT, EXTRA])
def test_learning_path_url_does_not_supply_missing_parent_metadata(monkeypatch, url):
    row = ordered(url)
    state = resource_snapshot(monkeypatch, [row], [row])
    assert len(search("needle", state, scope="page")) == 1
    with pytest.raises(ValueError, match="Regenerate chunks"):
        search("needle", state, scope="parent_resource")


def test_conflicting_parent_field_cannot_hide_url_membership(monkeypatch):
    other = "https://example.org/other-parent/"
    root, alternate = ordered(ROOT, [ROOT]), ordered(other, [other])
    sibling = ordered(EXTRA, [other, EXTRA])
    rows, selected = [root, alternate, sibling], [root]
    state = resource_snapshot(monkeypatch, rows, selected)
    for seed in (root, alternate):
        selected[:] = [seed]
        with pytest.raises(ValueError, match="stored sibling is omitted"):
            search("needle", state, scope="parent_resource")
        assert len(search("needle", state, scope="page")) == 1


def test_complete_learning_path_retains_order_and_citations(monkeypatch):
    pages = [ROOT, EXTRA, FIRST]
    rows = [ordered(url, pages) for url in pages]
    rows[1]["url"] = EXTRA + "?utm_source=source#section"
    before = deepcopy(rows)
    state = resource_snapshot(monkeypatch, list(reversed(rows)), [rows[2], rows[1]])
    result = search("needle", state, scope="parent_resource")
    assert [hit["context"]["page_url"] for hit in result] == pages
    assert [hit["url"] for hit in result] == [row["url"] for row in rows]
    assert [hit["snippet"] for hit in result] == [row["original_text"] for row in rows]
    assert rows == before
