"""Public-site acquisition must never depend on private source repositories."""

import html
import json
from types import SimpleNamespace

import pytest

from document_chunking import chunk_parsed_document
from learn_public import PublicLearnSources
from learn_repository import LearnSources

SITE = "https://learn.arm.com"
COURSE = SITE + "/courses/example/"
LESSON = COURSE + "deployment/run/"
INSIGHT = SITE + "/insights/sve/"


def session(pages):
    calls = []

    def get(url, **kwargs):
        assert url.startswith(SITE + "/"), "Only public Learn pages may be fetched"
        assert "headers" not in kwargs and "auth" not in kwargs
        calls.append(url)
        return SimpleNamespace(
            content=pages[url].encode(), url=url, raise_for_status=lambda: None
        )

    return SimpleNamespace(get=get, calls=calls)


def lesson_order(*urls):
    return html.escape(json.dumps([{"url": url} for url in urls]), quote=True)


def test_course_expands_published_curriculum_and_reuses_pages(gc, monkeypatch):
    other = COURSE + "deployment/check/"
    http = session(
        {
            COURSE: f'''<main><h1>Example course</h1><p>Deploy on Arm.</p>
          <ads-button data-course-lesson-order="{lesson_order(LESSON, other)}"></ads-button>
          <a href="{LESSON}">First lesson</a>
          <a href="/courses/unrelated/">Unrelated course</a>
          <a href="{COURSE}download.zip">Download</a></main>''',
            LESSON: f'''<main><nav><a href="{other}">Sibling</a></nav>
          <div class="course-body"><h1>Run model</h1><h3 id="run">Run</h3>
          <pre><code>model.forward(inputs)</code></pre>
          <h3 id="inspect">Inspect</h3><p>Check outputs.</p></div>
          <section data-course-completion-panel><p>Congratulations!</p></section></main>''',
            other: '<main><div class="course-body"><h1>Check model</h1><p>Validate.</p></div></main>',
        }
    )
    sources = LearnSources(http)
    monkeypatch.setattr(gc, "learn_sources", sources)
    monkeypatch.setattr(
        sources, "repository", lambda *_: pytest.fail("Repository access")
    )
    chunks = gc.create_chunks_for_source(COURSE, "Example", "Educational Course", "Arm")
    assert http.calls == [COURSE, LESSON, other]
    assert any(
        c.url == LESSON + "#run" and "model.forward(inputs)" in c.content
        for c in chunks
    )
    inspect = next(c for c in chunks if c.url == LESSON + "#inspect")
    assert "Run" not in inspect.heading_path
    assert all(c.resolved_url.startswith(SITE) for c in chunks)
    assert not any("Congratulations" in c.content for c in chunks)
    assert len(sources.documents(LESSON)) == 1
    assert http.calls == [COURSE, LESSON, other]


def test_single_lesson_does_not_fetch_siblings():
    http = session(
        {
            LESSON: f'''<main><div class="course-body"><h1>Run</h1><p>Run it.</p></div>
      <nav><a href="{COURSE}other/">Next</a></nav>
      <ads-button data-course-lesson-order="{lesson_order(LESSON, COURSE + "other/")}"></ads-button></main>'''
        }
    )
    assert len(PublicLearnSources(http).documents(LESSON)) == 1
    assert http.calls == [LESSON]


def insight_entry(anchor, question, answer):
    return f'''<div class="insight-entry" id="{anchor}"><ads-expansion-panel>
      <div slot="toggle"><span class="insight-entry__question-text">{question}</span></div>
      <div class="insight-entry__answer" slot="content">{answer}</div>
      </ads-expansion-panel></div>'''


