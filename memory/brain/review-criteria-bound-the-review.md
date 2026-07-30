---
name: review-criteria-bound-the-review
description: a reviewer finds what the criteria ask for and nothing else, so the criteria are the real review
type: pattern
date: 2026-07-29
confidence: high
reach: global
---

`agy` reviewed a codex change against four stated criteria and returned
`{"pass": true, "issues": []}`. Reading the same diff, I found two quality
nits it never mentioned — a timestamp computed inside a loop, and probes run
sequentially on an interactive command.

The reviewer was not lazy. Both nits sat outside the four criteria, all of
which genuinely held. A clean PASS was the correct answer to the question
asked.

**Why:** it is tempting to read an empty `issues` list as "the code is good".
It means "the code satisfies what you wrote down". Everything you care about
but did not state is invisible to the gate, and a reviewer that volunteered
opinions beyond its brief would be the harder failure mode — that is how you
get manufactured findings.

A sharper case followed the same day. A probe asked for "the agent names, one
per line" with two criteria about writing script. The retry produced three of
the four names — and passed, because completeness lived in the prompt and not
in the criteria. The gate cannot check what the prompt merely implies.

**How to apply:** write the criteria as if they are the only thing that will
be checked, because they are. If a quality bar matters, it is a criterion, not
a hope. And a PASS is evidence about the criteria, not about the change —
read the diff yourself before shipping. Related: [[no-self-review]],
[[agent-routing]].
