---
name: gemini-cli-retired-for-individuals
description: Gemini CLI stopped serving individual accounts on 2026-06-18; agy replaces it
type: gotcha
date: 2026-07-29
confidence: high
reach: global
---

`gemini` OAuth login now fails with *"This client is no longer supported for
Gemini Code Assist for individuals"*. On 2026-06-18 Google stopped serving
Gemini CLI and the Code Assist IDE extensions for the individuals / AI Pro /
AI Ultra tiers, and removed the Login-with-Google option for them.

Still supported on `gemini`: Code Assist Standard/Enterprise licences, Google
Cloud, and **paid Gemini API keys**. The individual replacement is
**Antigravity CLI**, binary `agy` — a different product with its own login.

**Why:** an install that succeeds tells you nothing about whether the account
tier is still served. `mam.py doctor` reports `gemini` as OK because the
binary resolves; the failure only appears on first call.

**How to apply:** for an individual Google account, use `agy`, not `gemini`.
Install on Windows with `irm https://antigravity.google/cli/install.ps1 | iex`
(lands in `%LOCALAPPDATA%\agy\bin`), then log in through the browser on first
run; credentials go to Windows Credential Manager. Headless: `agy -p`,
`--output-format json|stream-json`, `--json-schema`, `--model`,
`--dangerously-skip-permissions`, `--print-timeout` (default 5m — too short
for a build node).

Without the permissions flag, headless tool calls are **soft-denied**, so an
agy node cannot write its `out.md`. Alternative to the flag: grant in
`~/.gemini/antigravity-cli/settings.json`.

`agy` also has its own `--sandbox` ("terminal restrictions"), and it composes
with `--dangerously-skip-permissions` — verified on v1.1.8 that a sandboxed
run still reads workspace files and writes `out.md`. Use both, so
auto-approval is not also unrestricted. `--print-timeout` takes a Go duration
(`30m`), not a bare number.

If `agy` is missing from PATH after install, `agy install` configures the
shell paths; `agents.json` lists the absolute
`%LOCALAPPDATA%\agy\bin\agy.exe` first so the harness works either way.

Corrects an earlier note claiming Antigravity had no CLI at all. That was
inferred from the IDE's `bin/` folder holding only the IDE launcher — the CLI
is a separate product with a separate installer, so absence there proved
nothing. See [[agent-routing]].
