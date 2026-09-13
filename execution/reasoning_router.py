"""Deterministic reasoning-effort policy and bounded CLI option helpers."""

ROUTER_POLICY_VERSION = 3
LEVELS = ("low", "medium", "high", "xhigh", "max")
DIMENSIONS = ("scope", "uncertainty", "reasoning_complexity", "risk",
              "verification_complexity")
LOW = {"mechanical", "rename", "format", "lookup", "summary"}
HIGH = {"schema_migration", "security", "concurrency", "flaky_bug",
        "unknown_root_cause"}
XHIGH = {"cross_service_redesign", "prod_data_migration", "incident"}
KINDS = LOW | HIGH | XHIGH | {"review"}


def _dimensions(value):
    if value is None or value == {}:
        return {}
    if not isinstance(value, dict):
        raise ValueError("reasoning dimensions must be an object")
    if set(value) != set(DIMENSIONS):
        raise ValueError("non-empty reasoning dimensions must contain all five fields")
    if any(type(item) is not int or not 0 <= item <= 2 for item in value.values()):
        raise ValueError("reasoning dimensions must be integers from 0 to 2")
    return {name: value[name] for name in DIMENSIONS}


def _choice(name, value, choices, optional=True):
    if value is None and optional:
        return None
    if type(value) is not str or value not in choices:
        raise ValueError(f"invalid {name}")
    return value


def _provider_model(provider, model):
    if type(provider) is not str:
        raise ValueError("provider must be a string")
    if model is not None and (type(model) is not str or not model):
        raise ValueError("model must be a non-empty string or null")
    return provider, model


def validate_reasoning_config(value, allow_model=False):
    """Validate the nested public reasoning contract and return a safe copy."""
    if not isinstance(value, dict):
        raise ValueError("reasoning must be an object")
    allowed = {"effort", "task_kind", "dimensions", "cap"}
    if allow_model:
        allowed.add("model")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError("unknown reasoning fields: " + ", ".join(sorted(unknown)))
    result = dict(value)
    if "effort" in result:
        _choice("effort", result["effort"], ("auto", *LEVELS), optional=False)
    if "task_kind" in result:
        _choice("task kind", result["task_kind"], KINDS, optional=False)
    if "dimensions" in result:
        if result["dimensions"] is None:
            raise ValueError("reasoning dimensions must be an object")
        result["dimensions"] = _dimensions(result["dimensions"])
    if "cap" in result:
        _choice("policy cap", result["cap"], LEVELS, optional=False)
    if "model" in result:
        _provider_model("", result["model"])
    return result


def assess(task="", dimensions=None, task_kind=None, requested=None):
    if type(task) is not str or len(task) > 1600:
        raise ValueError("task must be a string up to 1600 chars")
    d = _dimensions(dimensions)
    kind = _choice("task kind", task_kind, KINDS) or ""
    request = _choice("effort", requested, ("auto", *LEVELS)) or "auto"
    score = sum(d.values())
    recommended = ("medium" if not d else "low" if score <= 2 else
                   "medium" if score <= 5 else "high" if score <= 8 else "xhigh")
    reasons = ["no dimensions supplied; conservative medium" if not d else
               f"dimension score {score}/10"]
    floor = "xhigh" if kind in XHIGH else "high" if kind in HIGH else "low" if kind in LOW else None
    if floor == "low" and not d:
        recommended = "low"
    elif floor and LEVELS.index(floor) > LEVELS.index(recommended):
        recommended = floor
    if floor:
        reasons.append(f"task kind {kind} floor {floor}")
    selected = recommended if request == "auto" else request
    if request != "auto":
        reasons.append("explicit effort requested")
    if floor and LEVELS.index(selected) < LEVELS.index(floor):
        selected = floor
        reasons.append("raised to task floor")
    return {"recommended": recommended, "selected": selected, "requested": request,
            "dimensions": d, "score": score, "task_kind": task_kind,
            "reasons": reasons, "status": "ok", "effective": None}


def capabilities(provider, model=None, capability_resolver=None):
    """Return configured effort levels, or ``None`` when they are unknown."""
    _provider_model(provider, model)
    if capability_resolver is not None:
        levels = capability_resolver(provider, model)
        return None if levels is None else set(levels)
    return None


def route(provider, model, task="", dimensions=None, task_kind=None,
          requested=None, cap=None, capability_resolver=None):
    _provider_model(provider, model)
    policy_cap = _choice("policy cap", cap, LEVELS)
    result = assess(task, dimensions, task_kind, requested)
    result.update(provider=provider, model=model, policy_version=ROUTER_POLICY_VERSION)
    support = capabilities(provider, model, capability_resolver)
    result["supported"] = sorted(support) if support is not None else None
    if policy_cap and LEVELS.index(result["selected"]) > LEVELS.index(policy_cap):
        result["selected"] = policy_cap
        result["reasons"].append(f"policy cap applied: {policy_cap}")
    chosen = result["selected"]
    if result["requested"] == "max" and (support is None or "max" not in support):
        result.update(effective=None, status="unsupported")
        result["reasons"].append("explicit max unsupported")
    elif support is None:
        result.update(effective=None, status="unknown_model")
        result["reasons"].append("unknown provider/model; no flag sent")
    elif chosen not in support:
        result.update(effective=None, status="unsupported")
        result["reasons"].append(f"{chosen} unsupported")
    else:
        result.update(effective=chosen, status="ok")
    return result


