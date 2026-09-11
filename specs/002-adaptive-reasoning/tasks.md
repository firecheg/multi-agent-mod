# Tasks

- [x] Implement `execution/reasoning_router.py`.
- [x] Route MAM graph nodes and verifiers independently; expose ask/review CLI options.
- [x] Route limited workers and include the decision in cache identity and results.
- [x] Expose readonly `reasoning_assess` through the context MCP server.
- [x] Record invocation metadata and preserve no retry behavior.
- [x] Reject unknown fields, partial dimensions, booleans, and invalid graph or
  batch reasoning before any worker process is scheduled.
- [x] Preserve positional prompt data while replacing provider-specific effort
  and model selectors before `--`.
- [x] Reuse one decision for context cache identity, worker argv, and result
  metadata; persist `argv.json` for limited workers.
- [x] Cover ask/review, graph author/verifier, batch, context read, MCP schemas,
  model capability boundaries, caps, and cache decisions with regression tests.
- [x] Run `python -X utf8 -m unittest test_reasoning_router test_mam
  test_shared_harness test_client_adapters test_context_budget
  test_index_workers test_read_gate test_integrations` (62 tests passed).
- [x] Document PowerShell CLI, graph, verifier, and MCP examples plus capability
  and authorization boundaries in `execution/REASONING.md`.
