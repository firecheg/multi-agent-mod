---
name: agent-routing
description: which CLI agent gets which kind of work, and why
type: decision
date: 2026-07-29
confidence: medium
reach: global
---

Work is routed by *capability*, not by preference. Each agent gets the jobs it
is measurably better at, and reviews the jobs it did not do.

| work | agent | why |
|---|---|---|
| spec, architecture, judging, synthesis across conflicting sources | claude | holds long context without drift; makes the final call |
| implementation, refactors, precise diffs, test writing | codex | sandboxed execution, tight diffs, iterates against a failing test |
| live web research, huge-document reading, visual/browser verification | agy | real search grounding, largest context window, multimodal |

**Why:** a single model doing every role reviews its own reasoning, and shared
blind spots survive. Routing by capability plus a hard author≠reviewer rule
turns three correlated agents into three partly-independent ones.

**How to apply:** pick the node's agent from the table above. Never let the
author of an artifact verify or review that artifact — `mam.py` refuses it at
graph-validation time. See [[no-self-review]] and [[loop-vs-graph]].

The third slot is `agy` (Antigravity CLI), not `gemini` — see
[[gemini-cli-retired-for-individuals]].
