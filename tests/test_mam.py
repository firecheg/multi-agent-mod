"""Offline checks for orchestration invariants and project-scoped memory."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "execution"))
import mam


class HarnessTests(unittest.TestCase):
    def test_self_review_rejects_same_alias_and_identity(self):
        same = {"name": "t", "nodes": [
            {"id": "a", "agent": "demo-worker", "prompt": "x"},
            {"id": "b", "agent": "demo-worker", "needs": ["a"], "review_of": "a", "prompt": "y"},
        ]}
        with self.assertRaisesRegex(ValueError, "self-review"):
            mam.validate(same)
        config = json.loads((Path(mam.HOME) / "examples/default-config.json").read_text())
        config["agents"]["alias"] = dict(config["agents"]["demo-worker"])
        config["reviewers"] = {"demo-worker": ["alias"]}
        registry = mam.ProviderRegistry(config)
        self.assertEqual(registry.reviewer_candidates("demo-worker"), [])
        config["agents"]["alias"]["author_identity"] = "independent"
        registry = mam.ProviderRegistry(config)
        self.assertEqual(registry.reviewer_candidates("demo-worker"), ["alias"])

    def test_placeholders_require_dependencies_and_render_once(self):
        with self.assertRaises(ValueError):
            mam.validate({"name": "t", "nodes": [{"id": "a", "agent": "demo-worker", "prompt": "{ghost}"}]})
        self.assertEqual(mam.render("{a}", {"a": "see {b}", "b": "SECRET"}), "see {b}")

    def test_verdict_parser_fails_closed(self):
        self.assertEqual(mam.parse_verdict('remark {"pass": false, "issues": ["bad"]}'),
                         (False, ["bad"]))
        self.assertFalse(mam.parse_verdict("no verdict")[0])

    def test_memory_scope_and_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(mam, "MEM", root / "memory"), patch.dict(mam.CFG, {"memory_max_chars": 1000}):
                mam.mem_write("brain", "fact", "one", "decision", "durable", "global")
                self.assertIn("durable", mam.mem_context("durable"))
                self.assertEqual(mam.mem_search("missing", 3), [])

    def test_graph_runs_with_mocked_demo_agents(self):
        spec = {"name": "tiny", "nodes": [
            {"id": "a", "agent": "demo-worker", "prompt": "input={input}", "memory": False},
            {"id": "b", "agent": "demo-reviewer", "needs": ["a"], "prompt": "{a}", "memory": False},
        ]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "WORK", Path(tmp)), \
                patch.object(mam, "RUNS", Path(tmp) / ".mam"), \
                patch.object(mam, "run_agent", side_effect=lambda agent, prompt, *args, **kwargs: agent + ":" + prompt):
            results, _, failed = mam.run_graph(spec, {"input": "x"}, quiet=True)
        self.assertFalse(failed)
        self.assertIn("demo-reviewer", results["b"])

    def test_ask_out_prints_head_and_wait_reports_failures(self):
        import argparse, io
        from contextlib import redirect_stdout

        def ask(out, reply):
            args = argparse.Namespace(agent="demo-worker", prompt="p", memory=False, reasoning=None,
                                      effort="auto", task_kind=None, model=None, out=str(out))
            with patch.object(mam, "run_agent", side_effect=reply), redirect_stdout(io.StringIO()) as buf:
                try:
                    mam.cmd_ask(args)
                except SystemExit as e:
                    return buf.getvalue(), e.code
            return buf.getvalue(), 0

        def wait(*files, timeout=0):
            with redirect_stdout(io.StringIO()) as buf, self.assertRaises(SystemExit) as e:
                mam.cmd_wait(argparse.Namespace(files=[str(f) for f in files], timeout=timeout))
            return buf.getvalue(), e.exception.code

        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "RUNS", Path(tmp) / ".mam"):
            ok, bad, missing = Path(tmp) / "ok.md", Path(tmp) / "bad.md", Path(tmp) / "none.md"
            printed, code = ask(ok, lambda *a, **k: "\n".join(f"line {i}" for i in range(20)))
            self.assertEqual(code, 0)
            self.assertIn("line 4", printed)
            self.assertNotIn("line 5", printed)
            self.assertIn("line 19", ok.read_text(encoding="utf-8"))

            _, code = ask(bad, mam.AgentError("logged out"))
            self.assertEqual(code, 1)
            self.assertEqual(wait(ok)[1], 0)
            printed, code = wait(ok, bad)
            self.assertEqual(code, 1)
            self.assertIn("logged out", printed)
            printed, code = wait(ok, missing)
            self.assertEqual(code, 2)
            self.assertIn("still running", printed)

    def test_graph_runs_with_runs_dir_outside_workspace(self):
        spec = {"name": "tiny", "nodes": [
            {"id": "a", "agent": "demo-worker", "prompt": "input={input}", "memory": False},
        ]}
        with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory() as runs,                 patch.object(mam, "WORK", Path(work)), patch.object(mam, "RUNS", Path(runs)),                 patch.object(mam, "run_agent", side_effect=lambda agent, prompt, *args, **kwargs: agent + ":" + prompt):
            results, run_dir, failed = mam.run_graph(spec, {"input": "x"}, quiet=True)
            self.assertFalse(failed)
            self.assertEqual(results["a"], "demo-worker:input=x")
            self.assertEqual(run_dir.parent, Path(runs))
            self.assertIn(run_dir.as_posix(), (run_dir / "journal.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
