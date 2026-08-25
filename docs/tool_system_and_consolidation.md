# Tool System & Consolidated CRUD Architecture

To maximize LLM tool selection accuracy and minimize prompt context overhead, Codeless organizes tool interfaces through **Consolidated CRUD Architecture**. Rather than exposing dozens of small, overlapping tools, operations are grouped into cohesive domain tools with explicit action parameters.

---

## 1. Consolidated Tool Registry

| Consolidated Tool | Action Parameter Options | Description |
|---|---|---|
| **`task`** | `list`, `kill`, `status`, `send_input` | Manage long-running background processes and asynchronous command tasks. |
| **`cron`** | `list`, `add`, `remove`, `status` | Manage scheduled recurring cron routines and background timers. |
| **`worktree`** | `create`, `list`, `remove`, `switch` | Manage isolated git worktree directories for risk-free sandbox experiments. |
| **`mcp_resource`** | `list`, `read`, `subscribe` | Query and stream resources from connected Model Context Protocol servers. |

---

## 2. Core Execution Tools

In addition to consolidated managers, the agent has access to streamlined core file and system tools:

- **`view_file`**: Read file content (text with line slicing, binary support for images/PDFs).
- **`write_to_file`**: Create new files or overwrite existing files atomically.
- **`replace_file_content`**: Perform single contiguous block diff replacement.
- **`multi_replace_file_content`**: Perform multi-chunk non-contiguous code updates in a single atomic pass.
- **`grep_search`**: High-performance Ripgrep pattern search across files and directories.
- **`list_dir`**: Traverse directory hierarchies.
- **`run_command`**: Execute shell commands with background task support and timeout controls.
- **`search_web` & `read_url_content`**: Unified Crawl4AI web research and markdown conversion.
- **`ask_question`**: Interactive multi-choice clarifying modal when user design input is required.

---

## 3. Action-Level Permission Controls

Each action within a consolidated tool can be independently governed by the permission system:

- **Safe Actions** (`task:list`, `cron:list`, `mcp_resource:read`) execute without prompting.
- **Mutating Actions** (`task:kill`, `cron:remove`, `worktree:create`) adhere to active permission mode rules and confirmation policies.

---

## 4. Tool Registry Deduplication

During runtime initialization, Codeless passes all registered tools through an active **Deduplication Filter**:
- Eliminates legacy aliases and duplicate schemas.
- Ensures the model prompt receives a compact, conflict-free system tool manifest.
- Reduces token consumption by up to 35% compared to unbounded tool catalogs.
