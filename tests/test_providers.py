import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "execution"))
from providers import ProviderConfigError, ProviderRegistry, load_config, validate_config
from worker_cli import invoke


def config(identity_a="team-a", identity_b="team-b"):
    return {
        "providers": {
            "third-party": {
                "argv": ["{python}", "{package_dir}/demo/offline_provider.py"],
                "input": "stdin", "output": "text",
                "model_args": ["--model", "{model}"],
                "effort_args": ["--effort", "{effort}"],
                "models": {"default": {"supported_effort": ["low", "medium", "high"]}},
                "default_model": "default", "author_identity": identity_a,
                "timeout_seconds": 10,
            },
            "review": {
                "argv": ["{python}", "{package_dir}/demo/offline_provider.py"],
                "input": "stdin", "output": "text",
                "model_args": ["--model", "{model}"],
                "effort_args": ["--effort", "{effort}"],
                "models": {"default": {"supported_effort": ["low", "medium", "high"]}},
                "default_model": "default", "author_identity": identity_b,
                "timeout_seconds": 10,
            },
        },
        "agents": {
            "worker": {"provider": "third-party", "model": "default", "role": "worker"},
            "reviewer": {"provider": "review", "model": "default", "role": "reviewer"},
        },
        "reviewers": {"worker": ["reviewer"]},
        "role_bindings": {"summary": "worker"},
    }


