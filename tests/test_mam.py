"""Offline checks for orchestration invariants and project-scoped memory."""

import argparse
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "execution"))
import mam


class HarnessTests(unittest.TestCase):
    def test_initiator_precedence(self):
        cfg = {"agents": {"claude-review": {"role": "review"},
                           "codex-review": {"role": "review"}},
               "initiator_detection": [{"env": "TEST_CODEX", "agent": "codex-review"}]}
        with patch.object(mam, "CFG", cfg), patch.dict(mam.os.environ, {}, clear=True):
            self.assertIsNone(mam.detect_initiator())
            mam.os.environ["TEST_CODEX"] = "yes"
            self.assertEqual(mam.detect_initiator(), "codex-review")
            mam.os.environ["MAM_INITIATOR"] = "claude-review"
            self.assertEqual(mam.detect_initiator(), "claude-review")
            mam.os.environ["MAM_INITIATOR"] = "codex-review"
            self.assertEqual(mam.detect_initiator("claude-review"), "claude-review")
            self.assertEqual(mam.detect_initiator(), "codex-review")

    def test_no_detected_coordinator_spawns_judge(self):
        cfg = json.loads((Path(mam.HOME) / "examples/default-config.json").read_text())
        cfg["agents"]["claude-opus"] = dict(cfg["agents"]["demo-reviewer"])
        spec = {"name": "no-pause", "nodes": [
            {"id": "judge", "agent": "claude-opus", "prompt": "judge", "memory": False}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "CFG", cfg), \
                patch.object(mam, "REGISTRY", mam.ProviderRegistry(cfg)), \
                patch.object(mam, "RUNS", Path(tmp) / ".mam"), \
                patch.dict(mam.os.environ, {}, clear=True), \
                patch.object(mam, "run_agent", return_value="spawned") as worker:
            results, run_dir, failed = mam.run_graph(spec, {}, quiet=True)
            self.assertFalse(failed)
            self.assertEqual(results["judge"], "spawned")
            self.assertEqual(json.loads((run_dir / "state.json").read_text())["status"], "complete")
            worker.assert_called_once()

    def test_coordinator_handoff_and_graph_resume_without_spawning(self):
        spec = {"name": "handoff", "nodes": [
            {"id": "review", "agent": "demo-worker", "prompt": "review {input}", "memory": False}
        ]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "RUNS", Path(tmp) / ".mam"), \
                patch.object(mam, "detect_initiator", return_value="demo-worker"), \
                patch.dict(mam.CFG, {"role_prompts": {"review": [str(Path(tmp) / "role.md")]}}), \
                patch.object(mam, "run_agent", side_effect=AssertionError("coordinator was spawned")):
            (Path(tmp) / "role.md").write_text("REVIEW RULES", encoding="utf-8")
            results, run_dir, failed = mam.run_graph(spec, {"input": "x"}, quiet=True)
            self.assertFalse(failed)
            self.assertTrue((run_dir / "review" / "coordinator-handoff.md").exists())
            self.assertNotIn("ROLE:", (run_dir / "review" / "coordinator-handoff.md").read_text())
            self.assertNotIn("REVIEW RULES", (run_dir / "review" / "coordinator-handoff.md").read_text())
            self.assertEqual(json.loads((run_dir / "state.json").read_text())["status"], "paused")
            mam._step_file(run_dir, "review").parent.mkdir()
            mam._step_file(run_dir, "review").write_text('{"pass": true}', encoding="utf-8")
            results, _, failed = mam.run_graph({}, {}, quiet=True, run_dir=run_dir, resume=True)
            self.assertFalse(failed)
            self.assertEqual(results["review"], '{"pass": true}')

    def test_role_resolution_for_ask_review_graph_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "RUNS", Path(tmp) / ".mam"), \
                patch.object(mam, "detect_initiator", return_value=None):
            ask = argparse.Namespace(agent="demo-worker", prompt="task", memory=False,
                                     reasoning=None, effort="auto", task_kind=None,
                                     model=None, out=None, thread=None, role="qa")
            with patch.object(mam, "run_agent", return_value="answer") as worker, \
                    redirect_stdout(io.StringIO()):
                mam.cmd_ask(ask)
            self.assertEqual(worker.call_args.kwargs["role"], "qa")
            target = Path(tmp) / "diff.txt"
            target.write_text("diff", encoding="utf-8")
            review = argparse.Namespace(author="demo-worker", by="demo-reviewer", path=str(target),
                                        task="task", criteria=["correct"], reasoning=None,
                                        effort="auto", task_kind=None, model=None, out=None,
                                        thread=None, initiator=None, no_in_session=False, role=None)
            with patch.object(mam, "run_agent", return_value="answer") as worker, \
                    redirect_stdout(io.StringIO()):
                mam.cmd_review(review)
            self.assertEqual(worker.call_args.kwargs["role"], "review")
            review.role = "qa"
            with patch.object(mam, "run_agent", return_value="answer") as worker, \
                    redirect_stdout(io.StringIO()):
                mam.cmd_review(review)
            self.assertEqual(worker.call_args.kwargs["role"], "qa")
            node = {"id": "graph-role", "agent": "demo-worker", "prompt": "task",
                    "memory": False, "role": "research"}
            with patch.object(mam, "run_agent", return_value="answer") as worker:
                mam.run_node(node, {}, Path(tmp) / "graph", lambda _: None)
            self.assertEqual(worker.call_args.kwargs["role"], "research")
            node = {"id": "verify-role", "agent": "demo-worker", "prompt": "task",
                    "memory": False, "verify": {"by": "demo-reviewer", "criteria": ["correct"]}}
            with patch.object(mam, "run_agent", side_effect=[
                    "answer", '{"pass": true, "issues": []}']) as worker:
                mam.run_node(node, {}, Path(tmp) / "graph", lambda _: None)
            self.assertEqual(worker.call_args_list[1].kwargs["role"], "review")
            node["id"] = "verify-override"
            node["role"] = "qa"
            with patch.object(mam, "run_agent", side_effect=[
                    "answer", '{"pass": true, "issues": []}']) as worker:
                mam.run_node(node, {}, Path(tmp) / "graph", lambda _: None)
            self.assertEqual([call.kwargs["role"] for call in worker.call_args_list], ["qa", "qa"])

    def test_doctor_flags_missing_role_prompt_file(self):
        cfg = json.loads((Path(mam.HOME) / "examples/default-config.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            cfg["role_prompts"] = {"review": [str(Path(tmp) / "missing.md")]}
            with patch.object(mam, "CFG", cfg), \
                    patch.object(mam, "REGISTRY", mam.ProviderRegistry(cfg)), \
                    patch.object(mam, "_notes", return_value=[]), \
                    patch.object(mam, "mem_lint", return_value=[]), \
                    redirect_stdout(io.StringIO()) as output:
                mam.cmd_doctor(argparse.Namespace(deep=False))
            self.assertIn("missing.md", output.getvalue())
            self.assertIn("MISS", output.getvalue())

    def test_no_in_session_restores_spawn(self):
        spec = {"name": "legacy", "nodes": [
            {"id": "a", "agent": "demo-worker", "prompt": "x", "memory": False}
        ]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "RUNS", Path(tmp) / ".mam"), \
                patch.object(mam, "detect_initiator", return_value="demo-worker"), \
                patch.object(mam, "run_agent", return_value="spawned") as worker:
            results, _, failed = mam.run_graph(spec, {}, quiet=True, no_in_session=True)
            self.assertFalse(failed)
            self.assertEqual(results["a"], "spawned")
            worker.assert_called_once()

    def test_resume_failure_falls_back_once_and_logs(self):
        cfg = json.loads((Path(mam.HOME) / "examples/default-config.json").read_text())
        cfg["providers"]["demo"].update(session_persistence=True, session_id_field="session_id")
        registry = mam.ProviderRegistry(cfg)
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "REGISTRY", registry), \
                patch.object(mam, "WORK", Path(tmp)):
            root, node = Path(tmp) / "run", Path(tmp) / "run" / "node"
            root.mkdir()
            session_file = mam._session_file(root, "node", "demo-worker")
            session_file.parent.mkdir()
            session_file.write_text("old", encoding="utf-8")
            with patch.object(mam.worker_cli, "invoke", side_effect=[ValueError("expired"),
                                                                         {"result": "fresh", "session_id": "new"}]) as invoke:
                self.assertEqual(mam.run_agent("demo-worker", "delta", node, session_dir=root,
                                               session_key="node", fallback_prompt="original task"), "fresh")
            self.assertEqual(invoke.call_count, 2)
            self.assertEqual(invoke.call_args_list[0].args[0], "delta")
            self.assertEqual(invoke.call_args_list[1].args[0], "original task")
            self.assertEqual(session_file.read_text(), "new")
            self.assertIn("fell back", (root / "resume-fallback.log").read_text())

    def test_nonpersistent_rounds_send_full_task(self):
        node = {"id": "work", "agent": "demo-worker", "prompt": "ORIGINAL TASK",
                "memory": False, "verify": {"by": "demo-reviewer", "criteria": ["correct"],
                                           "max_rounds": 2}}
        replies = [{"result": "first"}, {"result": '{"pass": false, "issues": ["fix"]}'},
                   {"result": "second"}, {"result": '{"pass": true, "issues": []}'}]
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(mam.worker_cli, "invoke", side_effect=replies) as invoke:
            self.assertEqual(mam.run_node(node, {}, Path(tmp), lambda _: None), "second")
            self.assertIn("ORIGINAL TASK", invoke.call_args_list[2].args[0])
            self.assertIn("ORIGINAL TASK", invoke.call_args_list[3].args[0])

    def test_sessions_are_scoped_to_node_and_reused_within_node(self):
        cfg = json.loads((Path(mam.HOME) / "examples/default-config.json").read_text())
        cfg["providers"]["demo"]["session_persistence"] = True
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "REGISTRY", mam.ProviderRegistry(cfg)), \
                patch.object(mam.worker_cli, "invoke", side_effect=[
                    {"result": "a", "session_id": "session-a"},
                    {"result": "b", "session_id": "session-b"},
                    {"result": "a2", "session_id": "session-a"}]) as invoke:
            root = Path(tmp)
            mam.run_agent("demo-worker", "task A", root / "a", session_dir=root, session_key="node-a")
            mam.run_agent("demo-worker", "task B", root / "b", session_dir=root, session_key="node-b")
            mam.run_agent("demo-worker", "delta A", root / "a2", session_dir=root,
                          session_key="node-a", fallback_prompt="task A full")
            self.assertNotEqual(mam._session_file(root, "node-a", "demo-worker"),
                                mam._session_file(root, "node-b", "demo-worker"))
            self.assertIsNone(invoke.call_args_list[1].kwargs["session_id"])
            self.assertEqual(invoke.call_args_list[2].kwargs["session_id"], "session-a")
            self.assertEqual(invoke.call_args_list[2].args[0], "delta A")

    def test_rounds_block_resumes_with_new_artifacts_only(self):
        cfg = json.loads((Path(mam.HOME) / "examples/default-config.json").read_text())
        cfg["providers"]["demo"]["session_persistence"] = True
        block = {"id": "trial", "rounds": {"max": 2, "until": "judge", "nodes": [
            {"id": "charge", "agent": "demo-worker", "prompt": "ORIGINAL TASK\n{previous}",
             "memory": False},
            {"id": "judge", "agent": "demo-reviewer", "prompt": "Judge {charge} {previous}",
             "memory": False}]}}
        replies = [{"result": "first charge", "session_id": "worker-id"},
                   {"result": '{"pass": false, "issues": ["retry"]}', "session_id": "judge-id"},
                   {"result": "second charge", "session_id": "worker-id"},
                   {"result": '{"pass": true, "issues": []}', "session_id": "judge-id"}]
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "REGISTRY", mam.ProviderRegistry(cfg)), \
                patch.object(mam.worker_cli, "invoke", side_effect=replies) as invoke:
            root = Path(tmp)
            result = mam.run_rounds(block, {"_mam_session_dir": root}, root, lambda _: None)
            self.assertIn('"pass": true', result)
            self.assertEqual(invoke.call_args_list[2].kwargs["session_id"], "worker-id")
            self.assertIn("first charge", invoke.call_args_list[2].args[0])
            self.assertNotIn("ORIGINAL TASK", invoke.call_args_list[2].args[0])

    def test_verdict_replays_original_author_output(self):
        cfg = json.loads((Path(mam.HOME) / "examples/default-config.json").read_text())
        spec = {"name": "replay", "nodes": [{"id": "work", "agent": "demo-worker",
            "prompt": "ORIGINAL TASK", "memory": False,
            "verify": {"by": "demo-reviewer", "criteria": ["correct"], "max_rounds": 1}}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "RUNS", Path(tmp) / ".mam"), \
                patch.object(mam, "CFG", cfg), patch.object(mam, "REGISTRY", mam.ProviderRegistry(cfg)), \
                patch.object(mam, "run_agent", return_value="ORIGINAL OUTPUT") as worker:
            _, run_dir, failed = mam.run_graph(spec, {}, quiet=True, initiator="demo-reviewer")
            self.assertFalse(failed)
            self.assertEqual(worker.call_count, 1)
            verdict = Path(tmp) / "verdict.json"
            verdict.write_text('{"pass": true, "issues": []}', encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                mam.cmd_verdict(argparse.Namespace(run=str(run_dir), file=str(verdict),
                                                   no_resume=False, initiator=None,
                                                   no_in_session=False))
            self.assertEqual(worker.call_count, 1)
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["results"]["work"], "ORIGINAL OUTPUT")
            self.assertEqual(state["status"], "complete")

    def test_review_thread_resumes_and_coordinator_short_circuits(self):
        cfg = json.loads((Path(mam.HOME) / "examples/default-config.json").read_text())
        cfg["providers"]["demo"]["session_persistence"] = True
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "RUNS", Path(tmp) / ".mam"), \
                patch.object(mam, "REGISTRY", mam.ProviderRegistry(cfg)), \
                patch.object(mam, "detect_initiator", return_value=None), \
                patch.object(mam.worker_cli, "invoke", side_effect=[
                    {"result": "first review", "session_id": "review-session"},
                    {"result": "second review", "session_id": "review-session"}]) as invoke:
            target = Path(tmp) / "diff.txt"
            target.write_text("new output", encoding="utf-8")
            args = argparse.Namespace(author="demo-worker", by="demo-reviewer", path=str(target),
                                      task="task", criteria=["correct"], reasoning=None,
                                      effort="auto", task_kind=None, model=None, out=None,
                                      thread="review-case", initiator=None, no_in_session=False)
            with redirect_stdout(io.StringIO()):
                mam.cmd_review(args)
                mam.cmd_review(args)
            self.assertEqual((Path(tmp) / ".mam" / "threads" / "review-case" /
                              "demo-reviewer.id").read_text(), "review-session")
            self.assertEqual(invoke.call_args_list[1].kwargs["session_id"], "review-session")
            self.assertTrue(invoke.call_args_list[1].args[0].startswith("Round continuation:"))
            self.assertNotIn("Criteria:", invoke.call_args_list[1].args[0])
            with patch.object(mam, "detect_initiator", return_value="demo-reviewer"), \
                    patch.object(mam, "run_agent", side_effect=AssertionError("spawned")), \
                    redirect_stdout(io.StringIO()) as output:
                mam.cmd_review(args)
            self.assertIn("reviewer is the coordinator (demo-reviewer)", output.getvalue())

    def test_ask_thread_fallback_contains_initial_task(self):
        cfg = json.loads((Path(mam.HOME) / "examples/default-config.json").read_text())
        cfg["providers"]["demo"]["session_persistence"] = True
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "RUNS", Path(tmp) / ".mam"), \
                patch.object(mam, "REGISTRY", mam.ProviderRegistry(cfg)), \
                patch.object(mam.worker_cli, "invoke", side_effect=[
                    {"result": "initial", "session_id": "ask-session"},
                    ValueError("resume expired"), {"result": "recovered", "session_id": "fresh"}]) as invoke:
            args = argparse.Namespace(agent="demo-worker", prompt="ORIGINAL TASK", memory=False,
                                      reasoning=None, effort="auto", task_kind=None,
                                      model=None, out=None, thread="ask-case")
            with redirect_stdout(io.StringIO()):
                mam.cmd_ask(args)
                args.prompt = "new feedback"
                mam.cmd_ask(args)
            self.assertEqual(invoke.call_args_list[1].args[0], "new feedback")
            self.assertEqual(invoke.call_args_list[1].kwargs["session_id"], "ask-session")
            self.assertIn("ORIGINAL TASK", invoke.call_args_list[2].args[0])
            self.assertIn("new feedback", invoke.call_args_list[2].args[0])

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
