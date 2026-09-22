"""Cold start: presets, detection, config generation, and a real subprocess
round trip through fake CLIs (no accounts, no network)."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "execution"))
import cold_start
from providers import ProviderConfigError, ProviderRegistry, validate_config
import worker_cli

FAKE_CLI = r'''
import json, sys
args = sys.argv[1:]
if "--prompt-file" in args:
    prompt = open(args[args.index("--prompt-file") + 1], encoding="utf-8").read()
    stdin = sys.stdin.read()
else:
    prompt, stdin = sys.stdin.read(), ""
model = args[args.index("--model") + 1] if "--model" in args else None
effort = args[args.index("--effort") + 1] if "--effort" in args else None
print(json.dumps({"result": f"echo:{prompt}", "is_error": False, "model": model,
                  "effort": effort, "stdin_when_file": stdin}))
'''

MATRIX = {
    "agents": {
        "codex-writer": {"preset": "codex", "model": "model-a", "role": "implementation"},
        "codex-checker": {"preset": "codex", "model": "model-b", "role": "review"},
        "claude-sonnet": {"preset": "claude", "model": "sonnet", "role": "implementation"},
        "claude-opus": {"preset": "claude", "model": "opus", "role": "spec, judge"},
    },
    "reviewers": {"codex-writer": ["claude-opus", "codex-checker"],
                  "claude-sonnet": ["codex-checker", "claude-opus"]},
    "review_policy": {"primary": "other_provider"},
    "roles": {"spec": "claude-opus", "implement": ["codex-writer", "claude-sonnet"], "judge": "claude-opus"},
}
DETECTED = [{"preset": "codex", "found": True, "path": "C:/tools/codex.exe"},
            {"preset": "claude", "found": True, "path": "C:/tools/claude.cmd"}]


class PresetTests(unittest.TestCase):
    def test_bundled_presets_build_valid_providers(self):
        presets = cold_start.load_presets()
        self.assertTrue({"claude", "codex", "gemini", "agy"} <= set(presets))
        for name, preset in presets.items():
            with self.subTest(preset=name):
                levels = preset["effort_levels"]
                answers = {"agents": {"a": {"preset": name, "model": "m"}}}
                config, _ = cold_start.build(answers, presets, [{"preset": name, "found": True, "path": "/x/cli"}])
                provider = validate_config(config)["providers"][name]
                self.assertEqual(provider["argv"][0], "/x/cli")
                self.assertEqual(bool(provider["effort_args"]), bool(levels),
                                 "an effort flag exists exactly when effort levels are declared")
                if preset["provider"].get("default_sandbox"):
                    self.assertIn(preset["provider"]["default_sandbox"], preset["sandbox_modes"])
                self.assertTrue(preset.get("checked"), "a preset records what it was checked against")

    def test_preset_argv_must_start_with_bin(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "bad.json").write_text(json.dumps({"name": "bad", "provider": {"argv": ["x"]}}))
            with self.assertRaisesRegex(cold_start.SetupError, "start with"):
                cold_start.load_presets(tmp)


class DetectTests(unittest.TestCase):
    def test_paths_before_commands_newest_first_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp, "v1", "cli.exe"), Path(tmp, "v2", "cli.exe")
            for i, p in enumerate((old, new)):
                p.parent.mkdir()
                p.write_text("x")
                os.utime(p, (1000 + i, 1000 + i))
            preset = {"cli": {"name": "cli", "cli": "Cli", "provider": {"argv": ["{bin}"]},
                              "detect": {"paths": [str(Path(tmp, "*", "cli.exe"))], "commands": ["cli"]}}}
            report = cold_start.detect(preset, which=lambda c: str(new),
                                       run=lambda *a, **k: subprocess.CompletedProcess(a, 0, "cli 9.9\n", ""))
        self.assertEqual(report[0]["path"], os.path.normpath(str(new)))
        self.assertEqual(report[0]["other_paths"], [os.path.normpath(str(old))])
        self.assertEqual(report[0]["version"], "cli 9.9")

    def test_missing_cli_is_reported_not_raised(self):
        preset = {"cli": {"name": "cli", "provider": {"argv": ["{bin}"]}, "detect": {"commands": ["cli"]}}}
        report = cold_start.detect(preset, which=lambda c: None)
        self.assertEqual((report[0]["found"], report[0]["path"], report[0]["version"]), (False, None, None))


class BuildTests(unittest.TestCase):
    def test_matrix_answers_become_a_valid_config(self):
        config, roles = cold_start.build(MATRIX, detected=DETECTED)
        cfg = validate_config(config)
        self.assertEqual(sorted(cfg["providers"]), ["claude", "codex"])
        self.assertEqual(sorted(cfg["providers"]["codex"]["models"]), ["model-a", "model-b"])
        self.assertEqual(cfg["providers"]["codex"]["argv"][0], "C:/tools/codex.exe")
        self.assertEqual(cfg["agents"]["codex-checker"]["author_identity"], "codex-checker")
        registry = ProviderRegistry(config)
        self.assertTrue(registry.primary_allowed("codex-writer", "claude-opus"))
        self.assertFalse(registry.primary_allowed("codex-writer", "codex-checker"))
        self.assertEqual(roles["implement"], ["codex-writer", "claude-sonnet"])

    def test_bad_answers_fail_with_a_question_to_ask(self):
        cases = (
            ({"agents": {"a": {"preset": "codex"}}}, "model is required"),
            ({"agents": {"a": {"preset": "nope", "model": "m"}}}, "unknown preset"),
            ({"agents": {"a": {"preset": "gemini", "model": "m"}}}, "was not detected"),
            ({"agents": {"a": {"preset": "codex", "model": "m"}}, "roles": {"spec": "ghost"}}, "configured agents"),
            ({"agents": {"a": {"preset": "codex", "model": "m", "effort": ["turbo"]}}}, "effort must list"),
            ({"agents": {"a": {"preset": "codex", "model": "m"}, "b": {"preset": "codex", "model": "m",
                                                                         "effort": ["low"]}}}, "other effort levels"),
            ({"agents": {"a": {"preset": "codex", "model": "m"}}, "review_policy": {"primary": "x"}}, "invalid"),
        )
        for answers, why in cases:
            with self.subTest(why=why), self.assertRaisesRegex(cold_start.SetupError, why):
                cold_start.build(answers, detected=DETECTED)

    def test_explicit_path_works_when_detection_missed(self):
        answers = {"agents": {"g": {"preset": "gemini", "model": "gemini-pro", "path": "D:/bin/gemini.cmd"}}}
        config, _ = cold_start.build(answers, detected=[])
        self.assertEqual(config["providers"]["gemini"]["argv"][0], "D:/bin/gemini.cmd")

    def test_write_refuses_to_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, roles = Path(tmp, "c", "config.json"), Path(tmp, "roles.json")
            cold_start.write(MATRIX, cfg, roles, detected=DETECTED)
            self.assertEqual(json.loads(roles.read_text())["spec"], "claude-opus")
            with self.assertRaisesRegex(cold_start.SetupError, "refusing to overwrite"):
                cold_start.write(MATRIX, cfg, roles, detected=DETECTED)
            cold_start.write(MATRIX, cfg, roles, force=True, detected=DETECTED)


class InputModeTests(unittest.TestCase):
    def test_prompt_file_token_and_input_mode_must_agree(self):
        base = json.loads((ROOT / "examples/default-config.json").read_text(encoding="utf-8"))
        demo = base["providers"]["demo"]
        for provider, why in (({**demo, "input": "file"}, "requires {prompt_file} in argv"),
                              ({**demo, "argv": [*demo["argv"], "{prompt_file}"]}, "requires input 'file'"),
                              ({**demo, "input": "socket"}, "must be 'stdin' or 'file'")):
            with self.subTest(why=why), self.assertRaisesRegex(ProviderConfigError, why):
                validate_config({**base, "providers": {"demo": provider}})


class FakeCliRoundTripTests(unittest.TestCase):
    """Generated config -> real subprocess through worker_cli, both input modes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        script = self.tmp / "fake_cli.py"
        script.write_text(FAKE_CLI, encoding="utf-8")
        common = {"output": "json", "model_args": ["--model", "{model}"],
                  "effort_args": ["--effort", "{effort}"], "timeout_seconds": 30}
        self.presets = {
            "piped": {"name": "piped", "vendor": "north", "effort_levels": ["low", "high"],
                      "provider": {"argv": ["{bin}", str(script)], "input": "stdin", **common}},
            "filed": {"name": "filed", "vendor": "south", "effort_levels": ["low", "high"],
                      "provider": {"argv": ["{bin}", str(script), "--prompt-file", "{prompt_file}"],
                                   "input": "file", **common}},
        }
        detected = [{"preset": p, "found": True, "path": sys.executable} for p in self.presets]
        answers = {"agents": {"writer": {"preset": "piped", "model": "w1"},
                              "reader": {"preset": "filed", "model": "r1"}},
                   "reviewers": {"writer": ["reader"]}, "review_policy": {"primary": "other_provider"}}
        config, _ = cold_start.build(answers, self.presets, detected)
        self.registry = ProviderRegistry(config)

    def tearDown(self):
        self._tmp.cleanup()

    def test_stdin_and_file_providers_answer(self):
        sent = "ROLE: worker\n\nhello from harness"
        for agent, stdin_expected in (("writer", None), ("reader", "")):
            with self.subTest(agent=agent):
                run = self.tmp / "runs" / agent
                out = worker_cli.invoke("hello from harness", run,
                                        {"agent": agent, "effort": "high"}, registry=self.registry, cwd=self.tmp)
                self.assertEqual(out["result"], "echo:" + sent)
                self.assertEqual(out["effort"], "high")
                if stdin_expected is not None:
                    self.assertEqual(out["stdin_when_file"], stdin_expected, "file mode leaves stdin empty")
                    self.assertEqual((run / "prompt.md").read_text(encoding="utf-8"), sent)

    def test_setup_cli_writes_config_that_doctor_loads(self):
        answers = {"agents": {"g": {"preset": "gemini", "model": "gemini-x", "path": sys.executable}}}
        (self.tmp / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("MAM_", "AGENT_HARNESS_"))}
        env.update(AGENT_HARNESS_MEMORY=str(self.tmp / "mem"), AGENT_HARNESS_ROLES=str(self.tmp / "roles.json"))
        cfg = self.tmp / "out" / "config.json"
        write = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "mam.py"), "setup", "write",
                                str(self.tmp / "answers.json"), "--config-out", str(cfg)],
                               cwd=self.tmp, env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(write.returncode, 0, write.stderr)
        doctor = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "mam.py"), "--config", str(cfg), "doctor"],
                                cwd=self.tmp, env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        self.assertIn("provider=gemini model=gemini-x", doctor.stdout)


if __name__ == "__main__":
    unittest.main()
