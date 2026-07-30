---
name: agents-can-lose-auth-mid-run
description: an agent can drop to a browser OAuth prompt in the middle of a graph, killing the node
type: gotcha
date: 2026-07-29
confidence: high
reach: global
---

A `build` graph died at its verifier gate because `agy` decided to
re-authenticate mid-run: it printed an OAuth URL, asked for a code, waited 60
seconds on a stdin that is `/dev/null` by design, and exited 1. Minutes
earlier and minutes later the same binary with the same flags answered fine —
the token refresh was simply due.

**Why:** an install that authenticated once is not authenticated forever, and
nothing warns you first. The symptom looks like a broken flag or a broken
config, so the instinct is to go change something that was never wrong.

**How to apply:** read the node's stderr before touching the configuration —
`Waiting for authentication` names the cause outright. Re-run the same call by
hand to tell a transient refresh apart from a real break; `mam.py doctor
--deep` does this for every agent at once. Long graphs are the exposed case,
so probe before a big run rather than after it fails.

Two harness properties turn this from a hang into a clean failure, and both
are load-bearing: `stdin=DEVNULL`
([[orchestrated-children-need-devnull-stdin]]) means the prompt cannot block
forever, and a failed node taints its dependents instead of feeding them its
error text — in that run `review` and `judge` were skipped rather than
reviewing an error message.
