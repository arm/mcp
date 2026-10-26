# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
"""Whole-name evidence through the public resource-level retrieval pipeline."""
import importlib

import numpy as np
import pytest
from rank_bm25 import BM25Okapi
from usearch.index import Index

from arm_kb_search import SearchResources, search
from arm_kb_search.search import build_bm25_index
from arm_kb_search.names import NameIndex

s = importlib.import_module('arm_kb_search.search')


class QueryModel:
    def __init__(self):
        self.queries = []

    def encode(self, queries):
        self.queries.extend(queries)
        return np.zeros((len(queries), 2), dtype=np.float32)


def row(number, title, text='', **fields):
    return dict(chunk_uuid=str(number), title=title, search_text=text,
                original_text=text, url=f'https://example.org/{number}', **fields)


def state(rows, dense=False):
    index = None
    if dense:
        index = Index(ndim=2, metric='l2sq', dtype='f32')
        index.add(np.arange(len(rows)), np.zeros((len(rows), 2), dtype=np.float32), threads=1)
    return SearchResources(rows, QueryModel(), index, build_bm25_index(rows), include_disclaimers=False, prepared_name_index=NameIndex(rows))


@pytest.mark.parametrize('query', ['AWS CLI', 'aws-cli', 'aws_cli', 'awscli', 'AWS.CLI'])
def test_name_lookup_finds_subject_even_when_ordinary_search_has_results(query):
    rows = [row(0, 'AWS CLI', 'Download the client.', doc_type='Install Guides'),
            row(1, 'Other tools', 'install install install tools'),
            *[row(i, 'Other', 'background') for i in range(2, 10)]]
    resources = state(rows)
    assert s.bm25_search('install ' + query, rows, resources.bm25_index)
    assert search('install ' + query, resources, k=1)[0]['url'] == 'https://example.org/0'


@pytest.mark.parametrize('spelling', ['Node.js', 'Node JS', 'node-js', 'node_js', 'nodejs'])
def test_document_variants_are_found_from_a_separate_explicit_inventory_source(spelling):
    rows = [row(0, 'Node.js', 'catalog record', doc_type='Ecosystem Dashboard', heading='Node.js'),
            row(1, spelling, 'server setup', doc_type='Tutorial'),
            *[row(i, 'Other', 'background') for i in range(2, 10)]]
    results = search('nodejs', state(rows), k=5, filters={'doc_type': 'Tutorial'})
    assert [r['url'] for r in results] == ['https://example.org/1']


def test_subject_title_beats_body_prerequisite_and_partial_name():
    rows = [row(0, 'Docker Compose', 'Manage services.', doc_type='Install Guides'),
            row(1, 'Docker', 'install dockercompose as a prerequisite', doc_type='Install Guides'),
            row(2, 'Compose', 'install docker containers', doc_type='Install Guides'),
            *[row(i, 'Other', 'background') for i in range(3, 12)]]
    assert search('install docker_compose', state(rows), k=1)[0]['url'] == 'https://example.org/0'


@pytest.mark.parametrize('filters', [
    {'platform': 'windows'}, {'edition': 'commercial'}, {'product': 'target'},
    {'doc_type': 'Tutorial'},
])
def test_name_candidates_apply_filters_before_truncation(filters):
    key, value = next(iter(filters.items()))
    rows = [row(0, 'Visual Studio Code', 'catalog', doc_type='Install Guides')]
    for i in range(1, 150):
        rows.append(row(i, 'visual_studio-code', 'reference', **{key: 'ineligible'}))
    rows.append(row(150, 'visualstudiocode', 'reference', **filters))
    hits = search('visual-studio_code', state(rows), k=1, filters=filters)
    assert [hit['url'] for hit in hits] == ['https://example.org/150']


