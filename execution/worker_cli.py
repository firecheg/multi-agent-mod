"""Safe subprocess adapter shared by orchestration, context and research."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

# Bootstrap sibling imports whether this module is loaded as a script, as
# `execution.worker_cli`, or via an installed console-script entry point —
# none of those paths add execution/'s own directory to sys.path for us.
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from providers import PROMPT_FILE, ProviderConfigError, ProviderRegistry, load_config
from reasoning_router import assessment_text, route, validate_reasoning_config


def command(provider, model, run, effort=None, registry=None, agent=None, sandbox=None):
    """Build a shell-free argv list from the configured provider registry.

    There is no vendor-specific fallback here: every provider, including any
    third-party CLI, is described entirely by the loaded configuration. A
    missing registry loads the default (env-selected, or bundled demo) one.
    """
    if registry is None:
        registry = ProviderRegistry(load_config())
    if agent is not None:
        return registry.command(agent, run, model=model, effort=effort, sandbox=sandbox)
    return registry.command_for_provider(provider, run, model=model, effort=effort, sandbox=sandbox)


def _decision(config, registry, provider, model, prompt):
    if "_reasoning_decision" in config:
        decision = config["_reasoning_decision"]
        if not isinstance(decision, dict):
            raise ValueError("_reasoning_decision must be an object")
        return decision
    reasoning = validate_reasoning_config({
        **({"effort": config["effort"]} if "effort" in config else {}),
        **({"task_kind": config["task_kind"]} if "task_kind" in config else {}),
        **({"dimensions": config["reasoning_dimensions"]} if "reasoning_dimensions" in config else {}),
        **({"cap": config["cap"]} if "cap" in config else {}),
    })
    return route(provider, model, assessment_text(config.get("_routing_task", prompt)),
                 reasoning.get("dimensions"), reasoning.get("task_kind"),
                 reasoning.get("effort", "auto"), reasoning.get("cap"),
                 capability_resolver=registry.capabilities)


def invoke(prompt, run, config, registry=None, cwd=None):
    """Run one configured provider and persist argv/reasoning/provenance logs.

    `run` is where logs (and this call's cache/results, for callers that use
    one) live; `cwd` is the working directory the subprocess itself sees and
    defaults to `run`. Orchestration passes the actual project directory so
    an agentic CLI's own tool use lands there; bounded context/research
    workers leave the default so the executor cannot side-effect the project.
    """
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    run = Path(run).resolve()
    run.mkdir(parents=True, exist_ok=True)
    cwd = Path(cwd).resolve() if cwd is not None else run
    if registry is None:
        registry = ProviderRegistry(load_config(config.get("config_path")))
    agent = config.get("agent")
    if agent:
        provider, profile_model, spec = registry.resolve(agent)
        model = config.get("model", profile_model)
    else:
        provider = config.get("provider")
        if not isinstance(provider, str) or not provider:
            raise ValueError("provider is required")
        spec = registry.provider(provider)
        model = config.get("model", spec.default_model)
    decision = _decision(config, registry, provider, model, prompt)
    (run / "reasoning.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    argv = command(provider, model, run, decision.get("effective"), registry=registry, agent=agent,
                  sandbox=config.get("sandbox"))
    identity = registry.identity(agent) if agent else spec.author_identity
    metadata = {"provider": provider, "model": model, "agent": agent,
                "author_identity": identity, "argv": argv,
                "reasoning": decision, "status": "dispatched"}
    (run / "argv.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    timeout = config.get("timeout_seconds", spec.timeout_seconds)
    if type(timeout) is not int or timeout <= 0:
        raise ValueError("timeout_seconds must be a positive integer")
    try:
        env = registry.environment(provider, model)
    except ProviderConfigError as exc:
        metadata.update(status="failed", error=str(exc))
        (run / "argv.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    stdin_text = prompt
    if spec.input == "file":
        # The CLI takes the prompt as an argument naming this file; stdin is
        # still created and closed empty so a CLI that also polls it cannot hang.
        (run / PROMPT_FILE).write_text(prompt, encoding="utf-8")
        stdin_text = ""
    try:
        # Passing ``input`` asks subprocess to create and close stdin.  Giving
        # stdin=PIPE as well is rejected by Python before the provider starts.
        proc = subprocess.run(argv, input=stdin_text, cwd=cwd, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, shell=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        metadata.update(status="failed", error=str(exc))
        (run / "argv.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    (run / "worker.json").write_text(proc.stdout, encoding="utf-8")
    (run / "stderr.log").write_text(proc.stderr, encoding="utf-8")
    metadata.update(returncode=proc.returncode, status="ok" if proc.returncode == 0 else "failed")
    (run / "argv.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    if proc.returncode:
        raise ValueError(f"{provider} exited {proc.returncode}; log: {run}; no automatic retry")
    parsed = registry.parse_provider_output(provider, proc.stdout)
    parsed.setdefault("is_error", False)
    parsed.setdefault("subtype", "success")
    parsed.setdefault("provider", provider)
    parsed.setdefault("model", model)
    parsed.setdefault("author_identity", identity)
    return parsed
