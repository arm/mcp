# Agent evaluations

This project tests how a coding agent performs a task with a particular
combination of prompts, MCP servers, tools, and skills. It runs the agent on
the task, starts a task-specific verifier, and saves the evidence needed to
compare configurations. These evaluations complement the MCP protocol and
skill checks in `mcp-local/tests/` and the retrieval questions in
`embedding-generation/eval_questions.json`.

## How an evaluation is organized

A **scenario** is a JSON file with three parts:

| Part | What it defines |
| --- | --- |
| `task` | The shared request, optional repository or local directory inputs, and the command that verifies the agent's result. |
| `configurations` | The agent and model to run, plus any configuration-specific prompt and MCP servers. |
| `run` | Local execution settings, including repetitions, the agent timeout, and optional retries. |

One **trial** is one task input run once under one configuration. The runner
creates the full input × configuration × repetition set. For example, two
codebases, two configurations, and three repetitions produce 12 trials. A
request-only task has one implicit input. Each trial gets a fresh workspace.
If an agent times out, the runner can retry the trial from a new workspace.
Retries do not add to the planned trial count. Trials run sequentially;
configuration order alternates between repetitions so the same configuration
does not always run first.

The runner handles the common lifecycle:

1. Validate the scenario and prepare snapshots of the input and MCP server
   sources. Run each configured MCP server build command once.
2. For each trial, create a fresh workspace and assemble the agent input:
   configuration prompt (if set), then the shared task request.
3. Select the adapter for `configurations[].agent.kind`. The adapter installs
   the servers' bundled skills, connects MCP servers with all their tools
   available, starts the agent, and records its trace, reported token use, and
   elapsed time.
4. Save the resulting workspace and a Git patch for Git inputs. If the agent
   completed or timed out, run the task's verifier against that workspace.
   Retry only a timed-out agent, up to the configured attempt limit.
5. Write one result per trial and a comparison report for the full run.

The shared task request states the goal that every configuration receives.
A configuration prompt can add instructions for a specific setup, such as how
to use an MCP server. This lets a scenario compare different prompts or MCP
capabilities while keeping the task and verifier the same.

## Files and responsibilities

```text
agent_evals/
  README.md                 This guide
  scenario.schema.json      Allowed scenario fields (JSON Schema Draft 2020-12)
  scenario.py               Scenario loading, validation, and trial planning
  runner.py                 Source setup, trial workspaces, verifier, artifacts
  codex_adapter.py          Codex CLI launch, MCP/skill setup, trace and usage
  report.py                 Result classification and comparison reports
  preflight.py              Local prerequisite and prepared-skill checks
  cli.py                    preflight, run, and report commands
  scenarios/<name>/         A scenario and its task-specific files
  tests/                    Framework tests
```

The schema is the reference for available fields. `scenario.py` uses
`jsonschema` to validate the document, then checks local paths and duplicate
identifiers. The runner's agent adapter registry currently contains Codex.
Another agent can be supported by registering an adapter that returns the
same agent result and installed skill list; the runner and verifier remain
shared.

## Define a scenario

Create a folder under `scenarios/` with a `scenario.json` and the files it
references. The [MEGAHIT scenario](scenarios/megahit-arm64/scenario.json) is
one complete example. Its migration task is only an example of the scenario
format; a task could instead ask an agent to answer a technical question,
review code, or exercise a new MCP tool or skill.

### Task and inputs

`task.request` holds a short shared request, or `task.request_file` points to
a UTF-8 file in the scenario folder. `task.inputs` is optional. When
present, it contains one or more named repository or directory inputs:

- `kind: "git"` supplies a repository and a full commit SHA in `revision`.
  The runner starts each trial from that commit in a fresh checkout. Branch
  and tag names are not accepted because they can change between runs.
- `kind: "local"` supplies a directory, which the runner copies for each
  trial. Git is not required.
Omit `task.inputs` for a request-only task, such as one knowledge question.
The runner then creates one empty workspace per configuration and repetition.

`task.verifier.command` is an argument list such as
`["python3", "verify.py"]`. The first element is the executable; later
elements are its literal arguments. The verifier decides what success means
for this task. It can run build or functional checks, inspect a produced
artifact, call a judge, or calculate an application-specific measure.
Scenario loading checks that a relative Python verifier script exists.

