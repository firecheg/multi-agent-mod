# Adaptive reasoning effort

Each invocation receives an independent deterministic recommendation. Callers
may supply `scope`, `uncertainty`, `reasoning_complexity`, `risk`, and
`verification_complexity` as integers 0..2. A non-empty dimensions object must
contain all five fields. Scores 0–2 recommend `low`, 3–5 `medium`, 6–8 `high`,
and 9–10 `xhigh`. A declared task kind can raise a floor for high impact work.
The router does not infer task kind from source, memory, workload, or file count.

The result records recommended, selected, requested, effective, provider,
model, status, and reasons. A cap changes selected/effective while preserving
the uncapped recommendation. `effective` means the CLI parameter to send or
sent; it does not measure internal thinking. Unknown models and unsupported
providers send no effort flag.
Haiku sends no effort flag. Automatic routing never selects `max`; `max` is
available only when explicitly requested and supported by the selected model.
