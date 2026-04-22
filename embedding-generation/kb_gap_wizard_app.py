"""Local Flask wizard for generating content-gap evaluation questions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request


APP_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = APP_ROOT / "wizard_outputs"

app = Flask(__name__)


QUESTION_PATTERNS: dict[str, list[str]] = {
    "foundations": [
        "What core concepts should someone understand before working with {topic} on Arm?",
        "How does {topic} work on Arm, and which capabilities or constraints matter most for practitioners?",
        "What official or high-signal reference material should a user read first for {topic} on Arm?",
    ],
    "implementation": [
        "How do I get started with {topic} on Arm in {environment}?",
        "What build, installation, or integration steps are required to use {topic} on Arm?",
        "What sample workflows or end-to-end tutorials exist for {topic} on Arm?",
    ],
    "optimization": [
        "What performance tuning guidance exists for {topic} on Arm?",
        "Which metrics, benchmarks, or profiling steps are recommended when optimizing {topic} on Arm?",
        "What Arm-specific features, libraries, or accelerators should be considered when improving {topic}?",
    ],
    "troubleshooting": [
        "What common issues arise when using {topic} on Arm, and how are they diagnosed or fixed?",
        "How can I validate that {topic} is configured correctly on Arm?",
        "What debugging guidance exists for {topic} on Arm in {environment}?",
    ],
    "coverage_gaps": [
        "What documentation is missing or thin today for {topic} on Arm, especially around {gap_focus}?",
        "If a user wanted practical guidance for {topic} on Arm, which questions would the current knowledge base struggle to answer?",
        "Where does the knowledge base provide only high-level coverage for {topic} instead of actionable implementation detail?",
    ],
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "knowledge-base-check"


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def select_environment(environments: list[str]) -> str:
    if environments:
        return ", ".join(environments[:2])
    return "their target environment"


def select_gap_focus(gaps: list[str], keywords: list[str]) -> str:
    combined = gaps + keywords
    if combined:
        return ", ".join(combined[:3])
    return "their highest-priority use cases"


def build_contextual_questions(
    topic: str,
    subtopics: list[str],
    environments: list[str],
    content_types: list[str],
    goals: list[str],
    gaps: list[str],
    keywords: list[str],
) -> dict[str, list[str]]:
    environment = select_environment(environments)
    gap_focus = select_gap_focus(gaps, keywords)

    sections: dict[str, list[str]] = {}
    for section, patterns in QUESTION_PATTERNS.items():
        rendered = [
            pattern.format(
                topic=topic,
                environment=environment,
                gap_focus=gap_focus,
            )
            for pattern in patterns
        ]
        sections[section] = rendered

    if subtopics:
        sections["subtopics"] = [
            f"What Arm-specific guidance exists for {subtopic} within the broader {topic} topic?"
            for subtopic in subtopics[:6]
        ]

    if content_types:
        sections["content_type_coverage"] = [
            f"Does the knowledge base provide strong {content_type.lower()} coverage for {topic} on Arm?"
            for content_type in content_types[:6]
        ]

    if goals:
        sections["user_goals"] = [
            f"If the user wants to {goal.lower()}, does the knowledge base provide enough actionable guidance for {topic} on Arm?"
            for goal in goals[:6]
        ]

    if keywords:
        sections["must_cover_terms"] = [
            f"What does the knowledge base say about {keyword} in the context of {topic} on Arm?"
            for keyword in keywords[:6]
        ]

    return sections


def trim_sections(sections: dict[str, list[str]], question_budget: int) -> dict[str, list[str]]:
    if question_budget <= 0:
        question_budget = 20

    per_section = max(1, question_budget // max(1, len(sections)))
    trimmed: dict[str, list[str]] = {}
    collected = 0

    for section_name, questions in sections.items():
        unique_questions = dedupe_preserve_order(questions)
        section_slice = unique_questions[:per_section]
        if section_slice:
            trimmed[section_name] = section_slice
            collected += len(section_slice)

    if collected >= question_budget:
        return trimmed

    overflow: list[tuple[str, str]] = []
    for section_name, questions in sections.items():
        existing = set(trimmed.get(section_name, []))
        for question in dedupe_preserve_order(questions):
            if question not in existing:
                overflow.append((section_name, question))

    for section_name, question in overflow:
        if collected >= question_budget:
            break
        trimmed.setdefault(section_name, []).append(question)
        collected += 1

    return trimmed


def summarize_request(payload: dict[str, Any]) -> str:
    topic = payload["topic"]
    audience = payload.get("audience") or "a target user"
    environments = normalize_list(payload.get("environments"))
    content_types = normalize_list(payload.get("content_types"))

    parts = [f"This plan is focused on **{topic}** for **{audience}**."]
    if environments:
        parts.append(f"It emphasizes **{', '.join(environments[:3])}**.")
    if content_types:
        parts.append(f"It specifically probes **{', '.join(content_types[:3]).lower()}** coverage.")
    parts.append(
        "The goal is to surface where the Arm MCP knowledge base can answer practical questions well and where important implementation detail is still missing."
    )
    return " ".join(parts)


def build_output(payload: dict[str, Any]) -> dict[str, Any]:
    topic = str(payload.get("topic", "")).strip()
    if not topic:
        raise ValueError("Topic is required.")

    subtopics = split_csv(str(payload.get("subtopics", "")))
    keywords = split_csv(str(payload.get("keywords", "")))
    goals = normalize_list(payload.get("goals"))
    gaps = split_csv(str(payload.get("known_gaps", "")))
    environments = normalize_list(payload.get("environments"))
    content_types = normalize_list(payload.get("content_types"))

    question_budget = int(payload.get("question_budget") or 20)
    question_budget = min(max(question_budget, 8), 48)

    raw_sections = build_contextual_questions(
        topic=topic,
        subtopics=subtopics,
        environments=environments,
        content_types=content_types,
        goals=goals,
        gaps=gaps,
        keywords=keywords,
    )
    sections = trim_sections(raw_sections, question_budget)
    question_count = sum(len(items) for items in sections.values())
    slug = slugify(topic)

    return {
        "title": topic,
        "slug": slug,
        "summary": summarize_request(
            {
                "topic": topic,
                "audience": str(payload.get("audience", "")).strip(),
                "environments": environments,
                "content_types": content_types,
            }
        ),
        "questions": sections,
        "question_count": question_count,
        "suggested_filename": f"{slug}_questions.json",
        "suggested_command": (
            f"./venv/bin/python content_checker.py wizard_outputs/{slug}_questions.json "
            f"--report-markdown-path wizard_outputs/{slug}_report.md "
            f"--report-json-path wizard_outputs/{slug}_report.json "
            f"--output-path wizard_outputs/{slug}_question_links_found.json"
        ),
    }


@app.get("/")
def index() -> str:
    return render_template("kb_gap_wizard.html")


@app.get("/api/health")
def health() -> Any:
    return jsonify({"status": "ok"})


@app.post("/api/generate")
def generate() -> Any:
    payload = request.get_json(silent=True) or {}
    try:
        result = build_output(payload)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.post("/api/save")
def save() -> Any:
    payload = request.get_json(silent=True) or {}
    try:
        result = build_output(payload)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / result["suggested_filename"]
    output_path.write_text(json.dumps(result["questions"], indent=2) + "\n")

    return jsonify(
        {
            "saved": True,
            "path": str(output_path.relative_to(APP_ROOT)),
            "question_count": result["question_count"],
            "suggested_command": result["suggested_command"],
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5001)
