# Cold start: connecting the person's agents

Goal: a validated `~/.agent-harness/config.json` and roles file that describe
the agents this person actually uses. Facts come from the machine; decisions
come from the person. One short question at a time.

## 1. Detect

```sh
agent-harness setup detect
```

Summarise for the person: which CLIs were found (with version), which were
not. Mention preset caveats that matter to them (for example a preset marked
"not run live", or a CLI whose headless mode needs broad permissions).
`agent-harness setup presets` lists every preset, including model backends
reached through Claude Code (`claude-deepseek`, `claude-glm`, `claude-kimi`,
`claude-qwen`).

## 2. Ask

1. Which of these CLIs do you use, and with which models? (Model ids exactly
   as the CLI expects them.)
2. Which agents write code?
3. For each author, which reviewers, in which order? Should the primary
   reviewer always run on a different provider than the author? (Only
   meaningful with two or more providers.)
4. Who writes specs and judges (`spec`, `judge`)? Who does live web research
   (`web`)? Who prosecutes in `court` (`prosecutor`, must differ from spec and
   implementer)? Any fallback when an agent is rate-limited?
5. Which cheap agent should do bounded reading for the context tools
   (`role_bindings`: `summary`, `code`, `context_read`)?
6. For model backends: which environment variable holds each key? Ask for the
   variable name only. Never ask for, read, write or repeat a key.

## 3. Write the answers

```json
{
  "agents": {
    "<profile>": {"preset": "<preset>", "model": "<model id>", "role": "implementation"}
  },
  "reviewers": {"<author profile>": ["<primary>", "<second>"]},
  "review_policy": {"primary": "other_provider"},
  "roles": {"spec": "<profile>", "implement": ["<first>", "<fallback>"], "judge": "<profile>"},
  "role_bindings": {"summary": "<cheap profile>", "code": "<cheap profile>", "context_read": "<cheap profile>"}
}
```

Optional per agent: `effort` (levels this model accepts), `path` (CLI not
detected), `env` (for example `{"ANTHROPIC_AUTH_TOKEN": "${THEIR_VARIABLE}"}`),
`author_identity` (only if two profiles are genuinely one account). Show the
file to the person before writing.

## 4. Write and verify

```sh
agent-harness setup write answers.json
agent-harness --config ~/.agent-harness/config.json doctor
```

`setup write` refuses to overwrite existing files; ask before adding
`--force`. It prints the config path: tell the person to set
`AGENT_HARNESS_CONFIG` to it. Do not change persistent environment variables
or client settings yourself without their consent.

`doctor` shows `OK` / `MISS` per agent (a missing CLI or an unset key
variable is named). Offer `doctor --deep` — one short call per agent, which is
the only proof that model ids and sign-ins work — and run it only if they
agree.

## 5. Connect clients

To expose the MCP tools, register `agent-harness-mcp` as an MCP server in the
client. If agent-harness's shared wiring is installed, connecting clients and
shared skills is handled by the shared-harness skill.
