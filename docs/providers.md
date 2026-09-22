# Providers and agent profiles

The harness executes configured command line workers through one registry. A
provider receives the task on standard input and returns text on standard
output (or JSON selected by `output`). The executor builds an argument list
with `shell=False`; configuration is never evaluated as shell code.

Set `AGENT_HARNESS_CONFIG` or pass `--config path/to/config.json` before a
`mam` subcommand. The bundled configuration uses the deterministic offline
`demo` provider:

```powershell
python mam.py ask demo-worker "check the configured path"
python mam.py --config examples/third-party-config.json ask third-party-worker "hello"
```

Each `providers` entry contains:

* `argv`: a non-empty argument vector. Supported substitutions are
  `{python}`, `{package_dir}`, `{model}`, `{effort}`, `{run}`, `{provider}` and
  `{sandbox}`. They remain individual arguments even when paths contain spaces.
* `input`: currently `stdin`.
* `output`: `text`, `json`, or `json_field`; the latter also requires
  `output_field` and accepts dotted JSON paths such as `response.answer`.
* `models`: model names mapped to `supported_effort` levels from
  `low`, `medium`, `high`, `xhigh`, `max`; `default_model` is a separate
  provider field naming one of those models.
* `model_args` and `effort_args`: optional argument templates appended to
  `argv` when a model or effective effort is selected.
* `author_identity`: the account or identity represented by the provider.
  Reviewer aliases with the same identity are rejected as self-review.
* `timeout_seconds`: a positive subprocess timeout.
* `session_persistence`: enable reuse of a provider session within one graph
  node or a named `ask`/`review --thread`.
  `resume_args` appends provider-neutral templates containing `{session_id}`;
  `resume_argv` replaces the arguments after the executable when a CLI needs a
  different subcommand layout. A persistent provider's normal `argv` must not
  include a no-persistence flag. `resume_sandbox_args` is optional; when
  absent, sandbox args are omitted from resumed calls.
* `session_id_field` reads a dotted field from JSON output; `session_id_regex`
  extracts the first capture group from stderr/stdout. The resulting id is
  stored in a separate id file per (node, agent), or per (thread, agent).
  A failed resume gets one fresh-session retry with the full task prompt and
  is recorded in `resume-fallback.log`.
* `input`: `stdin` (default) or `file`. With `file` the prompt is written to
  `<run>/prompt.md`, `argv` must contain `{prompt_file}`, and stdin stays
  empty — for CLIs that take the prompt only as an argument.
* `env`: variables set for this provider's process only. A value is a
  literal, may contain `{model}`, or is a whole-value `${NAME}` copied from
  your environment at run time; `""` removes an inherited variable. Names
  that look like credentials (`KEY`, `TOKEN`, `SECRET`, `PASSWORD`) accept
  only `${NAME}` references, never literal values. When a referenced variable
  is unset the agent counts as not installed, and `doctor` names the variable.

`agents` binds a stable alias to a provider and model and gives it a role.
`role_bindings` maps task roles such as `summary`, `code`, or `context_read`
to those aliases. `reviewers` lists eligible aliases. The alias is not an
identity: two aliases sharing `author_identity` are still one author. A
profile may override the provider identity with its own `author_identity` when
two configured accounts are genuinely independent.

## Role prompts

Keep global `AGENTS.md` minimal; put worker instructions in top-level
`role_prompts`, mapping a role to an ordered, non-empty list of Markdown files.

The role templates are
`examples/rules/{orchestrator,worker,coder,qa,reviewer,reader,researcher}.md`.
The demo config uses those relative paths. For an installed config, place the
role files beside it under `rules/` or adjust the paths.

```json
"role_prompts": {"review": ["rules/worker.md", "rules/reviewer.md"]}
```

Paths may be absolute, `~`-relative, or relative to the config file. `doctor`
lists them and marks missing files `MISS`; a fresh worker call with a missing
file fails before starting the CLI. Each CLI prompt begins `ROLE: <role>`.
Fresh sessions then receive the concatenated files, `---`, and the task;
resumed sessions receive only the role line and the new task/delta. A role
without configured files receives just the role line and task. Coordinator
handoffs receive neither. `ask`/`review --role` wins over a graph node's
`role`; otherwise `review` and verify steps use `review`, then the agent's
configured role applies.

The order of an author's `reviewers` list is a preference: the first
installed, independent entry is the primary reviewer, the next ones follow.
`review_policy` constrains the primary:

