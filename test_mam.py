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

# --- a declared gate must say what it checks -------------------------------
# The verifier checks the criteria and nothing else. run_node used to supply
# "The task is fully done and correct." when a verify block named none, so the
# gate ran, cost a call per round, and passed a stub with a TODO straight into
# the next node's prompt as finished work. A spec like that is now invalid.
for bad in ({"by": "agy"}, {"by": "agy", "criteria": []}, {"max_rounds": 3}):
    try:
        mam.validate({"name": "t", "nodes": [
            {"id": "a", "agent": "codex", "prompt": "x", "verify": bad}]})
        raise SystemExit(f"FAIL: gate without criteria was accepted: {bad}")
    except ValueError as e:
        assert "no criteria" in str(e), e
# an empty verify block is how you say "no gate" — still legal, still ungated
mam.validate({"name": "t", "nodes": [
    {"id": "a", "agent": "codex", "prompt": "x", "verify": {}}]})

import json
# --- roles bind to agents, and a clone with no roster says so ---------------
# A graph names roles so it runs on whatever the reader actually installed.
# Binding is where a personal roster meets a shared shape; both failure modes
# below are invisible in the spec itself and only true once bound.
_ROSTER = {"spec": "claude", "implement": "codex", "review": "agy", "judge": "claude"}
_g = {"name": "t", "nodes": [
    {"id": "a", "agent": "implement", "prompt": "x", "verify": {"by": "review", "criteria": ["c"]}},
    {"id": "b", "agent": "review", "needs": ["a"], "review_of": "a", "prompt": "y"},
    {"id": "c", "agent": "codex", "needs": ["a"], "prompt": "z"},
]}
_b = mam.bind_roles(_g, _ROSTER)
assert [n["agent"] for n in _b["nodes"]] == ["codex", "agy", "codex"], _b
assert _b["nodes"][0]["verify"]["by"] == "agy", "verify.by must bind too"
assert _g["nodes"][0]["agent"] == "implement", "bind_roles must not mutate the caller's spec"

# an unconfigured role names itself and points at init, rather than failing deep
try:
    mam.bind_roles(_g, {"implement": "codex"})
    raise SystemExit("FAIL: a graph bound with a missing role")
except ValueError as e:
    assert "'review'" in str(e) and "mam.py init" in str(e), e

# two roles, one agent: a cross-check that is really self-review. Structurally
# the spec is fine -- only the binding makes it a violation.
try:
    mam.bind_roles(_g, {"implement": "codex", "review": "codex", "spec": "claude"})
    raise SystemExit("FAIL: review and implement on one agent was accepted")
except ValueError as e:
    assert "differ" in str(e) or "self-review" in str(e), e

# every shipped graph binds under a plausible roster
for _p in (mam.HOME / "graphs").glob("*.json"):
    _spec = json.loads(_p.read_text(encoding="utf-8"))
    mam.bind_roles(_spec, {**_ROSTER, "review_2": "claude", "web": "agy", "prosecutor": "gemini"})

# --- agents.local.json layers over the tracked roster ----------------------
# The tracked file says what the agents are; a machine says where its binaries
# live and what extra models it pays for. Without the split, adding an agent
# means editing a tracked file and eating a conflict on every pull.
import shutil, tempfile as _tf
_d = pathlib.Path(_tf.mkdtemp())
_local = _d / "agents.local.json"
_orig_local, _orig_cfg = mam.AGENTS_LOCAL, mam.CFG
try:
    mam.AGENTS_LOCAL = _local
    assert mam.load_agents() == json.loads(
        (mam.HOME / "agents.json").read_text(encoding="utf-8")), "absent local file must change nothing"

    _local.write_text(json.dumps({
        "agents": {
            "codex": {"bin": "/opt/codex"},
            "extra": {"bin": "x", "args": [], "role": "r", "install": "i"},
        },
        "reviewers": {"extra": ["claude"]},
        "timeout": 99,
    }), encoding="utf-8")
    _m = mam.load_agents()
    assert _m["agents"]["codex"]["bin"] == "/opt/codex", "override did not apply"
    assert _m["agents"]["codex"]["args"], "overriding bin must not drop the other fields"
    assert "extra" in _m["agents"], "a local-only agent must be added"
    assert _m["timeout"] == 99, "top-level keys must be overridable"
    assert json.loads((mam.HOME / "agents.json").read_text(encoding="utf-8")
                      )["agents"]["codex"]["bin"] != "/opt/codex", "the tracked file must stay untouched"

    # an agent with no reviewers is not an author -- it would die mid-run with
    # "no installed cross-reviewer", so the gap is filled at load
    _local.write_text(json.dumps({"agents": {"lonely": {"bin": "x", "args": [], "role": "r", "install": "i"}}}),
                      encoding="utf-8")
    assert mam.load_agents()["reviewers"]["lonely"], "a new agent must get reviewers"
    assert "lonely" not in mam.load_agents()["reviewers"]["lonely"], "and never itself"

    _local.write_text(json.dumps({"reviewers": {"codex": ["codex", "claude"]}}), encoding="utf-8")
    try:
        mam.load_agents()
        raise SystemExit("FAIL: an agent reviewing itself was accepted from the local file")
    except ValueError as e:
        assert "its own reviewer" in str(e), e
