"""Small, offline publication hygiene check for the public source export."""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "build", "dist", ".mam", "__pycache__", ".pytest_cache"}
SKIP_NAMES = {"*.pyc", "*.whl"}
PRIVATE_DIRS = {".agent-harness", ".claude", ".codex", ".agents", ".specify", ".tmp"}
PRIVATE_NAMES = {"agents.local.json", "connections.json", "adapters.json", "auth.json", "credentials.json"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:(?:RSA|OPENSSH|EC|DSA|ENCRYPTED) )?PRIVATE KEY-----"),
    re.compile(r"(?:api[_-]?" + "key|access[_-]?token|secret[_-]?key)" + r"\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{16,}", re.I),
)


def _git_index(root: Path):
    try:
        inside = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                                check=True, capture_output=True, text=True).stdout.strip()
        if Path(inside).resolve() != root.resolve():
            return [(".", "wrong-root")]
        entries = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "-z"], check=True,
                                 capture_output=True, text=False).stdout.decode().split("\0")
        result = []
        for entry in entries:
            if not entry:
                continue
            meta, rel = entry.split("\t", 1)
            mode = meta.split()[0]
            result.append((rel, mode))
        return result
    except (OSError, subprocess.CalledProcessError):
        return None


def candidate_files(root: Path):
    """Return (relative path, mode, content); Git mode reads the index blob."""
    indexed = _git_index(root)
    if indexed is not None:
        result = []
        for rel, mode in indexed:
            if mode == "wrong-root":
                result.append((Path(rel), mode, None))
                continue
            try:
                body = subprocess.run(["git", "-C", str(root), "show", f":{rel}"], check=True,
                                      capture_output=True).stdout
            except (OSError, subprocess.CalledProcessError):
                result.append((Path(rel), mode, None))
                continue
            result.append((Path(rel), mode, body))
        return result
    result = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.is_symlink() or (getattr(path, 'is_junction', lambda: False)()):
            result.append((rel, "symlink", None))
            continue
        if not path.is_file():
            continue
        try:
            result.append((rel, "100644", path.read_bytes()))
        except OSError:
            result.append((rel, "unreadable", None))
    return result


def check(root: Path, deny_text: tuple[str, ...] = ()) -> list[str]:
    root = root.resolve()
    failures: list[str] = []
    for rel, mode, raw in candidate_files(root):
        parts = tuple(part.casefold() for part in rel.parts)
        name = rel.name.casefold()
        if mode in {"symlink", "120000"}:
            failures.append(f"{rel.as_posix()}: symlink requires review")
            continue
        if mode == "wrong-root":
            failures.append(".: root must be the Git working-tree root")
            continue
        if mode == "160000":
            failures.append(f"{rel.as_posix()}: submodule requires separate review")
            continue
        if mode == "unreadable" or raw is None:
            failures.append(f"{rel.as_posix()}: unreadable source")
            continue
        runtime = {".mam", "cache", "indexes", "transcripts", "backups", ".venv", "venv", "build", "dist", "__pycache__", "coverage"}
        if (any(part in PRIVATE_DIRS or part in runtime or part.endswith(".egg-info") for part in parts)
                or ("memory" in parts and rel.as_posix().casefold() != "memory/schema.md")):
            failures.append(f"{rel.as_posix()}: private runtime/config path")
            continue
        if name in PRIVATE_NAMES or name == ".env" or (name.startswith(".env.") and name != ".env.example") or name.endswith(".local.json"):
            failures.append(f"{rel.as_posix()}: private runtime/config path")
            continue
        if name.endswith((".pyc", ".whl")):
            failures.append(f"{rel.as_posix()}: generated artifact")
            continue
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            failures.append(f"{rel.as_posix()}: non-UTF-8 source requires review")
            continue
        if "\x00" in text:
            failures.append(f"{rel.as_posix()}: binary source requires review")
            continue
        if any(term and term.casefold() in text.casefold() for term in deny_text):
            failures.append(f"{rel.as_posix()}: maintainer identifier")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            failures.append(f"{rel.as_posix()}: possible secret pattern")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a source tree for obvious private publication leaks.")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--deny-text", action="append", default=[],
                        help="optional maintainer/project string to reject; repeat as needed")
    args = parser.parse_args()
    failures = check(Path(args.root), tuple(args.deny_text))
    for failure in failures:
        print(failure)
    if failures:
        print(f"publication check failed: {len(failures)} rule violation(s)")
        return 1
    print("publication check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
