"""Runnable check for the parts that can silently rot: the no-self-review rule,
memory retrieval, verdict parsing, and graph scheduling. No real agents called.

    python test_mam.py
"""
import os, pathlib
# Pin the suite to the bundled seed vault: the memory assertions name real
# notes, and a machine with MAM_MEMORY pointing at a private (or empty) vault
# would fail them for reasons that have nothing to do with the code.
os.environ["MAM_MEMORY"] = str(pathlib.Path(__file__).resolve().parent / "memory")

import mam

# --- no self-review, statically -------------------------------------------
same = {"name": "t", "nodes": [
    {"id": "a", "agent": "codex", "prompt": "x"},
    {"id": "b", "agent": "codex", "needs": ["a"], "review_of": "a", "prompt": "y"},
]}
try:
    mam.validate(same)
    raise SystemExit("FAIL: codex reviewing codex was accepted")
except ValueError as e:
    assert "self-review" in str(e), e

diff = {"name": "t", "nodes": [
    {"id": "a", "agent": "codex", "prompt": "x"},
    {"id": "b", "agent": "gemini", "needs": ["a"], "review_of": "a", "prompt": "y"},
]}
mam.validate(diff)

# and for the in-node verifier loop
try:
    mam.validate({"name": "t", "nodes": [
        {"id": "a", "agent": "codex", "prompt": "x", "verify": {"by": "codex"}}]})
    raise SystemExit("FAIL: codex verifying itself was accepted")
except ValueError as e:
    assert "differ" in str(e), e

# --- graph structure ------------------------------------------------------
for bad, why in [
    ({"name": "t", "nodes": [{"id": "a", "agent": "codex", "needs": ["ghost"], "prompt": "x"}]}, "unknown dep"),
    ({"name": "t", "nodes": [{"id": "a", "agent": "codex", "prompt": "x"},
                             {"id": "a", "agent": "gemini", "prompt": "y"}]}, "duplicate"),
]:
    try:
        mam.validate(bad)
        raise SystemExit(f"FAIL: accepted graph with {why}")
    except ValueError:
        pass

# --- unresolved placeholders must not reach an agent as literal text -------
for bad, why in [
    ({"name": "t", "nodes": [{"id": "a", "agent": "codex", "prompt": "use {ghost}"}]},
     "undefined placeholder"),
    # b does not wait on a, so {a} would race the shared ctx
    ({"name": "t", "nodes": [{"id": "a", "agent": "codex", "prompt": "x"},
                             {"id": "b", "agent": "agy", "prompt": "use {a}"}]},
     "undeclared dependency"),
]:
    try:
        mam.validate(bad)
        raise SystemExit(f"FAIL: accepted {why}")
    except ValueError as e:
        assert "references" in str(e), e

# a transitive ancestor is safe: it has certainly finished by then
mam.validate({"name": "t", "nodes": [
    {"id": "a", "agent": "codex", "prompt": "x"},
    {"id": "b", "agent": "agy", "needs": ["a"], "prompt": "{a}"},
    {"id": "c", "agent": "claude", "needs": ["b"], "prompt": "{a} and {b} and {input}"},
]})

# --- render substitutes once: no agent injecting into another's prompt -----
assert mam.render("{a}|{b}", {"a": "A", "b": "B"}) == "A|B"
# a's output mentions {b}; replacing key by key would have expanded it
assert mam.render("{a}", {"a": "see {b}", "b": "SECRET"}) == "see {b}"
assert mam.render("{ghost}", {"a": "A"}) == "{ghost}", "unknown keys stay literal"

# --- shipped graphs are valid --------------------------------------------
import json, pathlib
for g in (mam.HOME / "graphs").glob("*.json"):
    mam.validate(json.loads(g.read_text(encoding="utf-8")))

# --- bin candidates are portable: no machine-specific paths in the config --
import os, shutil, tempfile
for name, spec in mam.CFG["agents"].items():
    for cand in (spec["bin"] if isinstance(spec["bin"], list) else [spec["bin"]]):
        assert "Users/" not in cand and "Users\\" not in cand, f"{name}: {cand} is machine-specific"

_tmp = tempfile.mkdtemp()
for i, sub in enumerate(("old", "new")):
    os.makedirs(f"{_tmp}/{sub}")
    open(f"{_tmp}/{sub}/x.exe", "w").close()
    os.utime(f"{_tmp}/{sub}/x.exe", (0, 1000 + i))          # new is newer