finally:
    mam.AGENTS_LOCAL, mam.CFG = _orig_local, _orig_cfg
    shutil.rmtree(_d, ignore_errors=True)

# --- a role is a chain, and the first INSTALLED agent wins ------------------
# Agents go missing for reasons a config cannot see: rate limits, a logout, an
# uninstall. Naming a preference order costs a fallback instead of a failed run.
_chain = {"name": "t", "nodes": [
    {"id": "a", "agent": "implement", "prompt": "x"},
    {"id": "b", "agent": "review", "needs": ["a"], "review_of": "a", "prompt": "y"},
]}
_real_installed = mam.installed
try:
    mam.installed = lambda n: n != "agy"
    _b = mam.bind_roles(_chain, {"implement": ["agy", "codex"], "review": "claude"})
    assert _b["nodes"][0]["agent"] == "codex", "a missing first choice must fall through"

    mam.installed = lambda n: True
    _b = mam.bind_roles(_chain, {"implement": ["agy", "codex"], "review": "claude"})
    assert _b["nodes"][0]["agent"] == "agy", "the first choice wins when it is there"

    # a bare string is still a chain of one -- rosters written before chains
    # existed keep working
    _b = mam.bind_roles(_chain, {"implement": "codex", "review": "claude"})
    assert _b["nodes"][0]["agent"] == "codex", _b

    mam.installed = lambda n: False
    try:
        mam.bind_roles(_chain, {"implement": ["agy", "codex"], "review": "claude"})
        raise SystemExit("FAIL: bound a role whose whole chain is uninstalled")
    except ValueError as e:
        assert "none of them installed" in str(e), e
finally:
    mam.installed = _real_installed

# --- roles that must not collapse onto one agent ---------------------------
# Who plays which part in `court` follows from what each agent did: the judge
# wrote the brief, the defence wrote the code, the prosecutor did neither. That
# last one is a rule about three nodes rather than an edge between two, so
# review_of cannot express it and `distinct` does.
_court = {"name": "c", "distinct": [["spec", "implement", "prosecutor"]], "nodes": [
    {"id": "a", "agent": "spec", "prompt": "x"},
    {"id": "b", "agent": "implement", "needs": ["a"], "prompt": "y"},
]}
mam.bind_roles(_court, {"spec": "claude", "implement": "agy", "prosecutor": "codex"})
for _bad, _pair in (({"spec": "claude", "implement": "agy", "prosecutor": "claude"}, "spec"),
                    ({"spec": "claude", "implement": "agy", "prosecutor": "agy"}, "implement")):
    try:
        mam.bind_roles(_court, _bad)
        raise SystemExit(f"FAIL: prosecutor was allowed to be the {_pair}")
    except ValueError as e:
        assert "needs them apart" in str(e) and "init --role" in str(e), e

# the collapse can also arrive through a fallback, which is the case no one
# writes down: implement's first choice is gone, and its second is the prosecutor
_real = mam.installed
try:
    mam.installed = lambda n: n != "agy"
    try:
        mam.bind_roles(_court, {"spec": "claude", "implement": ["agy", "codex"], "prosecutor": "codex"})
        raise SystemExit("FAIL: a fallback collapsed two roles and was accepted")
    except ValueError as e:
        assert "needs them apart" in str(e), e
finally:
    mam.installed = _real

