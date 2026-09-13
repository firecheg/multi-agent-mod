# Working on Agent Harness

This repository contains reusable orchestration technology, not a personal agent installation.

- Preserve provider neutrality: roles reference configured agent profiles; providers declare commands, result formats and reasoning capabilities.
- Use narrow evidence and bounded worker tasks. Assign reasoning effort per task; work volume alone does not determine reasoning complexity.
- Keep runtime state, credentials, transcripts, project memory, indexes and personal skills out of Git.
- Run tests against temporary directories and the deterministic demo provider. Never invoke a paid provider as part of the default test suite.
- Independently review another author's changes. Different aliases with the same author identity do not provide independence.
- Preserve source attribution and MIT notices. Document unsupported capabilities honestly.
- Change client configuration only with an explicit client selection and reversible, conflict-aware operations.

For reusable coordination guidance, load only the triggered file under
`examples/rules/`: routing, source-reading, memory-collaboration, or
verification. Ordinary answers and small reversible edits need no delegation or
memory ritual.
