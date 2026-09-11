# Reasoning effort routing

The harness chooses effort independently for every new invocation. It does not
change the effort of the current host process, retry a failed call, escalate a
retry, or switch models. File count and estimated work amount do not affect the
choice.

## Input contract

The nested `reasoning` object accepts only these fields:

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

`effort` is `auto`, `low`, `medium`, `high`, `xhigh`, or `max`. `cap` is one
of the five explicit levels from `low` through `max`. Each dimension is an
integer from 0 through 2. A non-empty `dimensions` object must contain all five
fields; `{}` means unknown. Unknown dimensions default to `medium`. Complete
scores map to low (0–2), medium (3–5), high (6–8), and xhigh (9–10).

Known task kinds are:

- low: `mechanical`, `lookup`, `format`, `rename`, `summary`;
- neutral: `review`;
- high floor: `security`, `concurrency`, `schema_migration`, `flaky_bug`,
  `unknown_root_cause`;
- xhigh floor: `cross_service_redesign`, `prod_data_migration`, `incident`.

Omit `task_kind` for an unclassified task; its default is `medium` when no
dimensions are supplied. Unknown strings are rejected instead of being guessed.
Graph node and verifier `reasoning` objects may additionally contain `model`.
MCP worker reasoning cannot override provider, model, input/output budgets, or
timeouts.

The result keeps the uncapped complexity choice in `recommended`. `selected`
is the explicit choice or automatic recommendation after task floors and cap.
`effective` is the effort parameter planned for or sent to the CLI; it is not a
measurement of internal reasoning. In an invocation log, `argv` proves that the
parameter was dispatched. A standalone `reasoning_assess` result is only a plan.

Automatic routing never selects `max`. An explicit `max` is sent only for a
model whose capability table includes it. The runtime cannot establish whether
a human authorized `max`; callers must enforce that authorization before they
set the field. A cap can lower `selected` and `effective`, while `recommended`
continues to show the uncapped assessment and `reasons` records the cap.

## Supported models

| Provider | Model selector | Effort support |
|---|---|---|
| Codex | `gpt-5.6-luna`, `gpt-6-astra` | low, medium, high, xhigh, max |
| Codex | `gpt-5.5` | low, medium, high, xhigh |
| Claude | `sonnet`, `opus`, `claude-sonnet-4-6`, `claude-opus-4-6` | low, medium, high, max |
| Claude | `claude-sonnet-5`, `claude-opus-5`, `claude-opus-4-7`, `claude-opus-4-8` | low, medium, high, xhigh, max |
| Claude | `haiku`, `claude-haiku-4-5` | no effort parameter |

Version-suffixed forms of the listed Claude IDs use the same capability entry.
Unknown providers and models receive no effort parameter and return
`status: "unknown_model"`. A generic Codex agent without an explicit model is
therefore unknown; pass `--model` to `mam ask` or `mam review`, or set `model`
inside graph reasoning when reliable capability metadata is required. The
harness does not guess a generic Claude model.

## PowerShell CLI examples

Writing the dimensions to JSON avoids shell quoting mistakes:

```powershell
New-Item -ItemType Directory -Force -Path .\.mam | Out-Null
$dimensions = @'
{
  "scope": 1,
  "uncertainty": 1,
  "reasoning_complexity": 2,
  "risk": 1,
  "verification_complexity": 1
}
'@
[IO.File]::WriteAllText((Join-Path $PWD '.mam/reasoning.json'), $dimensions, [Text.UTF8Encoding]::new($false))

python -X utf8 "$env:MAM_HOME/mam.py" ask codex-luna "Implement the bounded parser" `
  --reasoning .\.mam\reasoning.json --task-kind concurrency `
  --model gpt-5.6-luna
```

`mam ask` does not expose `--cap` as a separate flag; put the cap in a graph or
MCP reasoning object. For one-shot CLI calls, the supported command is:

```powershell
python -X utf8 "$env:MAM_HOME/mam.py" review codex --by claude --path .\execution\reasoning_router.py `
  --task "Review the parser contract" --criteria "All invalid inputs fail before invocation" `
  --reasoning .\.mam\reasoning.json --task-kind review --model sonnet
```

## Graph and MCP examples

Author and verifier choices are separate:

```json
{
  "id": "implement",
  "agent": "codex-luna",
  "prompt": "Implement the agreed parser.",
  "reasoning": {
    "task_kind": "concurrency",
    "effort": "auto",
    "cap": "high",
    "model": "gpt-5.6-luna"
  },
  "verify": {
    "by": "claude",
    "criteria": ["The parser preserves positional prompt data."],
    "reasoning": {
      "task_kind": "review",
      "effort": "medium",
      "model": "sonnet"
    }
  }
}
```

`research_batch` keeps its fixed model mapping (`summary` to Haiku and `code`
to Luna). Its reasoning settings select the actual CLI effort parameter where
the model supports it; they do not change the model or worker budgets:

```json
{
  "project": "C:\\Programming\\multi-agent-mod",
  "tasks": [
    {
      "kind": "code",
      "question": "Trace the reasoning config into the worker invocation.",
      "paths": ["execution/context_budget.py", "execution/worker_cli.py"],
      "reasoning": {
        "task_kind": "concurrency",
        "dimensions": {
          "scope": 1,
          "uncertainty": 1,
          "reasoning_complexity": 2,
          "risk": 1,
          "verification_complexity": 1
        },
        "cap": "high"
      }
    }
  ]
}
```

MAM writes the decision and actual argv to each invocation `meta.json`.
Limited workers write `reasoning.json`, `argv.json`, and the decision in
`result.json`. Context cache identity includes the router policy version and the
complete decision, so a changed policy or choice cannot reuse an older result.

Existing clients must reconnect the MCP server to load the new tool schemas.
The common instructions require a fresh effort assessment for each child; the
router maps the supplied kind/dimensions without a paid classifier call.
