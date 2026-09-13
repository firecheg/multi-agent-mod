import tempfile
import unittest
from pathlib import Path
import subprocess

from tools.check_publication import check


class PublicationCheckTests(unittest.TestCase):
    def test_clean_candidate_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("provider-neutral example", encoding="utf-8")
            self.assertEqual(check(root), [])

    def test_private_paths_and_identifiers_fail_without_echoing_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".codex").mkdir()
            (root / ".codex" / "run.json").write_text("x", encoding="utf-8")
            (root / "notes.md").write_text("Example" + "Owner", encoding="utf-8")
            failures = check(root, ("Example" + "Owner",))
            self.assertTrue(any("private runtime" in item for item in failures))
            self.assertTrue(any("maintainer identifier" in item for item in failures))
            self.assertTrue(all(("Example" + "Owner") not in item for item in failures))

    def test_secret_shapes_fail_without_printing_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad.txt").write_text("api" + "_key=" + "X" * 24, encoding="utf-8")
            failures = check(root)
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0], "bad.txt: possible secret pattern")

    def test_git_index_is_authoritative_over_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            tracked = root / "tracked.txt"
            tracked.write_text("safe", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
            tracked.write_text("access" + "_token=" + "A" * 24, encoding="utf-8")
            self.assertEqual(check(root), [])
            subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
            self.assertEqual(check(root), ["tracked.txt: possible secret pattern"])

    def test_tracked_runtime_and_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".mam").mkdir()
            (root / ".mam" / "run.md").write_text("runtime", encoding="utf-8")
            (root / "memory").mkdir()
            (root / "memory" / "SCHEMA.md").write_text("generic schema", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            self.assertEqual(check(root), [".mam/run.md: private runtime/config path"])


    def test_pkcs8_and_encrypted_keys_are_rejected(self):
        for kind in ("", "ENCRYPTED ", "RSA "):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                header = "-----BEGIN " + kind + "PRIVATE" + " KEY-----"
                (root / "key.txt").write_text(header, encoding="utf-8")
                self.assertEqual(check(root), ["key.txt: possible secret pattern"])

    def test_staged_secret_survives_worktree_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            secret = root / "secret.txt"
            secret.write_text("access" + "_token=" + "A" * 24, encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "secret.txt"], check=True)
            secret.write_text("redacted working copy", encoding="utf-8")
            self.assertEqual(check(root), ["secret.txt: possible secret pattern"])

    def test_empty_git_index_does_not_scan_untracked_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".env").write_text("synthetic", encoding="utf-8")
            self.assertEqual(check(root), [])

    def test_force_tracked_runtime_and_binary_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            names = [".env.production", ".mam/run/prompt.md", "memory/projects/example/note.md", "build/out.txt", "example.egg-info/PKG-INFO"]
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic", encoding="utf-8")
            (root / "binary.dat").write_bytes(bytes([255, 0]))
            subprocess.run(["git", "-C", str(root), "add", "-f", "."], check=True)
            failures = check(root)
            self.assertEqual(len(failures), len(names) + 1)
            for name in names + ["binary.dat"]:
                self.assertTrue(any(item.startswith(name + ":") for item in failures), failures)

    def test_staged_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            oid = subprocess.run(["git", "-C", str(root), "hash-object", "-w", "--stdin"], input=b"../outside.txt", capture_output=True, check=True).stdout.decode().strip()
            subprocess.run(["git", "-C", str(root), "update-index", "--add", "--cacheinfo", "120000", oid, "link.txt"], check=True)
            self.assertEqual(check(root), ["link.txt: symlink requires review"])

    def test_git_subdirectory_is_not_silently_scanned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            child = root / "child"
            child.mkdir()
            self.assertEqual(check(child), [".: root must be the Git working-tree root"])


if __name__ == "__main__":
    unittest.main()
