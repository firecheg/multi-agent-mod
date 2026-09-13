"""Offline checks for primary/secondary reviewer selection and `reviewer:N` refs.

Scenario: two providers, two models on each. Authors write on either provider;
the primary reviewer must come from the other provider, the secondary may share
the author's provider but never the author's identity.
"""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "execution"))
import mam
from providers import ProviderConfigError, validate_config


def _raw_config(policy="other_provider", reviewers=None):
    raw = json.loads((Path(mam.HOME) / "examples/default-config.json").read_text(encoding="utf-8"))
    demo = raw["providers"]["demo"]
    raw["providers"] = {
        "north": {**demo, "author_identity": "north-account"},
        "south": {**demo, "author_identity": "south-account"},
    }
    raw["agents"] = {
        "north-writer": {"provider": "north", "author_identity": "north-writer"},
        "north-reviewer": {"provider": "north", "author_identity": "north-reviewer"},
        "north-writer-alias": {"provider": "north", "author_identity": "north-writer"},
        "south-writer": {"provider": "south", "author_identity": "south-writer"},
        "south-reviewer": {"provider": "south", "author_identity": "south-reviewer"},
    }
    raw["role_bindings"] = {}
    # Deliberately list the same-provider reviewer first for north-writer: the
    # policy, not the list order alone, must put south-reviewer in front.
    raw["reviewers"] = reviewers or {
        "north-writer": ["north-writer-alias", "north-reviewer", "south-reviewer"],
        "south-writer": ["north-reviewer", "south-reviewer"],
    }
    if policy is not None:
        raw["review_policy"] = {"primary": policy}
    return raw


class PolicyTestCase(unittest.TestCase):
    def use(self, raw, installed=lambda name: "/bin/" + name):
        cfg = validate_config(copy.deepcopy(raw))
        cfg["_config_path"] = "test"
        for p in (patch.object(mam, "CFG", cfg), patch.object(mam, "REGISTRY", mam.ProviderRegistry(cfg)),
                  patch.object(mam, "installed", installed)):
            p.start()
            self.addCleanup(p.stop)


class ConfigTests(unittest.TestCase):
    def test_policy_defaults_to_independent_and_rejects_unknown_values(self):
        self.assertEqual(validate_config(_raw_config(policy=None))["review_policy"],
                         {"primary": "independent"})
        for bad in ({"primary": "anyone"}, {"secondary": "x"}, "other_provider"):
            with self.subTest(bad=bad), self.assertRaises(ProviderConfigError):
                raw = _raw_config()
                raw["review_policy"] = bad
                validate_config(raw)

    def test_bundled_example_configs_still_validate(self):
        for path in (Path(mam.HOME) / "examples").glob("*config.json"):
            with self.subTest(path=path.name):
                validate_config(json.loads(path.read_text(encoding="utf-8")))


class PickReviewerTests(PolicyTestCase):
    def test_primary_comes_from_the_other_provider(self):
        self.use(_raw_config())
        self.assertEqual(mam.pick_reviewer("north-writer"), "south-reviewer")
        self.assertEqual(mam.pick_reviewer("south-writer"), "north-reviewer")

    def test_secondary_may_share_the_provider_but_not_the_identity(self):
        self.use(_raw_config())
        self.assertEqual(mam.pick_reviewers("north-writer", 2), ["south-reviewer", "north-reviewer"])
        self.assertEqual(mam.pick_reviewers("south-writer", 2), ["north-reviewer", "south-reviewer"])

    def test_no_cross_provider_primary_fails_closed(self):
        self.use(_raw_config(), installed=lambda n: None if n == "south-reviewer" else n)
        with self.assertRaisesRegex(mam.AgentError, "another provider"):
            mam.pick_reviewer("north-writer")

    def test_independent_policy_keeps_list_order(self):
        self.use(_raw_config(policy="independent"))
        self.assertEqual(mam.pick_reviewer("north-writer"), "north-reviewer")

    def test_too_few_reviewers_is_an_error(self):
        self.use(_raw_config())
        with self.assertRaisesRegex(mam.AgentError, "2 installed independent reviewer"):
            mam.pick_reviewers("north-writer", 3)