### Configurations

Every configuration has an `id` and an `agent` with `kind` and `model`.
Optional `agent.reasoning_effort` sets the model's reasoning level. The Codex
adapter passes it as `model_reasoning_effort`; when omitted, Codex uses its
own default. Supported levels depend on the selected model. The MEGAHIT
example sets both configurations to `medium` so they use the same level.
Optional `prompt` points to a file relative to the scenario JSON; it can
refer to a file above the scenario folder. Omitting `prompt` sends only the
shared request. Omitting `mcp_servers` gives
that configuration no scenario-provided MCP servers or skills.

The framework is intended to support three ways to supply an MCP server:

- **Local source and build:** Snapshot a local checkout, build it, and launch
  the result.
- **Git source and build:** Fetch a specified Git revision, build it locally,
  and launch the result. The MEGAHIT example uses this mode to keep its MCP
  server and bundled skills on a revision compatible with its prompt.
- **Published version:** Specify a server version and run that release
  directly, without a local build. This is planned; the runner does not yet
  resolve or pull a release from `version`.

For source builds, an entry in `mcp_servers` can define `source`, `build`,
and `launch`. The runner snapshots each source once per run. The Codex adapter
exposes all tools registered by each server. Set `skills_root` to the directory
containing that server's bundled skill folders, relative to its source root
(for example, `arm_mcp_definitions/skills`). The adapter installs every
`*/SKILL.md` skill under that directory in the trial's isolated profile.
Omit `skills_root` when there are no bundled skills to install. The intended
version-based path must also obtain the matching skills. Currently, `version`
is recorded in results but does not select the server that runs; that
selection will be added when the published-version path is implemented.
Scenario loading checks that a local source's `skills_root` directory exists.
For Git sources, this check runs after the source is fetched.

The launch command starts a local MCP process that speaks over stdin and
stdout. A configuration can name more than one MCP server. The current Codex
adapter uses a temporary Codex home so the trial gets its configured servers
and their bundled skills while retaining the developer's model provider and
CLI login.

### Run settings

`run.execution_target` is currently `"local"`. `repetitions` controls how
many times each input and configuration is tried, and
`agent_timeout_seconds` limits each agent attempt. Optional `max_attempts`
sets the total number of attempts per trial; it defaults to 1. Only an agent
timeout starts another attempt. The MEGAHIT scenario allows three attempts.
The optional `docker_access` setting lets the Codex agent use the local Docker
daemon when the task or bundled skills require Docker commands.

## Run a scenario locally

From the repository root, use Python 3.10+ and install the evaluation package:

```sh
python -m pip install -e agent_evals
```

This installs the `arm-agent-evals` command. Its three subcommands have
different purposes:

| Command | What it does |
| --- | --- |
| `preflight SCENARIO` | Validates the scenario, checks the verifier, Codex executable, skills in local MCP sources, and Docker daemon when Docker is explicitly used, then summarizes the planned run. It does not fetch or build sources or run trials. |
| `run SCENARIO --output DIR` | Repeats preflight, prepares sources and servers, checks skills in prepared sources, runs each agent and verifier, and writes trial artifacts and a comparison report. |
| `report DIR` | Reads results saved by an earlier `run` and regenerates the comparison report. It does not rerun agents or verifiers. |

Start by checking the scenario and planned trial count:

```sh
arm-agent-evals preflight agent_evals/scenarios/megahit-arm64/scenario.json
```

The summary shows each input's repository or local path and each configuration ID.
It also lists the checks that passed. Use `--json` for the same information in a
machine-readable form.

The MEGAHIT example requires Codex CLI authentication and a working Docker
daemon. Its MCP source is pinned to a revision before PR #259 while its
migration prompt uses the original scan skill. To try one repetition of each
configuration:

```sh
arm-agent-evals run agent_evals/scenarios/megahit-arm64/scenario.json \
  --output /tmp/agent-eval-example --repetitions 1
```

Omit `--repetitions` to use the scenario's configured count. The output path
must be new and outside any local input or MCP server source. During a run,
the CLI prints setup, agent, and verifier progress to stderr; the final JSON
summary goes to stdout. Preflight does not fetch Git sources or run build
commands; `run` checks those and prepared skill files before the first agent
trial.
`run` writes a report automatically; use `report` only when you need to
regenerate it from the saved results.

