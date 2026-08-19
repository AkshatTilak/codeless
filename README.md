# Codeless

> *"Code less: you steer the base, the harness builds."*

Autonomous agent execution harness engineered specifically to orchestrate, execute, and verify software projects governed by the **Agent Buildable Base (ABB)** paradigm.

---

## Overview

Codeless bridges the declarative, modular architecture of **Agent Buildable Base** with autonomous agent execution, deterministic guardrails, shadow workspace isolation, and multi-track verification.

- **CLI Entrypoints**: `codeless`, `clh`
- **Config Home**: `~/.codeless/`
- **Architecture**: Hard-forked foundation from `HKUDS/OpenHarness` with isolated `src/codeless/abb/` runtime bridge.

## Core Features

- **Zero-Pollution Shadow Workspaces**: Automatically provisions `~/.codeless/projects/<project_hash>/abb_workspace/` from ABB templates, keeping user codebases pristine.
- **In-Repo Dev Override**: Supports `.codeless/abb_workspace/` for direct dogfooding and template development.
- **Deterministic Guardrails & Verification**: Enforces DAG task dependencies, YAML frontmatter schemas, and two-track automated verification.
- **Universal Provider Gateway**: Provider-agnostic engine supporting Anthropic, OpenAI, Claude/Codex subscriptions, and local models.

## Development Setup

```powershell
# Install dependencies with uv
uv sync --extra dev

# Run test suite
uv run pytest -q

# Run Codeless CLI
uv run codeless --help
```
