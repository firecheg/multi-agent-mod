# Reasoning effort

The harness chooses reasoning effort independently for every invocation. It
does not change the effort of the calling process, retry a failed call,
escalate a retry, or switch models. File count and estimated amount of work do
not affect the choice.

## Input contract

A nested `reasoning` object accepts only these fields (graph nodes and
verifiers may also set `model`):

```json
{
  "effort": "auto",
  "task_kind": "concurrency",
  "dimensions": {
    "scope": 1,
    "uncertainty": 2,
    "reasoning_complexity": 2,
    "risk": 1,
    "verification_complexity": 2
  },
  "cap": "high"
}
```

* `effort`: `auto`, `low`, `medium`, `high`, `xhigh` or `max`.
* `cap`: one of `low` through `max`; lowers the selected level.
* `dimensions`: all five integers from 0 to 2, or `{}` for unknown. A complete
  score maps to low (0-2), medium (3-5), high (6-8) and xhigh (9-10). Without
  dimensions the recommendation is medium.
* `task_kind` sets a floor:
  * low: `mechanical`, `lookup`, `format`, `rename`, `summary` (low when no
    dimensions are given);
  * neutral: `review`;
  * high: `security`, `concurrency`, `schema_migration`, `flaky_bug`,
    `unknown_root_cause`;
  * xhigh: `cross_service_redesign`, `prod_data_migration`, `incident`.

Unknown fields and task kinds are rejected rather than guessed. MCP worker
reasoning cannot override provider, model, budgets or timeouts.

## Result

* `recommended`: the uncapped assessment.
* `selected`: the explicit choice or the recommendation after floors and cap.
* `effective`: the effort parameter planned or sent to the CLI. It is not a
  measurement of internal reasoning; the invocation log's argument vector
  proves what was dispatched.
* `status`: `ok`, `unsupported` (the model does not declare the level) or
  `unknown_model` (no capability data; no effort flag is sent).
* `reasons`: why, including floors and caps.

Automatic routing never selects `max`. An explicit `max` is sent only to a
model whose configured `supported_effort` includes it; the harness cannot know
whether a human authorised it, so callers must enforce that. Which levels a
model supports is configuration, see [providers](providers.md).

## Example

```json
{
  "id": "implement",
  "agent": "implement",
  "prompt": "Implement the agreed parser.",
  "reasoning": {"task_kind": "concurrency", "effort": "auto", "cap": "high"},
  "verify": {
    "by": "reviewer:1",
    "criteria": ["The parser preserves positional prompt data."],
    "reasoning": {"task_kind": "review", "effort": "medium"}
  }
}
```

Every invocation directory records the decision in `reasoning.json` and the
dispatched command in `argv.json`; bounded context workers also write
`result.json`.
Context cache identity includes the router policy version and the complete
decision, so a changed policy or choice cannot reuse an older result.
