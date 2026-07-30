---
name: no-self-review
description: an agent may never verify or review its own output
type: decision
date: 2026-07-29
confidence: high
reach: global
---

Author != reviewer. Enforced statically in `validate()` (a `review_of` node
whose agent matches the author's agent raises) and at runtime in `run_node()`
(a `verify.by` equal to the node's agent raises).

**Why:** a model asked to check its own work grades its own reasoning chain,
not the artifact. It reliably confirms whatever it already concluded. The
failure is silent — you get a confident PASS on broken code.

**How to apply:** every gate names a different agent. When no other agent is
installed, `pick_reviewer` raises rather than falling back to the author — an
unverified result is better than a fake verification. Related:
[[agent-routing]].

**Known hole:** enforcement keys off *declared* metadata — `review_of` and
`verify.by`. A node that quietly interpolates `{a}` and asks "check this",
without declaring `review_of: a`, is not caught, and `mam.py review` trusts
the author name the caller passes. Detecting review *intent* in free-text
prompts is not tractable; declare the relationship and the runner enforces it.
Found by codex reviewing this harness — the review that produced this note is
itself the pattern working.
