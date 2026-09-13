"""Offline checks for graph roles, `init`, `distinct` groups and rounds blocks."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "execution"))
import mam


def _config(tmp):
    """Demo provider with four independent authors and one alias of `alpha`."""
    raw = json.loads((Path(mam.HOME) / "examples/default-config.json").read_text(encoding="utf-8"))
    base = raw["agents"]["demo-worker"]
    for name, identity in (("alpha", "author-a"), ("beta", "author-b"),
                           ("gamma", "author-c"), ("delta", "author-d"),
                           ("alpha-alias", "author-a")):
        raw["agents"][name] = {**base, "author_identity": identity}
    path = Path(tmp) / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return mam.load_config(str(path))


class RolesTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        cfg = _config(self.tmp)
        self._patches = [
            patch.object(mam, "CFG", cfg),
            patch.object(mam, "REGISTRY", mam.ProviderRegistry(cfg)),
            patch.object(mam, "installed", lambda name: "/bin/" + name),
            patch.object(mam, "ROLES_FILE", self.tmp / "home" / "roles.json"),
            patch.object(mam, "WORK", self.tmp),
            patch.object(mam, "RUNS", self.tmp / ".mam"),
            patch.object(mam, "MEM", self.tmp / "memory"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()


class BindRolesTests(RolesTestCase):
    ROSTER = {"spec": "alpha", "implement": "beta", "review": "gamma", "judge": "alpha"}
    GRAPH = {"name": "t", "nodes": [
        {"id": "a", "agent": "implement", "prompt": "x", "verify": {"by": "review", "criteria": ["c"]}},
        {"id": "b", "agent": "review", "needs": ["a"], "review_of": "a", "prompt": "y"},
        {"id": "c", "agent": "beta", "needs": ["a"], "prompt": "z"},
    ]}

    def test_roles_bind_to_agents_without_mutating_the_spec(self):
        bound = mam.bind_roles(self.GRAPH, self.ROSTER)
        self.assertEqual([n["agent"] for n in bound["nodes"]], ["beta", "gamma", "beta"])
        self.assertEqual(bound["nodes"][0]["verify"]["by"], "gamma")
        self.assertEqual(self.GRAPH["nodes"][0]["agent"], "implement")

    def test_missing_role_names_itself_and_points_at_init(self):
        with self.assertRaises(ValueError) as caught:
            mam.bind_roles(self.GRAPH, {"implement": "beta"})
        self.assertIn("'review'", str(caught.exception))
        self.assertIn("init", str(caught.exception))

    def test_two_roles_on_one_agent_is_self_review(self):
        with self.assertRaisesRegex(ValueError, "differ|self-review|independent"):
            mam.bind_roles(self.GRAPH, {"implement": "beta", "review": "beta"})

    def test_two_roles_on_one_author_identity_is_self_review(self):
        with self.assertRaisesRegex(ValueError, "differ|self-review|same author"):
            mam.bind_roles(self.GRAPH, {"implement": "alpha", "review": "alpha-alias"})

    def test_role_chain_first_installed_agent_wins(self):
        graph = {"name": "t", "nodes": [
            {"id": "a", "agent": "implement", "prompt": "x"},
            {"id": "b", "agent": "review", "needs": ["a"], "review_of": "a", "prompt": "y"},
        ]}
        roster = {"implement": ["delta", "beta"], "review": "gamma"}
        with patch.object(mam, "installed", lambda n: None if n == "delta" else n):
            self.assertEqual(mam.bind_roles(graph, roster)["nodes"][0]["agent"], "beta")
        self.assertEqual(mam.bind_roles(graph, roster)["nodes"][0]["agent"], "delta")
        self.assertEqual(mam.bind_roles(graph, {"implement": "beta", "review": "gamma"})
                         ["nodes"][0]["agent"], "beta")
        with patch.object(mam, "installed", lambda n: None):
            with self.assertRaisesRegex(ValueError, "none of them installed"):
                mam.bind_roles(graph, roster)


class DistinctTests(RolesTestCase):
    COURT = {"name": "c", "distinct": [["spec", "implement", "prosecutor"]], "nodes": [
        {"id": "a", "agent": "spec", "prompt": "x"},
        {"id": "b", "agent": "implement", "needs": ["a"], "prompt": "y"},
    ]}

    def test_distinct_roles_accept_three_authors(self):
        mam.bind_roles(self.COURT, {"spec": "alpha", "implement": "beta", "prosecutor": "gamma"})

    def test_distinct_roles_reject_a_collapse(self):
        for roster in ({"spec": "alpha", "implement": "beta", "prosecutor": "alpha"},
                       {"spec": "alpha", "implement": "beta", "prosecutor": "beta"},
                       {"spec": "alpha", "implement": "beta", "prosecutor": "alpha-alias"}):
            with self.subTest(roster=roster):
                with self.assertRaises(ValueError) as caught:
                    mam.bind_roles(self.COURT, roster)
                self.assertIn("needs them apart", str(caught.exception))
                self.assertIn("init --role", str(caught.exception))

    def test_a_fallback_can_collapse_roles_too(self):
        roster = {"spec": "alpha", "implement": ["delta", "gamma"], "prosecutor": "gamma"}
        with patch.object(mam, "installed", lambda n: None if n == "delta" else n):
            with self.assertRaisesRegex(ValueError, "needs them apart"):
                mam.bind_roles(self.COURT, roster)


class RoundsTests(RolesTestCase):
    LOOP = {"name": "t", "nodes": [{"id": "block", "rounds": {"max": 4, "until": "decide", "nodes": [
        {"id": "accuse", "agent": "alpha", "prompt": "a {round} {previous}"},
        {"id": "decide", "agent": "beta", "prompt": "d {accuse}"},
        {"id": "act", "agent": "gamma", "prompt": "f {decide}"},
    ]}}]}

    def _run(self, verdicts):
        calls = []
        verdicts = iter(verdicts)
        real = mam.run_node

        def fake(node, ctx, run_dir, log):
            if node.get("rounds"):
                return real(node, ctx, run_dir, log)   # exercise run_rounds itself
            calls.append((node["id"], ctx.get("round"), bool(ctx.get("previous"))))
            return next(verdicts) if node["id"] == "decide" else node["id"]

        with patch.object(mam, "run_node", fake):
            results, _, failed = mam.run_graph(self.LOOP, {}, quiet=True)
        return results, failed, calls

    def test_block_repeats_until_the_decider_passes(self):
        mam.validate(self.LOOP)
        results, failed, calls = self._run(['not yet {"pass": false, "issues": ["do it"]}',
                                            'better {"pass": true, "issues": []}'])
        self.assertFalse(failed)
        self.assertEqual([c[0] for c in calls], ["accuse", "decide", "act", "accuse", "decide"])
        self.assertEqual((calls[0][1], calls[3][1]), ("1 of 4", "2 of 4"))
        self.assertEqual((calls[0][2], calls[3][2]), (False, True))
        self.assertTrue(results["block"].startswith("better"))
        self.assertEqual(results["accuse"], "accuse")

    def test_running_out_of_rounds_is_a_failure(self):
        results, failed, calls = self._run(['{"pass": false, "issues": ["still wrong"]}'] * 9)
        self.assertEqual(failed, {"block"})
        self.assertIn("still wrong", results["block"])
        self.assertEqual(sum(1 for c in calls if c[0] == "act"), 4)

    def test_invalid_blocks_do_not_validate(self):
        for block, why in (
            ({"id": "x", "rounds": {"until": "nope", "nodes": [{"id": "a", "agent": "alpha", "prompt": "p"}]}},
             "names no node"),
            ({"id": "x", "agent": "alpha", "prompt": "p",
              "rounds": {"until": "a", "nodes": [{"id": "a", "agent": "alpha", "prompt": "p"}]}},
             "takes no agent"),
            ({"id": "x", "rounds": {"until": "a", "nodes": [{"id": "a", "agent": "alpha", "prompt": "{nope}"}]}},
             "neither an input"),
            ({"id": "x", "rounds": {"until": "a", "nodes": [
                {"id": "a", "rounds": {"until": "b", "nodes": [{"id": "b", "agent": "alpha", "prompt": "p"}]}}]}},
             "cannot nest"),
        ):
            with self.subTest(why=why):
                with self.assertRaisesRegex(ValueError, why):
                    mam.validate({"name": "t", "nodes": [block]})

    def test_self_review_inside_a_block_is_still_rejected(self):
        spec = {"name": "t", "nodes": [{"id": "x", "rounds": {"until": "b", "nodes": [
            {"id": "a", "agent": "alpha", "prompt": "p"},
            {"id": "b", "agent": "alpha-alias", "review_of": "a", "prompt": "q {a}"},
        ]}}]}
        with self.assertRaisesRegex(ValueError, "self-review"):
            mam.validate(spec)


class InitAndCliTests(RolesTestCase):
    def _args(self, **kw):
        base = dict(spec=None, implement=None, review=None, review_2=None, judge=None, web=None, role=None)
        return types.SimpleNamespace(**{**base, **kw})

    def test_init_writes_roles_and_defaults_the_judge(self):
        with contextlib.redirect_stdout(io.StringIO()):
            mam.cmd_init(self._args(spec=["alpha"], implement=["beta", "delta"], review=["gamma"],
                                    role=["prosecutor=delta,gamma"]))
        roles = json.loads(mam.ROLES_FILE.read_text(encoding="utf-8"))
        self.assertEqual(roles, {"spec": "alpha", "implement": ["beta", "delta"], "review": "gamma",
                                 "prosecutor": ["delta", "gamma"], "judge": "alpha"})
        with contextlib.redirect_stdout(io.StringIO()):
            mam.cmd_init(self._args(review=["delta"]))
        self.assertEqual(json.loads(mam.ROLES_FILE.read_text(encoding="utf-8"))["review"], "delta")

    def test_init_refuses_unknown_or_missing_agents(self):
        with self.assertRaises(SystemExit) as caught:
            mam.cmd_init(self._args(implement=["nobody"]))
        self.assertIn("unknown agent", str(caught.exception.code))
        with self.assertRaises(SystemExit):
            mam.cmd_init(self._args())                  # nothing asked, nothing stored
        self.assertFalse(mam.ROLES_FILE.exists())

    def test_init_warns_when_implement_and_review_share_an_author(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mam.cmd_init(self._args(implement=["alpha"], review=["alpha-alias"]))
        self.assertIn("self-review", out.getvalue())

    def test_graph_command_binds_roles_before_running(self):
        mam.ROLES_FILE.parent.mkdir(parents=True)
        mam.ROLES_FILE.write_text(json.dumps({"implement": "beta"}), encoding="utf-8")
        spec_path = self.tmp / "g.json"
        spec_path.write_text(json.dumps({"name": "g", "nodes": [
            {"id": "a", "agent": "implement", "prompt": "x"}]}), encoding="utf-8")
        seen = {}

        def fake_run_graph(spec, inputs, quiet=False):
            seen["spec"] = spec
            return {}, mam.RUNS, set()

        with patch.object(mam, "run_graph", fake_run_graph), contextlib.redirect_stdout(io.StringIO()):
            mam.cmd_graph(types.SimpleNamespace(spec=str(spec_path), set=None, input=None))
        self.assertEqual(seen["spec"]["nodes"][0]["agent"], "beta")

    def test_doctor_reports_missing_roles(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mam.cmd_doctor(types.SimpleNamespace(deep=False))
        self.assertIn("roles     (none)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
