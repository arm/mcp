#!/usr/bin/env python3
"""Prepare Arm MCP documentation updates across local and downstream docs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_WORKDIR = SCRIPT_DIR / "workdir"
DEFAULT_REPORTS_DIR = SCRIPT_DIR / "reports"

SOURCE_README = REPO_ROOT / "README.md"
AGENT_INSTALL_GUIDE = REPO_ROOT / "agent-integrations" / "agent-install-instructions.md"
MCP_SERVER_JSON = REPO_ROOT / "mcp-local" / "server.json"


@dataclass(frozen=True)
class RepoSpec:
    alias: str
    clone_url: Optional[str]
    local_path: Path
    branch_prefix: str
    current_repo: bool = False


@dataclass(frozen=True)
class TargetSpec:
    name: str
    url: str
    category: str
    repo_alias: Optional[str]
    mode: str
    notes: str = ""
    explicit_repo_path: Optional[str] = None
    locator: str = "auto"


@dataclass
class SourceConfig:
    source_path: Path
    section_text: str
    client_blocks: dict[str, str]
    generic_json: str
    generic_toml: str
    docker_image: str
    docker_pull: str
    performix_note: str


@dataclass
class RepoPlan:
    spec: RepoSpec
    branch_name: str
    cloned: bool = False
    branch_created: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class TargetResult:
    spec: TargetSpec
    status: str
    repo_alias: Optional[str] = None
    repo_path: Optional[Path] = None
    branch_name: Optional[str] = None
    file_path: Optional[Path] = None
    summary: str = ""
    details: list[str] = field(default_factory=list)
    pr_title: Optional[str] = None


REPOS: dict[str, RepoSpec] = {
    "current-repo": RepoSpec(
        alias="current-repo",
        clone_url=None,
        local_path=REPO_ROOT,
        branch_prefix="docs/arm-mcp-config",
        current_repo=True,
    ),
    "arm-learning-paths": RepoSpec(
        alias="arm-learning-paths",
        clone_url="https://github.com/ArmDeveloperEcosystem/arm-learning-paths.git",
        local_path=DEFAULT_WORKDIR / "repos" / "arm-learning-paths",
        branch_prefix="docs/arm-mcp-config",
    ),
    "awesome-copilot": RepoSpec(
        alias="awesome-copilot",
        clone_url="https://github.com/github/awesome-copilot.git",
        local_path=DEFAULT_WORKDIR / "repos" / "awesome-copilot",
        branch_prefix="docs/arm-mcp-config",
    ),
    "mcp-arm": RepoSpec(
        alias="mcp-arm",
        clone_url="https://github.com/mcp/arm.git",
        local_path=DEFAULT_WORKDIR / "repos" / "mcp-arm",
        branch_prefix="docs/arm-mcp-config",
    ),
    "iflow-arm-mcp": RepoSpec(
        alias="iflow-arm-mcp",
        clone_url="https://github.com/iflow-mcp/arm-mcp.git",
        local_path=DEFAULT_WORKDIR / "repos" / "iflow-arm-mcp",
        branch_prefix="docs/arm-mcp-config",
    ),
    "echiugoog-arm-mcp": RepoSpec(
        alias="echiugoog-arm-mcp",
        clone_url="https://github.com/echiugoog/arm-mcp.git",
        local_path=DEFAULT_WORKDIR / "repos" / "echiugoog-arm-mcp",
        branch_prefix="docs/arm-mcp-config",
    ),
}


TARGETS: list[TargetSpec] = [
    TargetSpec(
        name="Arm MCP README",
        url="https://github.com/arm/mcp",
        category="local-doc",
        repo_alias="current-repo",
        mode="report-only",
        explicit_repo_path="README.md",
        notes="Source of truth; include in report but do not rewrite automatically.",
    ),
    TargetSpec(
        name="Agent install instructions",
        url="https://github.com/arm/mcp/blob/main/agent-integrations/agent-install-instructions.md",
        category="local-doc",
        repo_alias="current-repo",
        mode="auto",
        explicit_repo_path="agent-integrations/agent-install-instructions.md",
    ),
    TargetSpec(
        name="Developer Arm landing page",
        url="https://developer.arm.com/servers-and-cloud-computing/arm-mcp-server",
        category="arm-web",
        repo_alias=None,
        mode="manual",
        notes="Backed by non-local publishing workflow; report manual update.",
    ),
    TargetSpec(
        name="Learning path root",
        url="https://learn.arm.com/learning-paths/servers-and-cloud-computing/arm-mcp-server/",
        category="learning-path",
        repo_alias="arm-learning-paths",
        mode="auto",
        locator="learn-arm",
    ),
    TargetSpec(
        name="Learning path overview",
        url="https://learn.arm.com/learning-paths/servers-and-cloud-computing/arm-mcp-server/1-overview/",
        category="learning-path",
        repo_alias="arm-learning-paths",
        mode="auto",
        locator="learn-arm",
    ),
    TargetSpec(
        name="Docker MCP Toolkit setup",
        url="https://learn.arm.com/learning-paths/servers-and-cloud-computing/docker-mcp-toolkit/2-setup/",
        category="learning-path",
        repo_alias="arm-learning-paths",
        mode="auto",
        locator="learn-arm",
    ),
    TargetSpec(
        name="Install guide: GitHub Copilot",
        url="https://learn.arm.com/install-guides/github-copilot/",
        category="install-guide",
        repo_alias="arm-learning-paths",
        mode="auto",
        locator="learn-arm",
    ),
    TargetSpec(
        name="Install guide: Codex CLI",
        url="https://learn.arm.com/install-guides/codex-cli/",
        category="install-guide",
        repo_alias="arm-learning-paths",
        mode="auto",
        locator="learn-arm",
    ),
    TargetSpec(
        name="Install guide: Claude Code",
        url="https://learn.arm.com/install-guides/claude-code/",
        category="install-guide",
        repo_alias="arm-learning-paths",
        mode="auto",
        locator="learn-arm",
    ),
    TargetSpec(
        name="Install guide: Gemini",
        url="https://learn.arm.com/install-guides/gemini/",
        category="install-guide",
        repo_alias="arm-learning-paths",
        mode="auto",
        locator="learn-arm",
    ),
    TargetSpec(
        name="mcp/arm mirror",
        url="https://github.com/mcp/arm/arm-mcp",
        category="downstream-github",
        repo_alias="mcp-arm",
        mode="auto",
        locator="repo-readme",
    ),
    TargetSpec(
        name="Docker Hub image page",
        url="https://hub.docker.com/r/armlimited/arm-mcp",
        category="dockerhub",
        repo_alias=None,
        mode="manual",
        notes="Docker Hub description/config is not updated via this repo today.",
    ),
    TargetSpec(
        name="Docker MCP catalog overview",
        url="https://hub.docker.com/mcp/server/arm-mcp/overview",
        category="dockerhub",
        repo_alias=None,
        mode="manual",
        notes="Requires Docker catalog workflow or portal update.",
    ),
    TargetSpec(
        name="Docker MCP catalog config",
        url="https://hub.docker.com/mcp/server/arm-mcp/config",
        category="dockerhub",
        repo_alias=None,
        mode="manual",
        notes="Track against mcp-local/server.json and Docker publishing workflow.",
    ),
    TargetSpec(
        name="Awesome Copilot agent doc",
        url="https://github.com/github/awesome-copilot/blob/main/agents/arm-migration.agent.md",
        category="downstream-github",
        repo_alias="awesome-copilot",
        mode="auto",
        explicit_repo_path="agents/arm-migration.agent.md",
    ),
    TargetSpec(
        name="iflow arm-mcp",
        url="https://github.com/iflow-mcp/arm-mcp",
        category="downstream-github",
        repo_alias="iflow-arm-mcp",
        mode="auto",
        locator="repo-readme",
    ),
    TargetSpec(
        name="echiugoog arm-mcp",
        url="https://github.com/echiugoog/arm-mcp",
        category="downstream-github",
        repo_alias="echiugoog-arm-mcp",
        mode="auto",
        locator="repo-readme",
    ),
    TargetSpec(
        name="AWS Builders article",
        url="https://dev.to/aws-builders/aws-graviton-migration-with-kiro-cli-and-the-arm-mcp-server-38fd",
        category="external-article",
        repo_alias=None,
        mode="manual",
        notes="Third-party article; include recommended outreach/manual update note only.",
    ),
    TargetSpec(
        name="Docker blog article",
        url="https://www.docker.com/blog/automate-arm-migration-docker-mcp-copilot/",
        category="external-article",
        repo_alias=None,
        mode="manual",
        notes="External editorial workflow; include manual update note only.",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare documentation updates for Arm MCP configuration changes."
    )
    parser.add_argument(
        "--mode",
        choices=("report", "prepare", "update"),
        default="update",
        help="report only, clone/branch prep, or clone/branch plus file updates",
    )
    parser.add_argument(
        "--source-readme",
        type=Path,
        default=SOURCE_README,
        help="Path to the README that defines the canonical MCP config",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORKDIR,
        help="Directory used for cloned repos",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional explicit report path",
    )
    parser.add_argument(
        "--branch-name",
        default=None,
        help="Override branch name for all prepared repos",
    )
    parser.add_argument(
        "--llm-model",
        default="gpt-5.4",
        help="OpenAI model used for optional doc rewrites",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM-assisted edits and use deterministic/manual handling only",
    )
    parser.add_argument(
        "--reset-clones",
        action="store_true",
        help="Delete non-current cloned repos before preparing them again",
    )
    return parser.parse_args()


def run(
    args: list[str],
    *,
    cwd: Path,
    capture_output: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        capture_output=capture_output,
        check=check,
    )


def git_current_branch(repo_path: Path) -> str:
    try:
        result = run(["git", "branch", "--show-current"], cwd=repo_path)
        branch = result.stdout.strip()
        return branch or "HEAD"
    except subprocess.CalledProcessError:
        return "HEAD"


def sanitize_branch_name(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._/-]+", "-", value).strip("-")
    return clean or "docs/arm-mcp-config"


def extract_source_config(readme_path: Path) -> SourceConfig:
    content = readme_path.read_text(encoding="utf-8")

    section_match = re.search(
        r"### 2\. Configure Your MCP Client\s*(.*?)\n### 3\. Restart Your MCP Client",
        content,
        re.DOTALL,
    )
    if not section_match:
        raise ValueError(f"Unable to find MCP client config section in {readme_path}")
    section_text = section_match.group(1).strip()

    block_pattern = re.compile(
        r"####\s+([^\n]+)\n(.*?)(```[A-Za-z0-9]*\n.*?\n```)",
        re.DOTALL,
    )
    client_blocks: dict[str, str] = {}
    for heading, _, fenced_block in block_pattern.findall(section_text):
        client_blocks[heading.strip()] = fenced_block.strip()

    claude_block = client_blocks.get("Claude Code")
    toml_block = client_blocks.get("MCP Clients using TOML format (e.g. Codex CLI)")
    if not claude_block or not toml_block:
        raise ValueError("Unable to extract canonical JSON/TOML config blocks from README")

    json_match = re.search(r"```json\n(.*?)\n```", claude_block, re.DOTALL)
    toml_match = re.search(r"```toml\n(.*?)\n```", toml_block, re.DOTALL)
    if not json_match or not toml_match:
        raise ValueError("Missing fenced JSON/TOML config blocks in README")

    json_config = json.loads(json_match.group(1))
    generic_json = json.dumps(
        {
            "command": json_config["mcpServers"]["arm-mcp"]["command"],
            "args": json_config["mcpServers"]["arm-mcp"]["args"],
        },
        indent=2,
    )

    args_list = json_config["mcpServers"]["arm-mcp"]["args"]
    toml_lines = ["[mcp_servers.arm-mcp]", 'command = "docker"', "args = ["]
    for item in args_list:
        toml_lines.append(f'  "{item}",')
    toml_lines.append("]")
    generic_toml = "\n".join(toml_lines)

    image = next((item for item in reversed(args_list) if "arm-mcp" in item), "armlimited/arm-mcp")
    docker_pull = f"docker pull {image}:latest" if ":" not in image else f"docker pull {image}"
    performix_note = (
        "The SSH-related volume mounts are optional and are only needed when enabling Arm Performix."
    )

    return SourceConfig(
        source_path=readme_path,
        section_text=section_text,
        client_blocks=client_blocks,
        generic_json=generic_json,
        generic_toml=generic_toml,
        docker_image=image,
        docker_pull=docker_pull,
        performix_note=performix_note,
    )


def build_agent_install_content(source: SourceConfig) -> str:
    return textwrap.dedent(
        f"""\
        # Arm MCP Server Installation

        Search online for the latest MCP configuration instructions for your agent, then configure the Arm MCP server using the Docker image.

        Pull the Docker image:

        ```bash
        docker pull {source.docker_image}:latest
        ```

        Use the following command and args in your MCP configuration (adjusting the format as required by your agent).

        The examples below include optional SSH-related volume mounts for **Arm Performix**. If you are not using Arm Performix, you can omit the `/run/keys` mounts.

        For JSON-based configurations:

        ```json
        {source.generic_json}
        ```

        For TOML-based configurations:

        ```toml
        {source.generic_toml}
        ```

        Replace `/path/to/your/workspace` with the absolute path to the project you want the MCP server to access.
        If you are enabling Arm Performix, also replace the SSH private key and `known_hosts` paths with your local files.
        """
    ).rstrip() + "\n"


class OpenAIRewriter:
    def __init__(self, model: str) -> None:
        self.model = model
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = self._detect_base_url()

    def available(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _detect_base_url(self) -> Optional[str]:
        for env_name in (
            "OPENAI_API_PROXY_URL",
            "OPENAI_API_PROXY",
            "DOC_UPDATER_OPENAI_BASE_URL",
            "OPENAI_BASE_URL",
            "OPENAI_API_BASE",
        ):
            value = os.getenv(env_name)
            if value:
                value = value.rstrip("/")
                if value.endswith("/models"):
                    value = value[: -len("/models")]
                return value
        return "https://api.openai.com/v1"

    def rewrite_markdown(
        self,
        *,
        target: TargetSpec,
        content: str,
        source: SourceConfig,
    ) -> tuple[str, str]:
        if not self.available():
            raise RuntimeError("OpenAI API credentials/base URL are not configured")

        instructions = (
            "You update documentation for the Arm MCP server. "
            "Make the smallest possible edit set. Preserve front matter, headings, and surrounding prose. "
            "Update only content related to configuring the Arm MCP server so it matches the canonical source. "
            "Do not invent new product claims or remove unrelated guidance. "
            "Return strict JSON with keys updated_content and summary."
        )

        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": instructions}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                {
                                    "target_name": target.name,
                                    "target_url": target.url,
                                    "canonical_source_path": str(source.source_path),
                                    "canonical_json_config": source.generic_json,
                                    "canonical_toml_config": source.generic_toml,
                                    "performix_note": source.performix_note,
                                    "current_content": content,
                                },
                                indent=2,
                            ),
                        }
                    ],
                },
            ],
            "reasoning": {"effort": "medium"},
            "text": {"format": {"type": "json_object"}},
        }

        response = requests.post(
            f"{self.base_url}/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        output_text = data.get("output_text")
        if not output_text:
            output_text = extract_output_text(data)
        parsed = json.loads(output_text)
        updated_content = parsed["updated_content"]
        summary = parsed.get("summary", "Updated with canonical Arm MCP config")
        return updated_content, summary


def extract_output_text(response_json: dict) -> str:
    output = response_json.get("output", [])
    for item in output:
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text", "")
    raise ValueError("OpenAI response did not contain output_text")


def prepare_repo(
    plan: RepoPlan,
    *,
    mode: str,
    reset_clone: bool,
) -> None:
    spec = plan.spec
    if spec.current_repo:
        if mode != "report":
            try:
                run(["git", "switch", "-c", plan.branch_name], cwd=spec.local_path)
                plan.branch_created = True
            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr.strip()
                if "already exists" in stderr:
                    run(["git", "switch", plan.branch_name], cwd=spec.local_path)
                    plan.branch_created = True
                else:
                    plan.errors.append(stderr or "Unable to create branch in current repo")
        return

    if reset_clone and spec.local_path.exists():
        shutil.rmtree(spec.local_path)

    spec.local_path.parent.mkdir(parents=True, exist_ok=True)
    if mode != "report":
        if not spec.local_path.exists():
            run(["git", "clone", spec.clone_url, str(spec.local_path)], cwd=REPO_ROOT)
            plan.cloned = True
        try:
            run(["git", "switch", "-c", plan.branch_name], cwd=spec.local_path)
            plan.branch_created = True
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip()
            if "already exists" in stderr:
                run(["git", "switch", plan.branch_name], cwd=spec.local_path)
                plan.branch_created = True
            else:
                plan.errors.append(stderr or "Unable to create branch")


def parse_github_blob_path(url: str) -> Optional[tuple[str, str]]:
    parsed = urlparse(url)
    if parsed.netloc != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 5 and parts[2] == "blob":
        owner_repo = "/".join(parts[:2])
        repo_path = "/".join(parts[4:])
        return owner_repo, repo_path
    return None


def locate_target_file(spec: TargetSpec, repo_root: Path) -> tuple[Optional[Path], list[str]]:
    details: list[str] = []
    if spec.explicit_repo_path:
        candidate = repo_root / spec.explicit_repo_path
        if candidate.exists():
            return candidate, details
        details.append(f"Explicit path not found: {candidate}")
        return None, details

    blob = parse_github_blob_path(spec.url)
    if blob:
        _, repo_path = blob
        candidate = repo_root / repo_path
        if candidate.exists():
            return candidate, details

    if spec.locator == "repo-readme":
        for candidate_name in ("README.md", "README.mdx", "readme.md"):
            candidate = repo_root / candidate_name
            if candidate.exists():
                return candidate, details
        details.append("No repo README found")
        return None, details

    if spec.locator == "learn-arm":
        return locate_learn_arm_file(spec, repo_root)

    details.append("No locator matched for target")
    return None, details


def locate_learn_arm_file(spec: TargetSpec, repo_root: Path) -> tuple[Optional[Path], list[str]]:
    parsed = urlparse(spec.url)
    slug_parts = [part for part in parsed.path.strip("/").split("/") if part]
    details: list[str] = []
    if not slug_parts:
        return None, ["Target URL did not contain path segments"]

    candidate_files = list(repo_root.rglob("*.md")) + list(repo_root.rglob("*.mdx"))
    if not candidate_files:
        return None, ["No Markdown files found in arm-learning-paths clone"]

    def score(path: Path) -> int:
        path_text = str(path.relative_to(repo_root)).lower()
        score_value = 0
        for part in slug_parts:
            normalized = part.lower()
            if normalized in path_text:
                score_value += 5
        final_slug = slug_parts[-1].lower()
        if final_slug in path_text:
            score_value += 10
        if "arm-mcp" in path_text:
            score_value += 3
        if "mcp-server" in path_text:
            score_value += 3
        return score_value

    ranked = sorted(candidate_files, key=score, reverse=True)
    best = ranked[0]
    best_score = score(best)
    if best_score <= 0:
        return None, ["Unable to resolve learn.arm.com page to a repo file"]

    details.append(f"Resolved from URL slug using best path score {best_score}")
    return best, details


def replace_first_fenced_block(content: str, language: str, replacement: str) -> str:
    pattern = re.compile(rf"```{language}\n.*?\n```", re.DOTALL)
    new_block = f"```{language}\n{replacement}\n```"
    updated, count = pattern.subn(new_block, content, count=1)
    return updated if count else content


def deterministic_update(
    target: TargetSpec,
    file_path: Path,
    content: str,
    source: SourceConfig,
) -> tuple[Optional[str], str]:
    if file_path == AGENT_INSTALL_GUIDE:
        updated = build_agent_install_content(source)
        if updated != content:
            return updated, "Regenerated install guide from canonical README config"
        return None, "Install guide already matched generated content"

    if file_path.suffix.lower() in {".md", ".mdx"} and "armlimited/arm-mcp" in content:
        updated = content
        if "```json" in updated:
            updated = replace_first_fenced_block(updated, "json", source.generic_json)
        if "```toml" in updated:
            updated = replace_first_fenced_block(updated, "toml", source.generic_toml)
        if updated != content:
            return updated, "Replaced existing Arm MCP fenced config blocks"
        return None, "Found Arm MCP references but no deterministic fenced-block replacement applied"

    return None, "No deterministic updater available for this file"


def update_target(
    target: TargetSpec,
    *,
    repo_plan: Optional[RepoPlan],
    source: SourceConfig,
    use_llm: bool,
    rewriter: OpenAIRewriter,
    mode: str,
) -> TargetResult:
    result = TargetResult(
        spec=target,
        status="pending",
        repo_alias=target.repo_alias,
        repo_path=repo_plan.spec.local_path if repo_plan else None,
        branch_name=repo_plan.branch_name if repo_plan else None,
        pr_title=f"docs: update Arm MCP configuration in {target.name.lower()}",
    )

    if target.mode == "report-only":
        result.status = "source-of-truth"
        result.summary = "Tracked in report as the canonical source; no edit attempted."
        return result

    if target.mode == "manual":
        result.status = "manual"
        result.summary = target.notes or "Manual update required"
        return result

    if not repo_plan:
        result.status = "blocked"
        result.summary = "No repo plan was created for this target"
        return result

    file_path, locate_details = locate_target_file(target, repo_plan.spec.local_path)
    result.details.extend(locate_details)
    result.file_path = file_path
    if not file_path:
        result.status = "manual"
        result.summary = "Could not confidently resolve a file path; review manually."
        return result

    if mode in {"report", "prepare"}:
        result.status = "prepared"
        result.summary = f"Prepared branch and resolved target file {file_path}"
        return result

    content = file_path.read_text(encoding="utf-8")
    updated_content, summary = deterministic_update(target, file_path, content, source)
    if updated_content is None and use_llm and file_path.suffix.lower() in {".md", ".mdx"}:
        try:
            updated_content, summary = rewriter.rewrite_markdown(
                target=target,
                content=content,
                source=source,
            )
        except Exception as exc:  # noqa: BLE001
            result.details.append(f"LLM rewrite failed: {exc}")

    if updated_content is None:
        result.status = "manual"
        result.summary = summary
        return result

    if updated_content == content:
        result.status = "unchanged"
        result.summary = summary
        return result

    file_path.write_text(updated_content, encoding="utf-8")
    result.status = "updated"
    result.summary = summary
    return result


def build_report_path(explicit_path: Optional[Path]) -> Path:
    if explicit_path:
        explicit_path.parent.mkdir(parents=True, exist_ok=True)
        return explicit_path
    DEFAULT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_REPORTS_DIR / f"documentation-update-report-{stamp}.md"


def write_report(
    report_path: Path,
    *,
    source: SourceConfig,
    repo_plans: dict[str, RepoPlan],
    target_results: Iterable[TargetResult],
) -> None:
    results = list(target_results)
    updated = [result for result in results if result.status == "updated"]
    prepared = [result for result in results if result.status == "prepared"]
    unchanged = [result for result in results if result.status == "unchanged"]
    manual = [result for result in results if result.status == "manual"]
    blocked = [result for result in results if result.status == "blocked"]
    source_of_truth = [result for result in results if result.status == "source-of-truth"]

    lines: list[str] = []
    lines.append("# Arm MCP Documentation Update Report")
    lines.append("")
    lines.append(f"Generated: {dt.datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("## Canonical Source")
    lines.append("")
    lines.append(f"- Source file: `{source.source_path}`")
    lines.append(f"- Docker image: `{source.docker_image}`")
    lines.append(f"- Pull command: `{source.docker_pull}`")
    lines.append(f"- Note: {source.performix_note}")
    lines.append("")
    lines.append("### Generic JSON Config")
    lines.append("")
    lines.append("```json")
    lines.append(source.generic_json)
    lines.append("```")
    lines.append("")
    lines.append("### Generic TOML Config")
    lines.append("")
    lines.append("```toml")
    lines.append(source.generic_toml)
    lines.append("```")
    lines.append("")
    lines.append("## Repo Branches")
    lines.append("")
    for plan in repo_plans.values():
        location = str(plan.spec.local_path)
        lines.append(f"- `{plan.spec.alias}`: branch `{plan.branch_name}` at `{location}`")
        if plan.errors:
            for error in plan.errors:
                lines.append(f"  - error: {error}")
    lines.append("")
    lines.append("## Automated Updates Applied")
    lines.append("")
    if updated:
        for result in updated:
            lines.append(f"- `{result.spec.name}`: {result.summary}")
            if result.file_path:
                lines.append(f"  - file: `{result.file_path}`")
            if result.pr_title:
                lines.append(f"  - suggested PR title: {result.pr_title}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Prepared But Not Edited")
    lines.append("")
    if prepared or unchanged:
        for result in [*prepared, *unchanged]:
            lines.append(f"- `{result.spec.name}`: {result.summary}")
            if result.file_path:
                lines.append(f"  - file: `{result.file_path}`")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Manual Follow-Up")
    lines.append("")
    if manual or blocked or source_of_truth:
        for result in [*manual, *blocked, *source_of_truth]:
            lines.append(f"- `{result.spec.name}`: {result.summary}")
            lines.append(f"  - url: {result.spec.url}")
            if result.file_path:
                lines.append(f"  - resolved file: `{result.file_path}`")
            for detail in result.details:
                lines.append(f"  - detail: {detail}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## MCP Registry")
    lines.append("")
    lines.append(f"- Local metadata file: `{MCP_SERVER_JSON}`")
    lines.append("- Publish workflow: use `mcp-publisher` against the current `server.json` after review.")
    lines.append("- Verification command:")
    lines.append("")
    lines.append("```bash")
    lines.append('curl -s "https://registry.modelcontextprotocol.io/v0.1/servers?search=arm/arm-mcp" | jq \'.\'')
    lines.append("```")
    lines.append("")
    lines.append("- Suggested publish reminder:")
    lines.append("")
    lines.append("```bash")
    lines.append("mcp-publisher publish --help")
    lines.append("```")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    source = extract_source_config(args.source_readme)
    report_path = build_report_path(args.report)

    use_llm = not args.no_llm
    rewriter = OpenAIRewriter(args.llm_model)
    if use_llm and not rewriter.available():
        print(
            "LLM editing requested but OPENAI_API_KEY/base URL were not found; "
            "continuing without LLM assistance.",
            file=sys.stderr,
        )
        use_llm = False

    branch_name = args.branch_name or sanitize_branch_name(
        f"docs/arm-mcp-config-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )

    repo_plans: dict[str, RepoPlan] = {}
    for target in TARGETS:
        if not target.repo_alias or target.repo_alias in repo_plans:
            continue
        spec = REPOS[target.repo_alias]
        local_path = spec.local_path
        if spec.alias != "current-repo":
            local_path = args.work_dir / "repos" / spec.alias
            REPOS[target.repo_alias] = RepoSpec(
                alias=spec.alias,
                clone_url=spec.clone_url,
                local_path=local_path,
                branch_prefix=spec.branch_prefix,
                current_repo=spec.current_repo,
            )
            spec = REPOS[target.repo_alias]
        repo_plan = RepoPlan(spec=spec, branch_name=branch_name)
        prepare_repo(repo_plan, mode=args.mode, reset_clone=args.reset_clones)
        repo_plans[target.repo_alias] = repo_plan

    results: list[TargetResult] = []
    for target in TARGETS:
        repo_plan = repo_plans.get(target.repo_alias) if target.repo_alias else None
        result = update_target(
            target,
            repo_plan=repo_plan,
            source=source,
            use_llm=use_llm,
            rewriter=rewriter,
            mode=args.mode,
        )
        results.append(result)

    write_report(report_path, source=source, repo_plans=repo_plans, target_results=results)
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
