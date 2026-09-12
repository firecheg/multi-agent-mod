# Operating manual — every agent in this repo reads this

Canonical file. `CLAUDE.md` and `GEMINI.md` point here.

This repository composes configured CLI agents into graphs with shared memory.
Keep provider roles and runtime contracts stable. Graph nodes write their complete
answer to the bootstrap `out.md` path; verifier nodes emit only
`{"pass": bool, "issues": [...]}`. Do not review your own output: an independent
reviewer reads the actual files on disk.

Ordinary answers and small reversible edits need no memory search or delegation.
For substantial work, read only instructions and source needed for the real
question, preserve user constraints and existing changes, and leave a repeatable
check. Keep memory scoped to the project; write only durable facts and never
secrets. Do not publish, message others, or perform irreversible actions without
permission.

Detailed rules, loaded by trigger:

- [`docs/agent-rules/routing.md`](docs/agent-rules/routing.md): routing, effort, canaries, retries.
- [`docs/agent-rules/source-reading.md`](docs/agent-rules/source-reading.md): bounded reading.
- [`docs/agent-rules/memory-collaboration.md`](docs/agent-rules/memory-collaboration.md): memory and review.
- [`docs/agent-rules/verification.md`](docs/agent-rules/verification.md): checks and reporting.

House style: prefer the shortest checkable change, stdlib and native platform
features, and explicit validation at trust boundaries. Preserve MIT attribution.