```json
"review_policy": {"primary": "other_provider"}
```

* `independent` (default): any reviewer with another author identity may be
  primary.
* `other_provider`: the primary reviewer must also run on a different
  provider than the author. Later reviewers only need another identity, so a
  second model on the author's own provider can still be the second reader.
  With no installed cross-provider candidate, selection fails closed.

The policy applies wherever the harness picks a reviewer itself: `review`
without `--by`, a `verify` block without `by`, and graph agents written as
`reviewer:1`, `reviewer:2`, ... A `reviewer:N` node must declare `review_of`
(or appear as `verify.by`, meaning the node's own author); it resolves after
roles bind, so a fallback in the author's role chain also changes who reviews.
Explicitly named reviewers are taken as written, subject only to the identity
rule.

For an arbitrary third-party CLI, copy `examples/third-party-config.json`,
replace its `argv` with the CLI and worker path, and keep the worker's prompt
input on stdin. Declaring only the reasoning levels the model actually
supports makes an unsupported request visible in the persisted reasoning
decision; the harness does not silently fall back to a more expensive model.
An empty `supported_effort` list is valid and means the configured model is
known but supports no effort flag. An unknown model/provider is reported as
`unknown_model`; a configured model with a missing requested level is reported
as `unsupported`.

The bundled `demo` provider is explicitly a test/demo worker. It computes a
hash of stdin and prints metadata; it never contacts an LLM service.

The coordinator is resolved only from `--initiator agent`, then
`MAM_INITIATOR`, then the first matching `initiator_detection` entry. With no
match, all graph steps run via CLI. A coordinator-bound graph step writes a
full prompt to the run directory and pauses. Submit `agent-harness verdict
<run> <file|->` to resume it; `--no-in-session` restores subprocess spawning.
`review` prints an in-session notice when its reviewer is the coordinator.
Use the same `--thread name` on later `ask` or `review` calls to resume that
agent's session; omit it for independent calls. Thread names may contain
letters, digits, dots, underscores and hyphens.

For Claude Code and Codex CLI, add this ordered detection table at config root
(replace aliases if yours differ):

```json
"initiator_detection": [
  {"env": "CODEX_SESSION_ID", "agent": "codex-sol"},
  {"env": "CLAUDECODE", "value": "1", "agent": "claude-opus"}
]
```

The bundled `presets/claude.json` and `presets/codex.json` use these resumable,
lean worker arguments. For an existing config, keep its executable path,
models, and reasoning settings while applying the corresponding fields:

```json
"claude": {
  "argv": ["<existing claude executable>", "-p", "--output-format", "json", "--setting-sources=", "--strict-mcp-config", "--mcp-config", "{\"mcpServers\":{}}", "--disable-slash-commands"],
  "session_persistence": true,
  "resume_args": ["--resume", "{session_id}"],
  "session_id_field": "session_id"
},
"codex": {
  "argv": ["<existing codex executable>", "exec", "--skip-git-repo-check", "--color", "never", "-c", "project_doc_max_bytes=0", "--ignore-user-config", "-c", "windows.sandbox=\"unelevated\"", "--disable", "plugins", "--disable", "apps"],
  "session_persistence": true,
  "resume_argv": ["exec", "resume", "--skip-git-repo-check", "-c", "project_doc_max_bytes=0", "--ignore-user-config", "-c", "windows.sandbox=\"unelevated\"", "--disable", "plugins", "--disable", "apps", "{session_id}", "-"],
  "resume_sandbox_args": ["-c", "sandbox_mode=\"{sandbox}\""],
  "session_id_regex": "session id: ([^\\s]+)"
}
```

The final `-` makes `codex exec resume` read its prompt from stdin. The
harness places configured model, effort and sandbox options before the session
id. `codex exec resume` accepts `--skip-git-repo-check`, `--ignore-user-config`,
`--disable`, `--enable`, `-m` and `-c`, but not
`--color` or `-s`; keep colour only on normal calls and map the sandbox via
`-c` on resume. Do not add `resume_drop_args` (it is unsupported).

`--ignore-user-config` also drops the `[windows] sandbox` setting from
`~/.codex/config.toml`. Without it Codex on Windows silently downgrades
`-s workspace-write` to `read-only`, so a worker can neither edit files nor run
commands. `-c windows.sandbox="unelevated"` restores the sandbox without admin
rights; the `[windows]` table has no effect elsewhere.