os.environ["MAM_TEST_DIR"] = _tmp
_hits = mam._bins({"bin": ["$MAM_TEST_DIR/*/x.exe"]})
# by parent dir, not substring: a tmp path or username containing "new" would
# make a substring check pass while newest-first is broken
assert [pathlib.Path(h).parent.name for h in _hits] == ["new", "old"], _hits
assert mam._bins({"bin": ["~/nope"]})[0] != "~/nope", "~ must expand"
assert mam._bins({"bin": [f"{_tmp}/none/*.exe"]}) == [f"{_tmp}/none/*.exe"], "a pattern with no match must survive for the error message"

# A match that cannot be stat'd (dangling symlink, file vanished mid-glob) must
# not crash the sort. Break the *newest* one — the case that decides ordering —
# and require it to sort last so `which` falls through to a binary that exists.
_getmtime = os.path.getmtime
os.path.getmtime = lambda p: (_ for _ in ()).throw(FileNotFoundError(p)) if "new" in p else _getmtime(p)
try:
    _order = mam._bins({"bin": ["$MAM_TEST_DIR/*/x.exe", "codex"]})
    assert [pathlib.Path(h).parent.name for h in _order[:2]] == ["old", "new"], _order
    assert _order[-1] == "codex", "the plain PATH candidate must survive"
finally:
    os.path.getmtime = _getmtime
assert os.path.getmtime is _getmtime, "monkeypatch leaked into later tests"
shutil.rmtree(_tmp)

# --- the vault can live outside the clone ---------------------------------
# Without this the harness writes every note into whatever repo it was cloned
# from, so a note about a private project lands in a public one. MEM is bound
# at import, so this has to be a fresh interpreter.
import subprocess, sys
_vault = str(pathlib.Path(tempfile.gettempdir(), "mam-vault-probe").resolve())
_probe = subprocess.run([sys.executable, "-c", "import mam; print(mam.MEM)"],
                        cwd=str(mam.HOME), capture_output=True, text=True,
                        env={**os.environ, "MAM_MEMORY": _vault})
assert _probe.stdout.strip() == _vault, _probe.stdout + _probe.stderr

# --- reviewer selection never returns the author --------------------------
for author in mam.CFG["agents"]:
    assert author not in mam.CFG["reviewers"][author], f"{author} lists itself as reviewer"

# --- verdict parsing ------------------------------------------------------
assert mam.parse_verdict('{"pass": true, "issues": []}') == (True, [])
assert mam.parse_verdict('sure!\n{"pass": false, "issues": ["boom"]}\nhope that helps') == (False, ["boom"])
assert mam.parse_verdict("PASS")[0] is False, "unparseable must fail closed"
assert mam.parse_verdict("{not json}")[0] is False
# a gate must fail closed on a schema violation, not coerce it: bool("false") is True
assert mam.parse_verdict('{"pass": "false", "issues": []}')[0] is False, "string pass coerced to True"
assert mam.parse_verdict('{"pass": 1, "issues": []}')[0] is False
assert mam.parse_verdict('{"issues": []}')[0] is False, "missing pass must fail"
assert mam.parse_verdict('{"pass": true, "issues": "nope"}')[0] is False, "issues must be a list"
assert mam.parse_verdict('{"pass": true, "issues": [{"x": 1}]}')[0] is False
# a stray brace after the verdict must not swallow it: the old greedy \{.*\}
# ran to the LAST } in the message and turned a valid PASS into a rejection
assert mam.parse_verdict('{"pass": true, "issues": []}\n\nHope that helps! }') == (True, [])
assert mam.parse_verdict('```json\n{"pass": false, "issues": ["x"]}\n```') == (False, ["x"])
# a preceding unrelated object must be stepped over, not parsed as the verdict
assert mam.parse_verdict('{"note": "thinking"}\n{"pass": true, "issues": []}') == (True, [])

# --- an agent that writes no out.md must fail loudly, not return its stdout --
# Regression: `claude` printed "Not logged in" and exited; that text was being
# returned as the node's result and fed to downstream nodes as real work.
import sys, tempfile
mam.CFG["agents"]["_null"] = {
    "bin": [sys.executable], "args": ["-c", "print('Not logged in')"], "install": "-"}
with tempfile.TemporaryDirectory() as td:
    try:
        got = mam.run_agent("_null", "task", pathlib.Path(td) / "n")
        raise SystemExit(f"FAIL: stdout returned as a result: {got!r}")
    except mam.AgentError as e:
        assert "wrote no out.md" in str(e), e
        assert "Not logged in" in str(e), "error must surface what the agent actually said"
del mam.CFG["agents"]["_null"]

# --- the agent must be told where its files are in absolute terms ----------
# agy resolves a relative path against the directory handed to --add-dir, not
# against cwd: it found no prompt, wrote out.md into the memory vault, and
# returned an invented PASS with rc=0. The node dir here is INSIDE WORK, which
# is exactly the case the old relative-path code got wrong.
mam.CFG["agents"]["_null"] = {
    "bin": [sys.executable], "args": ["-c", "print('x')", "{prompt}"], "install": "-"}
