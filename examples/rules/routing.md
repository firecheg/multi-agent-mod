# Routing

For substantial engineering work, the coordinator owns analysis and judgment; configured summary workers handle orientation and classification, and configured code workers handle implementation and author tests. The coordinator does not implement, write tests or explore code itself, even when doing it directly looks faster; when unsure whether work is substantial, delegate.

Substantial means: a code change in more than one file or beyond about 20 lines, a new feature, debugging, or code exploration beyond one or two files. Only answers, reading a single file and one-line configuration edits stay local with minimal necessary tools.

The coordinator keeps decisions, not raw output. Start workers with `ask|review ... --out <file>` and collect them with one `wait <files>` instead of polling logs; send checks to a file and keep only the result. For work that spans several milestones, keep a task state file (goal, decisions, branches, what is verified, what is left) and update it at each milestone, so compaction or a fresh thread loses only raw output.

Minimal-solution guidance (for example a "lazy senior engineer" skill) belongs in code worker tasks, not in the coordinator: the worker writes the minimal solution itself, and the coordinator reviews task fit and defects only, without separate simplification passes.

Choose effort per task: `low` mechanical, `medium` ordinary engineering, `high` difficult diagnosis or safety, `xhigh` exceptional cross service work. `max` requires explicit permission; unsupported settings are `effective unset`.

Give a route report only for delegated or substantial work: the actual configured model, role, status and run reference in the first update, on routing changes and in the final update. Simple answers have no route report.

Allow one initial attempt and one targeted correction after a diagnosed failure. After two failures, reassess scope or escalate for a factual reason. Check route availability first; do not spend a paid call on an unavailable route.
