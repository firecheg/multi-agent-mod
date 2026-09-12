# multi-agent skill changelog

Semver in `metadata.version` of `SKILL.md`. The skill is linked into the skills
directory from a clone, so `git pull` is the upgrade — bump the version in the
same commit that changes behaviour, or nobody can tell which one they have.

- **1.11.1** — custom graphs go to the project's `.mam/graphs/`, not the
  harness clone; `.gitignore` tracks only the bundled graphs.
- **1.11.0** — the skill matches the shipped roster and graphs: `codex-astra`
  is in the routing table, bundled graphs are marked agent- or role-based,
  `doctor` is for harness operations rather than every call, recall uses
  `mem context`, and this changelog moved out of `SKILL.md`.
- **1.10.0** — current-author routing, Codex Luna implementation, per-call
  reasoning effort and bounded shared-harness context guidance are documented.
- **1.9.0** — `rounds` blocks: several nodes repeat until one of them returns a
  passing verdict. `graph court` is three parties arguing inside one.
- **1.8.0** — `graph court`: the author defends its own work against a
  prosecutor who wrote neither the brief nor the code, and the judge who wrote
  the brief rules. A spec can declare roles that must not collapse.
- **1.7.0** — a role takes a preference order, not one agent; the first
  installed one wins. `--review-2` is now its own flag, and `--role NAME=a,b`
  sets roles beyond the built-in ones.
- **1.6.0** — `agents.local.json` holds what is true of one machine (binary
  paths, extra models); the tracked roster stays pullable.
- **1.5.0** — graphs name roles, not agents, and `init` binds them to whatever
  the user has. Ask before assuming a roster. Adds `graph build-2r`.
- **1.4.0** — a graph node's `verify` block must list `criteria`; the spec is
  rejected at validation instead of running a gate that checks nothing.
- **1.3.0** — a partial or blocked run must be reported as one, not as a pass.
  And `review` now requires at least one `--criteria` and refuses the
  run at parse time without it. Previously it substituted "Correct, minimal,
  no obvious bugs.", which reads like a review and checks nothing: an
  876-line diff came back `{"pass": true, "issues": []}` and the gate looked
  like it had held.
- **1.2.0** — codex is invoked with `--sandbox workspace-write` instead of
  `--full-auto`, which codex 0.147 removed from `exec` (every build node died
  with rc=2 before reaching the model). A per-node `sandbox` now replaces that
  flag rather than appending a second one.
- **1.1.0** — the memory vault can live outside the clone (`MAM_MEMORY`);
  `doctor` prints which vault is live.
- **1.0.0** — first public release. Routing table, the no-self-review rule,
  `doctor` / `ask` / `review` / `graph` / `mem`, harness discovery via
  `$MAM_HOME`.
