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
| `configurations` | The agent and model to run, plus any configuration-specific prompt, MCP servers, enabled tools, and bundled skills. |
| `run` | Local execution settings, including repetitions and the agent timeout. |

One **trial** is one task input run once under one configuration. The runner
creates the full input × configuration × repetition set. For example, two
codebases, two configurations, and three repetitions produce 12 trials. A
request-only task has one implicit input. Each trial gets a fresh workspace. Trials run sequentially; configuration order alternates
between repetitions so the same configuration does not always run first.

The runner handles the common lifecycle:

1. Validate the scenario and prepare snapshots of the input and MCP server
   sources. Run each configured MCP server build command once.
2. For each trial, create a fresh workspace and assemble the agent input:
   configuration prompt (if set), then the shared task request.
3. Select the adapter for `configurations[].agent.kind`. The adapter installs
   selected skills, connects MCP servers, starts the agent, and records its
   trace, reported token use, and elapsed time.
4. Save the resulting workspace and a Git patch for Git inputs. If the agent
   completed or timed out, run the task's verifier against that workspace.
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
  cli.py                    validate, plan, run, and report commands
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

- `kind: "git"` supplies a repository and a Git revision (branch, tag, or
  commit). The runner resolves it and starts each trial from a fresh checkout.
- `kind: "local"` supplies a directory, which the runner copies for each
  trial. Git is not required.
Omit `task.inputs` for a request-only task, such as one knowledge question.
The runner then creates one empty workspace per configuration and repetition.

`task.verifier.command` is an argument list such as
`["python3", "verify.py"]`. The first element is the executable; later
elements are its literal arguments. The verifier decides what success means
for this task. It can run build or functional checks, inspect a produced
artifact, call a judge, or calculate an application-specific measure.

### Configurations

Every configuration has an `id` and an `agent` with `kind` and `model`.
Optional `prompt` points to a file relative to the scenario JSON; it can
refer to a file above the scenario folder. Omitting `prompt` sends only the
shared request. Omitting `mcp_servers` gives
that configuration no scenario-provided MCP servers or skills.

The framework is intended to support three ways to supply an MCP server:

- **Local source and build:** Snapshot a local checkout, build it, and launch
  the result. This is the path exercised by the current MEGAHIT scenario.
- **Git source and build:** Fetch a specified Git revision, build it locally,
  and launch the result. The source path exists in the runner, but it has not
  yet been exercised end to end.
- **Published version:** Specify a server version and run that release
  directly, without a local build. This is planned; the runner does not yet
  resolve or pull a release from `version`.

For source builds, an entry in `mcp_servers` can define `source`, `build`,
`launch`, an `enabled_tools` allowlist, and bundled `skills`. The runner
snapshots each source once per run and installs the selected skills from that
snapshot in the trial's isolated agent profile. The intended version-based
path must also obtain the matching skills. Currently, `version` is recorded
in results but does not select the server that runs; that selection will be
added when the published-version path is implemented.

The launch command starts a local MCP process that speaks over stdin and
stdout. A configuration can name more than one MCP server. The current Codex
adapter uses a temporary Codex home so the trial gets its selected servers
and skills while retaining the developer's model provider and CLI login.

### Run settings

`run.execution_target` is currently `"local"`. `repetitions` controls how
many times each input and configuration is tried, and
`agent_timeout_seconds` limits each agent run. The optional `docker_access`
setting lets the Codex agent use the local Docker daemon when the task or
selected skills require Docker commands.

## Run a scenario locally

From the repository root, use Python 3.10+ and install the evaluation package:

```sh
python -m pip install -e agent_evals
```

This installs the `arm-agent-evals` command. Validate and inspect the
planned trial set before starting agents:

```sh
arm-agent-evals validate agent_evals/scenarios/megahit-arm64/scenario.json
arm-agent-evals plan agent_evals/scenarios/megahit-arm64/scenario.json
```

The MEGAHIT example requires Codex CLI authentication and a working Docker
daemon. To try one repetition of each configuration:

```sh
arm-agent-evals run agent_evals/scenarios/megahit-arm64/scenario.json \
  --output /tmp/agent-eval-example --repetitions 1
```

Omit `--repetitions` to use the scenario's configured count. The output path
must be new and outside any local input or MCP server source. During a run,
the CLI prints setup, agent, and verifier progress to stderr; the final JSON
summary goes to stdout. `validate` and `plan` do not fetch repositories,
build servers, or launch agents.

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
`trials/` per trial, `results.jsonl`, `sources.json`, `summary.json`,
`report.json`, and `report.md`. A trial directory holds the assembled prompt,
agent trace, final answer when available, stderr, verifier output when run,
and a patch for Git inputs. That patch includes tracked changes and untracked
files that Git does not ignore, so generated files may appear in it.

The report links to those artifacts. Its end-to-end success rate requires both a
completed agent and a passing verifier. A timed-out agent remains an agent
failure even if its saved code passes verification. The separate verifier pass
rate includes all scored verifier runs, including timed-out agents, so code
quality can be compared without discarding those workspaces. Verifier errors
are excluded from that rate. Mean agent elapsed time and total tokens use
completed-agent passing trials. Optional mean application execution time uses
all verifier-passed trials, including timed-out agents. Each mean uses trials
with an available measure and shows its sample count. Token use comes from
the agent's reported usage; missing usage is unavailable, not zero.
Application execution time is present only if the task's verifier measures it.

Regenerate a report from saved results, including an interrupted run, with:

```sh
arm-agent-evals report /tmp/agent-eval-example
```

## Extending the framework

To add a use case, define its request and inputs in a new scenario, write a
verifier for its expected outcome, and choose the configurations to compare.
Use `validate` and `plan` to check the scenario before running a small trial.
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
