# multi-agent-mod

**An AI reviewing its own code says it looks good. This makes that impossible.**

`mam.py` composes the CLI agents you already pay for — `claude`, `codex`,
`agy` — into graphs where the agent that *wrote* something is never the agent
that *checks* it. One Python file, standard library only, no dependencies, no
API keys beyond the logins you already have.

```
router ──► node ──► node ──► node          graph = coordination between nodes
            │
            └─ act ─ check ─ revise ─┐     loop  = behaviour inside one node
               ▲                     │
               └── verifier (≠ author)
```

---

## Why bother

A model asked to check its own output re-runs the reasoning that produced it.
It does not re-derive the answer; it confirms the chain. That is why
self-review returns a confident PASS on broken code — and why "let me
double-check that" from a single agent is worth so much less than it sounds.

Two models from different labs, each doing the part it is actually better at,
disagree in useful ways. This repo is the plumbing that makes them disagree on
purpose, in a loop that terminates.

A real example, from this repo's own history. Claude wrote a binary-resolution
helper that globbed a path and sorted matches by mtime. Codex, reviewing the
diff with no stake in it, returned:

> `sorted(glob.glob(cand), key=os.path.getmtime)` does not handle stat errors.
> A dangling symlink raises `FileNotFoundError`, so `_bins` dies and never
> tries the next candidate.

Correct, and invisible to the author — who had just tested it on a machine
where every match happened to exist. That is the whole product in one
paragraph.

---

## What you get

| | |
|---|---|
| `mam review` | cross-review of a diff or file; the reviewer is chosen to *not* be the author |
| `mam graph build` | spec → implement → an independent verifier gates it → adversarial review → judge |
| `mam graph research` | live web and local repo searched in parallel, then a synthesis that names the conflicts instead of averaging them |
| `mam ask` | one agent, with relevant memory injected |
| `mam mem` | a git-tracked markdown vault all three agents read and write |
| `mam doctor` | what's installed, who reviews whom, and (`--deep`) who actually answers |

Every run leaves `.mam/<timestamp>-<name>/` behind: the prompt each agent got,
the answer it gave, the journal. Nothing is reconstructed after the fact — the
log *is* the run, so you can audit any claim back to the agent that made it.

---

## Install

Three minutes, most of it browser logins.

```bash
git clone https://github.com/firecheg/multi-agent-mod ~/multi-agent-mod
npm i -g @openai/codex @anthropic-ai/claude-code
```

```powershell
irm https://antigravity.google/cli/install.ps1 | iex
```

Run `claude` and `agy` once each and finish their browser logins — both are
interactive and neither can be scripted. Then:

```bash
python ~/multi-agent-mod/mam.py doctor
```

`doctor` prints what resolved, what's missing, and who reviews whom. Missing
agents don't break the tool — only the graphs that need them. `OK` means the
binary resolved, **not** that the account is authorised; auth fails on the
first real call. `doctor --deep` closes that gap by actually calling each
agent once. It is opt-in because it costs real calls: on its first run here it
correctly reported one agent as installed-but-dead while three answered.

The agy installer writes its `bin` to the persisted User PATH but cannot touch
an already-running shell, so `agy` stays "not recognized" until you open a
**new** terminal. `mam.py` is unaffected — `agents.json` lists the install path
ahead of the bare name.

### One install, every repo

`HOME` (the clone) holds config and graphs. `WORK` is wherever you ran the
command — that is where agents actually operate, and run artifacts land in
`WORK/.mam/`. Override with `MAM_WORKSPACE`. So you install once and every
project on the machine gets it.

**Point the vault somewhere private before you use it in anger:**

```bash
export MAM_MEMORY="$HOME/.mam-memory"     # setx MAM_MEMORY "%USERPROFILE%\.mam-memory"
```

One vault serves every project, so notes written while you work on a private
repo end up wherever the vault lives — and by default that is this clone, i.e.
a public repo you might push. `MAM_MEMORY` moves it out. The bundled `memory/`
stays as a seed you can copy from; `doctor` prints which vault is live.

### As a Claude Code skill