def to_worker_config(reasoning):
    """Map a validated reasoning dict onto worker_cli/context_budget config keys.

    `validate_reasoning_config` uses the public field name "dimensions"; the
    worker config dict (consumed by `worker_cli.invoke`/`context_budget.summarize`)
    expects "reasoning_dimensions" instead, matching its own `effort`/`task_kind`/
    `cap`/`model` top-level keys. Centralizing the rename keeps every caller —
    mam.py, index_workers.py, context_server.py — in sync.
    """
    names = {"effort": "effort", "task_kind": "task_kind", "dimensions": "reasoning_dimensions",
             "cap": "cap", "model": "model"}
    return {names[key]: value for key, value in reasoning.items() if key in names}


def assessment_text(task):
    if type(task) is not str:
        raise ValueError("routing task must be a string")
    return task if len(task) <= 1600 else task[:1597] + "..."


def _split_options(args):
    values = list(args)
    try:
        separator = values.index("--")
    except ValueError:
        separator = len(values)
    return values[:separator], values[separator:]


def _assignment(value, key):
    if type(value) is not str or "=" not in value:
        return None
    name, assigned = value.split("=", 1)
    if name != key:
        return None
    if len(assigned) >= 2 and assigned[0] == assigned[-1] and assigned[0] in "\"'":
        assigned = assigned[1:-1]
    return assigned


def replace_effort_args(args, provider, effort):
    if type(provider) is not str:
        raise ValueError("provider must be a string")
    if effort is not None:
        _choice("effort", effort, LEVELS, optional=False)
    head, tail = _split_options(args)
    out, index = [], 0
    while index < len(head):
        value = head[index]
        if provider == "claude" and value == "--effort":
            index += 2 if index + 1 < len(head) else 1
            continue
        if provider == "claude" and value.startswith("--effort="):
            index += 1
            continue
        if provider == "codex" and value in ("--config", "-c") and index + 1 < len(head) \
                and _assignment(head[index + 1], "model_reasoning_effort") is not None:
            index += 2
            continue
        if provider == "codex" and ((value.startswith("--config=") and
                _assignment(value[len("--config="):], "model_reasoning_effort") is not None) or
                (value.startswith("-c") and value != "-c" and
                 _assignment(value[2:], "model_reasoning_effort") is not None)):
            index += 1
            continue
        out.append(value)
        index += 1
    if effort:
        if provider == "claude":
            out.extend(["--effort", effort])
        elif provider == "codex":
            out.extend(["-c", f'model_reasoning_effort="{effort}"'])
    return out + tail


def model_from_args(args, provider):
    if type(provider) is not str:
        raise ValueError("provider must be a string")
    head, _ = _split_options(args)
    explicit, configured = [], []
    index = 0
    while index < len(head):
        value = head[index]
        if value in ("--model", "-m") and index + 1 < len(head):
            explicit.append(head[index + 1]); index += 2; continue
        if value.startswith("--model="):
            explicit.append(value.split("=", 1)[1]); index += 1; continue
        if value.startswith("-m") and value != "-m":
            explicit.append(value[2:]); index += 1; continue
        if provider == "codex" and value in ("--config", "-c") and index + 1 < len(head):
            selected = _assignment(head[index + 1], "model")
            if selected is not None:
                configured.append(selected); index += 2; continue
        if provider == "codex" and value.startswith("--config="):
            selected = _assignment(value[len("--config="):], "model")
            if selected is not None:
                configured.append(selected)
        elif provider == "codex" and value.startswith("-c") and value != "-c":
            selected = _assignment(value[2:], "model")
            if selected is not None:
                configured.append(selected)
        index += 1
    if explicit and configured and set(explicit) != set(configured):
        raise ValueError("conflicting model selectors")
    choices = explicit or configured
    if len(set(choices)) > 1:
        raise ValueError("conflicting model selectors")
    model = choices[-1] if choices else None
    _provider_model(provider, model)
    return model


def replace_model_args(args, provider, model):
    _provider_model(provider, model)
    if model is None:
        return list(args)
    head, tail = _split_options(args)
    out, index = [], 0
    while index < len(head):
        value = head[index]
        if value in ("--model", "-m"):
            index += 2 if index + 1 < len(head) else 1
            continue
        if value.startswith("--model=") or (value.startswith("-m") and value != "-m"):
            index += 1
            continue
        if provider == "codex" and value in ("--config", "-c") and index + 1 < len(head) \
                and _assignment(head[index + 1], "model") is not None:
            index += 2
            continue
        if provider == "codex" and ((value.startswith("--config=") and
                _assignment(value[len("--config="):], "model") is not None) or
                (value.startswith("-c") and value != "-c" and
                 _assignment(value[2:], "model") is not None)):
            index += 1
            continue
        out.append(value); index += 1
    return out + ["--model", model] + tail
