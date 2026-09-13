import pytest

from arm_kb_search.search import rerank_candidates


def _docker_candidates():
    common_scores = {
        "rrf_score": 0.02,
        "distance": 0.3,
        "bm25_score": 5.0,
        "lexical_prepass_score": 0.6,
    }
    return [
        {
            "metadata": {
                "chunk_uuid": "learning-path",
                "title": "Docker on Arm",
                "heading": "Use Docker",
                "url": "https://learn.arm.com/learning-paths/cross-platform/docker/",
                "doc_type": "Learning Paths",
                "search_text": "Use Docker containers on Arm",
            },
            **common_scores,
        },
        {
            "metadata": {
                "chunk_uuid": "install-guide",
                "title": "Docker on Arm",
                "heading": "Docker Engine",
                "url": "https://learn.arm.com/install-guides/docker/",
                "doc_type": "Install Guides",
                "search_text": "Install Docker Engine on Arm",
            },
            **common_scores,
        },
    ]


@pytest.mark.parametrize(
    "query",
    (
        "How do I install Docker?",
        "Set up Docker",
        "Download Docker",
    ),
)
def test_install_intent_prefers_install_guide(query):
    ranked = rerank_candidates(query, _docker_candidates())

    assert ranked[0]["metadata"]["chunk_uuid"] == "install-guide"


def test_general_usage_intent_preserves_learning_path_preference():
    ranked = rerank_candidates("How do I use Docker?", _docker_candidates())

    assert ranked[0]["metadata"]["chunk_uuid"] == "learning-path"
