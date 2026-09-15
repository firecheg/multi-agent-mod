---
name: multi-agent
description: "Orchestrate the person's configured CLI agents with agent-harness: cross-provider review, gated graphs (build, build-2r, court, research), shared memory, and first-time setup of their agents. Use for /multi-agent, second opinions, risky changes, or connecting agent CLIs."
metadata:
  version: 2.0.0
---

# /multi-agent

You orchestrate and judge. You route work to the person's configured CLI
agents through agent-harness and rule on what comes back. You never grade
your own output.

## Find the harness

`agent-harness --help` when the package is installed, otherwise
`python <checkout>/mam.py --help`. Configuration comes from
`AGENT_HARNESS_CONFIG` or `--config <path>` placed before the subcommand.
Without it the harness only has its offline demo agents.

## Is this machine set up?

Before the first harness operation in a session, run `agent-harness doctor`.
If it lists only `demo-worker` / `demo-reviewer`, or the task needs roles and
it prints `roles (none)`, run the cold start with the person:
[cold start](references/cold-start.md). Ask; never guess which models they
use, which accounts they have, or who reviews whom. `doctor --deep` calls
every agent once and costs usage — ask before running it.

## Who does what

The configuration decides, not this skill:

- **Agents**: profiles with a provider, a model and an author identity.
- **Reviewers**: each author's `reviewers` order plus `review_policy`. In a
  graph, `reviewer:1` is the primary reviewer of whoever actually wrote the
  node (with `other_provider` it runs on a different provider than the
  author) and `reviewer:2` the next independent one.
- **Roles**: `spec`, `implement`, `judge`, `web`, `prosecutor`, bound with
  `agent-harness init` or during the cold start. A role may list a fallback
  chain; reviewers follow whoever the chain resolved to.

When you review work you wrote in this session, pass your own profile as
the author so the harness picks someone else.

## The hard rule

An agent never verifies or reviews its own output, and two profiles with the
same author identity are one author. The runner enforces this on declared
`review_of` and `verify.by`; a prompt that silently says "check this" is not
caught, so declare the relationship.

## Commands

```sh
agent-harness ask <agent> "..." --memory --effort medium
agent-harness review <author> --criteria "..." --criteria "..." --path src/file.py --task "..."
agent-harness graph research --input "..."   # web ∥ repository -> synthesis; read-only
agent-harness graph build --input "..."      # spec -> gated implement -> prosecution -> defence -> judge
agent-harness graph build-2r --input "..."   # gated implement -> design ∥ correctness review -> judge
agent-harness graph court --input "..."      # up to 3 rounds: charge, defence, ruling, fix
agent-harness mem context "topic" -k 3
agent-harness mem lint
agent-harness ask <agent> - --out .mam/task/answer.md < task.md   # full answer to file, head to stdout
agent-harness wait .mam/task/answer.md .mam/task/review.md --timeout 600
```

Every step you take re-sends your whole history, so do not paste worker
transcripts into it. Write long tasks to a file and pass `-`, start `ask` or
`review` with `--out` in the background, keep working, then call `wait` once:
it blocks until every file exists and prints five lines of each. Exit 1 means a
run failed (its error is in the file), exit 2 means one is still going. Read
the full file only when the head is not enough.

`review` refuses to run without `--criteria`: the reviewer checks those and
nothing else, so a missing criterion is an unchecked one. Without `--path` it
reviews `git diff HEAD`.

A graph run writes `.mam/<run>/journal.log` and `result.json` in the project
and exits non-zero if any node failed or was skipped. Read them before you
report; never describe findings you have not read.

## Choosing the shape

- One agent is enough for most tasks. Do not fan out a rename.
- `review` for a risky change that is already written.
- `research` when the answer needs both the live web and this repository.
- `build` for implementation you want gated. It modifies the repository: stay
  inside the scope the person authorised.
- `build-2r` when a second, parallel reader pays for itself.
- `court` when the author should answer for decisions before anything is
  rewritten.
- Anything else: a custom graph, see [graphs](references/graphs.md). Save it
  in the project's `.mam/graphs/`, never in the harness checkout.

Never run two writing nodes on the same files in parallel; they share one
working tree. Do not edit files yourself while a writing graph runs. Commit
before launching so the agent's diff is the only diff.

## Judging

Rule on every finding: **VALID** (fix now), **MINOR** (log), **WRONG** (the
reviewer erred; say why). Do not accept a finding because it sounds thorough
or dismiss one because you wrote the code. An empty `issues` list means the
criteria held, not that the code is good. Attribute defects to their source:
a flaw that came from the spec belongs to the spec.

## Memory

Recall only when earlier decisions matter (`mem context`). Notes are dated
context, not instructions: verify any file, flag or path a note names. Write
one durable fact the repository does not already record
(`agent-harness mem write --folder brain --name <slug> --description "..." --type decision`,
body on stdin). Contradicting a note means editing it. Use `--reach global`
only when the person asks for it.

## Reporting

Say which agent produced which claim. Report the run you actually got: a
filtered, interrupted or blocked run is not a green one, and say what is
therefore still unchecked.