def test_name_resources_preserve_bm25_statistics_and_original_embedding_query():
    rows = [row(0, 'AWS CLI', 'aws cli download', doc_type='Install Guides'),
            row(1, 'Other', 'other text'), row(2, 'Elsewhere', 'background')]
    bm25 = build_bm25_index(rows)
    prose = BM25Okapi([s._bm25_tokens(r['search_text']) for r in rows])
    before = (bm25.idf.copy(), bm25.doc_len[:], bm25.avgdl)
    resources = state(rows, dense=True)
    query = 'How do I install AWS_CLI on Linux?'
    search(query, resources)
    assert resources.embedding_model.queries == [query]
    assert (resources.bm25_index.idf, resources.bm25_index.doc_len, resources.bm25_index.avgdl) == before
    np.testing.assert_array_equal(resources.bm25_index.get_scores(['aws']), prose.get_scores(['aws']))


def test_name_spelling_does_not_also_earn_code_identifier_bonus():
    rows = [row(0, 'AWS CLI', 'aws_cli', doc_type='Install Guides')]
    resources = state(rows)
    # With no sparse/vector channel, only the shared name/field evidence remains.
    resources.bm25_index = None
    scores = [search(q, resources, k=1)[0]['score'] for q in ['aws cli', 'aws-cli', 'aws_cli', 'awscli']]
    assert scores == pytest.approx([scores[0]] * len(scores))


def test_repeated_equivalent_names_do_not_multiply_field_credit():
    rows = [row(0, 'AWS CLI', 'client documentation', doc_type='Install Guides')]
    resources = state(rows)
    resources.bm25_index = None
    single = search('awscli', resources, k=1)
    repeated = search('aws-cli aws_cli AWS CLI awscli', resources, k=1)
    assert repeated[0]['score'] == pytest.approx(single[0]['score'])


def test_existing_intrinsic_exact_names_and_types_keep_their_evidence():
    original = 'SVE svadd_f32_m svint32_t svuint32_t'
    rows = [row(0, 'AWS CLI', 'client', doc_type='Install Guides'),
            row(1, 'SVE intrinsic', original, heading='svadd[_f32]_m', doc_type='Intrinsic', product='SVE'),
            row(2, 'Other', 'background')]
    resources = state(rows)
    assert search(original, resources, k=1)[0]['url'] == 'https://example.org/1'


def test_name_projection_preserves_existing_compiler_document_intent():
    rows = [row(0, 'LLVM Toolchain', 'compiler guide', doc_type='Install Guides')]
    resources = state(rows)
    query = s._analyze_query('LLVM Toolchain guide', resources._name_index)
    metadata = row(1, 'LLVM Toolchain guide', 'compiler documentation', doc_type='Tutorial')
    projected = set(s.tokenize_for_search(s._matching_text(query, metadata['title'])))
    _, bonus = s._document_type_bonuses(query, metadata, title_tokens=projected,
                                      heading_tokens=set(), url_tokens=set(), title_url_tokens=projected)
    assert query.compiler_guide_query
    assert bonus == pytest.approx(0.35)


def test_name_projection_preserves_existing_provider_query_intent():
    resources = state([row(0, 'Google Cloud', 'catalog', doc_type='Install Guides')])
    query = s._analyze_query('Google Cloud', resources._name_index)
    provider, _ = s._document_type_bonuses(query, {'doc_type': 'Google Cloud Documentation'},
                                        title_tokens=set(), heading_tokens=set(),
                                        url_tokens=set(), title_url_tokens=set())
    assert provider == pytest.approx(0.18)


@pytest.mark.parametrize('query', ['AWS CLI.', 'aws-cli.', 'awscli.', 'aws_cli.'])
def test_terminal_sentence_period_retains_whole_name_credit(query):
    resources = state([row(0, 'AWS CLI', 'client', doc_type='Install Guides')])
    resources.bm25_index = None
    plain = search('awscli', resources, k=1)
    punctuated = search(query, resources, k=1)
    assert punctuated[0]['score'] == pytest.approx(plain[0]['score'])


