"""Evaluate sectioned content questions against retrieval results and summarize gaps with GPT."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib3
from pathlib import Path
from typing import Any

import requests
from sentence_transformers import SentenceTransformer


REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_LOCAL_DIR = REPO_ROOT / "mcp-local"
if str(MCP_LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_LOCAL_DIR))

from utils.search_utils import build_bm25_index, deduplicate_urls, hybrid_search, load_metadata, load_usearch_index  # noqa: E402


DEFAULT_OPENAI_BASE_URL = "https://openai-api-proxy.geo.arm.com/api/providers/openai/v1/"


def sentence_transformer_cache_folder() -> str | None:
    return os.getenv("SENTENCE_TRANSFORMERS_HOME") or None


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def trim_text(text: str, limit: int) -> str:
    normalized = normalize_text(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def load_question_sections(path: Path) -> dict[str, list[str]]:
    with path.open() as file:
        payload = json.load(file)

    if not isinstance(payload, dict):
        raise ValueError("Question file must be a JSON object keyed by topic.")

    sections: dict[str, list[str]] = {}
    for topic, questions in payload.items():
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("Each top-level key must be a non-empty topic string.")
        if not isinstance(questions, list):
            raise ValueError(f"Topic '{topic}' must map to a list of questions.")

        normalized_questions: list[str] = []
        for entry in questions:
            if isinstance(entry, str):
                question = entry.strip()
            elif isinstance(entry, dict) and isinstance(entry.get("question"), str):
                question = entry["question"].strip()
            else:
                raise ValueError(
                    f"Topic '{topic}' contains an unsupported question entry. "
                    "Use strings or objects with a 'question' field."
                )

            if not question:
                raise ValueError(f"Topic '{topic}' contains an empty question.")
            normalized_questions.append(question)

        sections[topic] = normalized_questions

    return sections


def build_runtime(index_path: Path, metadata_path: Path, model_name: str) -> dict[str, Any]:
    metadata = load_metadata(str(metadata_path))
    if not metadata:
        raise ValueError(f"Metadata not found or empty: {metadata_path}")

    embedding_model = SentenceTransformer(
        model_name,
        cache_folder=sentence_transformer_cache_folder(),
        local_files_only=True,
    )
    usearch_index = load_usearch_index(
        str(index_path),
        embedding_model.get_sentence_embedding_dimension(),
    )
    if usearch_index is None:
        raise ValueError(f"USearch index not found or invalid: {index_path}")

    bm25_index = build_bm25_index(metadata)
    return {
        "metadata": metadata,
        "embedding_model": embedding_model,
        "usearch_index": usearch_index,
        "bm25_index": bm25_index,
    }


def retrieve_question(
    question: str,
    runtime: dict[str, Any],
    top_k: int,
    chunk_chars: int,
) -> dict[str, Any]:
    raw_results = hybrid_search(
        question,
        runtime["usearch_index"],
        runtime["metadata"],
        runtime["embedding_model"],
        runtime["bm25_index"],
        k=top_k,
    )
    results = deduplicate_urls(raw_results, max_chunks_per_url=1)[:top_k]

    serialized_results: list[dict[str, Any]] = []
    for rank, item in enumerate(results, start=1):
        metadata = item["metadata"]
        serialized_results.append(
            {
                "rank": rank,
                "url": metadata.get("url"),
                "resolved_url": metadata.get("resolved_url"),
                "title": metadata.get("title"),
                "doc_type": metadata.get("doc_type"),
                "heading": metadata.get("heading"),
                "heading_path": metadata.get("heading_path") or [],
                "chunk_uuid": metadata.get("chunk_uuid") or metadata.get("uuid"),
                "chunk_preview": trim_text(metadata.get("original_text") or metadata.get("search_text") or "", chunk_chars),
                "rerank_score": round(float(item.get("rerank_score", 0.0)), 6),
                "bm25_score": round(float(item.get("bm25_score", 0.0)), 6) if item.get("bm25_score") is not None else None,
                "distance": round(float(item.get("distance", 0.0)), 6) if item.get("distance") is not None else None,
            }
        )

    return {
        "question": question,
        "results": serialized_results,
    }


def build_question_links_found(
    sections: dict[str, list[str]],
    runtime: dict[str, Any],
    top_k: int,
    chunk_chars: int,
) -> dict[str, Any]:
    output_sections: dict[str, list[dict[str, Any]]] = {}
    total_questions = 0

    for topic, questions in sections.items():
        topic_rows = []
        for question in questions:
            topic_rows.append(retrieve_question(question, runtime, top_k=top_k, chunk_chars=chunk_chars))
            total_questions += 1
        output_sections[topic] = topic_rows

    return {
        "summary": {
            "topic_count": len(output_sections),
            "question_count": total_questions,
            "top_k": top_k,
            "chunk_preview_chars": chunk_chars,
        },
        "topics": output_sections,
    }


def build_llm_payload(question_links_found: dict[str, Any]) -> list[dict[str, Any]]:
    llm_topics: list[dict[str, Any]] = []
    for topic, questions in question_links_found["topics"].items():
        topic_questions = []
        for row in questions:
            topic_questions.append(
                {
                    "question": row["question"],
                    "retrieved_results": [
                        {
                            "rank": result["rank"],
                            "url": result["url"],
                            "resolved_url": result["resolved_url"],
                            "title": result["title"],
                            "doc_type": result["doc_type"],
                            "heading_path": result["heading_path"],
                            "chunk_preview": result["chunk_preview"],
                        }
                        for result in row["results"]
                    ],
                }
            )
        llm_topics.append({"topic": topic, "questions": topic_questions})
    return llm_topics


def build_llm_prompt(question_links_found: dict[str, Any]) -> tuple[str, str]:
    instructions = (
        "You are evaluating retrieval quality for a documentation knowledge base. "
        "For each question, judge whether the retrieved links and chunk previews are sufficient to answer the question well. "
        "Use these labels only: correct, partial, incorrect. "
        "A result is correct when the retrieved evidence directly answers the question with the right source(s). "
        "A result is partial when it is relevant but missing critical details or only weakly supports the answer. "
        "A result is incorrect when the evidence is off-topic or clearly insufficient. "
        "Return strict JSON with this shape: "
        "{"
        "\"overall\": {\"question_count\": int, \"correct_count\": int, \"partial_count\": int, \"incorrect_count\": int}, "
        "\"topics\": ["
        "{\"topic\": str, \"question_count\": int, \"correct_count\": int, \"partial_count\": int, \"incorrect_count\": int, "
        "\"accuracy_summary\": str, \"major_weaknesses\": [str], "
        "\"question_evaluations\": [{\"question\": str, \"verdict\": \"correct|partial|incorrect\", \"reason\": str, \"best_urls\": [str]}]}"
        "], "
        "\"cross_topic_weaknesses\": [str], "
        "\"report_markdown\": str"
        "}. "
        "Counts must be internally consistent. Keep reasons concise and evidence-based."
    )
    user_input = json.dumps(
        {
            "evaluation_metadata": question_links_found["summary"],
            "topics": build_llm_payload(question_links_found),
        },
        indent=2,
    )
    return instructions, user_input


def extract_response_text(response_json: dict[str, Any]) -> str:
    output_text = response_json.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    chunks: list[str] = []
    for item in response_json.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def parse_json_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", stripped)
        stripped = re.sub(r"\n```$", "", stripped)

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def call_openai_report(
    *,
    api_key: str,
    base_url: str,
    model: str,
    question_links_found: dict[str, Any],
    timeout: int,
    verify: bool | str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    instructions, user_input = build_llm_prompt(question_links_found)
    url = base_url.rstrip("/") + "/responses"
    payload = {
        "model": model,
        "instructions": instructions,
        "input": user_input,
        "max_output_tokens": 12000,
    }

    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
        verify=verify,
    )
    response.raise_for_status()
    response_json = response.json()
    response_text = extract_response_text(response_json)
    if not response_text:
        raise ValueError("The model response did not contain any text output.")
    return parse_json_response(response_text), response_json


def normalize_report_counts(report: dict[str, Any]) -> dict[str, Any]:
    topics = report.get("topics")
    if not isinstance(topics, list):
        topics = []
        report["topics"] = topics

    overall_counts = {
        "question_count": 0,
        "correct_count": 0,
        "partial_count": 0,
        "incorrect_count": 0,
    }

    for topic in topics:
        evaluations = topic.get("question_evaluations")
        if not isinstance(evaluations, list):
            evaluations = []
            topic["question_evaluations"] = evaluations

        correct_count = 0
        partial_count = 0
        incorrect_count = 0
        for evaluation in evaluations:
            verdict = str(evaluation.get("verdict", "")).strip().lower()
            if verdict == "correct":
                correct_count += 1
            elif verdict == "partial":
                partial_count += 1
            else:
                incorrect_count += 1
                evaluation["verdict"] = "incorrect"

        question_count = len(evaluations)
        topic["question_count"] = question_count
        topic["correct_count"] = correct_count
        topic["partial_count"] = partial_count
        topic["incorrect_count"] = incorrect_count

        overall_counts["question_count"] += question_count
        overall_counts["correct_count"] += correct_count
        overall_counts["partial_count"] += partial_count
        overall_counts["incorrect_count"] += incorrect_count

    report["overall"] = overall_counts
    if not isinstance(report.get("cross_topic_weaknesses"), list):
        report["cross_topic_weaknesses"] = []
    return report


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def markdown_bullets(items: list[str]) -> list[str]:
    normalized_items = [normalize_text(item) for item in items if normalize_text(item)]
    if not normalized_items:
        return ["- None identified."]
    return [f"- {item}" for item in normalized_items]


def format_accuracy(correct: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{(correct / total) * 100:.1f}%"


def write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    overall = report.get("overall", {})
    lines = [
        "# Content Checker Report",
        "",
        "## Overall Summary",
        "",
        f"- Questions evaluated: {overall.get('question_count', 0)}",
        f"- Correct: {overall.get('correct_count', 0)}",
        f"- Partial: {overall.get('partial_count', 0)}",
        f"- Incorrect: {overall.get('incorrect_count', 0)}",
        f"- Accuracy: {format_accuracy(overall.get('correct_count', 0), overall.get('question_count', 0))}",
    ]

    lines.extend(["", "## Cross-Topic Weaknesses", ""])
    lines.extend(markdown_bullets(report.get("cross_topic_weaknesses", [])))

    for topic in report.get("topics", []):
        topic_name = topic.get("topic", "Unknown Topic")
        question_count = topic.get("question_count", 0)
        correct_count = topic.get("correct_count", 0)
        partial_count = topic.get("partial_count", 0)
        incorrect_count = topic.get("incorrect_count", 0)
        accuracy_summary = normalize_text(topic.get("accuracy_summary", ""))
        weaknesses = topic.get("major_weaknesses", [])
        evaluations = topic.get("question_evaluations", [])
        misses = [item for item in evaluations if item.get("verdict") != "correct"]

        lines.extend(
            [
                "",
                f"## {topic_name}",
                "",
                f"- Questions evaluated: {question_count}",
                f"- Correct: {correct_count}",
                f"- Partial: {partial_count}",
                f"- Incorrect: {incorrect_count}",
                f"- Accuracy: {format_accuracy(correct_count, question_count)}",
            ]
        )
        if accuracy_summary:
            lines.extend(["", accuracy_summary])

        lines.extend(["", "### Major Weaknesses", ""])
        lines.extend(markdown_bullets(weaknesses))

        lines.extend(["", "### Questions Marked Partial or Incorrect", ""])
        if not misses:
            lines.append("- None. All questions in this topic were marked correct.")
        else:
            for evaluation in misses:
                question = normalize_text(evaluation.get("question", ""))
                verdict = str(evaluation.get("verdict", "incorrect")).strip().lower() or "incorrect"
                reason = normalize_text(evaluation.get("reason", ""))
                best_urls = [url for url in evaluation.get("best_urls", []) if normalize_text(url)]

                lines.append(f"- `{verdict}`: {question}")
                if reason:
                    lines.append(f"  Reason: {reason}")
                if best_urls:
                    lines.append(f"  Best URLs: {', '.join(best_urls)}")

    report_markdown = report.get("report_markdown")
    if isinstance(report_markdown, str) and normalize_text(report_markdown):
        lines.extend(["", "## Model Narrative", "", report_markdown.rstrip()])

    path.write_text("\n".join(lines).rstrip() + "\n")


def print_summary(report: dict[str, Any]) -> None:
    overall = report.get("overall", {})
    print(f"Questions: {overall.get('question_count', 0)}")
    print(f"Correct: {overall.get('correct_count', 0)}")
    print(f"Partial: {overall.get('partial_count', 0)}")
    print(f"Incorrect: {overall.get('incorrect_count', 0)}")
    print()
    for topic in report.get("topics", []):
        print(
            f"{topic.get('topic', 'Unknown Topic')}: "
            f"{topic.get('correct_count', 0)}/{topic.get('question_count', 0)} correct "
            f"({topic.get('partial_count', 0)} partial, {topic.get('incorrect_count', 0)} incorrect)"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run sectioned content questions through local retrieval and summarize quality with GPT."
    )
    parser.add_argument("questions_path", help="Path to a JSON object keyed by topic with lists of questions.")
    parser.add_argument("--index-path", default="usearch_index.bin")
    parser.add_argument("--metadata-path", default="metadata.json")
    parser.add_argument("--model-name", default="all-MiniLM-L6-v2")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--chunk-chars", type=int, default=700)
    parser.add_argument("--output-path", default="question_links_found.json")
    parser.add_argument("--report-json-path", default="content_checker_report.json")
    parser.add_argument("--report-markdown-path", default="content_checker_report.md")
    parser.add_argument("--responses-json-path", default="content_checker_openai_response.json")
    parser.add_argument("--openai-model", default="gpt-5.4")
    parser.add_argument("--openai-base-url", default=DEFAULT_OPENAI_BASE_URL)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--ca-bundle", help="Path to a CA bundle PEM file for the OpenAI proxy.")
    parser.add_argument("--insecure-skip-tls-verify", action="store_true")
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()

    sections = load_question_sections(Path(args.questions_path))
    runtime = build_runtime(
        index_path=Path(args.index_path),
        metadata_path=Path(args.metadata_path),
        model_name=args.model_name,
    )

    question_links_found = build_question_links_found(
        sections=sections,
        runtime=runtime,
        top_k=args.top_k,
        chunk_chars=args.chunk_chars,
    )
    write_json(Path(args.output_path), question_links_found)
    print(f"Wrote retrieval evidence to {args.output_path}")

    if args.skip_llm:
        print("Skipping LLM evaluation.")
        return 0

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY must be set unless --skip-llm is used.")

    verify: bool | str = True
    if args.ca_bundle:
        verify = args.ca_bundle
    elif args.insecure_skip_tls_verify:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        verify = False

    report, raw_response = call_openai_report(
        api_key=api_key,
        base_url=args.openai_base_url,
        model=args.openai_model,
        question_links_found=question_links_found,
        timeout=args.timeout,
        verify=verify,
    )
    report = normalize_report_counts(report)
    write_json(Path(args.report_json_path), report)
    write_markdown_report(Path(args.report_markdown_path), report)
    write_json(Path(args.responses_json_path), raw_response)

    print_summary(report)
    print()
    print(f"Wrote model report to {args.report_json_path}")
    print(f"Wrote markdown report to {args.report_markdown_path}")
    print(f"Wrote raw OpenAI response to {args.responses_json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