`skills/multi-agent/SKILL.md` makes Claude act as the orchestrator on
`/multi-agent`, or whenever a task asks for cross-review or an independent
second opinion. It carries the routing table, the hard rule and the command
set, so nothing has to be re-derived per session.

It lives in this repo so it is versioned alongside the interface it drives
(`metadata.version`, semver, bumped in the commit that changes behaviour), and
is linked into the skills directory rather than copied — two copies drift and
nobody notices. From the clone:

```bash
mkdir -p ~/.claude/skills && ln -s "$PWD/skills/multi-agent" ~/.claude/skills/multi-agent
```

```powershell
mkdir -Force "$env:USERPROFILE\.claude\skills"; cmd /c mklink /J "$env:USERPROFILE\.claude\skills\multi-agent" "$PWD\skills\multi-agent"
```

A junction needs no administrator rights. `git pull` is the upgrade.

The skill looks for the harness at `$MAM_HOME/mam.py`, falling back to
`~/multi-agent-mod/mam.py`. Cloned elsewhere? Set it once:

```powershell
setx MAM_HOME "$PWD"
```

```bash
printf 'export MAM_HOME=%q\n' "$PWD" >> ~/.profile
```

---

## Use

```bash
python mam.py doctor                        # what's installed, memory health
python mam.py ask codex "..." --memory      # one agent, vault context injected
python mam.py review codex --path src/x.py  # cross-review; picks a non-author
python mam.py graph build --input "..."     # run a graph
python mam.py mem search "topic"
python mam.py mem lint
```

`review` defaults to `git diff HEAD`. Give it `--task` (what the author was
asked for) and repeatable `--criteria` — **a reviewer without criteria invents
its own**, and an empty `issues` list then means "the criteria I made up held",
which is worth nothing. Write criteria as if they are the only thing that will
ever be checked, because they are.

---

## Who does what, and why

Routing is by **capability**, not preference. The point is that three
correlated models become three *partly independent* ones once each is doing the
job it is actually better at and checking the jobs it did not do.

| work | agent | why it wins here |
|---|---|---|
| spec, architecture, judging, reconciling conflicting sources, final verdict | **claude** | holds a long brief without drifting; comfortable making the call and saying why the other agent was wrong |
| implementation, refactors, tight diffs, test-writing, anything that must *run* | **codex** | OS-level sandbox, iterates against a failing test, doesn't sprawl the diff |
| live web research, huge-document reading, browser/visual verification | **agy** | real search grounding, largest context, multimodal |

**`agy` is Antigravity CLI, and it is what you want — not `gemini`.** Google
stopped serving Gemini CLI for individual / AI Pro / AI Ultra accounts on
2026-06-18 and removed Login-with-Google for them; OAuth now fails with *"no
longer supported for Gemini Code Assist for individuals"*. `gemini` is kept in
`agents.json` because it still works on a **paid** API key, Code Assist
Standard/Enterprise, or Google Cloud — but for an individual account, use
`agy`. Details: `memory/brain/gemini-cli-retired-for-individuals.md`.

The Antigravity **IDE** is a separate product from the `agy` CLI and has no
headless mode. Use it by hand for what an IDE beats a pipe at, and hand results
to the pipeline through `memory/thinking/`.

**Images and video are out of band.** No agent here generates them reliably
from the CLI. Do that in the vendors' own apps and reference the asset by path
— don't build a graph node around it, and don't trust a claim that a node
produced one.

### What the design actually enforces

- **Author never reviews author.** Checked at graph-validation *and* at
  runtime; when no other agent is installed the run **fails** rather than
  falling back to self-review.
- **Verifiers fail closed.** Unparseable verdict → FAIL. Uncertain → FAIL.
  A gate that defaults to PASS is not a gate.
- **Reviewers read disk, not the author's summary.** Written into the review
  prompts and into `AGENTS.md`.
- **No manufactured findings.** Review prompts explicitly permit "nothing
  found" — otherwise reviewers invent issues to look useful.
- **Memory is context, not instruction.** Injected notes are labelled as such,
  so an agent doesn't obey a stale note as if it were an order.
- **File-based I/O.** Prompts to `prompt.md`, answers to `out.md`. Sidesteps
  Windows argv limits and shell quoting entirely and leaves a full audit trail.