_nd = mam.WORK / ".mam" / "_pathprobe"
try:
    try:
        mam.run_agent("_null", "task", _nd)
    except mam.AgentError:
        pass  # no out.md, as expected — we only want the argv it was launched with
    _boot = [a for a in json.loads((_nd / "meta.json").read_text(encoding="utf-8"))["argv"]
             if "follow its instructions" in a][0]
    assert (_nd / "prompt.md").as_posix() in _boot, _boot
    assert (_nd / "out.md").as_posix() in _boot, _boot
    # and the assertion above is only meaningful if relative would differ here
    assert (_nd / "prompt.md").relative_to(mam.WORK).as_posix() != (_nd / "prompt.md").as_posix()
finally:
    shutil.rmtree(_nd, ignore_errors=True)
    del mam.CFG["agents"]["_null"]

# --- a note piped in on stdin must survive the round trip ------------------
# Windows decodes stdin with the console code page, so UTF-8 bytes came back
# as cp1251 and mem write stored a double-encoded note. Nothing failed; the
# vault just filled with unreadable text.
_body = "агент резолвит пути от --add-dir, а не от cwd"
with tempfile.TemporaryDirectory() as td:
    subprocess.run([sys.executable, str(mam.HOME / "mam.py"), "mem", "write",
                    "--folder", "brain", "--name", "probe", "--description", "d",
                    "--type", "gotcha", "--reach", "global"],
                   input=_body.encode("utf-8"), cwd=str(mam.HOME), check=True,
                   capture_output=True, env={**os.environ, "MAM_MEMORY": td})
    _back = (pathlib.Path(td) / "brain" / "probe.md").read_text(encoding="utf-8")
    assert _body in _back, f"stdin mangled on the way into the vault: {_back!r}"

# --- a BOM in out.md must not ride into the next node's prompt -------------
# codex writes one; under plain utf-8 it survived as ﻿, reached every
# downstream prompt, and crashed any console that was not UTF-8.
mam.CFG["agents"]["_bom"] = {"bin": [sys.executable], "install": "-", "args": ["-c", (
    "import pathlib,sys; s=sys.argv[1]; "
    "p=pathlib.Path(s.split(' answer to ')[1].split(' (')[0]); "
    "p.write_bytes(b'\\xef\\xbb\\xbfhello')"), "{prompt}"]}
with tempfile.TemporaryDirectory() as td:
    got = mam.run_agent("_bom", "task", pathlib.Path(td) / "n")
    assert got == "hello", f"BOM survived into the node result: {got!r}"
del mam.CFG["agents"]["_bom"]

# --- memory ---------------------------------------------------------------
hits = mam.mem_search("self-review reviewer author", 3)
assert hits, "memory search found nothing"
assert any(p.stem == "no-self-review" for p, _ in hits), [p.stem for p, _ in hits]
assert "## Memory" in mam.mem_context("loop graph coordination", 2)
assert mam.mem_search("zzzqqqxyzzy", 3) == []
assert not mam.mem_lint(), mam.mem_lint()

# short technical terms are exactly what a vault gets asked about
assert {"ai", "go", "c#", "ml"} <= mam._terms("AI Go C# ML"), mam._terms("AI Go C# ML")
assert "the" not in mam._terms("the thing"), "stopwords must not score"

# the excerpt must contain the match, not the head of the note
body = "padding. " * 900 + "NEEDLE_XYZ here" + " tail." * 200
assert "NEEDLE_XYZ" in mam._excerpt(body, {"needle_xyz"}), "excerpt cut away the match"
assert len(mam._excerpt(body, {"needle_xyz"})) <= 2600
assert mam._excerpt("short note", {"nothing"}) == "short note"

# --- the verifier loop: reject, feed the issues back, accept ---------------
_real_run_agent = mam.run_agent
NODE = {"id": "b", "agent": "codex", "prompt": "do it", "memory": False,
        "verify": {"by": "agy", "max_rounds": 3, "criteria": ["c1"]}}

def _loop_agent(verdicts):
    calls = []
    def fake(agent, prompt, node_dir, timeout=None, sandbox=None):
        calls.append((agent, prompt))
        if agent == "codex":
            return f"attempt {sum(1 for a, _ in calls if a == 'codex')}"
        v = verdicts[min(sum(1 for a, _ in calls if a == "agy"), len(verdicts)) - 1]
        return '{"pass": %s, "issues": ["fix the thing"]}' % ("true" if v else "false")
    return calls, fake

