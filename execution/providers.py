"""Configuration driven command providers for the public Agent Harness.

Provider definitions are data.  The executor only constructs an argument
vector and sends a prompt on stdin; it never invokes a shell or evaluates a
configuration string.  This keeps the core usable with any CLI that follows
the small stdin/stdout contract, including the bundled deterministic demo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from dataclasses import dataclass


LEVELS = ("low", "medium", "high", "xhigh", "max")
_TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ALLOWED_TOKENS = {"python", "package_dir", "model", "effort", "run", "provider", "sandbox", "prompt_file"}
_OUTPUTS = {"text", "json", "json_field"}
# stdin: the prompt is written to the process's standard input.
# file: the prompt is written to <run>/prompt.md, passed as {prompt_file}, and
# stdin stays empty — for CLIs that only accept the prompt as an argument.
_INPUTS = {"stdin", "file"}
PROMPT_FILE = "prompt.md"
# Provider `env`: literal values, "{model}", or a whole-value "${NAME}" copied
# from the caller's environment at run time. "" removes an inherited variable.
# Anything that looks like a credential must be a reference, never a literal.
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.I)


class ProviderConfigError(ValueError):
    """Raised before a configured subprocess can be started."""


def _string(value, label, *, nonempty=True):
    if not isinstance(value, str) or (nonempty and not value):
        raise ProviderConfigError(f"{label} must be a non-empty string")
    return value


def _string_list(value, label, *, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value) or not all(
            isinstance(item, str) and item for item in value):
        raise ProviderConfigError(f"{label} must be a list of non-empty strings")
    return list(value)


def _check_tokens(values, label):
    for value in values:
        unknown = set(_TOKEN.findall(value)) - _ALLOWED_TOKENS
        if unknown:
            raise ProviderConfigError(
                f"{label} uses unknown template token(s): {', '.join(sorted(unknown))}")
    return values


def _capabilities(model_spec, label):
    if isinstance(model_spec, list):
        levels = model_spec
    elif isinstance(model_spec, dict):
        levels = model_spec.get("supported_effort", model_spec.get("effort_levels"))
    else:
        raise ProviderConfigError(f"{label} must be an object or effort list")
    if not isinstance(levels, list) or any(
            type(item) is not str or item not in LEVELS for item in levels):
        raise ProviderConfigError(f"{label}.supported_effort must list reasoning levels")
    return tuple(dict.fromkeys(levels))


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    argv: tuple[str, ...]
    model_args: tuple[str, ...]
    effort_args: tuple[str, ...]
    sandbox_args: tuple[str, ...]
    default_sandbox: str | None
    output: str
    output_field: str | None
    default_model: str
    models: dict[str, tuple[str, ...]]
    author_identity: str
    timeout_seconds: int
    input: str = "stdin"
    env: tuple[tuple[str, str], ...] = ()

    def capabilities(self, model: str | None = None):
        selected = model or self.default_model
        return set(self.models.get(selected, ())) if selected in self.models else None


# independent: any reviewer with another author identity may review first.
# other_provider: the first (primary) reviewer must also run on another provider.
_PRIMARY_POLICIES = {"independent", "other_provider"}


def validate_config(config):
    """Validate and normalize the public JSON config without starting a CLI."""
    if not isinstance(config, dict):
        raise ProviderConfigError("configuration must be an object")
    allowed = {"memory_k", "memory_max_chars", "timeout", "providers", "agents",
               "reviewers", "review_policy", "role_bindings", "limits", "shared_dir"}
    unknown = set(config) - allowed
    if unknown:
        raise ProviderConfigError("unknown configuration fields: " + ", ".join(sorted(unknown)))
    providers = config.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ProviderConfigError("providers must be a non-empty object")
    normalized = dict(config)
    normalized["providers"] = {}
    for name, raw in providers.items():
        _string(name, "provider name")
        if not isinstance(raw, dict):
            raise ProviderConfigError(f"providers.{name} must be an object")
        allowed_provider = {"argv", "input", "output", "output_field", "model_args",
                            "effort_args", "sandbox_args", "default_sandbox", "models",
                            "default_model", "author_identity", "timeout_seconds", "env"}
        extra = set(raw) - allowed_provider
        if extra:
            raise ProviderConfigError(f"providers.{name}: unknown fields: {', '.join(sorted(extra))}")
        argv = _check_tokens(_string_list(raw.get("argv"), f"providers.{name}.argv", nonempty=True),
                             f"providers.{name}.argv")
        input_mode = raw.get("input", "stdin")
        if input_mode not in _INPUTS:
            raise ProviderConfigError(f"providers.{name}.input must be 'stdin' or 'file'")
        mentions_file = any("{prompt_file}" in item for item in argv)
        if input_mode == "file" and not mentions_file:
            raise ProviderConfigError(f"providers.{name}: input 'file' requires {{prompt_file}} in argv")
        if input_mode == "stdin" and mentions_file:
            raise ProviderConfigError(f"providers.{name}: {{prompt_file}} requires input 'file'")
        output = raw.get("output", "text")
        if output not in _OUTPUTS:
            raise ProviderConfigError(f"providers.{name}.output must be text, json, or json_field")
        output_field = raw.get("output_field")
        if output == "json_field":
            _string(output_field, f"providers.{name}.output_field")
        elif output_field is not None:
            raise ProviderConfigError(f"providers.{name}.output_field only applies to json_field")
        models_raw = raw.get("models")
        if not isinstance(models_raw, dict) or not models_raw:
            raise ProviderConfigError(f"providers.{name}.models must be a non-empty object")
        models = {model: _capabilities(spec, f"providers.{name}.models.{model}")
                  for model, spec in models_raw.items()}
        for model in models:
            _string(model, f"providers.{name}.models model")
        default_model = raw.get("default_model")
        if default_model not in models:
            raise ProviderConfigError(f"providers.{name}.default_model must name a configured model")
        identity = _string(raw.get("author_identity"), f"providers.{name}.author_identity")
        timeout = raw.get("timeout_seconds", config.get("timeout", 180))
        if type(timeout) is not int or timeout <= 0:
            raise ProviderConfigError(f"providers.{name}.timeout_seconds must be a positive integer")
        model_args = _check_tokens(_string_list(raw.get("model_args", []),
                                                f"providers.{name}.model_args"),
                                   f"providers.{name}.model_args")
        effort_args = _check_tokens(_string_list(raw.get("effort_args", []),
                                                 f"providers.{name}.effort_args"),
                                    f"providers.{name}.effort_args")
        # A provider that never declares sandbox_args has no sandbox concept at
        # all; a per-task override is then a configuration error, not a no-op.
        sandbox_args = _check_tokens(_string_list(raw.get("sandbox_args", []),
                                                  f"providers.{name}.sandbox_args"),
                                     f"providers.{name}.sandbox_args")
        default_sandbox = raw.get("default_sandbox")
        if default_sandbox is not None:
            _string(default_sandbox, f"providers.{name}.default_sandbox")
        if default_sandbox and not sandbox_args:
            raise ProviderConfigError(f"providers.{name}.default_sandbox requires sandbox_args")
        env = raw.get("env", {})
        if not isinstance(env, dict):
            raise ProviderConfigError(f"providers.{name}.env must be an object")
        for key, value in env.items():
            if not isinstance(key, str) or not _ENV_NAME.fullmatch(key):
                raise ProviderConfigError(f"providers.{name}.env: invalid variable name {key!r}")
            if not isinstance(value, str):
                raise ProviderConfigError(f"providers.{name}.env.{key} must be a string")
            if _ENV_REF.search(value) and not _ENV_REF.fullmatch(value):
                raise ProviderConfigError(f"providers.{name}.env.{key}: ${{NAME}} must be the whole value")
            if set(_TOKEN.findall(_ENV_REF.sub("", value))) - {"model"}:
                raise ProviderConfigError(f"providers.{name}.env.{key}: only {{model}} and ${{NAME}} are expanded")
            if value and _SECRET_NAME.search(key) and not _ENV_REF.fullmatch(value):
                raise ProviderConfigError(
                    f"providers.{name}.env.{key} looks like a credential: write ${{YOUR_VARIABLE}}, "
                    f"never the value")
        normalized["providers"][name] = {
            "env": dict(env),
            "argv": argv, "input": input_mode, "output": output,
            "output_field": output_field, "model_args": model_args,
            "effort_args": effort_args, "sandbox_args": sandbox_args,
            "default_sandbox": default_sandbox, "models": models,
            "default_model": default_model, "author_identity": identity,
            "timeout_seconds": timeout,
        }
    agents = config.get("agents", {})
    if not isinstance(agents, dict) or not agents:
        raise ProviderConfigError("agents must be a non-empty object")
    normalized["agents"] = {}
    for alias, raw in agents.items():
        _string(alias, "agent profile name")
        if not isinstance(raw, dict):
            raise ProviderConfigError(f"agents.{alias} must be an object")
        extra = set(raw) - {"provider", "model", "role", "description", "author_identity"}
        if extra:
            raise ProviderConfigError(f"agents.{alias}: unknown fields: {', '.join(sorted(extra))}")
        provider = _string(raw.get("provider"), f"agents.{alias}.provider")
        if provider not in normalized["providers"]:
            raise ProviderConfigError(f"agents.{alias} references unknown provider {provider!r}")
        model = raw.get("model", normalized["providers"][provider]["default_model"])
        if model not in normalized["providers"][provider]["models"]:
            raise ProviderConfigError(f"agents.{alias} references unknown model {model!r}")
        if "author_identity" in raw:
            _string(raw["author_identity"], f"agents.{alias}.author_identity")
        normalized["agents"][alias] = {"provider": provider, "model": model,
                                        "role": raw.get("role", "worker"),
                                        "description": raw.get("description", ""),
                                        **({"author_identity": raw["author_identity"]}
                                           if "author_identity" in raw else {})}
    reviewers = config.get("reviewers", {})
    if not isinstance(reviewers, dict):
        raise ProviderConfigError("reviewers must be an object")
    normalized["reviewers"] = {}
    for author, names in reviewers.items():
        if author not in normalized["agents"] or not isinstance(names, list) or not all(
                isinstance(item, str) and item in normalized["agents"] for item in names):
            raise ProviderConfigError(f"reviewers.{author} must list configured agent profiles")
        normalized["reviewers"][author] = list(names)
    policy = config.get("review_policy", {})
    if not isinstance(policy, dict) or set(policy) - {"primary"} \
            or policy.get("primary", "independent") not in _PRIMARY_POLICIES:
        raise ProviderConfigError(
            "review_policy must be an object with primary: " + " or ".join(sorted(_PRIMARY_POLICIES)))
    normalized["review_policy"] = {"primary": policy.get("primary", "independent")}
    bindings = config.get("role_bindings", {})
    if not isinstance(bindings, dict) or any(
            not isinstance(role, str) or not isinstance(alias, str) or alias not in normalized["agents"]
            for role, alias in bindings.items()):
        raise ProviderConfigError("role_bindings must map role names to configured agent profiles")
    normalized["role_bindings"] = dict(bindings)
    for key in ("memory_k", "memory_max_chars"):
        if key in normalized and (type(normalized[key]) is not int or normalized[key] < 0):
            raise ProviderConfigError(f"{key} must be a non-negative integer")
    if "timeout" in normalized and (type(normalized["timeout"]) is not int or normalized["timeout"] <= 0):
        raise ProviderConfigError("timeout must be a positive integer")
    return normalized


def load_config(path=None):
    """Load explicit config, env-selected config, or the bundled public demo."""
    selected = path or os.environ.get("AGENT_HARNESS_CONFIG")
    if selected:
        config_path = Path(selected).expanduser().resolve()
    else:
        config_path = Path(__file__).resolve().parents[1] / "examples" / "default-config.json"
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderConfigError(f"cannot load config {config_path}: {exc}") from exc
    result = validate_config(data)
    result["_config_path"] = str(config_path)
    return result


class ProviderRegistry:
    def __init__(self, config):
        self.config = validate_config(config) if "_config_path" not in config else config

    def profile(self, alias):
        try:
            return self.config["agents"][alias]
        except KeyError as exc:
            raise ProviderConfigError(f"unknown agent profile {alias!r}") from exc

    def provider(self, name):
        try:
            raw = self.config["providers"][name]
        except KeyError as exc:
            raise ProviderConfigError(f"unknown provider {name!r}") from exc
        return ProviderSpec(name=name, argv=tuple(raw["argv"]),
                            model_args=tuple(raw["model_args"]), effort_args=tuple(raw["effort_args"]),
                            sandbox_args=tuple(raw.get("sandbox_args", ())),
                            default_sandbox=raw.get("default_sandbox"),
                            output=raw["output"], output_field=raw.get("output_field"),
                            default_model=raw["default_model"], models=raw["models"],
                            author_identity=raw["author_identity"],
                            timeout_seconds=raw["timeout_seconds"],
                            input=raw.get("input", "stdin"),
                            env=tuple(raw.get("env", {}).items()))

    def environment(self, provider, model=None, base=None):
        """The subprocess environment for `provider`: the caller's environment
        with the provider's `env` applied. A missing referenced variable fails
        before anything starts, naming the variable to set."""
        spec = self.provider(provider)
        env = dict(os.environ if base is None else base)
        for key, value in spec.env:
            if value == "":
                env.pop(key, None)
                continue
            ref = _ENV_REF.fullmatch(value)
            if ref:
                if ref.group(1) not in env or not env[ref.group(1)]:
                    raise ProviderConfigError(
                        f"provider {provider!r} needs environment variable {ref.group(1)} (for {key})")
                env[key] = env[ref.group(1)]
            else:
                env[key] = value.replace("{model}", model or spec.default_model)
        return env

    def resolve(self, alias):
        profile = self.profile(alias)
        spec = self.provider(profile["provider"])
        return profile["provider"], profile["model"], spec

    def capabilities(self, provider, model=None):
        return self.provider(provider).capabilities(model)

    def identity(self, alias):
        provider, _, spec = self.resolve(alias)
        return self.profile(alias).get("author_identity", spec.author_identity)

    def role_agent(self, role):
        """Return the explicitly configured agent for a role.

        Missing bindings fail closed. Choosing the first configured profile
        could silently route a bounded read to an unintended or costly worker.
        """
        bound = self.config.get("role_bindings", {}).get(role)
        if not bound:
            raise ProviderConfigError(f"missing role binding for {role!r}")
        return bound

    def reviewer_candidates(self, author):
        author_identity = self.identity(author)
        result = []
        for candidate in self.config.get("reviewers", {}).get(author, []):
            if self.identity(candidate) != author_identity:
                result.append(candidate)
        return result

    def primary_allowed(self, author, candidate):
        """Whether `candidate` may be the primary reviewer of `author`'s work.

        Identity independence is checked by reviewer_candidates; this adds the
        configured primary policy on top of it.
        """
        if self.config.get("review_policy", {}).get("primary", "independent") != "other_provider":
            return True
        return self.profile(candidate)["provider"] != self.profile(author)["provider"]

    @staticmethod
    def _expand(value, *, model, effort, run, provider, sandbox=""):
        values = {"python": sys.executable,
                  "package_dir": str(Path(__file__).resolve().parents[1]),
                  "model": model or "", "effort": effort or "", "run": str(run),
                  "provider": provider, "sandbox": sandbox or "",
                  "prompt_file": str(Path(run) / PROMPT_FILE)}
        return _TOKEN.sub(lambda match: values[match.group(1)], value)

    def command(self, alias, run, model=None, effort=None, sandbox=None):
        provider, profile_model, spec = self.resolve(alias)
        return self.command_for_provider(provider, run, model=model or profile_model,
                                         effort=effort, sandbox=sandbox)

    def command_for_provider(self, provider, run, model=None, effort=None, sandbox=None):
        spec = self.provider(provider)
        model = model or spec.default_model
        if model not in spec.models:
            raise ProviderConfigError(f"unknown model {model!r} for provider {provider!r}")
        args = [self._expand(item, model=model, effort=effort, run=run, provider=provider)
                for item in spec.argv]
        if spec.model_args:
            args.extend(self._expand(item, model=model, effort=effort, run=run, provider=provider)
                        for item in spec.model_args)
        if effort:
            if effort not in spec.capabilities(model):
                raise ProviderConfigError(f"{provider}/{model} does not support effort {effort}")
            args.extend(self._expand(item, model=model, effort=effort, run=run, provider=provider)
                        for item in spec.effort_args)
        if sandbox is not None or spec.default_sandbox:
            mode = sandbox if sandbox is not None else spec.default_sandbox
            if mode:
                if not spec.sandbox_args:
                    raise ProviderConfigError(f"provider {provider!r} has no sandbox_args configured")
                args.extend(self._expand(item, model=model, effort=effort, run=run,
                                         provider=provider, sandbox=mode)
                            for item in spec.sandbox_args)
        return args

    def parse_output(self, alias, stdout):
        provider, _, spec = self.resolve(alias)
        return self._parse_output(provider, spec, stdout)

    def parse_provider_output(self, provider, stdout):
        spec = self.provider(provider)
        return self._parse_output(provider, spec, stdout)

    @staticmethod
    def _parse_output(provider, spec, stdout):
        if spec.output == "text":
            return {"result": stdout, "usage": None, "modelUsage": None,
                    "total_cost_usd": None}
        try:
            value = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ProviderConfigError(f"{provider} returned invalid JSON: {exc}") from exc
        if spec.output == "json":
            if not isinstance(value, dict):
                raise ProviderConfigError(f"{provider} JSON output must be an object")
            return value
        result = value
        for part in spec.output_field.split("."):
            if not isinstance(result, dict) or part not in result:
                raise ProviderConfigError(f"{provider} JSON output missing field {spec.output_field!r}")
            result = result[part]
        if not isinstance(result, str):
            raise ProviderConfigError(f"{provider} output field must be text")
        return {"result": result, "usage": value.get("usage") if isinstance(value, dict) else None,
                "modelUsage": value.get("modelUsage") if isinstance(value, dict) else None,
                "total_cost_usd": value.get("total_cost_usd") if isinstance(value, dict) else None}


def scrub_legacy_environment():
    """Keep old private installation selectors from changing public defaults."""
    for key in ("MAM_HOME", "MAM_CONFIG"):
        os.environ.pop(key, None)
