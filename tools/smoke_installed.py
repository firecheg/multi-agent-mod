"""Run the bundled demo through an already-installed Agent Harness package."""

from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile


def main():
    with tempfile.TemporaryDirectory(prefix="agent-harness-smoke-") as tmp:
        root = Path(tmp)
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("MAM_") or key.startswith("AGENT_HARNESS_"):
                env.pop(key, None)
        env["HOME"] = str(root / "home")
        env["USERPROFILE"] = str(root / "home")
        env["AGENT_HARNESS_MEMORY"] = str(root / "memory")
        env["AGENT_HARNESS_SHARED"] = str(root / "shared")
        env["AGENT_HARNESS_RUNS"] = str(root / "runs")
        result = subprocess.run([sys.executable, "-m", "mam", "ask", "demo-worker", "smoke"],
                                cwd=root, env=env, capture_output=True, text=True,
                                encoding="utf-8", shell=False, timeout=30)
        if result.returncode:
            raise SystemExit(result.stderr or result.stdout)
        if "DEMO PROVIDER" not in result.stdout:
            raise SystemExit("installed demo provider did not run")
        print(result.stdout.strip())
        doctor = subprocess.run([sys.executable, "-m", "mam", "doctor"],
                                cwd=root, env=env, capture_output=True, text=True,
                                encoding="utf-8", shell=False, timeout=30)
        graphs = next((line for line in doctor.stdout.splitlines() if line.startswith("graphs ")), "")
        if doctor.returncode or not all(f"'{name}'" in graphs for name in ("build", "build-2r", "court", "research")):
            raise SystemExit("installed package does not ship the bundled graphs:\n" + (doctor.stderr or doctor.stdout))
        print(graphs)
        presets = subprocess.run([sys.executable, "-m", "mam", "setup", "presets"],
                                 cwd=root, env=env, capture_output=True, text=True,
                                 encoding="utf-8", shell=False, timeout=30)
        if presets.returncode or not {"claude", "codex", "gemini", "agy"} <= set(json.loads(presets.stdout or "{}")):
            raise SystemExit("installed package does not ship the CLI presets:\n" + (presets.stderr or presets.stdout))
        print("presets", sorted(json.loads(presets.stdout)))
        skills = subprocess.run([sys.executable, "-c",
                                 "import mam, pathlib; root = pathlib.Path(mam.__file__).parent / 'skills'; "
                                 "print(sorted(str(p.relative_to(root)).replace('\\\\', '/') for p in root.rglob('*.md')))"],
                                cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
                                shell=False, timeout=30)
        needed = ["multi-agent/SKILL.md", "multi-agent/references/cold-start.md",
                  "multi-agent/references/graphs.md"]
        if (Path(__file__).resolve().parents[1] / "tools" / "export_mod.py").is_file():
            needed.append("shared-harness/SKILL.md")
        if skills.returncode or not all(f"'{name}'" in skills.stdout for name in needed):
            raise SystemExit("installed package does not ship the bundled skills:\n" + (skills.stderr or skills.stdout))
        print("skills", skills.stdout.strip())


if __name__ == "__main__":
    main()
