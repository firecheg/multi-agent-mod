# Usage

Use `python mam.py ask codex-luna "task" --effort auto --task-kind security`.
For dimensions, pass `--reasoning '{"risk":2,"uncertainty":1}'` (or a JSON
file). Graph nodes can set `reasoning: {"effort":"auto", "dimensions": {...}}`;
verification has its own `reasoning` block and is classified independently.

Routing is a policy recommendation, not a calibrated confidence score. Future
providers are reported as unsupported until an adapter declares their flag.
