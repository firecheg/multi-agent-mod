# Implementation Plan

1. Graphify adapter: явная привязка проекта к графу, bounded CLI query, локальный артефакт.
2. Два CLI worker adapter и research_batch MCP с лимитами и без автоматического fallback.
3. Общий read gate, native Claude/Codex registration с сохранением чужих hooks.
4. Тесты, два smoke-вызова, актуализация правил и отчёт о границах enforcement.

Codex owns workers, registry and MCP. Luna owns only read_gate.py/test_read_gate.py.
Existing user changes in agents.json and graphs remain untouched.