def test_terminal_sentence_period_in_document_retains_whole_name_credit():
    resources = state([row(0, 'AWS CLI', 'client', doc_type='Install Guides')])
    raw = [dict(metadata=row(1, 'AWS CLI', 'client'))]
    punctuated = [dict(metadata=row(1, 'aws_cli.', 'client'))]
    plain_score = s.rerank_candidates('awscli', raw, name_index=resources._name_index)[0]['rerank_score']
    score = s.rerank_candidates('awscli', punctuated, name_index=resources._name_index)[0]['rerank_score']
    assert score == pytest.approx(plain_score)


def test_flattened_search_text_does_not_assemble_a_name_across_fields():
    resources = state([row(0, 'AWS CLI', 'catalog', doc_type='Install Guides')])
    analysis = s._analyze_query('awscli', resources._name_index)
    metadata = row(1, 'AWS', 'unrelated body', heading='CLI')
    metadata['search_text'] = 'AWS CLI unrelated body'
    assert s._score_lexical_exactness(analysis, metadata) == 0.0
    assert s.rerank_candidates('awscli', [dict(metadata=metadata)],
                               name_index=resources._name_index)[0]['rerank_score'] == 0.0


def test_name_projection_preserves_compiler_tuning_guide_classification():
    resources = state([row(0, 'LLVM Toolchain', 'catalog', doc_type='Install Guides')])
    query = s._analyze_query('LLVM Toolchain guide', resources._name_index)
    metadata = row(1, 'LLVM Toolchain guide', 'compiler', doc_type='Tuning Guide')
    projected = set(s.tokenize_for_search(s._matching_text(query, metadata['title'])))
    _, bonus = s._document_type_bonuses(query, metadata, title_tokens=projected,
                                      heading_tokens=set(), url_tokens=set(), title_url_tokens=projected)
    assert bonus == 0.0


def test_flattened_fallback_without_raw_body_cannot_gain_name_credit():
    resources = state([row(0, 'AWS CLI', 'catalog', doc_type='Install Guides')])
    analysis = s._analyze_query('awscli', resources._name_index)
    metadata = {'title': 'AWS', 'heading': 'CLI', 'search_text': 'AWS CLI'}
    assert s._score_lexical_exactness(analysis, metadata) == 0.0


@pytest.mark.parametrize('query', ['install sklearn on arm', 'how do I install sk_learn on arm',
                                  'install scikit-learn on arm'])
def test_contextual_installation_prefers_product_over_generic_action(query, tmp_path):
    rows = [row(0, 'Scikit-learn', 'Package: Scikit-learn. Arm Linux support. Official installation documentation.',
                heading='Scikit-learn', heading_path=['Linux', 'Scikit-learn'], doc_type='Ecosystem Dashboard'),
            row(1, 'Install Arm tools', 'Install tools on Arm.', heading='Install Arm tools', doc_type='Tutorial'),
            row(2, 'Other library', 'Install scikit-learn as a prerequisite on Arm.', doc_type='Tutorial'),
            *[row(i, 'Background', 'background') for i in range(3, 12)]]
    aliases = [dict(canonical='Scikit-learn', labels=['Scikit-learn'],
                    aliases=['sklearn', 'sk learn'], provenance='reviewed test alias')]
    path = tmp_path / 'names.json'
    NameIndex.precompute(rows, path, aliases)
    resources = state(rows)
    resources._name_index = NameIndex.load_precomputed(rows, path)
    assert search(query, resources, k=1)[0]['url'] == 'https://example.org/0'


@pytest.mark.parametrize('query', ['How do I install AWS CLI on Ubuntu Arm64?',
                                  'How do I install aws_cli on Ubuntu Arm64?'])
def test_installation_subject_does_not_switch_long_queries_to_short_scoring(query):
    rows = [row(0, 'AWS CLI', 'Download the AWS CLI client.', heading='Install AWS CLI',
                doc_type='Install Guides'),
            row(1, 'Install another product on Ubuntu Arm64', 'Install tools on Ubuntu Arm64.',
                heading='Install another product on Ubuntu Arm64', doc_type='Tutorial')]
    candidates = [dict(metadata=r, bm25_score=25.0) for r in rows]
    results = s.rerank_candidates(query, candidates, name_index=NameIndex(rows))
    assert results[0]['metadata']['chunk_uuid'] == '0'
