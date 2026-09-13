"""Bundled skills must not drift from the code they describe.

Every command, module, graph, preset and MCP tool a skill names has to exist;
every relative link has to resolve. A skill that documents a command the
harness no longer has is worse than no skill.
"""

import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
IS_HARNESS = (ROOT / "tools" / "export_mod.py").is_file()
EXPECTED_SKILLS = {"multi-agent", "shared-harness"} if IS_HARNESS else {"multi-agent"}
SKILLS = sorted(p for p in (ROOT / "skills").iterdir() if (p / "SKILL.md").is_file())
TEXTS = {p: p.read_text(encoding="utf-8") for skill in SKILLS for p in skill.rglob("*.md")}
# A command is only something written as one: at the start of a line (code
# blocks) or right after a backtick. Prose that merely names the harness is not.
COMMAND = r"(?:^|`)agent-harness (?:--config \S+ )?"


def _subcommands():
    tree = ast.parse((ROOT / "mam.py").read_text(encoding="utf-8"))
    return {node.args[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_parser"}


def _choices(module):
    text = (ROOT / "execution" / f"{module}.py").read_text(encoding="utf-8")
    match = re.search(r"add_argument\('command', choices=\[([^\]]+)\]", text)
    return set(re.findall(r"'([a-z-]+)'", match.group(1))) if match else set()


class SkillStructureTests(unittest.TestCase):
    def test_skills_are_bundled_with_valid_frontmatter(self):
        self.assertEqual({p.name for p in SKILLS}, EXPECTED_SKILLS)
        for skill in SKILLS:
            with self.subTest(skill=skill.name):
                head = re.match(r"---\n(.*?)\n---\n", (skill / "SKILL.md").read_text(encoding="utf-8"), re.S)
                self.assertIsNotNone(head, "SKILL.md needs frontmatter")
                fields = dict(re.findall(r"^(\w+):\s*(.*)$", head.group(1), re.M))
                self.assertEqual(fields.get("name"), skill.name)
                description = fields.get("description", "").strip('"')
                self.assertTrue(40 <= len(description) <= 320,
                                "the description is listed in every session: keep it short but specific")

    def test_relative_links_resolve(self):
        for path, text in TEXTS.items():
            for target in re.findall(r"\]\((?!https?://)([^)#]+)\)", text):
                with self.subTest(file=path.relative_to(ROOT).as_posix(), link=target):
                    self.assertTrue((path.parent / target).resolve().exists())

    def test_skills_stay_neutral(self):
        for path, text in TEXTS.items():
            with self.subTest(file=path.relative_to(ROOT).as_posix()):
                self.assertIsNone(re.search("[а-яА-ЯёЁ]", text), "bundled skills are English")
                self.assertIsNone(re.search(r"(?i)\bluna\b|\bastra\b|MAM_HOME|multi-agent-mod", text),
                                  "no maintainer roster or legacy install names")


class SkillReferencesExistTests(unittest.TestCase):
    def test_agent_harness_subcommands_exist(self):
        known = _subcommands()
        for path, text in TEXTS.items():
            for command in re.findall(COMMAND + r"([a-z][a-z-]*)", text, re.M):
                with self.subTest(file=path.name, command=command):
                    self.assertIn(command, known)

    def test_setup_and_mem_actions_exist(self):
        mam = (ROOT / "mam.py").read_text(encoding="utf-8")
        for path, text in TEXTS.items():
            for group, action in re.findall(COMMAND + r"(setup|mem) ([a-z][a-z-]*)", text, re.M):
                with self.subTest(file=path.name, action=f"{group} {action}"):
                    self.assertRegex(mam, r'choices=\[[^\]]*"' + re.escape(action) + '"')

    def test_execution_modules_and_commands_exist(self):
        for path, text in TEXTS.items():
            for module, command in re.findall(r"python -m execution\.([a-z_]+)(?: ([a-z][a-z-]*))?", text):
                with self.subTest(file=path.name, module=module, command=command):
                    self.assertTrue((ROOT / "execution" / f"{module}.py").is_file())
                    if command and _choices(module):
                        self.assertIn(command, _choices(module))

    def test_named_graphs_presets_and_examples_exist(self):
        for path, text in TEXTS.items():
            for graph in re.findall(COMMAND + r"graph ([a-z][a-z0-9-]*)\b(?!\.json)", text, re.M):
                with self.subTest(file=path.name, graph=graph):
                    self.assertTrue((ROOT / "graphs" / f"{graph}.json").is_file())
            for preset in re.findall(r"`(claude-[a-z]+)`", text):
                with self.subTest(file=path.name, preset=preset):
                    self.assertTrue((ROOT / "presets" / f"{preset}.json").is_file())
            for example in re.findall(r"`(examples/[\w.-]+)`", text):
                with self.subTest(file=path.name, example=example):
                    self.assertTrue((ROOT / example).is_file())

    def test_mcp_tool_table_matches_the_server(self):
        if not IS_HARNESS:
            self.skipTest("shared skill is not bundled")
        server = (ROOT / "execution" / "context_server.py").read_text(encoding="utf-8")
        tools = set(re.findall(r"'name':'([a-z_]+)'", server))
        text = TEXTS[ROOT / "skills" / "shared-harness" / "SKILL.md"]
        self.assertEqual(set(re.findall(r"^\| `([a-z_]+)` \|", text, re.M)), tools)

    def test_roles_are_used_by_bundled_graphs(self):
        graphs_text = " ".join(p.read_text(encoding="utf-8") for p in (ROOT / "graphs").glob("*.json"))
        text = TEXTS[ROOT / "skills" / "multi-agent" / "SKILL.md"]
        listed = re.search(r"\*\*Roles\*\*: (.*?) bound", text, re.S).group(1)
        roles = [r.strip() for r in listed.replace("`", "").split(",") if r.strip()]
        self.assertTrue(roles)
        for role in roles:
            with self.subTest(role=role):
                self.assertTrue(f'"agent": "{role}"' in graphs_text, f"no bundled graph uses role {role!r}")
        worker_code = " ".join((ROOT / "execution" / f).read_text(encoding="utf-8")
                               for f in ("context_server.py", "index_workers.py"))
        for binding in ("summary", "code", "context_read"):
            with self.subTest(binding=binding):
                self.assertIn(binding, worker_code)


if __name__ == "__main__":
    unittest.main()
