# Documentation Updater

`documentation_updater.py` prepares documentation updates whenever the Arm MCP server configuration changes.

It treats the local [README.md](/Users/joeste01/git/mcp-clean/README.md) as the source of truth for MCP client configuration, then:

- clones or reuses the repos that back the docs we can edit,
- creates a working branch per repo,
- attempts automated updates for targets it can resolve confidently,
- marks manual-only targets in the report,
- writes a Markdown report listing the PRs that should be created.

## Scope

The script is preloaded with the targets requested for the current Arm MCP config refresh:

- local Arm MCP docs in this repo
- Arm Learning Paths and install guides in `ArmDeveloperEcosystem/arm-learning-paths`
- GitHub-hosted downstream docs such as `awesome-copilot`
- third-party/manual targets such as Docker Hub pages, `developer.arm.com`, `dev.to`, and Docker blog posts
- MCP Registry publishing/reporting steps using `mcp-local/server.json`

## Usage

From the repo root:

```bash
python3 documentation-updater/documentation_updater.py
```

Useful flags:

```bash
python3 documentation-updater/documentation_updater.py --mode report
python3 documentation-updater/documentation_updater.py --mode prepare
python3 documentation-updater/documentation_updater.py --mode update --no-llm
python3 documentation-updater/documentation_updater.py --report documentation-updater/reports/arm-mcp-config-refresh.md
```

Modes:

- `report`: analyze targets and write the report only
- `prepare`: clone repos, create branches, and write the report
- `update`: clone repos, create branches, attempt file edits, and write the report

## LLM-Assisted Editing

LLM usage is optional. When enabled, the script uses `gpt-5.4` through the OpenAI Responses API to rewrite target Markdown files with minimal changes.

Required environment variables:

```bash
export OPENAI_API_KEY=...
export OPENAI_API_PROXY_URL=...
```

The script accepts any of these proxy/base-url env vars:

- `OPENAI_API_PROXY_URL`
- `OPENAI_API_PROXY`
- `DOC_UPDATER_OPENAI_BASE_URL`
- `OPENAI_BASE_URL`
- `OPENAI_API_BASE`

If the configured URL ends with `/models`, the script strips that suffix and sends requests to `/responses`.

## Output

By default the script writes:

- repo clones under `documentation-updater/workdir/repos/`
- reports under `documentation-updater/reports/`

The report includes:

- the extracted canonical config snippets
- repo branches prepared for each automatable target
- files updated automatically
- files that still need manual review
- manual-only targets
- MCP Registry publish/check commands, including the registry query requested for `arm/arm-mcp`

## Current Assumptions

- the canonical configuration source is the local [README.md](/Users/joeste01/git/mcp-clean/README.md)
- the MCP Registry metadata source is [mcp-local/server.json](/Users/joeste01/git/mcp-clean/mcp-local/server.json)
- Learn site pages are edited via `ArmDeveloperEcosystem/arm-learning-paths`
- Docker Hub, `developer.arm.com`, `dev.to`, and Docker blog pages are report/manual targets unless a backed-by-git path is added later
- the script prepares branches and PR recommendations; it does not push branches or open PRs remotely

## Likely Next Extension

If you want end-to-end automation later, the next step is adding optional `gh`/API integration to push branches and open draft PRs after review.
