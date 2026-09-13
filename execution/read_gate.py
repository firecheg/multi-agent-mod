"""Bound full-file reads issued through a client's pre-tool-use hook.

Recognizes the request shapes of a few clients (Claude Code's Read/Bash tool
hooks, a generic PowerShell hook, Codex's exec_command) by the `tool_name`
field the hook payload carries; this is not a universal sandbox and does not
claim to cover every client or every way to read a file. It is deliberately a
small recognizer, rather than a shell parser: commands whose syntax is not
understood are allowed through for the normal tool to handle, and the gate
only denies a confidently identified unbounded read.
"""

from __future__ import annotations

import shlex
from pathlib import Path
import re


_EXEMPT = {"agents.md", "claude.md", "skill.md"}
_READERS = {"cat", "head", "tail", "less", "more", "get-content", "gc", "type"}
_TARGETS = {"grep", "rg", "select-string"}


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _split_operator(command: str, operator: str) -> list[str] | None:
    """Split on an unquoted operator; return None for unmatched quotes."""
    parts, start, quote = [], 0, None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote:
            if ch == quote and (i == 0 or command[i - 1] != "^"):
                quote = None
        elif ch in "\"'":
            quote = ch
        elif command.startswith(operator, i):
            parts.append(command[start:i])
            start = i + len(operator)
            i += len(operator) - 1
        i += 1
    if quote:
        return None
    parts.append(command[start:])
    return parts


def _tokens(segment: str) -> list[str] | None:
    try:
        return [_unquote(token) for token in shlex.split(segment, posix=False)]
    except ValueError:
        return None


def _numeric(value: str) -> bool:
    return bool(re.fullmatch(r"[1-9]\d*", value))


def _bounded(tokens: list[str], reader: str) -> bool:
    if reader in {"head", "tail"}:
        for i, token in enumerate(tokens[1:], 1):
            if re.fullmatch(r"-[1-9]\d*", token):
                return True
            if token in {"-n", "--lines"} and i + 1 < len(tokens) and _numeric(tokens[i + 1]):
                return True
            if token.startswith("--lines=") and _numeric(token.split("=", 1)[1]):
                return True
        return False
    if reader == "get-content" or reader == "gc":
        for i, token in enumerate(tokens[1:], 1):
            name, _, value = token.partition("=")
            if name.lower() in {"-totalcount", "-head", "-tail"} and _numeric(value):
                return True
            if token.lower() in {"-totalcount", "-head", "-tail"} and i + 1 < len(tokens):
                if _numeric(tokens[i + 1]):
                    return True
    return False


def _literal_paths(tokens: list[str], reader: str) -> list[str]:
    values = []
    i = 1
    while i < len(tokens):
        token = tokens[i]
        low = token.lower()
        if reader in {"get-content", "gc"} and low in {"-path", "-literalpath"}:
            if i + 1 < len(tokens):
                candidate = tokens[i + 1]
                if not any(mark in candidate for mark in ("$", "*", "?", "`", "$(", "%")):
                    values.append(candidate)
                i += 2
                continue
        if token.startswith("-") or (reader in {"head", "tail"} and re.fullmatch(r"-\d+", token)):
            if low in {"-n", "--lines", "-totalcount", "-head", "-tail", "-encoding"}:
                i += 2
            else:
                i += 1
            continue
        if any(mark in token for mark in ("$", "*", "?", "`", "$(", "%")):
            i += 1
            continue
        values.append(token)
        i += 1
    return values


def _targeted_pipeline(segments: list[list[str]]) -> bool:
    for tokens in segments[1:]:
        if not tokens:
            continue
        command = Path(tokens[0]).name.lower()
        if command in _TARGETS:
            return True
        if command == "select-object":
            for i, token in enumerate(tokens[1:], 1):
                name, _, value = token.partition("=")
                if name.lower() in {"-first", "-last"} and _numeric(value):
                    return True
                if token.lower() in {"-first", "-last"} and i + 1 < len(tokens) and _numeric(tokens[i + 1]):
                    return True
    return False


def _deny(path: Path, lines: int, threshold: int) -> dict:
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"Reading all of {path.name} ({lines} lines) is bounded. "
            "Use a search and a line range, or agent_harness.context_read with a specific "
            "question (research_batch/Graphify for related files)."
        ),
    }}


def _check_file(path_text: str, cwd: str | Path, threshold: int) -> dict:
    path = Path(path_text)
    if not path.is_absolute():
        path = Path(cwd) / path
    try:
        path = path.resolve()
        if path.name.lower() in _EXEMPT or not path.is_file():
            return {}
        with path.open(encoding="utf-8", errors="replace") as stream:
            lines = sum(1 for _ in stream)
    except (OSError, ValueError):
        return {}
    return _deny(path, lines, threshold) if lines > threshold else {}


def check(request: dict, threshold: int = 350) -> dict:
    """Return a Claude hook denial for confidently detected large full reads."""
    if request.get("tool_name") == "Read":
        inp = request.get("tool_input") or {}
        if inp.get("offset") is not None or inp.get("limit") is not None:
            return {}
        path = inp.get("file_path")
        return _check_file(path, request.get("cwd", "."), threshold) if isinstance(path, str) else {}

    tool_name = request.get("tool_name")
    if tool_name not in {"Bash", "PowerShell", "exec_command"}:
        return {}
    inp = request.get("tool_input") or {}
    command = inp.get("command") if tool_name != "exec_command" else inp.get("cmd")
    if not isinstance(command, str) or not command.strip():
        return {}
    segments_text = _split_operator(command, "|")
    if segments_text is None or len(segments_text) > 1 and any(op in command for op in ("||",)):
        return {}
    segments = [_tokens(segment) for segment in segments_text]
    if any(tokens is None or not tokens for tokens in segments):
        return {}
    first = segments[0]
    reader = Path(first[0]).name.lower()
    if reader not in _READERS:
        return {}
    if len(segments) > 1:
        # A query/filter pipeline limits what reaches the agent. Other pipes
        # (including cat | cat) remain unbounded and are checked below.
        if _targeted_pipeline(segments):
            return {}
    if len(segments) == 1 and _bounded(first, reader):
        return {}
    if len(segments) == 1 and any(len(parts or []) > 1 for parts in (_split_operator(command, ">"), _split_operator(command, ">>"))):
        return {}
    paths = _literal_paths(first, reader)
    if not paths:
        return {}
    cwd = inp.get("cwd", inp.get("workdir", request.get("cwd", ".")))
    for path in paths:
        result = _check_file(path, cwd, threshold)
        if result:
            return result
    return {}
