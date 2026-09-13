"""Provider `env`: credential references, clearing inherited variables, model
expansion, fail-closed when a referenced variable is unset, and the backend
presets that rely on it."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "execution"))
import cold_start
import mam
from providers import ProviderConfigError, ProviderRegistry, validate_config
import worker_cli

ECHO_ENV = """
import json, os, sys
sys.stdin.read()
print(json.dumps({"result": "ok", "is_error": False,
                  "base": os.environ.get("ANTHROPIC_BASE_URL"),
                  "token": os.environ.get("ANTHROPIC_AUTH_TOKEN"),
                  "api_key_present": "ANTHROPIC_API_KEY" in os.environ,
                  "model_env": os.environ.get("ANTHROPIC_MODEL")}))
"""


def _config(env, script=None):
    base = json.loads((ROOT / "examples/default-config.json").read_text(encoding="utf-8"))
    provider = copy.deepcopy(base["providers"]["demo"])
    if script:
        provider.update(argv=[sys.executable, str(script)], output="json", model_args=[], effort_args=[])
    provider["env"] = env
    base["providers"] = {"demo": provider}
    return base


class EnvValidationTests(unittest.TestCase):
    def test_credentials_must_be_references(self):
        for env, why in (({"ANTHROPIC_AUTH_TOKEN": "sk-literal-value"}, "looks like a credential"),
                         ({"X_API_KEY": "${A}suffix"}, "whole value"),
                         ({"bad-name": "x"}, "invalid variable name"),
                         ({"MODEL_HINT": "{effort}"}, "only {model}"),
                         ({"N": 5}, "must be a string")):
            with self.subTest(why=why), self.assertRaisesRegex(ProviderConfigError, why):
                validate_config(_config(env))
        validate_config(_config({"ANTHROPIC_AUTH_TOKEN": "${MY_TOKEN}", "ANTHROPIC_API_KEY": "",
                                 "ANTHROPIC_BASE_URL": "https://example.test", "ANTHROPIC_MODEL": "{model}"}))

    def test_environment_resolves_clears_and_fails_closed(self):
        registry = ProviderRegistry(_config({"ANTHROPIC_AUTH_TOKEN": "${MY_TOKEN}", "ANTHROPIC_API_KEY": "",
                                             "ANTHROPIC_MODEL": "{model}"}))
        env = registry.environment("demo", "m1", base={"MY_TOKEN": "t", "ANTHROPIC_API_KEY": "inherited"})
        self.assertEqual((env["ANTHROPIC_AUTH_TOKEN"], env["ANTHROPIC_MODEL"]), ("t", "m1"))
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        with self.assertRaisesRegex(ProviderConfigError, "MY_TOKEN"):
            registry.environment("demo", "m1", base={})


class EnvRoundTripTests(unittest.TestCase):
    def test_subprocess_sees_only_the_provider_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp, "echo_env.py")
            script.write_text(ECHO_ENV, encoding="utf-8")
            config = _config({"ANTHROPIC_BASE_URL": "https://backend.test",
                              "ANTHROPIC_AUTH_TOKEN": "${HARNESS_TEST_TOKEN}",
                              "ANTHROPIC_API_KEY": "", "ANTHROPIC_MODEL": "{model}"}, script)
            registry = ProviderRegistry(config)
            with patch.dict(os.environ, {"HARNESS_TEST_TOKEN": "secret-from-env", "ANTHROPIC_API_KEY": "leak"}):
                out = worker_cli.invoke("hi", Path(tmp, "run"), {"agent": "demo-worker"}, registry=registry)
            self.assertEqual((out["base"], out["token"], out["api_key_present"], out["model_env"]),
                             ("https://backend.test", "secret-from-env", False, "demo"))
            argv_log = Path(tmp, "run", "argv.json").read_text(encoding="utf-8")
            self.assertNotIn("secret-from-env", argv_log, "credentials never land in invocation logs")
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("HARNESS_TEST_TOKEN", None)
                with self.assertRaisesRegex(ProviderConfigError, "HARNESS_TEST_TOKEN"):
                    worker_cli.invoke("hi", Path(tmp, "run2"), {"agent": "demo-worker"}, registry=registry)


class DoctorAndSelectionTests(unittest.TestCase):
    def test_unset_credential_marks_the_agent_missing(self):
        cfg = validate_config(_config({"ANTHROPIC_AUTH_TOKEN": "${HARNESS_UNSET_TOKEN}"}))
        cfg["_config_path"] = "test"
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "CFG", cfg), \
                patch.object(mam, "REGISTRY", ProviderRegistry(cfg)), patch.object(mam, "MEM", Path(tmp)), \
                patch.object(mam, "ROLES_FILE", Path(tmp, "roles.json")), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HARNESS_UNSET_TOKEN", None)
            self.assertIsNone(mam.installed("demo-worker"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                mam.cmd_doctor(types.SimpleNamespace(deep=False))
        self.assertIn("MISS demo-worker", out.getvalue())
        self.assertIn("HARNESS_UNSET_TOKEN", out.getvalue())


class BackendPresetTests(unittest.TestCase):
    def test_backend_presets_are_separate_providers_with_references(self):
        presets = cold_start.load_presets()
        for name in ("claude-deepseek", "claude-glm", "claude-kimi", "claude-qwen"):
            with self.subTest(preset=name):
                env = presets[name]["provider"]["env"]
                self.assertRegex(env["ANTHROPIC_AUTH_TOKEN"], r"^\$\{[A-Z_]+\}$")
                self.assertEqual(env["ANTHROPIC_API_KEY"], "")
                self.assertTrue(env["ANTHROPIC_BASE_URL"].startswith("https://"))
                self.assertNotEqual(presets[name]["vendor"], presets["claude"]["vendor"])

    def test_answers_can_rename_the_credential_variable(self):
        detected = [{"preset": p, "found": True, "path": "C:/tools/claude.cmd"} for p in ("claude", "claude-glm")]
        answers = {"agents": {
            "opus": {"preset": "claude", "model": "opus"},
            "glm": {"preset": "claude-glm", "model": "glm-5.1", "env": {"ANTHROPIC_AUTH_TOKEN": "${MY_GLM_KEY}"}},
            "glm-fast": {"preset": "claude-glm", "model": "glm-5", "env": {"ANTHROPIC_AUTH_TOKEN": "${OTHER}"}}}}
        with self.assertRaisesRegex(cold_start.SetupError, "conflicts"):
            cold_start.build(answers, detected=detected)
        del answers["agents"]["glm-fast"]
        answers["reviewers"] = {"glm": ["opus"]}
        answers["review_policy"] = {"primary": "other_provider"}
        config, _ = cold_start.build(answers, detected=detected)
        self.assertEqual(config["providers"]["claude-glm"]["env"]["ANTHROPIC_AUTH_TOKEN"], "${MY_GLM_KEY}")
        self.assertTrue(ProviderRegistry(config).primary_allowed("glm", "opus"),
                        "Claude Code with GLM inside is not the same provider as Anthropic")

    def test_every_preset_says_whether_it_ran_live(self):
        for name, preset in cold_start.load_presets().items():
            with self.subTest(preset=name):
                self.assertRegex(preset["checked"], r"run live|not run live")


if __name__ == "__main__":
    unittest.main()
