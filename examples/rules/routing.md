# Routing

The coordinator owns analysis, decisions, specification acceptance, and judgment. Route by kind of work, not simply by size. Implementation, tests, debugging, and code exploration beyond one or two files go to configured workers. Small reversible operations stay local.

| Task | Route |
|---|---|
| Large files, logs, or a code map | `demo-worker` with `--role reading`; narrow facts, `file:line`, short quotes, maximum length, no conclusions |
| Live research | Configured research agent with `--role research`; primary sources, links and dates, facts apart from guesses |
| Analysis, design, trade-offs, specs, acceptance | Coordinator in-session; never delegated |
| Implementation and author tests | Configured implementation agent with `--role implementation` |
| Behavior check against criteria | Configured QA agent with `--role qa`; name the criteria and base branch |
| Independent review | Other provider's reviewer with `--role review` and `review --thread`; coordinator's own provider reviews in-session. For diffs up to about 300 lines, coordinator reads them; for larger diffs, other-provider reviewer reads first and coordinator verifies findings |
| Fix after review | The same author, with `--thread` and only new findings |

The bundled `demo-worker` and `demo-reviewer` are offline placeholders. Replace aliases with your configured agents before using paid routes. Never use the author or an alias with the same author identity as an independent reviewer.

For a code worker, save a full specification to a file: first line `/ponytail` when that skill is installed; finished decisions; files and touchpoints; files to read; done criteria; tests to add; exact check command and known pre-existing failures; report format and line limit. CLI workers start without user settings, MCP servers, or skills; the harness prepends `ROLE: <role>` and the configured role files. The specification decides any further reading.

Start workers with `agent-harness ask|review ... --out <file>` and collect them with one `agent-harness wait <files>`. For multiple rounds, reuse `--thread`. A coordinator-bound graph step writes a handoff prompt; provide the verdict with `agent-harness verdict <run> <file|->` and resume the graph. Keep a short milestone state file for long work.

Choose effort by reasoning difficulty: `low` mechanical, `medium` ordinary engineering, `high` difficult diagnosis or safety, `xhigh` exceptional work. Request `max` only with explicit permission. Report the actual model, role, status, and run reference for delegated work. Check route availability before a paid call; after one attempt and one targeted correction, reassess rather than repeating blindly.