calls, mam.run_agent = _loop_agent([False, True])
out = mam.run_node(NODE, {}, pathlib.Path("."), lambda m: None)
assert out == "attempt 2", f"did not retry after rejection: {out!r}"
attempts = [p for a, p in calls if a == "codex"]
assert "fix the thing" not in attempts[0], "issues leaked into the first attempt"
assert "fix the thing" in attempts[1], "verifier's issues were not fed back to the author"

# exhausting the rounds is a failure, not a pass with a warning attached
calls, mam.run_agent = _loop_agent([False, False, False])
try:
    got = mam.run_node(NODE, {}, pathlib.Path("."), lambda m: None)
    raise SystemExit(f"FAIL: rejected work returned as success: {got!r}")
except mam.AgentError as e:
    assert "all 3 rounds" in str(e), e
assert sum(1 for a, _ in calls if a == "codex") == 3, "wrong number of retries"
mam.run_agent = _real_run_agent

# --- doctor stays offline unless --deep -----------------------------------
# The whole point of plain doctor is that it is instant; a probe smuggled into
# it would turn a status check into a fleet of billed agent calls.
import contextlib, io
class _NS:
    def __init__(self, deep): self.deep = deep

probed = []
mam.run_agent = lambda agent, *a, **k: (probed.append(agent), "ok")[1]
with contextlib.redirect_stdout(io.StringIO()):
    mam.cmd_doctor(_NS(deep=False))
assert not probed, f"plain doctor called agents: {probed}"
with contextlib.redirect_stdout(io.StringIO()) as out:
    mam.cmd_doctor(_NS(deep=True))
assert probed, "--deep probed nothing"

# a probe that dies must be reported, not crash the whole command
def _dying(agent, *a, **k):
    raise mam.AgentError("no credentials")
mam.run_agent = _dying
with contextlib.redirect_stdout(io.StringIO()) as out:
    mam.cmd_doctor(_NS(deep=True))
assert "no credentials" in out.getvalue(), "probe failure was swallowed"
mam.run_agent = _real_run_agent

# --- reach: a repo-scoped note must not leak into a sibling project --------
_fm = "---\nname: x\ndescription: d\ntype: gotcha\nreach: %s\n%s---\n\nbody"
scoped = _fm % ("repo", "project: alpha\n")
_w = mam.WORK
mam.WORK = pathlib.Path("/x/alpha"); assert mam._in_reach(scoped), "hidden in its own project"
mam.WORK = pathlib.Path("/x/beta"); assert not mam._in_reach(scoped), "leaked into a sibling"
assert mam._in_reach(_fm % ("global", "")), "global must reach everywhere"
assert mam._in_reach("no frontmatter at all"), "unmarked notes stay visible"
mam.WORK = _w

# --- scheduler: deps respected, independents run together -----------------
order, spec = [], {"name": "sched", "concurrency": 4, "nodes": [
    {"id": "a", "agent": "codex", "prompt": "a"},
    {"id": "b", "agent": "gemini", "prompt": "b"},
    {"id": "c", "agent": "claude", "needs": ["a", "b"], "prompt": "c {a} {b}"},
]}
_real_run_node = mam.run_node
mam.run_node = lambda n, ctx, d, log: (order.append((n["id"], mam.render(n["prompt"], ctx))), n["id"])[1]
res, run_dir, failed = mam.run_graph(spec, {}, quiet=True)
assert order[-1][0] == "c", order
assert order[-1][1] == "c a b", f"deps not substituted into prompt: {order[-1][1]!r}"
assert set(res) == {"a", "b", "c"} and not failed
import shutil; shutil.rmtree(run_dir)

# --- a failed node must not feed its error text to its dependents ----------
# Regression: node b once received node a's timeout message as normal input.
ran = []
def _boom(n, ctx, d, log):
    ran.append((n["id"], dict(ctx)))
    if n["id"] == "a":
        raise mam.AgentError("codex timed out")
    return n["id"]
mam.run_node = _boom
res, run_dir, failed = mam.run_graph(spec, {}, quiet=True)
assert failed == {"a", "c"}, f"failure did not taint the dependent: {failed}"
assert res["a"].startswith("FAILED:"), res["a"]
assert res["c"].startswith("SKIPPED:"), f"c ran on a failed dep: {res['c']!r}"
assert not any(nid == "c" for nid, _ in ran), "c was executed despite a failed dep"
assert all("a" not in ctx for nid, ctx in ran), "failed output leaked into ctx"
assert res["b"] == "b", "an unrelated branch must still run"
shutil.rmtree(run_dir)
mam.run_node = _real_run_node

print("ok")