class ReviewerRefTests(PolicyTestCase):
    GRAPH = {"name": "build", "nodes": [
        {"id": "build", "agent": "implement", "prompt": "x"},
        {"id": "primary", "agent": "reviewer:1", "needs": ["build"], "review_of": "build", "prompt": "{build}"},
        {"id": "secondary", "agent": "reviewer:2", "needs": ["build"], "review_of": "build", "prompt": "{build}"},
    ]}
    ROLES = {"implement": ["north-writer", "south-writer"]}

    def test_reviewers_follow_the_author_the_role_bound_to(self):
        self.use(_raw_config())
        bound = mam.bind_roles(self.GRAPH, self.ROLES)
        self.assertEqual([n["agent"] for n in bound["nodes"]],
                         ["north-writer", "south-reviewer", "north-reviewer"])
        self.assertEqual(self.GRAPH["nodes"][1]["agent"], "reviewer:1")

    def test_a_fallback_author_swaps_the_reviewers(self):
        self.use(_raw_config(), installed=lambda n: None if n == "north-writer" else n)
        bound = mam.bind_roles(self.GRAPH, self.ROLES)
        self.assertEqual([n["agent"] for n in bound["nodes"]],
                         ["south-writer", "north-reviewer", "south-reviewer"])

    def test_verify_by_reviewer_ref_uses_the_node_author(self):
        self.use(_raw_config())
        spec = {"name": "g", "nodes": [{"id": "a", "agent": "south-writer", "prompt": "x",
                                        "verify": {"by": "reviewer:1", "criteria": ["c"]}}]}
        self.assertEqual(mam.bind_roles(spec, {})["nodes"][0]["verify"]["by"], "north-reviewer")

    def test_refs_inside_rounds_blocks_resolve(self):
        self.use(_raw_config())
        spec = {"name": "g", "nodes": [{"id": "block", "rounds": {"until": "judge", "nodes": [
            {"id": "fix", "agent": "implement", "prompt": "x"},
            {"id": "judge", "agent": "reviewer:1", "review_of": "fix", "prompt": "{fix}"},
        ]}}]}
        bound = mam.bind_roles(spec, self.ROLES)
        self.assertEqual(bound["nodes"][0]["rounds"]["nodes"][1]["agent"], "south-reviewer")

    def test_bad_refs_are_rejected(self):
        self.use(_raw_config())
        cases = (
            ({"name": "g", "nodes": [{"id": "a", "agent": "reviewer:1", "prompt": "x"}]}, "needs review_of"),
            ({"name": "g", "nodes": [
                {"id": "a", "agent": "north-writer", "prompt": "x"},
                {"id": "b", "agent": "reviewer:3", "review_of": "a", "needs": ["a"], "prompt": "{a}"}]},
             "cannot resolve"),
            ({"name": "g", "nodes": [
                {"id": "a", "agent": "north-writer", "prompt": "x"},
                {"id": "b", "agent": "reviewer:1", "review_of": "a", "needs": ["a"], "prompt": "{a}"},
                {"id": "c", "agent": "reviewer:1", "review_of": "b", "needs": ["b"], "prompt": "{b}"}]},
             "itself a reviewer reference"),
        )
        for spec, why in cases:
            with self.subTest(why=why), self.assertRaisesRegex(ValueError, why):
                mam.bind_roles(spec, {})

    def test_alias_of_the_author_is_never_a_reviewer(self):
        self.use(_raw_config(policy="independent", reviewers={
            "north-writer": ["north-writer-alias", "north-reviewer", "south-reviewer"]}))
        self.assertNotIn("north-writer-alias", mam.pick_reviewers("north-writer", 2))


class GraphRunTests(PolicyTestCase):
    def test_bound_graph_runs_with_the_selected_reviewers(self):
        self.use(_raw_config())
        seen = []
        with tempfile.TemporaryDirectory() as tmp, patch.object(mam, "WORK", Path(tmp)), \
                patch.object(mam, "RUNS", Path(tmp) / ".mam"), \
                patch.object(mam, "MEM", Path(tmp) / "memory"), \
                patch.object(mam, "run_agent",
                             side_effect=lambda agent, prompt, *a, **k: seen.append(agent) or agent):
            spec = mam.bind_roles(ReviewerRefTests.GRAPH, {"implement": "south-writer"})
            _, _, failed = mam.run_graph(spec, {}, quiet=True)
        self.assertFalse(failed)
        self.assertEqual(sorted(seen), ["north-reviewer", "south-reviewer", "south-writer"])


if __name__ == "__main__":
    unittest.main()
