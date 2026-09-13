# Cold start: connecting your agents

The harness does not ship anyone's roster. Which CLIs you have is a fact about
your machine; which models you pay for and who writes or reviews is your
decision. Setup separates the two.

## 1. Detect

```sh
agent-harness setup detect
```

Prints JSON for every bundled preset: whether the CLI was found, its path,
version, the effort levels and sandbox modes its flags accept, what the preset
was checked against, and caveats. Native installs are preferred over package
manager shims; newer versioned installs over older ones. Nothing is called
except `--version`.

`agent-harness setup presets` lists the same presets without probing.

| Preset | CLI | Prompt | Answer | Run live |
|---|---|---|---|---|
| `claude` | Claude Code | stdin, `-p` | JSON `result` | yes |
| `codex` | Codex CLI | stdin, `exec` | stdout final message | yes |
| `gemini` | Gemini CLI | stdin (headless) | JSON `response` | no |
| `agy` | Antigravity CLI | prompt file, `--print` | stdout text | no |
| `cursor` | Cursor CLI | prompt file, `--print --force` | stdout text | no |
| `opencode` | OpenCode | attached prompt file, `run --auto` | stdout text | no |
| `aider` | Aider | `--message-file` | stdout text (with Aider log) | no |
| `qwen` | Qwen Code | stdin | stdout text | no |
| `copilot` | GitHub Copilot CLI | prompt file, `--prompt --silent` | stdout text | no |

Model backends through Claude Code (`ANTHROPIC_BASE_URL` pointed at the
vendor's Anthropic-compatible endpoint) are presets too:
`claude-deepseek`, `claude-glm`, `claude-kimi`, `claude-qwen`. Each reads its
key from your environment (`DEEPSEEK_API_KEY`, `ZAI_API_KEY`,
`MOONSHOT_API_KEY`, `DASHSCOPE_API_KEY`; rename with `env` in the answers)
and counts as its own provider for `review_policy`, separate from Anthropic.
OpenCode and Aider reach the same models through their own provider support.

Presets marked "no" were built from vendor documentation and tested against
fake CLIs, not against the real program; confirm them with `doctor --deep`.

A CLI that is not listed can be added as a provider by hand (see
[providers](providers.md)). A provider whose CLI only takes the prompt as an
argument sets `"input": "file"` and puts `{prompt_file}` in `argv`.

## 2. Answer

Only the person knows these; an agent running setup should ask, not guess:

* Which of the detected CLIs do you use, and with which models?
* Who writes code, who reviews it? For each author, in which order should
  reviewers be tried?
* Should the primary reviewer always come from a different provider
  (`review_policy.primary: other_provider`)? With a single provider, keep the
  default `independent`.
* Which agent fills each graph role (`spec`, `implement`, `judge`, `web`,
  `prosecutor`)? A role may list a fallback chain.

Write the answers as JSON:

```json
{
  "agents": {
    "writer":   {"preset": "codex",  "model": "<model you use>", "role": "implementation"},
    "reviewer": {"preset": "codex",  "model": "<second model>",  "role": "review"},
    "planner":  {"preset": "claude", "model": "<model you use>", "role": "spec, judge"}
  },
  "reviewers": {"writer": ["planner", "reviewer"]},
  "review_policy": {"primary": "other_provider"},
  "roles": {"spec": "planner", "implement": "writer", "judge": "planner"}
}
```

Per agent you may also set `effort` (the levels this model accepts; defaults
to what the CLI flag accepts), `path` (when detection missed the CLI), `env`
(override a preset variable, e.g. `{"ANTHROPIC_AUTH_TOKEN": "${MY_KEY}"}`) and
`author_identity` (only when two profiles are genuinely the same account —
by default every profile is its own author).

## 3. Write and verify

```sh
agent-harness setup write answers.json
agent-harness --config ~/.agent-harness/config.json doctor --deep
```

`write` builds providers from the presets and your answers, validates the
result, and writes `~/.agent-harness/config.json` plus the roles file. It
refuses to overwrite existing files without `--force`. Point
`AGENT_HARNESS_CONFIG` at the config for your shell and MCP clients.

`doctor --deep` makes one short call per installed agent. It is the only step
that proves a model name exists and the account is signed in; model names and
per-model effort support change faster than any preset.

## Credentials

Setup never reads, copies or stores credentials. Each CLI keeps its own sign-in.
