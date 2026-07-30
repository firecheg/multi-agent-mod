---
name: codex-binary-version-skew
description: the npm codex shim can be older than the model your config asks for
type: gotcha
date: 2026-07-29
confidence: high
reach: global
---

`codex exec` failed with HTTP 400 `The 'gpt-5.6-sol' model requires a newer
version of Codex` — the npm-installed shim on PATH was 0.117.0 while the Codex
desktop app shipped 0.146.0-alpha at
`%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`. Same account, same
`~/.codex/config.toml`, two binaries, only one new enough for the configured
model.

**Why:** the desktop app self-updates its bundled binary; the npm global does
not. `shutil.which("codex")` finds whichever shim PATH resolves first, which
is the stale one.

**How to apply:** `agents.json` `bin` accepts a list of candidates and takes
the first that resolves — the app binary is listed ahead of the bare `codex`
name for exactly this reason. The hashed directory changes on every app
update, so the candidate is the glob
`~/AppData/Local/OpenAI/Codex/bin/*/codex.exe` and the newest match wins; no
hash is ever pasted into config. If codex still 400s on the model,
`npm i -g @openai/codex@latest`. `python mam.py doctor` prints which binary
actually resolved.
