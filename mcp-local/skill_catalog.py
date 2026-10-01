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

"""Publish the bundled Agent Skills as resources and user-selectable prompts."""

from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider
import yaml


SKILLS_ROOT = Path(__file__).resolve().parent / "skills"


def register_skills(mcp: FastMCP) -> None:
    # Only publish shipped skills, never instructions from the mounted workspace.
    mcp.add_provider(SkillsDirectoryProvider(roots=SKILLS_ROOT))
    for path in sorted(SKILLS_ROOT.glob("*/SKILL.md")):
        content = path.read_text(encoding="utf-8")
        metadata = yaml.safe_load(content.split("---", 2)[1])
        # Capture each document without exposing a file/path parameter over MCP.
        def make_prompt(document: str):
            def skill_prompt() -> str:
                return document

            return skill_prompt

        mcp.prompt(name=metadata["name"], description=metadata["description"])(
            make_prompt(content)
        )
