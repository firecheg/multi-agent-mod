import importlib.util
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("read_gate", Path(__file__).resolve().parents[1] / "execution/read_gate.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReadGateTests(unittest.TestCase):
    def _big(self, root, name="large file.txt"):
        path = root / name
        path.write_text("line\n" * 400, encoding="utf-8")
        return path

    def test_full_read_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = self._big(root)
            result = module.check({"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": f'cat "{path.name}"'}})
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_small_and_targeted_reads_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); small = root / "small.txt"; small.write_text("x\n")
            self.assertEqual(module.check({"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": "cat small.txt"}}), {})
            path = self._big(root)
            for command in (f'head -n 10 "{path.name}"', f'Get-Content "{path.name}" -TotalCount 10', f'cat "{path.name}" | rg needle'):
                self.assertEqual(module.check({"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": command}}), {})

    def test_literalpath_and_multiple_files_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = self._big(root)
            result = module.check({"tool_name": "PowerShell", "cwd": str(root), "tool_input": {"command": f'Get-Content -LiteralPath "{path.name}"'}})
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
            result = module.check({"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": f'cat small.txt "{path.name}"'}})
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_quoted_windows_path_and_exemptions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = self._big(root, "folder name.txt")
            result = module.check({"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": f'cat "{path}"'}})
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
            agents = self._big(root, "AGENTS.md")
            self.assertEqual(module.check({"tool_name": "Read", "cwd": str(root), "tool_input": {"file_path": str(agents)}}), {})

    def test_unrelated_allowed_but_cat_pipeline_is_not_targeted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = self._big(root)
            self.assertEqual(module.check({"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": "git status"}}), {})
            result = module.check({"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": f'cat "{path.name}" | cat'}})
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_missing_file_and_read_range_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(module.check({"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": "cat missing.txt"}}), {})
            path = self._big(root)
            self.assertEqual(module.check({"tool_name": "Read", "cwd": str(root), "tool_input": {"file_path": str(path), "offset": 1}}), {})


if __name__ == "__main__":
    unittest.main()
