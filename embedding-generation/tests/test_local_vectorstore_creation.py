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

"""Input validation and focused regression tests for lossless embedding windows."""

import re
from unittest.mock import patch

import pytest

import local_vectorstore_creation as generator
from local_vectorstore_creation import load_local_yaml_files


def test_load_local_yaml_files_requires_intrinsic_chunks(tmp_path, monkeypatch):
    intrinsic_dir = tmp_path / "intrinsic_chunks"
    intrinsic_dir.mkdir()
    monkeypatch.setenv("INTRINSIC_CHUNKS_DIR", str(intrinsic_dir))
    monkeypatch.setenv("YAML_DATA_DIR", str(tmp_path / "yaml_data"))

    with pytest.raises(FileNotFoundError, match="No intrinsic chunk YAML files found"):
        load_local_yaml_files()


class PieceTokenizer:
    """Expose subword boundaries and words larger than a window's budget."""

    def num_special_tokens_to_add(self, pair=False):
        return 2

    def __call__(
        self, text, add_special_tokens=True, return_offsets_mapping=False,
        truncation=False, padding=False,
    ):
        assert not truncation and not padding
        offsets = [
            (start, min(start + 3, word.end()))
            for word in re.finditer(r"\S+", text)
            for start in range(word.start(), word.end(), 3)
        ]
        result = {"input_ids": list(range(len(offsets) + 2 * add_special_tokens))}
        if return_offsets_mapping:
            result["offset_mapping"] = offsets
        return result


class SeamTokenizer(PieceTokenizer):
    """Joining context and body can cost more than separately counting them."""

    def __call__(self, text, add_special_tokens=True, **kwargs):
        result = super().__call__(text, add_special_tokens=add_special_tokens, **kwargs)
        if add_special_tokens and "\n\n" in text:
            result["input_ids"] += [0] * (len(result["input_ids"]) // 2)
        return result


def source(body, **overrides):
    return {
        "uuid": "document", "chunk_uuid": "parent",
        "url": "https://example.com/manual/#section",
        "title": "Manual", "heading": "Install", "heading_path": ["Install"],
        "keywords": "manual",
        "content": f"Document Title: Manual\nHeading Path: Install\n\n{body}",
        **overrides,
    }


def assert_lossless(body, texts, metadata, tokenizer, limit):
    """Reconstruct exact characters, including whitespace, from emitted inputs."""
    assert texts and len(texts) == len(metadata)
    assert metadata[0]["content_start_char"] == 0
    covered = 0
    reconstructed = []
    for text, row in zip(texts, metadata):
        start, end = row["content_start_char"], row["content_end_char"]
        assert 0 <= start <= covered <= end <= len(body)
        assert end > covered or not body
        window = body[start:end]
        assert text.endswith(window)
        reconstructed.append(window[covered - start:])
        covered = end
        count = len(tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"])
        assert count <= limit
        assert row["embedding_token_count"] == count
        assert row["parent_content_length"] == len(body)
    assert covered == len(body)
    assert "".join(reconstructed) == body


def test_document_windows_preserve_body_with_overlap():
    body = "  " + "\t\n".join(f"word{index}" for index in range(50)) + "  "
    tokenizer = PieceTokenizer()
    texts, metadata = generator.prepare_embedding_records(
        [source(body)], tokenizer, max_seq_length=24, overlap_tokens=3,
    )
    assert_lossless(body, texts, metadata, tokenizer, 24)
    assert len(texts) > 1
    assert all(a["content_end_char"] > b["content_start_char"]
               for a, b in zip(metadata, metadata[1:]))


def test_subword_windows_prefer_whole_word_boundaries():
    body = " ".join(["abcdefgh"] * 12)
    spans = generator._window_spans(PieceTokenizer(), body, max_tokens=8, overlap_tokens=2)
    assert len(spans) > 1
    assert spans[0][0] == 0 and spans[-1][1] == len(body)
    for start, end in spans:
        assert start == 0 or body[start - 1].isspace()
        assert end == len(body) or body[end - 1].isspace()
        assert len(PieceTokenizer()(body[start:end], add_special_tokens=False)["input_ids"]) <= 8
    assert all(next_start < end for (_, end), (next_start, _) in zip(spans, spans[1:]))


def test_oversized_words_make_progress_without_losing_text():
    body = "prefix " * 45 + "x" * 600 + " suffix"
    tokenizer = PieceTokenizer()
    texts, metadata = generator.prepare_embedding_records(
        [source(body)], tokenizer, max_seq_length=48, overlap_tokens=8,
    )
    assert_lossless(body, texts, metadata, tokenizer, 48)
    assert len(texts) > 1
    assert all(b["content_start_char"] > a["content_start_char"]
               for a, b in zip(metadata, metadata[1:]))


def test_seam_trimming_rechecks_actual_token_count():
    tokenizer = SeamTokenizer()
    body = "word " * 40
    text, count, fitted, trimmed = generator._fit_embedding_text(
        tokenizer, "Manual", "\n\n", body, max_seq_length=24,
    )
    assert trimmed and fitted and body.startswith(fitted)
    assert text == "Manual\n\n" + fitted
    assert count == len(tokenizer(text)["input_ids"]) <= 24


def test_seam_overflow_retries_smaller_budget_without_dropping_text():
    body = "word " * 40 + "tail  "
    tokenizer = SeamTokenizer()
    with patch.object(generator, "_window_spans", wraps=generator._window_spans) as spans:
        texts, metadata = generator.prepare_embedding_records(
            [source(body)], tokenizer, max_seq_length=32, overlap_tokens=3,
        )
    budgets = [call.args[2] for call in spans.call_args_list]
    assert len(budgets) > 1, "Fixture must exercise the coverage-repair retry"
    assert all(later < earlier for earlier, later in zip(budgets, budgets[1:]))
    assert_lossless(body, texts, metadata, tokenizer, 32)


def test_intrinsics_preserve_raw_input_and_one_vector():
    body = "operation " * 100
    record = source(body, content=body, chunk_uuid="intrinsic_example")
    texts, metadata = generator.prepare_embedding_records(
        [record], PieceTokenizer(), max_seq_length=24, overlap_tokens=3,
    )
    assert texts == [body]  # Legacy encoder truncation remains unchanged.
    assert len(metadata) == 1
    assert metadata[0]["chunk_uuid"] == record["chunk_uuid"]
    assert metadata[0]["chunk_count"] == 1
    assert metadata[0]["embedding_window_policy"] == "legacy_single_vector"
    assert metadata[0]["original_text"] == body
    assert body in metadata[0]["search_text"]
