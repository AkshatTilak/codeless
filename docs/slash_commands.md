# Interactive Slash Commands Reference

Codeless features interactive **Slash Commands** available directly within the terminal chat interface. Slash commands allow you to control runtime modes, inspect task graphs, query architectural memory, take checkpoints, and audit drift without leaving the session.

---

## Command Quick Reference

| Command | Aliases | Description | Example Usage |
|---|---|---|---|
| `/mode` | `/m` | Switch operational mode and domain write boundaries | `/mode plan`, `/mode agent` |
| `/checkpoint` | `/cp` | Save, list, inspect, and restore dual-state git snapshots | `/checkpoint save v1`, `/checkpoint restore v1` |
| `/drift` | `/d` | Run codebase and spec drift audit | `/drift`, `/drift --feed-issues` |
| `/tasks` | `/t` | Inspect task DAG and active subtask progress | `/tasks`, `/tasks sub` |
| `/plan` | `/p` | View active implementation plan and milestones | `/plan` |
| `/feature` | `/f` | Inspect and list system feature specifications | `/feature`, `/feature auth` |
| `/references`| `/ref` | Query the 11-domain architectural memory bank | `/references db`, `/references api` |
| `/stack` | `/st` | View project stack manifest and test commands | `/stack` |
| `/prefs` | `/pr` | View user conventions and preferences | `/prefs` |
| `/skills` | — | Inspect registered skills and dual-format YAML index | `/skills` |
| `/mcp` | — | Inspect connected MCP servers and available tools | `/mcp` |
| `/help` | `/?` | Display the interactive help directory | `/help` |

---

## Detailed Command Walkthroughs

### 1. `/mode` (`/m`)
Switch the agent's write boundaries dynamically:
```text
> /mode plan
🔄 Operational Mode switched to: PLAN
Domain write boundary updated: writes restricted to tasks/ and design/.
```

### 2. `/checkpoint` (`/cp`)
Capture or restore snapshots of both code and ABB task state:
```text
> /checkpoint save before_refactor "State before refactoring models"
🛡️ Checkpoint Saved:
  - ID: `cp_20260825_141500_3a8f1b`
  - Name: `before_refactor`
  - Files: 42
  - Location: shadow

> /checkpoint restore before_refactor --force
✅ Successfully restored checkpoint 'before_refactor' (cp_20260825_141500_3a8f1b).
```

### 3. `/drift` (`/d`)
Detect discrepancies between code, task DAGs, and specs:
```text
> /drift --feed-issues
🔍 Running ABB Drift Audit...
⚠️ Drift Audit Detected 1 Issue(s):
  - [SCHEMA] tasks/sub/04_task.md: Missing required frontmatter field 'id'

📝 Logged drift findings to: `references/issues/technical_debt.md`
```

### 4. `/references` (`/ref`)
Query architectural memory bank domains directly:
```text
> /references db
📚 Memory Bank: references/db/
  - models.md: Core ORM schema definitions and relationships
  - migrations.md: Migration guidelines and index strategy
```

### 5. `/stack` (`/st`)
Display the active technology stack and verification requirements:
```text
> /stack
🛠️ Project Stack Manifest (from STACK.md):
  - Language: Python >=3.11
  - Package Manager: uv
  - Linter: ruff
  - Test Suite: pytest
  - Verification Command: `uv run pytest -q && uv run ruff check src tests`
```