# --- a rounds block: three parties argue until the decider stops them -------
# The verify loop pairs one author with one verifier, which cannot seat a
# three-cornered argument: whoever is not the verifier speaks once, and the
# party that has to re-read the code after each fix is the one you cannot
# afford to silence.
_orig_rn = mam.run_node
_calls = []
_verdicts = iter(['not yet {"pass": false, "issues": ["do the thing"]}',
                  'better {"pass": true, "issues": []}'])
def _fake(node, ctx, run_dir, log):
    if node.get("rounds"):
        return _orig_rn(node, ctx, run_dir, log)   # exercise run_rounds itself
    _calls.append((node["id"], ctx.get("round"), bool(ctx.get("previous"))))
    return next(_verdicts) if node["id"] == "decide" else node["id"]

_loop = {"name": "t", "nodes": [{"id": "block", "rounds": {"max": 4, "until": "decide", "nodes": [
    {"id": "accuse", "agent": "codex", "prompt": "a {round} {previous}"},
    {"id": "decide", "agent": "claude", "prompt": "d {accuse}"},
    {"id": "act", "agent": "agy", "prompt": "f {decide}"},
]}}]}
mam.validate(_loop)
mam.run_node = _fake
try:
    _res, _dir, _failed = mam.run_graph(_loop, {}, quiet=True)
    assert not _failed, _failed
    assert [c[0] for c in _calls] == ["accuse", "decide", "act", "accuse", "decide"], _calls
    assert _calls[0][1] == "1 of 4" and _calls[3][1] == "2 of 4", "round must be offered"
    assert _calls[0][2] is False and _calls[3][2] is True, "{previous} is empty first, filled after"
    assert _res["block"].startswith("better"), _res["block"]
    assert _res["accuse"] == "accuse", "sub-node outputs must reach the outer results"
    shutil.rmtree(_dir, ignore_errors=True)

    # running out of rounds is a failure, not a quiet pass
    _calls.clear()
    _verdicts = iter(['{"pass": false, "issues": ["still wrong"]}'] * 9)
    _res, _dir, _failed = mam.run_graph(_loop, {}, quiet=True)
    assert _failed == {"block"}, _failed
    assert "still wrong" in _res["block"], _res["block"]
    assert sum(1 for c in _calls if c[0] == "act") == 4, "every round must run the fix"
    shutil.rmtree(_dir, ignore_errors=True)
finally:
    mam.run_node = _orig_rn

for _bad, _why in (
    ({"id": "x", "rounds": {"until": "nope", "nodes": [{"id": "a", "agent": "claude", "prompt": "p"}]}}, "names no node"),
    ({"id": "x", "agent": "claude", "prompt": "p",
      "rounds": {"until": "a", "nodes": [{"id": "a", "agent": "claude", "prompt": "p"}]}}, "takes no agent"),
    ({"id": "x", "rounds": {"until": "a", "nodes": [{"id": "a", "agent": "claude", "prompt": "{nope}"}]}}, "neither an input"),
):
    try:
        mam.validate({"name": "t", "nodes": [_bad]})
        raise SystemExit(f"FAIL: accepted a block that should not validate ({_why})")
    except ValueError as e:
        assert _why in str(e), e

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
        assert json.loads((pathlib.Path(td) / "n/meta.json").read_text(encoding="utf-8"))["status"] == "failed"
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
assert all(why in ("missing or invalid reach", "legacy project has no valid binding")
           for _, why in mam.mem_lint()), mam.mem_lint()

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
    def fake(agent, prompt, node_dir, timeout=None, sandbox=None, **kwargs):
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

# --- Изоляция памяти: временное хранилище не затрагивает личные заметки. ---
import unittest
from unittest.mock import patch


class MemoryIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.first = self.root / "first" / "same"
        self.second = self.root / "second" / "same"
        self.first.mkdir(parents=True)
        self.second.mkdir(parents=True)
        self.patches = [patch.object(mam, "MEM", self.vault),
                        patch.object(mam, "WORK", self.first)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def note(self, scope, name="legacy"):
        text = (f"---\nname: {name}\ndescription: d\ntype: gotcha\n"
                f"{scope}---\n\nneedle secret")
        p = self.vault / f"{name}.md"
        p.write_text(text, encoding="utf-8")
        return p

    def write(self, name="shared", body="needle original", **kwargs):
        return mam.mem_write("brain", name, "d", "gotcha", body, **kwargs)

    def test_same_basename_is_isolated(self):
        p = self.write()
        self.assertTrue(mam.mem_search("needle"))
        mam.WORK = self.second
        self.assertFalse(mam.mem_search("needle"))
        self.assertNotIn("original", mam.mem_context("needle"))

    def test_same_slug_cannot_overwrite_another_project(self):
        first = self.write()
        mam.WORK = self.second
        second = self.write(body="needle second")
        self.assertNotEqual(first, second)
        self.assertIn("original", first.read_text(encoding="utf-8"))
        self.assertEqual(self.write(body="needle updated"), second)
        self.assertIn("updated", second.read_text(encoding="utf-8"))
        self.assertEqual(second.relative_to(self.vault).parts,
                         ("projects", mam.project_id(), "brain", "shared.md"))
        self.assertEqual(mam._meta(second.read_text(encoding="utf-8"))["project_id"],
                         mam.project_id())

    def test_unknown_and_missing_reach_are_hidden_and_linted(self):
        for i, scope in enumerate(("", "reach: typo\n", "reach: repo\n")):
            with self.subTest(scope=scope):
                p = self.note(scope, str(i))
                self.assertFalse(mam._in_reach(p.read_text(encoding="utf-8")))
                self.assertTrue(any(n == p for n, _ in mam.mem_lint()))
        self.assertFalse(mam._in_reach("no frontmatter"))
        self.assertFalse(mam.mem_search("needle"))

    def test_global_is_explicit_and_available_everywhere(self):
        p = self.write(reach="global")
        mam.WORK = self.second
        self.assertEqual(mam.mem_search("needle")[0][0], p)
        self.assertFalse(mam.mem_lint())

    def test_legacy_requires_explicit_identity_binding(self):
        p = self.note("reach: repo\nproject: same\n")
        self.assertFalse(mam.mem_search("needle"))
        self.assertTrue(mam.mem_lint())
        (self.vault / "legacy-projects.json").write_text(
            json.dumps({"same": mam.project_identity()}), encoding="utf-8")
        self.assertEqual(mam.mem_search("needle")[0][0], p)
        self.assertFalse(mam.mem_lint())
        mam.WORK = self.second
        self.assertFalse(mam.mem_search("needle"))

    def test_invalid_registry_fails_closed(self):
        self.note("reach: repo\nproject: same\n")
        registry = self.vault / "legacy-projects.json"
        for value in ("{", "[]", '{"same": null}', '{"same": "same"}'):
            with self.subTest(value=value):
                registry.write_text(value, encoding="utf-8")
                self.assertFalse(mam.mem_search("needle"))
                self.assertTrue(mam.mem_lint())

    def test_invalid_project_id_cannot_fall_back_to_legacy(self):
        (self.vault / "legacy-projects.json").write_text(
            json.dumps({"same": mam.project_identity()}), encoding="utf-8")
        for value in ("", " bad-id"):
            with self.subTest(value=value):
                self.note(f"reach: repo\nproject: same\nproject_id:{value}\n")
                self.assertFalse(mam.mem_search("needle"))
                self.assertTrue(mam.mem_lint())

    def test_existing_scope_is_not_overwritten(self):
        p = self.vault / "brain" / "shared.md"
        p.parent.mkdir()
        original = "---\nreach: repo\nproject: other\n---\n\noriginal"
        p.write_text(original, encoding="utf-8")
        with self.assertRaises(ValueError):
            self.write(reach="global")
        self.assertEqual(p.read_text(encoding="utf-8"), original)

    def test_wikilinks_do_not_pull_other_project_notes(self):
        self.write("entry", "needle [[private]]")
        mam.WORK = self.second
        self.write("private", "hidden payload")
        mam.WORK = self.first
        self.assertEqual([p.stem for p, _ in mam.mem_search("needle")], ["entry"])
        self.assertNotIn("hidden payload", mam.mem_context("needle"))

    def test_paths_and_metadata_cannot_escape_namespace(self):
        for folder, name in (("../outside", "x"), ("brain", "../x"),
                             (str(self.root / "outside"), "x"), ("brain", "a/b"),
                             ("..\\outside", "x"),
                             ("projects", "x"), ("brain", "a:stream")):
            with self.subTest(folder=folder, name=name):
                with self.assertRaises(ValueError):
                    mam.mem_write(folder, name, "d", "gotcha", "body")
        with self.assertRaises(ValueError):
            mam.mem_write("brain", "x", "d\nreach: global", "gotcha", "body")
        with self.assertRaises(ValueError):
            self.write(reach="typo")
        self.assertEqual(list(self.vault.rglob("*.md")), [])

    def test_total_context_budget_and_truncation(self):
        for i in range(5):
            self.write(f"note-{i}", "needle " + "large text " * 500)
        with patch.dict(mam.CFG, {"memory_max_chars": 900}):
            result = mam.mem_context("needle")
        self.assertLessEqual(len(result), 900)
        self.assertIn("needle", result)
        self.assertIn("[Memory truncated]", result)
        self.assertTrue(result.endswith("\n\n---\n\n"))
        self.assertLessEqual(len(mam.mem_context("needle")), 6000)

    def test_zero_budget_disables_context(self):
        self.write()
        with patch.dict(mam.CFG, {"memory_max_chars": 0}):
            self.assertEqual(mam.mem_context("needle"), "")

    def test_invalid_budget_is_rejected(self):
        for value in (-1, 1.5, "900", True):
            with self.subTest(value=value), patch.dict(mam.CFG, {"memory_max_chars": value}):
                with self.assertRaises(ValueError):
                    mam.mem_context("needle")

    def test_git_worktree_and_subdirectory_share_project(self):
        if not shutil.which("git"):
            self.skipTest("git unavailable")
        def git(*args):
            subprocess.run(["git", *args], cwd=self.first, check=True,
                           capture_output=True)
        git("init", "-q")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-m", "test")
        worktree = self.root / "worktree"
        git("worktree", "add", "--detach", str(worktree))
        first = self.write()
        nested = self.first / "nested"
        nested.mkdir()
        for workspace in (nested, worktree):
            mam.WORK = workspace
            self.assertEqual(mam.mem_search("needle")[0][0], first)
            self.assertEqual(self.write(body="needle updated"), first)

    def test_small_note_is_not_marked_truncated(self):
        self.write()
        result = mam.mem_context("needle")
        self.assertIn("original", result)
        self.assertNotIn("[Memory truncated]", result)

    def test_remember_prompt_uses_project_namespace(self):
        with patch.object(mam, "run_agent", return_value="ok") as run:
            mam.run_node({"id": "remember", "agent": "codex", "prompt": "x",
                          "memory": False, "remember": True}, {}, self.root,
                         lambda msg: None)
        prompt = run.call_args.args[1]
        self.assertIn((self.vault / "projects" / mam.project_id() / "brain").as_posix(), prompt)
        self.assertIn(f"project_id: {mam.project_id()}", prompt)


class ReasoningIntegrationTests(unittest.TestCase):
    def test_run_agent_preserves_long_prompt_and_logs_actual_argv(self):
        prompt = "full prompt " + "x" * 2200
        spec = {"args":["exec", "-c", "model=gpt-5.5", "--model", "gpt-5.6-luna",
                        "--output-last-message", "{out}", "{prompt}"]}
        def completed(argv, **kwargs):
            output = pathlib.Path(argv[argv.index("--output-last-message") + 1])
            output.write_text("ok", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "", "")
        with tempfile.TemporaryDirectory() as td, \
                patch.object(mam, "resolve", return_value=("codex.exe", spec)), \
                patch.object(mam.subprocess, "run", side_effect=completed):
            node = pathlib.Path(td) / "node"
            result = mam.run_agent("codex-luna", prompt, node, model="gpt-6-astra",
                                   task_kind="security", routing_task=prompt)
            meta = json.loads((node / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual((node / "prompt.md").read_text(encoding="utf-8"), prompt)
        self.assertEqual(result, "ok")
        self.assertEqual(meta["reasoning"]["model"], "gpt-6-astra")
        self.assertEqual(meta["reasoning"]["effective"], "high")
        self.assertIn('model_reasoning_effort="high"', meta["argv"])
        self.assertEqual(meta["argv"].count("--model"), 1)

    def test_node_and_verifier_route_the_original_task_independently(self):
        calls = []
        def fake(agent, prompt, node_dir, *args, **kwargs):
            calls.append((agent, prompt, kwargs))
            return ('{"pass": true, "issues": []}' if agent == "agy" else "work")
        node = {"id":"n", "agent":"codex", "prompt":"original task",
                "memory":False, "task_kind":"security",
                "verify":{"by":"agy", "criteria":["correct"]}}
        with tempfile.TemporaryDirectory() as td, patch.object(mam, "run_agent", side_effect=fake):
            self.assertEqual(mam.run_node(node, {}, pathlib.Path(td), lambda _:None), "work")
        self.assertEqual(calls[0][2]["task_kind"], "security")
        self.assertEqual(calls[0][2]["routing_task"], "original task")
        self.assertEqual(calls[1][2]["task_kind"], "review")
        self.assertEqual(calls[1][2]["routing_task"], "original task")

    def test_invalid_graph_reasoning_fails_before_any_node(self):
        spec = {"name":"invalid-reasoning", "nodes":[
            {"id":"a", "agent":"codex", "prompt":"a"},
            {"id":"b", "agent":"claude", "prompt":"b", "reasoning":False},
        ]}
        with patch.object(mam, "run_node") as run:
            with self.assertRaises(ValueError):
                mam.run_graph(spec, {}, quiet=True)
            run.assert_not_called()

    def test_cli_dimension_file_contract(self):
        complete = {name:1 for name in mam.validate_reasoning_config(
            {"dimensions":{"scope":1,"uncertainty":1,"reasoning_complexity":1,
                           "risk":1,"verification_complexity":1}})["dimensions"]}
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "reasoning.json"
            path.write_text(json.dumps(complete), encoding="utf-8")
            self.assertEqual(mam.load_reasoning_dimensions(str(path)), complete)
        with self.assertRaises(ValueError):
            mam.load_reasoning_dimensions('{"scope": 1}')

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

# --- per-node sandbox must yield exactly one --sandbox --------------------
# Regression: codex 0.147 dropped --full-auto from `exec`, so every build node
# died with rc=2 before a single model call. The flag now lives in agents.json
# as `--sandbox workspace-write`, which a per-node override has to REPLACE —
# appending a second --sandbox makes clap reject the invocation outright.
argv = mam.apply_sandbox(
    ["exec", "--sandbox", "workspace-write", "--skip-git-repo-check", "prompt"],
    "danger-full-access")
assert argv.count("--sandbox") == 1, argv
assert argv[-2:] == ["--sandbox", "danger-full-access"], argv
assert "workspace-write" not in argv, argv
assert argv[:2] == ["exec", "--skip-git-repo-check"], f"unrelated args dropped: {argv}"
# a config still carrying the removed flag must not resurrect it
assert "--full-auto" not in mam.apply_sandbox(["exec", "--full-auto"], "read-only")
# and the shipped config must actually be runnable by current codex
assert "--full-auto" not in mam.CFG["agents"]["codex"]["args"], "codex exec rejects --full-auto"

# --- `review` refuses to run without criteria ------------------------------
# Regression: a review launched with only --task returned {"pass": true,
# "issues": []} on an 876-line diff. The reviewer was not lazy -- it checks the
# criteria and nothing else, and there were none, so the gate was vacuous. The
# old code substituted "Correct, minimal, no obvious bugs." and made that
# invisible. Refuse instead: the parser is the only place this can be enforced
# before a model call is paid for.
_p = subprocess.run([sys.executable, "mam.py", "review", "claude", "--task", "t"],
                    cwd=str(mam.HOME), capture_output=True, text=True,
                    encoding="utf-8", errors="replace")
assert _p.returncode == 2, f"review ran without criteria: rc={_p.returncode}"
assert "--criteria" in _p.stderr, _p.stderr
# and it fails at parse time, before picking a reviewer or reading the diff
assert "reviewed by" not in _p.stderr, "a model call was reached anyway"
_help = subprocess.run([sys.executable, "mam.py", "review", "--help"],
                       cwd=str(mam.HOME), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
assert _help.returncode == 0 and "--reasoning" in _help.stdout, _help.stdout + _help.stderr

_suite = unittest.TestSuite()
_suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(MemoryIsolationTests))
_suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ReasoningIntegrationTests))
_result = unittest.TextTestRunner(verbosity=2).run(_suite)
if not _result.wasSuccessful():
    raise SystemExit(1)
print("ok")
