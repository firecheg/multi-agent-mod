---
name: cli-structured-output-flags
description: verified schema-enforcement flags for codex, agy and claude, and why the harness does not use them
type: reference
date: 2026-07-29
confidence: high
reach: global
---

Read from each binary's own `--help`, not from documentation:

| CLI | flag | value |
|---|---|---|
| `codex exec` | `--output-schema <FILE>` | path to a JSON Schema file only |
| `agy` | `--json-schema <schema>` | inline string **or** path |
| `claude` | `--json-schema <schema>` | works only with `--print` |

All three also take `--add-dir` and `--output-format`.

**Why the harness ignores them:** enforcement applies to the CLI's *stdout*,
while `run_agent` deliberately takes the answer from `out.md` — see
[[verifier-gate-parses-free-text]]. Using a schema would mean a second
invocation path for verifier nodes. `parse_verdict` already fails closed, so
the payoff is fewer *spurious* rejections, not more safety. Wire it in when
`.mam/` runs actually show verdicts being rejected on formatting.

**The epistemic bit, which is the durable part:** in the run that produced
this note, `agy` claimed all three flags with `[confirmed]` tags and
decorative URLs, several of which did not resolve. The `claude` synthesis node
correctly refused to certify what it could not check and singled out
`claude --json-schema` as "likely mistaken" — and was **wrong**; the flag is
real. Well-calibrated doubt is still doubt, not evidence. A self-asserted
`[confirmed]` and a confident rebuttal were both worth less than one run of
`--help`. Prefer the cheap empirical check over adjudicating between two
models' priors. See [[no-self-review]].
