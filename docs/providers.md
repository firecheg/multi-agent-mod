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
