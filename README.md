# Multi-agent orchestration

This package is the generated multi-agent subset of Agent Harness: orchestration, providers, cold start, graphs, reasoning, memory and MCP. It is generated from Agent Harness; edit the harness, not this tree.

It has no automatic client wiring: you connect the skill, the MCP server and the read hook to your clients yourself, as described below. If you want that wiring managed for all your agents, install Agent Harness instead. Installing this package and Agent Harness in one environment is unsupported: their files and console entry points conflict.

## Install

Python 3.11 or newer, from a clone of this repository:

```sh
python -m pip install .
agent-harness --help
```

## Cold start

Run the cold start through the bundled `multi-agent` skill (see
[cold start](skills/multi-agent/references/cold-start.md)): `agent-harness setup detect`,
answer the questions, `agent-harness setup write answers.json`, then
`agent-harness doctor`. Set `AGENT_HARNESS_CONFIG` to the config path it prints, and
`AGENT_HARNESS_MEMORY` if the memory vault should live somewhere other than
`~/.agent-harness/memory`. Clients only see variables that existed when they started.

## Add the skill to a client

Copy or link `skills/multi-agent` into the client's skills directory, for example:

```sh
# Claude Code
cp -r skills/multi-agent ~/.claude/skills/multi-agent
# Codex
cp -r skills/multi-agent ~/.codex/skills/multi-agent
```

On Windows use `Copy-Item -Recurse`, or a junction
(`New-Item -ItemType Junction -Path <target> -Target <clone>\skills\multi-agent`) so a
`git pull` updates the skill too. Restart the client.

## Register the MCP server

`agent-harness-mcp` is a stdio server. Use the absolute path of the installed command
(`where agent-harness-mcp` on Windows, `command -v agent-harness-mcp` elsewhere).

Claude Code (`~/.claude.json`):

```json
{"mcpServers": {"agent_harness": {"command": "/abs/path/agent-harness-mcp", "args": []}}}
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.agent_harness]
command = "/abs/path/agent-harness-mcp"
args = []
```

## Register the read hook (optional)

The hook denies whole-file reads of large files and points the agent to a line range
or the `context_read` tool. It reads the tool call as JSON on stdin:

```sh
python -m execution.context_budget hook
```

Use the absolute path of the interpreter the package is installed in. Claude Code
(`~/.claude/settings.json`):

```json
{"hooks": {"PreToolUse": [{"matcher": "Read|Bash",
  "hooks": [{"type": "command", "command": "/abs/path/python -m execution.context_budget hook", "timeout": 10}]}]}}
```

Codex (`~/.codex/hooks.json`) takes the same entry with `"matcher": "Bash"`. Merge
these entries into existing settings rather than replacing them, and restart the client.
