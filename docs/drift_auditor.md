# Codebase Drift Auditor & Feedback Loop

The **Codebase Drift Auditor** is an automated governance mechanism that continuously compares the state of the codebase, task files, feature specifications, and skill indices against the project architectural contract defined in `STACK.md`.

---

## 1. What is Architectural Drift?

Over long development cycles, software repositories naturally drift from their architectural specifications:
- **Schema Drift**: Subtasks missing required YAML fields or having invalid statuses.
- **DAG Dependency Drift**: Subtasks marked `done` whose prerequisites were never completed.
- **Skill Index Drift**: Skills present on disk but omitted from `skills/skills.md` (or vice-versa).
- **Topology Drift**: Codebase files violating architectural directory patterns established in `references/structure/`.

The Drift Auditor catches and categorizes these regressions before they compound into technical debt.

---

## 2. Interactive Auditing via `/drift` (`/d`)

In an interactive session, run `/drift`:

```text
/drift
```

### Clean Audit Output
```text
> /drift
🔍 Running ABB Drift Audit...
✅ Drift Audit Passed: Workspace, tasks, and skills are perfectly synchronized with specifications.
```

### Discrepancy Detection Output
If schema or structural inconsistencies are detected:

```text
> /drift
🔍 Running ABB Drift Audit...
⚠️ Drift Audit Detected 2 Issue(s):
  - [SCHEMA] tasks/sub/99_discrepancy.md: Missing required frontmatter field 'id'
  - [SKILLS] skills/qa/new_skill/SKILL.md: Skill exists on disk but is not indexed in skills.md
```

---

## 3. Automated Issue Logging (`--feed-issues`)

To turn drift audit findings into actionable tasks, pass `--feed-issues` (or `--feed`):

```text
/drift --feed-issues
```

*Sample Result:*
```text
🔍 Running ABB Drift Audit...
⚠️ Drift Audit Detected 2 Issue(s):
  - [SCHEMA] tasks/sub/99_discrepancy.md: Missing required frontmatter field 'id'
  - [SKILLS] skills/qa/new_skill/SKILL.md: Skill exists on disk but is not indexed in skills.md

📝 Logged drift findings to: `references/issues/technical_debt.md`
```

The auditor appends structured issue entries with timestamps and reproduction details to `references/issues/technical_debt.md`, making them directly discoverable by planning agents in subsequent sessions.

---

## 4. Real-Time Heuristic Drift Detection Hook

In addition to explicit `/drift` audits, the runtime includes a lightweight **`DriftDetectionHook`** that runs on the post-tool execution pipeline:

- Whenever an agent edits a task file (`tasks/sub/*.md`) or specification document (`features/*.md`), the hook runs a fast heuristic check on modified frontmatter fields.
- If an invalid status transition or schema defect is introduced, the agent receives an immediate inline warning in the tool result payload, allowing it to self-correct in the very same turn.
