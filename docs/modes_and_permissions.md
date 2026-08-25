# Operational Modes & Domain Write Boundaries

Codeless features a robust **4-Mode Operational Architecture** that establishes deterministic write boundaries and safety controls. This ensures agents only modify appropriate files for the current phase of development (e.g. preventing code edits while drafting architecture plans or governing ABB specifications).

---

## 1. The 4 Operational Modes

| Mode | Purpose | Allowed Write Scope | Mutating Tools Allowed |
|---|---|---|---|
| **`PLAN`** | Architecture design, SRS requirements, feature specs, ABB governance & task decomposition | Full ABB workspace (`tasks/**`, `design/**`, `features/**`, `references/**`, `skills/**`, `workflows/**`, `STACK.md`, `CONVENTIONS.md`, `agent.md`, `TODO.md`) | File edits within ABB workspace; mutating bash/exec blocked |
| **`AGENT`** | Full implementation & code writing | Complete repository & workspace | All tools permitted (gated by Two-Track verification) |
| **`ASK`** | Q&A, conceptual inquiries, code explanation | Strictly Read-Only (0 writes) | Mutating tools disabled |
| **`CODEBASE`** | Code exploration, semantic search, debugging | Strictly Read-Only (0 writes) | Mutating tools disabled |

---

## 2. Dynamic Mode Switching

You can seamlessly switch modes during an interactive session using the `/mode` (`/m`) slash command:

```text
/mode plan
/mode agent
/mode ask
/mode codebase
```

### Checking Active Mode
Typing `/mode` without arguments displays the current mode and its boundary constraints:

```text
> /mode
Operational Modes & Domain Write Boundaries:
  - `AGENT`    : Unrestricted implementation & verification (Two-Track gate active)
  - `PLAN`     : Architecture, planning & ABB governance (full read/write in ABB; codebase is read-only)
  - `ASK`      : Strictly read-only inquiry (all mutating operations blocked)
  - `CODEBASE` : Codebase exploration & memory queries (strictly read-only)

Usage: `/mode <agent|plan|ask|codebase>`
```

---

## 3. Launching in a Specific Mode via CLI

To launch a session locked in a specific mode, use the `--permission-mode` flag:

```bash
# Launch in PLAN mode
codeless --permission-mode plan "Design the authentication system"

# Launch in standard AGENT mode
codeless --permission-mode default "Fix the bug in parser.py"

# Launch in non-interactive full auto mode (e.g. for CI sandboxes)
codeless --permission-mode full_auto -p "Run test suite and format code"
```

---

## 4. Domain Write Boundary Enforcement

When an agent attempts a file write operation, the permission controller checks:
1. The **active mode** in `AppState`.
2. The **target file path** normalized through the virtualization layer.

```mermaid
graph TD
    AgentCall[Tool Execution: write_file / edit_file] --> CheckMode{Operational Mode}
    
    CheckMode -->|PLAN| PlanCheck{Target inside ABB workspace?}
    PlanCheck -->|Yes| AllowWrite[Allow Write to ABB Workspace]
    PlanCheck -->|No (Source Code)| BlockWrite[Block with Permission Error]
    
    CheckMode -->|ASK / CODEBASE| BlockAll[Block Write: Strictly Read-Only]
    
    CheckMode -->|AGENT| CheckGate[Two-Track Verification Gate]
    CheckGate --> AllowWrite
```

### Example: Write Attempt in PLAN Mode
If an agent in `PLAN` mode attempts to edit `src/main.py`:
```text
⚠️ Permission Denied: Write to 'src/main.py' is blocked in PLAN mode. 
Writes in PLAN mode are restricted to ABB workspace files.
Switch to AGENT mode using `/mode agent` to perform code modifications.
```

---

## 5. Confirmation Triggers & Bash Execution Guards

In addition to mode boundaries, Codeless provides action-level safety:
- **Destructive Commands**: Dangerous shell commands (`rm -rf`, `format`, dropping databases) require explicit user confirmation.
- **Git State Protection**: Destructive git rollbacks or checkouts require `--force` or explicit prompt confirmation.
- **Network Access**: High-risk outbound requests are subject to approval when operating outside `full_auto`.
