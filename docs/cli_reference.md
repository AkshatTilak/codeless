# CLI Reference & Invocation Guide

Codeless provides a full-featured terminal interface and headless command-line client supporting interactive REPL sessions, headless CI scripts, multi-turn reasoning, and shadow workspace management.

---

## Basic Syntax

```bash
codeless [OPTIONS] [COMMAND] [PROMPT]
```

Aliases: `clh`

---

## Core Execution Modes

### 1. Interactive Terminal Session (Default)
Starts the rich Ink/TUI terminal session:

```bash
codeless
```

Start with an initial prompt:
```bash
codeless "Refactor the database connection pool in src/db.py"
```

### 2. Headless Print Mode (`-p`, `--print`)
Executes the prompt headlessly and prints the result directly to stdout:

```bash
# Standard text output
codeless -p "Explain how the permission system works"

# Structured JSON output (for scripts and CI)
codeless -p "Analyze the repo and output risks" --output-format json

# Streamed JSON events
codeless -p "Generate test cases for auth.py" --output-format stream-json
```

### 3. Dry-Run Mode (`--dry-run`)
Previews resolved configuration, operational mode, active ABB location, registered tools, and skills without invoking the LLM:

```bash
codeless --dry-run
```

---

## Command Reference

### `codeless setup`
Run interactive onboarding to choose workflows, configure model credentials, and set preferences:
```bash
codeless setup
```

### `codeless abb`
Inspect and manage Agent Buildable Base (ABB) workspaces and location migrations:

```bash
# View active ABB status and resolved paths
codeless abb status

# Migrate active workspace between shadow (home directory) and local (.codeless/)
codeless abb migrate shadow
codeless abb migrate local --force
```

### `codeless projects`
Manage shadow workspaces and disk usage across projects:

```bash
# List all registered shadow project workspaces
codeless projects list

# Clean up stale or inactive shadow workspaces
codeless projects clean
codeless projects clean --all
```

### `codeless cron`
Inspect and manage scheduled cron jobs and background background recurring tasks:

```bash
codeless cron list
codeless cron add "0 * * * *" "uv run pytest -q"
codeless cron remove <job_id>
```

### `codeless mcp`
Manage external Model Context Protocol (MCP) server integrations:

```bash
codeless mcp list
codeless mcp add github "npx -y @modelcontextprotocol/server-github"
codeless mcp test <server_name>
codeless mcp remove <server_name>
```

### `codeless plugin`
Manage installed workflow plugins:

```bash
codeless plugin list
codeless plugin install <plugin_name_or_path>
```

### `codeless auth` & `codeless provider`
Manage API keys, endpoints, and multi-provider profiles:

```bash
codeless auth login
codeless provider list
codeless provider set anthropic
```

---

## Global Options & Flags

| Flag | Description | Options / Defaults |
|---|---|---|
| `--abb-location <loc>` | Specify ABB workspace storage location | `shadow` *(default, ~/.codeless)*, `local` *(in-repo)* |
| `--permission-mode <mode>` | Operational permission safety mode | `default` *(AGENT)*, `plan`, `full_auto` |
| `--model, -m <model>` | Specify model alias or identifier | e.g. `sonnet`, `opus`, `claude-3-7-sonnet-20250219` |
| `--effort <level>` | Reasoning effort tier | `low`, `medium`, `high`, `xhigh` |
| `--max-turns <int>` | Maximum allowed agentic tool turns | e.g. `25` |
| `--continue, -c` | Continue the most recent session in directory | Flag |
| `--resume, -r <id>` | Resume a specific session by ID or picker | Session UUID |
| `--dangerously-skip-permissions` | Bypass all permission checks | Sandbox / CI use only |
| `--theme <name>` | TUI color theme | `default`, `dark`, `minimal`, `cyberpunk`, `solarized` |
| `--debug, -d` | Enable detailed debug output | Flag |
| `--settings <path>` | Load settings from JSON file or JSON string | File path or JSON literal |

---

## Common Workflow Examples

### Starting a Plan-Only Session in Shadow Mode
```bash
codeless --permission-mode plan --abb-location shadow "Design the microservice architecture"
```

### Running Automated Code Review in CI
```bash
codeless -p "Review unstaged diff for security issues" --output-format json --max-turns 10
```

### Checking Shadow Project Footprint
```bash
codeless projects list
```
