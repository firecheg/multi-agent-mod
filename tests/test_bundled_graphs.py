"""Bundled graphs stay valid, neutral and bindable under a realistic roster."""

import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "execution"))
import mam
from providers import validate_config

GRAPHS = sorted((Path(mam.HOME) / "graphs").glob("*.json"))
ROLES = {"spec": "south-writer", "implement": ["north-writer", "south-writer"],
         "judge": "south-reviewer", "web": "south-reviewer", "prosecutor": "north-reviewer"}


def _config():
    raw = json.loads((Path(mam.HOME) / "examples/default-config.json").read_text(encoding="utf-8"))
    demo = raw["providers"]["demo"]
    raw["providers"] = {"north": {**demo, "author_identity": "north"},
                        "south": {**demo, "author_identity": "south"}}
    raw["agents"] = {name: {"provider": name.split("-")[0], "author_identity": name}
                     for name in ("north-writer", "north-reviewer", "south-writer", "south-reviewer")}
    raw["role_bindings"] = {}
    raw["reviewers"] = {"north-writer": ["north-reviewer", "south-reviewer"],
                        "south-writer": ["north-reviewer", "south-reviewer"]}
    raw["review_policy"] = {"primary": "other_provider"}
    cfg = validate_config(raw)
    cfg["_config_path"] = "test"
    return cfg


class BundledGraphTests(unittest.TestCase):
    def setUp(self):
        cfg = _config()
        for p in (patch.object(mam, "CFG", cfg), patch.object(mam, "REGISTRY", mam.ProviderRegistry(cfg)),
                  patch.object(mam, "installed", lambda name: "/bin/" + name)):
            p.start()
            self.addCleanup(p.stop)

    def test_expected_graphs_are_bundled(self):
        self.assertEqual({p.stem for p in GRAPHS}, {"build", "build-2r", "court", "research"})

    def test_graphs_are_neutral(self):
        for path in GRAPHS:
            with self.subTest(graph=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(re.search("[а-яА-ЯёЁ]", text), "bundled graphs are English")
                agents = set(re.findall(r'"(?:agent|by)":\s*"([^"]+)"', text))
                roles_or_refs = {a for a in agents if a in ROLES or re.fullmatch(r"reviewer:[1-9]", a)}
                self.assertEqual(agents, roles_or_refs, "graphs name roles or reviewer refs, never agents")
                self.assertNotIn('"sandbox"', text, "a sandbox override breaks providers without one")

    def test_graphs_validate_and_bind(self):
        for path in GRAPHS:
            with self.subTest(graph=path.name):
                spec = json.loads(path.read_text(encoding="utf-8"))
                mam.validate(spec)
                bound = mam.bind_roles(spec, ROLES)
                agents = [m["agent"] for n in bound["nodes"] for m in (mam._sub_nodes(n) or [n])]
                self.assertTrue(set(agents) <= set(mam.CFG["agents"]), agents)

    def test_build_reviewers_follow_the_implementer(self):
        spec = json.loads((Path(mam.HOME) / "graphs/build.json").read_text(encoding="utf-8"))
        by_id = {n["id"]: n for n in mam.bind_roles(spec, ROLES)["nodes"]}
        self.assertEqual(by_id["build"]["agent"], "north-writer")
        self.assertEqual((by_id["review"]["agent"], by_id["defense"]["agent"],
                          by_id["build"]["verify"]["by"]), ("south-reviewer", "north-reviewer", "north-reviewer"))
        with patch.object(mam, "installed", lambda n: None if n == "north-writer" else n):
            by_id = {n["id"]: n for n in mam.bind_roles(spec, ROLES)["nodes"]}
        self.assertEqual((by_id["build"]["agent"], by_id["review"]["agent"], by_id["defense"]["agent"]),
                         ("south-writer", "north-reviewer", "south-reviewer"))

    def test_build_runs_offline_end_to_end(self):
        spec = mam.bind_roles(json.loads((Path(mam.HOME) / "graphs/build.json").read_text(encoding="utf-8")), ROLES)
        replies = {"verify": 'ok {"pass": true, "issues": []}'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "WORK", Path(tmp)), \
                patch.object(mam, "RUNS", Path(tmp) / ".mam"), patch.object(mam, "MEM", Path(tmp) / "memory"), \
                patch.object(mam, "run_agent",
                             side_effect=lambda agent, prompt, node_dir, *a, **k:
                             replies["verify"] if Path(node_dir).name == "verify" else f"{agent} done"):
            results, _, failed = mam.run_graph(spec, {"input": "task"}, quiet=True)
        self.assertFalse(failed, results)
        self.assertEqual(results["judge"], "south-reviewer done")


if __name__ == "__main__":
    unittest.main()
