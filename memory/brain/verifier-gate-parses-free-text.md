---
name: verifier-gate-parses-free-text
description: the verifier gate parses free-form JSON-in-prose, no CLI ever gets a native schema-enforcement flag
type: gotcha
date: 2026-07-29
confidence: high
reach: repo
project: multi-agent-mod
---

Nothing in `agents.json` passes `--output-schema`, `--json-schema`, or
`--output-format` to any agent. The verifier gate works entirely by asking in
prose (`VERIFY_TMPL` in `mam.py`) for `{"pass": bool, "issues": [str]}`, then
`parse_verdict` extracts it from free text — `raw_decode` from each `{`,
taking the first object that carries a `pass` field — and manually checks
`type(ok) is bool` plus `list[str]` for issues, failing closed on any parse
or type error. (This note originally said "a greedy regex `\{.*\}`", which
was accurate when written and is why the parser got replaced: that pattern
ran to the last brace in the message.)

**Why:** [[gemini-cli-retired-for-individuals]] documents that `agy` supports
`--json-schema` and `--output-format json|stream-json`, which reads like the
harness should be using native enforcement. It isn't — that flag name lives
only in a memory note, not in the shipped `agy` argv. A capability being
documented as available is not evidence it's wired up; the two need checking
separately.

**How to apply:** if the verifier gate ever starts failing in a way that
looks like a formatting problem, the fix is in `VERIFY_TMPL`'s wording or
`parse_verdict`'s parsing/type-checks, not a CLI flag — no flag is wired, so
there is none to tune. If someone wants real schema enforcement, that's new work
(wiring `--json-schema`/`--output-schema` into `agents.json` per-agent args),
not a config toggle. See [[no-self-review]] for the other half of this gate's
design.