class ProviderTests(unittest.TestCase):
    def test_arbitrary_provider_runs_offline_and_records_effort(self):
        registry = ProviderRegistry(config())
        with tempfile.TemporaryDirectory() as tmp:
            result = invoke("hello", Path(tmp), {"agent": "worker", "effort": "high"}, registry=registry)
            self.assertIn("DEMO PROVIDER", result["result"])
            self.assertIn("--effort", json.loads((Path(tmp) / "argv.json").read_text())["argv"])
            decision = json.loads((Path(tmp) / "reasoning.json").read_text())
            self.assertEqual(decision["effective"], "high")
            self.assertEqual(decision["provider"], "third-party")

    def test_invalid_config_is_rejected_before_subprocess(self):
        bad = config()
        del bad["providers"]["third-party"]["models"]
        with self.assertRaises(ProviderConfigError):
            validate_config(bad)

    def test_role_prompts_fresh_resumed_unknown_and_agent_default(self):
        cfg = config()
        cfg["providers"]["third-party"].update(
            session_persistence=True, resume_args=["--resume", "{session_id}"])
        cfg["role_prompts"] = {"review": ["rules/common.md", "rules/review.md"]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rules").mkdir()
            (root / "rules" / "common.md").write_text("Common rules", encoding="utf-8")
            (root / "rules" / "review.md").write_text("Review rules", encoding="utf-8")
            config_path = root / "config.json"
            config_path.write_text(json.dumps(cfg), encoding="utf-8")
            registry = ProviderRegistry(load_config(config_path))
            with patch("worker_cli.subprocess.run",
                       return_value=SimpleNamespace(stdout="ok", stderr="", returncode=0)) as process:
                invoke("task", root / "fresh", {"agent": "worker", "role": "review"}, registry=registry)
                self.assertEqual(process.call_args.kwargs["input"],
                                 "ROLE: review\n\nCommon rules\n\nReview rules\n\n---\n\ntask")
                invoke("delta", root / "resumed", {"agent": "worker", "role": "review"},
                       registry=registry, session_id="old-session")
                self.assertEqual(process.call_args.kwargs["input"], "ROLE: review\n\ndelta")
                invoke("other", root / "unknown", {"agent": "worker", "role": "unknown"},
                       registry=registry)
                self.assertEqual(process.call_args.kwargs["input"], "ROLE: unknown\n\nother")
                invoke("plain", root / "default", {"agent": "worker"}, registry=registry)
                self.assertEqual(process.call_args.kwargs["input"], "ROLE: worker\n\nplain")

    def test_role_prompts_validation_and_missing_file(self):
        cfg = config()
        for bad in ([], {"review": []}, {"review": [""]}, {"review": [7]}):
            cfg["role_prompts"] = bad
            with self.assertRaises(ProviderConfigError):
                validate_config(cfg)
        cfg["role_prompts"] = {"review": ["missing.md"]}
        self.assertEqual(validate_config(cfg)["role_prompts"], cfg["role_prompts"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            registry = ProviderRegistry(load_config(path))
            self.assertEqual(registry.config["role_prompts"], cfg["role_prompts"])
            with patch("worker_cli.subprocess.run", side_effect=AssertionError("spawned")):
                with self.assertRaisesRegex(ProviderConfigError, "role_prompts.review"):
                    invoke("task", Path(tmp) / "run", {"agent": "worker", "role": "review"},
                           registry=registry)

    def test_aliases_with_same_identity_are_not_reviewers(self):
        cfg = config(identity_b="team-a")
        registry = ProviderRegistry(cfg)
        self.assertEqual(registry.reviewer_candidates("worker"), [])

    def test_session_ids_are_captured_from_json_and_stderr(self):
        cfg = config()
        cfg["providers"]["third-party"].update(
            session_persistence=True, session_id_field="session_id",
            resume_args=["--resume", "{session_id}"])
        cfg["providers"]["review"].update(
            session_persistence=True, session_id_regex=r"session id: ([^\s]+)")
        registry = ProviderRegistry(cfg)
        self.assertEqual(registry.session_id("worker", '{"session_id":"claude-1"}', "", None, agent=True), "claude-1")
        self.assertEqual(registry.session_id("reviewer", "", "session id: codex-2", None, agent=True), "codex-2")

    def test_resume_argv_uses_provider_layout(self):
        cfg = config()
        cfg["providers"]["review"].update(
            session_persistence=True,
            resume_argv=["{package_dir}/demo/offline_provider.py", "exec", "resume", "{session_id}"])
        registry = ProviderRegistry(cfg)
        self.assertEqual(registry.command("reviewer", "run", session_id="s-1"), [
            "{python}".format(python=sys.executable),
            str(Path(__file__).resolve().parents[1]) + "/demo/offline_provider.py",
            "exec", "resume", "--model", "default", "s-1"
        ])

    def test_codex_and_claude_resume_argv(self):
        cfg = config()
        cfg["providers"]["review"].update(
            argv=["codex", "exec", "--skip-git-repo-check", "--color", "never"],
            session_persistence=True,
            resume_argv=["exec", "resume", "--skip-git-repo-check", "-c",
                         "project_doc_max_bytes=0", "--ignore-user-config", "--disable",
                         "plugins", "--disable", "apps", "{session_id}", "-"],
            model_args=["-m", "{model}"],
            effort_args=["-c", 'model_reasoning_effort="{effort}"'],
            sandbox_args=["-s", "{sandbox}"],
            resume_sandbox_args=["-c", 'sandbox_mode="{sandbox}"'],
            default_sandbox="workspace-write")
        cfg["providers"]["third-party"].update(
            argv=["claude", "-p", "--output-format", "json"],
            session_persistence=True, resume_args=["--resume", "{session_id}"])
        registry = ProviderRegistry(cfg)
        codex = registry.command("reviewer", "run", effort="low", session_id="codex-1")
        self.assertEqual(codex, ["codex", "exec", "resume", "--skip-git-repo-check", "-c",
                                 "project_doc_max_bytes=0", "--ignore-user-config", "--disable",
                                 "plugins", "--disable", "apps", "-m", "default", "-c",
                                 'model_reasoning_effort="low"', "-c",
                                 'sandbox_mode="workspace-write"', "codex-1", "-"])
        self.assertNotIn("--color", codex)
        self.assertNotIn("-s", codex)
        claude = registry.command("worker", "run", session_id="claude-1")
        self.assertEqual(claude[:5], ["claude", "-p", "--output-format", "json", "--resume"])
        self.assertIn("claude-1", claude)

    def test_removed_resume_drop_args_is_rejected(self):
        cfg = config()
        cfg["providers"]["review"]["resume_drop_args"] = ["--no-session-persistence"]
        with self.assertRaises(ProviderConfigError):
            ProviderRegistry(cfg)

    def test_initiator_detection_requires_configured_alias(self):
        cfg = config()
        cfg["initiator_detection"] = [{"env": "HOST_SESSION", "agent": "missing"}]
        with self.assertRaises(ProviderConfigError):
            ProviderRegistry(cfg)
        cfg["initiator_detection"] = [{"env": "HOST_SESSION", "agent": "reviewer"}]
        self.assertEqual(ProviderRegistry(cfg).config["initiator_detection"], cfg["initiator_detection"])


if __name__ == "__main__":
    unittest.main()