---

## Graphs

`graphs/build.json` — spec (claude) → build (codex, gated by an agy verifier
loop, up to 3 rounds) → adversarial review (agy) → judge (claude). Claude wrote
neither the code nor the review it judges.

`graphs/research.json` — web (agy) ∥ repo (codex) in parallel → synthesis
(claude).

A node is JSON:

```json
{
  "id": "build",
  "agent": "codex",
  "needs": ["spec"],
  "prompt": "Implement this spec:\n{spec}",
  "verify": { "by": "agy", "max_rounds": 3, "criteria": ["..."] },
  "review_of": "some_other_node",
  "remember": true,
  "memory": false,
  "sandbox": "danger-full-access"
}
```

`{node_id}` interpolates that node's output, `{input}` the CLI argument. Nodes
whose deps are satisfied run in parallel. `verify` is the loop (retry with the
verifier's issues appended); `needs` is the graph.

Every `{placeholder}` must resolve to an input or to a node the referencing
node actually waits on — validation rejects anything else. An unresolved one
would reach the agent as literal text and read as an instruction; referencing a
node you don't wait on is a race against shared context.

**Loop or graph?** Improving a result *within* a step → loop. Handing work
*between* components → graph. See `memory/brain/loop-vs-graph.md`.

**Parallel nodes share one working tree.** Two agents writing the same files
concurrently clobber each other silently. Fan out read-only lenses; chain
writers behind `needs`. The orchestrator shares that tree as well: commit
before launching a writing graph and don't touch the files until it returns.

---

## Memory

An Obsidian-style vault: one fact per markdown file, YAML frontmatter,
`[[wikilinks]]`, git-tracked, readable without any tooling. Schema in
`memory/SCHEMA.md`.

The `memory/` in this repo is a **seed** — real notes from building the thing,
kept because an empty vault teaches nothing about the format. Your own vault
should live outside the clone (`MAM_MEMORY`, above), which keeps your notes out
of a public repo and out of every `git pull` conflict.

Every graph node gets the top-k relevant notes prepended automatically
(`"memory": false` to opt out). Nodes marked `"remember": true` write durable
learnings back. All three agents read the same vault, so a gotcha codex hit on
Tuesday is context agy has on Friday.

Retrieval is lexical scoring plus one hop along wikilinks — a linked note is
pulled in at damped relevance, which is where most of the "it knew the related
thing" comes from. No embeddings; swap in a vector index when keyword recall
measurably misses, not before.

Because one vault serves every project, **reach is declared at write time and
never widened at read time**. `mem write --reach repo` (the default) stamps the
current project and stays scoped to it; `--reach global` reaches everywhere.

`AGENTS.md` is the shared operating manual — codex and agy both pick it up by
that name; `CLAUDE.md` and `GEMINI.md` are two-line pointers to it, so every
agent loads the same rules whichever filename it looks for.

---

## Check

```bash
python test_mam.py
```

Covers the parts that rot silently: the no-self-review rule (static and
runtime), graph validation, fail-closed verdict parsing, binary resolution,
memory retrieval and lint, and dependency-ordered scheduling. No real agents
are called, so it runs offline in a second.

---

## Honest limits

**The rule keys off declared metadata** (`review_of`, `verify.by`). A node that
interpolates `{a}` and asks "check this" without declaring the relationship is
not caught, and `mam.py review` trusts the author name you pass it. Declare the
relationship and the runner enforces it; detecting review intent in free-text
prompts is not tractable.

**Cross-review is not proof.** It catches what a second, differently-trained
reader would catch. In this repo's own review rounds, roughly half the findings
were real and half were confidently wrong — which is why a human judges each
one and the skill tells the orchestrator to rule VALID / MINOR / WRONG rather
than accept the list.

**No worktree isolation.** Parallel writers clobber each other; see above.

**Skipped on purpose:** embeddings, a daemon, a TUI, cron scheduling, retries
with backoff, streaming output. Add the vector index when `mem search` starts
missing things; add scheduling when you actually want unattended runs.

---

MIT. Issues and PRs welcome — especially reviewer prompts that catch things
these ones miss.
