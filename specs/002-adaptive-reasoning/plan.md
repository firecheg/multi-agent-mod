# Plan

1. Add a stdlib router with validated dimensions, conservative hard floors, and
   provider capability metadata.
2. Apply one sanitized effort flag per MAM, worker, batch, cache, and MCP call.
3. Persist routing metadata beside invocation results and document the contract.
4. Run the existing unittest suite plus focused router and subprocess argument
   checks.
