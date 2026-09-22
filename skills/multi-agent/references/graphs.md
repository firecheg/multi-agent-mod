# Writing a custom graph

A graph is JSON: `{"name": "...", "concurrency": N, "nodes": [...]}`. Save it
in the project's `.mam/graphs/<name>.json` and run
`agent-harness graph .mam/graphs/<name>.json --input "..."`.

## Node fields

| Field | Meaning |
|---|---|
| `id` | Unique name; `{id}` in later prompts inserts this node's output |
| `agent` | A configured profile, a role (`spec`, `implement`, ...), or `reviewer:N` |
| `role` | Optional role prompt bundle; overrides the agent profile's role |
| `needs` | Nodes this one waits for; independent nodes run in parallel |
| `prompt` | Text; `{input}` is the CLI input, `--set key=value` adds more keys |
| `verify` | `{"by": ..., "max_rounds": N, "criteria": [...]}` — a different agent gates each attempt; criteria are required |
| `review_of` | Declares the node as a review of another node; the same author is rejected |
| `remember` | Ask the agent to report one durable memory note |
| `memory` | `false` to skip injecting vault context |
| `reasoning` | Effort contract, see the harness `docs/reasoning.md` |
| `sandbox` | Provider-specific permission mode; only for providers that declare one |

`reviewer:N` needs `review_of` (or sits in `verify.by`, meaning the node's own
author) and resolves after roles bind. A placeholder that is neither an input
nor a declared ancestor fails validation before any agent runs.

## Loops

- **Inside one step** — `verify`: the author retries with the verifier's
  issues until it passes or `max_rounds` runs out (a failure, not a pass).
- **Several parties arguing** — a `rounds` block replaces `agent` and
  `prompt`: `{"id": "trial", "needs": [...], "rounds": {"max": 3, "until":
  "<decider id>", "nodes": [...]}}`. Sub-nodes run in order each round and get
  `{round}` and `{previous}` (the last round's transcript). The block ends
  when the decider's answer ends in `{"pass": true, "issues": []}`. Blocks do
  not nest.
- **Roles that must differ** without a review edge: top-level
  `"distinct": [["spec", "implement", "prosecutor"]]`.

## Output contract

A worker's free text is what `{id}` hands on, so a node that changes files or
runs checks ends its prompt with this tail and lists it in `verify.criteria`:

```text
changed_files: <path per line, or none>
checks: <command> -> <pass|fail: first error line>, or none run
assumptions: <what was not verified>
```

A verifier fails an attempt whose tail is missing or claims a check it did not
show. Read-only and debate nodes skip the tail.

Coordinator-bound nodes pause with a prompt file in the run directory. Answer
in-session, then submit `agent-harness verdict <run> <file|->` and rerun the
graph to continue. Set `--initiator <alias>` explicitly or configure
`initiator_detection`; `--no-in-session` forces legacy CLI spawning.

Improving a result within a step is a loop (`verify`); handing work between
components is a graph (`needs`).
