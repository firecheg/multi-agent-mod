import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "execution"))
from providers import ProviderConfigError, ProviderRegistry, validate_config
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

    def test_aliases_with_same_identity_are_not_reviewers(self):
        cfg = config(identity_b="team-a")
        registry = ProviderRegistry(cfg)
        self.assertEqual(registry.reviewer_candidates("worker"), [])


if __name__ == "__main__":
    unittest.main()