## Verify results and read the report

The runner starts the verifier from the scenario folder after an agent
completes or times out. It passes these paths as environment variables:

| Variable | Path provided |
| --- | --- |
| `AGENT_EVAL_WORKSPACE` | The agent's trial workspace. |
| `AGENT_EVAL_TRIAL_DIR` | The directory for this trial's artifacts. |
| `AGENT_EVAL_SCENARIO_DIR` | The scenario folder. |
| `AGENT_EVAL_VERIFIER_RESULT` | Where the verifier may write a JSON result. |
| `AGENT_EVAL_INPUT_SOURCE` | The clean input snapshot, for Git or local inputs. |

Exit code 0 means pass, 1 means task failure, and 2 or higher means verifier
error. The verifier may write a JSON object with `success` and task-specific
measures to `AGENT_EVAL_VERIFIER_RESULT`. A verifier can use common helpers,
but its success checks and optional measures belong to its use case.

The output directory contains `sources/`, `setup-logs/`, one directory under
`trials/` per trial, `run.json`, `results.jsonl`, `sources.json`, `summary.json`,
`report.json`, and `report.md`. A trial directory holds the assembled prompt
and one merged `result.json`. When retries are enabled, its `attempts/001`,
`attempts/002`, and later directories hold separate workspaces, agent traces,
stderr, verifier output, and Git patches. Without retries, these artifacts
remain directly in the trial directory. A patch includes tracked changes and
untracked files that Git does not ignore, so generated files may appear in it.

For reproduction, `run.json` records the host OS, architecture, Python version,
repetition count, and observed agent CLI versions (including `codex --version`).
The saved `scenario.json` contains the agent configuration; each trial's
`result.json` records its outcome.
`sources.json` records resolved Git commits and source snapshots. When an MCP
server is built as a tagged Docker image and launched from that tag, it also
records the image reference, image ID, OS, architecture, and available registry
digests. An unavailable CLI version or non-Docker image is recorded as `null`.

The report links to the merged result, each attempt's result, and the final
attempt's artifacts. Earlier attempt artifacts remain in their attempt
directories. The report shows one outcome per trial. Its end-to-end success
rate requires a completed agent and a passing verifier on the terminating
attempt. The comparison's "Not scored" count combines planned trials with no
saved result and saved trials that could not be scored. The saved `report.json`
keeps those counts separate. The report also counts every timed-out attempt,
including timeouts followed by a successful retry. The verifier pass rate uses
the terminating attempt, including a timed-out agent; verifier errors are
excluded. Mean agent elapsed time and total tokens use end-to-end successful
trials only. A retry contributes the completed attempt's measures without
adding earlier timeout durations or tokens. Optional mean application
execution time uses verifier-passed terminating attempts. Each mean uses
trials with an available measure and shows its sample count. Token use comes
from the agent's reported usage; missing usage is unavailable, not zero.
Application execution time is present only if the task's verifier measures it.
For each Codex trial, the report also counts distinct attempts to call an MCP
`knowledge_base_search` tool and lists installed skills whose `SKILL.md` files
appear in successful read commands in the agent trace. A skill read does not
prove the agent followed its instructions. A missing activity summary is shown
as unavailable; an empty skill list appears as `none` in the report.
With retries, these report fields describe the terminating attempt; earlier
attempts retain their own activity in their saved results.

Regenerate a report from saved results, including an interrupted run, with:

```sh
arm-agent-evals report /tmp/agent-eval-example
```

## Extending the framework

To add a use case, define its request and inputs in a new scenario, write a
verifier for its expected outcome, and choose the configurations to compare.
Use `preflight` to check the scenario before running a small trial.
To add another agent, implement an adapter for its launch, MCP and skill
setup, trace, and usage format, then register its `agent.kind` in
`runner.py`.

Framework tests can be run with:

```sh
python -m unittest discover -s agent_evals/tests
```

These are local, trusted evaluations. Source build commands and verifiers
execute on the developer machine. With `docker_access: true`, an agent can
use the host Docker daemon, including containers with host mounts; the
Codex workspace-write setting alone cannot confine those Docker writes to
the trial workspace.