def test_insights_preserve_question_boundaries_and_public_anchors():
    page = '<main><h1>SVE Insights</h1><section class="insight-overview"><h2 id="insight-overview-title">Overview</h2><p>SVE overview.</p></section>'
    page += insight_entry(
        "tail",
        "How do I handle tails?",
        '<p>Use predication.</p><h2 id="example">Example</h2><pre><code>svwhilelt_b32(i, n);</code></pre>',
    )
    page += insight_entry(
        "length",
        "How do I choose vector length?",
        '<h2 id="example">Example</h2><p>Use svcntw().</p>',
    )
    http = session({INSIGHT: page + "</main>"})
    docs = LearnSources(http).documents(INSIGHT)
    chunks = [c for d in docs for c in chunk_parsed_document(d, "Insights", ["SVE"])]
    assert len(docs) == 3
    assert {c["url"] for c in chunks} == {
        INSIGHT + "#insight-overview-title",
        INSIGHT + "#tail",
        INSIGHT + "#length",
    }
    tail = [c for c in chunks if c["url"].endswith("#tail")]
    assert all(c["heading_path"][0] == "How do I handle tails?" for c in tail)
    assert all("svcntw" not in c["content"] for c in tail)
    assert all(c["resolved_url"] == INSIGHT for c in chunks)


@pytest.mark.parametrize(
    "entries",
    [
        "",
        insight_entry("q", "Question", ""),
        insight_entry("q", "Question", "<p>Answer</p>") * 2,
    ],
)
def test_malformed_insights_fail_before_silently_losing_answers(entries):
    with pytest.raises(ValueError):
        PublicLearnSources(
            session({INSIGHT: "<main>" + entries + "</main>"})
        ).documents(INSIGHT)


def test_published_quiz_keeps_correctness_and_feedback():
    http = session(
        {
            LESSON: """<main><div class="course-body"><h1>Check understanding</h1>
      <form data-knowledge-check id="quiz"><fieldset><legend>Which compiler?</legend>
      <label class="course-knowledge-check-option"><input data-correct="true">
      <span class="course-knowledge-check-option-text">Native Arm compiler</span></label>
      <label class="course-knowledge-check-option"><input data-correct="false">
      <span class="course-knowledge-check-option-text">x86 compiler</span>
      <span class="course-knowledge-check-option-feedback" hidden>Wrong target.</span></label>
      </fieldset><button>Retry</button></form></div></main>"""
        }
    )
    docs = PublicLearnSources(http).documents(LESSON)
    chunks = chunk_parsed_document(docs[0], "Educational Course", [])
    assert len(chunks) == 1 and chunks[0]["url"] == LESSON + "#quiz"
    text = chunks[0]["content"]
    assert "Correct answer: Native Arm compiler" in text
    assert (
        "Incorrect answer: x86 compiler" in text and "Feedback: Wrong target." in text
    )
    assert "Retry" not in text


def test_discovery_uses_public_cards_and_keeps_curated_rows(gc, monkeypatch):
    http = session(
        {
            SITE
            + "/courses/": f'<main><ads-card data-course-card><h2>Example</h2><ads-cta-link link="{COURSE}"></ads-cta-link></ads-card></main>',
            SITE
            + "/insights/": f'<main><ads-card class="insights-area-card" link="{INSIGHT}"><h3>SVE</h3></ads-card></main>',
        }
    )
    sources = LearnSources(http)
    # Public discovery is independent of the Learning Paths archive.
    monkeypatch.setattr(
        sources, "repository", lambda *_: SimpleNamespace(discovered_sources=lambda: [])
    )
    monkeypatch.setattr(gc, "learn_sources", sources)
    gc.register_source(
        "Educational Course", "CC-BY-SA-4.0", "Curated", COURSE, ["curated"]
    )
    gc.reconcile_learn_sources(discover=False)
    assert http.calls == []
    gc.reconcile_learn_sources(discover=True)
    assert len(gc.all_sources) == 2
    assert gc.all_sources[0]["display_name"] == "Curated"
    assert gc.all_sources[0]["keywords"] == "curated"


def test_learn_transcripts_use_public_pages(gc, monkeypatch):
    sources = LearnSources(
        session(
            {
                LESSON: '<main><div class="course-body"><h1>Transcript</h1><p>Instructions.</p></div></main>'
            }
        )
    )
    monkeypatch.setattr(gc, "learn_sources", sources)
    chunks = gc.create_chunks_for_source(
        "https://example.com/video", "Video", "Video", "Arm", LESSON
    )
    assert chunks and chunks[0].url == "https://example.com/video"
    assert chunks[0].resolved_url == LESSON
