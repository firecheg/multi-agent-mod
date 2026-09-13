"""Cold start: detect installed agent CLIs and build a provider config from answers.

The harness never guesses which models a person pays for. `detect` reports
facts about this machine; the person (usually through an agent following the
multi-agent skill) answers which models they use and who writes or reviews;
`build` turns those answers plus bundled CLI presets into a validated config.
"""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from providers import LEVELS, ProviderConfigError, validate_config

PRESETS_DIR = _HERE.parent / "presets"
_PRESET_KEYS = {"name", "cli", "vendor", "detect", "provider", "effort_levels",
                "sandbox_modes", "checked", "notes"}
_ANSWER_KEYS = {"agents", "reviewers", "review_policy", "roles", "role_bindings",
                "memory_k", "memory_max_chars", "timeout"}
_AGENT_KEYS = {"preset", "model", "role", "description", "author_identity", "effort", "path", "env"}


class SetupError(ValueError):
    pass


def load_presets(directory=PRESETS_DIR):
    presets = {}
    for path in sorted(Path(directory).glob("*.json")):
        preset = json.loads(path.read_text(encoding="utf-8"))
        unknown = set(preset) - _PRESET_KEYS
        if unknown or preset.get("name") != path.stem:
            raise SetupError(f"preset {path.name}: bad fields or name ({', '.join(sorted(unknown))})")
        if not preset["provider"]["argv"] or preset["provider"]["argv"][0] != "{bin}":
            raise SetupError(f"preset {path.name}: argv must start with {{bin}}")
        presets[path.stem] = preset
    return presets


def _candidates(detect, which=shutil.which):
    found = []
    for pattern in detect.get("paths", []):
        expanded = os.path.expandvars(os.path.expanduser(pattern))
        hits = glob.glob(expanded) if any(ch in expanded for ch in "*?[") else (
            [expanded] if os.path.isfile(expanded) else [])
        # Newest first: an installer that keeps versioned directories should
        # resolve to the version it runs today, not the oldest leftover.
        found += sorted(hits, key=lambda p: os.path.getmtime(p), reverse=True)
    for command in detect.get("commands", []):
        hit = which(command)
        if hit:
            found.append(hit)
    unique = {}
    for path in found:
        path = os.path.normpath(path)
        unique.setdefault(os.path.normcase(path), path)
    return list(unique.values())


