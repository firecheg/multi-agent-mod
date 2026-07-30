---
name: orchestrated-children-need-devnull-stdin
description: a spawned agent CLI without stdin=DEVNULL burns its entire timeout waiting
type: gotcha
date: 2026-07-29
confidence: high
reach: global
---

Graph nodes hung for the full 1800 s timeout while the same `codex exec`
command run by hand finished in ~70 s. Cause: `subprocess.run` without an
explicit `stdin` lets the child inherit the parent's, and the agent CLI
blocked reading it. Adding `stdin=subprocess.DEVNULL` in `run_agent` fixed it;
both nodes then completed in 76 s and 64 s.

**Why:** the failure is invisible. A blocked child produces no output and no
error — it looks exactly like a slow model, so the instinct is to raise the
timeout, which makes it worse.

**How to apply:** every orchestrated child process gets
`stdin=subprocess.DEVNULL`. Never let it inherit. Also worth suspecting first
whenever a node's duration lands suspiciously close to its configured timeout
rather than anywhere below it.

Isolation note: PowerShell happened to work while Git Bash hung, which made
this look shell-specific. It was not — with the fix both shells pass. Don't
stop at the first correlated variable. Related: [[codex-binary-version-skew]].