def _version(path, args, run=subprocess.run):
    try:
        proc = run([path, *args], capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=20, stdin=subprocess.DEVNULL, shell=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (proc.stdout or proc.stderr).strip().splitlines()
    return text[0][:120] if proc.returncode == 0 and text else None


def detect(presets=None, which=shutil.which, run=subprocess.run):
    """What is installed, per preset. Facts only; no models, no accounts."""
    presets = load_presets() if presets is None else presets
    report = []
    for name, preset in presets.items():
        paths = _candidates(preset.get("detect", {}), which)
        entry = {"preset": name, "cli": preset.get("cli", name), "vendor": preset.get("vendor"),
                 "found": bool(paths), "path": paths[0] if paths else None,
                 "other_paths": paths[1:], "version": None,
                 "effort_levels": preset.get("effort_levels", []),
                 "sandbox_modes": preset.get("sandbox_modes", []),
                 "checked": preset.get("checked"), "notes": preset.get("notes")}
        if paths:
            entry["version"] = _version(paths[0], preset.get("detect", {}).get("version_args", ["--version"]), run)
        report.append(entry)
    return report


def build(answers, presets=None, detected=None):
    """Answers + presets -> (validated provider config, roles)."""
    presets = load_presets() if presets is None else presets
    if not isinstance(answers, dict) or set(answers) - _ANSWER_KEYS:
        raise SetupError("answers must be an object with: " + ", ".join(sorted(_ANSWER_KEYS)))
    agents = answers.get("agents")
    if not isinstance(agents, dict) or not agents:
        raise SetupError("answers.agents must name at least one agent")
    paths = {d["preset"]: d["path"] for d in (detected or []) if d.get("found")}

    providers, profiles = {}, {}
    for alias, spec in agents.items():
        if not isinstance(spec, dict) or set(spec) - _AGENT_KEYS:
            raise SetupError(f"agents.{alias}: allowed fields are {', '.join(sorted(_AGENT_KEYS))}")
        preset = presets.get(spec.get("preset"))
        if preset is None:
            raise SetupError(f"agents.{alias}: unknown preset {spec.get('preset')!r}; "
                             f"known: {', '.join(sorted(presets))}")
        model = spec.get("model")
        if not isinstance(model, str) or not model:
            raise SetupError(f"agents.{alias}: model is required — ask which model this agent uses")
        name = preset["name"]
        binary = spec.get("path") or paths.get(name)
        if not binary:
            raise SetupError(f"agents.{alias}: {preset.get('cli', name)} was not detected; "
                             f"install it or give its path")
        provider = providers.setdefault(name, {
            **{k: v for k, v in preset["provider"].items()},
            "argv": [binary, *preset["provider"]["argv"][1:]],
            "models": {}, "default_model": model,
            "author_identity": preset.get("vendor") or name,
        })
        existing = provider.get("_bin")
        if existing and existing != binary:
            raise SetupError(f"agents.{alias}: {name} already uses {existing}; one binary per preset")
        provider["_bin"] = binary
        overrides = spec.get("env", {})
        if not isinstance(overrides, dict):
            raise SetupError(f"agents.{alias}.env must map variable names to values or ${{NAME}} references")
        merged = {**preset["provider"].get("env", {}), **provider.get("_env_override", {})}
        for key, value in overrides.items():
            if key in provider.get("_env_override", {}) and provider["_env_override"][key] != value:
                raise SetupError(f"agents.{alias}.env.{key} conflicts with another {name} agent")
            merged[key] = value
        provider["_env_override"] = {**provider.get("_env_override", {}), **overrides}
        if merged:
            provider["env"] = merged
        levels = spec.get("effort", preset.get("effort_levels", []))
        if not isinstance(levels, list) or any(level not in LEVELS for level in levels):
            raise SetupError(f"agents.{alias}.effort must list levels from {', '.join(LEVELS)}")
        previous = provider["models"].get(model)
        if previous is not None and previous["supported_effort"] != levels:
            raise SetupError(f"agents.{alias}: model {model!r} already declared with other effort levels")
        provider["models"][model] = {"supported_effort": list(levels)}
        profiles[alias] = {"provider": name, "model": model,
                           "role": spec.get("role", "worker"),
                           "description": spec.get("description", ""),
                           # Every profile is its own author unless the person says
                           # two profiles are one account; a different model on the
                           # same vendor is a different reader.
                           "author_identity": spec.get("author_identity", alias)}
    for provider in providers.values():
        provider.pop("_bin", None)
        provider.pop("_env_override", None)

    config = {"providers": providers, "agents": profiles,
              "reviewers": answers.get("reviewers", {}),
              "role_bindings": answers.get("role_bindings", {})}
    for key in ("review_policy", "memory_k", "memory_max_chars", "timeout"):
        if key in answers:
            config[key] = answers[key]
    try:
        validate_config(json.loads(json.dumps(config)))
    except ProviderConfigError as exc:
        raise SetupError(f"generated config is invalid: {exc}") from exc

    roles = answers.get("roles", {})
    if not isinstance(roles, dict):
        raise SetupError("answers.roles must map role names to an agent or a list of agents")
    for role, chain in roles.items():
        chain_list = [chain] if isinstance(chain, str) else chain
        if not isinstance(chain_list, list) or not chain_list or any(a not in profiles for a in chain_list):
            raise SetupError(f"roles.{role} must name configured agents")
    return config, roles


def write(answers, config_path, roles_path, force=False, presets=None, detected=None):
    config_path, roles_path = Path(config_path), Path(roles_path)
    config, roles = build(answers, presets, detected if detected is not None else detect(presets))
    targets = [config_path] + ([roles_path] if roles else [])
    existing = [p for p in targets if p.exists()]
    if existing and not force:
        raise SetupError("refusing to overwrite " + ", ".join(map(str, existing)) + " (use --force)")
    for path, data in ((config_path, config), (roles_path, roles)):
        if path is roles_path and not roles:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    return {"config": str(config_path), "roles": str(roles_path) if roles else None,
            "providers": sorted(config["providers"]), "agents": sorted(config["agents"])}
