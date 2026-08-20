"""Agent definition loading system for Codeless."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from codeless.config.paths import get_config_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Valid color names for agents (matches AgentColorName in TS).
AGENT_COLORS: frozenset[str] = frozenset(
    {
        "red",
        "green",
        "blue",
        "yellow",
        "purple",
        "orange",
        "cyan",
        "magenta",
        "white",
        "gray",
    }
)

#: Valid effort level strings (maps to EFFORT_LEVELS in TS).
EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high")

#: Valid permission mode strings (maps to PERMISSION_MODES in TS).
PERMISSION_MODES: tuple[str, ...] = (
    "default",
    "acceptEdits",
    "bypassPermissions",
    "plan",
    "dontAsk",
)

#: Valid memory scope strings (maps to AgentMemoryScope in TS).
MEMORY_SCOPES: tuple[str, ...] = ("user", "project", "local")

#: Valid isolation mode strings.
ISOLATION_MODES: tuple[str, ...] = ("worktree", "remote")


# ---------------------------------------------------------------------------
# AgentDefinition model
# ---------------------------------------------------------------------------


class AgentDefinition(BaseModel):
    """Full agent definition with all configuration fields.

    Field mapping to TypeScript ``BaseAgentDefinition``:
    - ``name``          → ``agentType``
    - ``description``   → ``whenToUse``
    - ``system_prompt`` → ``getSystemPrompt()`` return value
    - ``tools``         → ``tools`` (None means all tools / ``['*']``)
    - ``disallowed_tools`` → ``disallowedTools``
    - ``skills``        → ``skills``
    - ``mcp_servers``   → ``mcpServers``
    - ``hooks``         → ``hooks``
    - ``color``         → ``color``
    - ``model``         → ``model``
    - ``effort``        → ``effort``
    - ``permission_mode`` → ``permissionMode``
    - ``max_turns``     → ``maxTurns``
    - ``filename``      → ``filename``
    - ``base_dir``      → ``baseDir``
    - ``critical_system_reminder`` → ``criticalSystemReminder_EXPERIMENTAL``
    - ``required_mcp_servers`` → ``requiredMcpServers``
    - ``background``    → ``background``
    - ``initial_prompt`` → ``initialPrompt``
    - ``memory``        → ``memory``
    - ``isolation``     → ``isolation``
    - ``omit_claude_md`` → ``omitClaudeMd``
    """

    # --- required ---
    name: str
    description: str

    # --- prompt / tools ---
    system_prompt: str | None = None
    tools: list[str] | None = None  # None means all tools allowed; ['*'] is equivalent
    disallowed_tools: list[str] | None = None

    # --- model & effort ---
    model: str | None = None  # model override; None means inherit default
    effort: str | int | None = None  # "low" | "medium" | "high" or positive int

    # --- permissions ---
    permission_mode: str | None = None  # one of PERMISSION_MODES

    # --- agent loop control ---
    max_turns: int | None = None  # maximum agentic turns before stopping; must be > 0

    # --- skills & mcp ---
    skills: list[str] = Field(default_factory=list)
    mcp_servers: list[Any] | None = None  # str refs or {name: config} dicts
    required_mcp_servers: list[str] | None = None  # server name patterns that must be present

    # --- hooks ---
    hooks: dict[str, Any] | None = None  # session-scoped hooks registered when agent starts

    # --- ui ---
    color: str | None = None  # one of AGENT_COLORS

    # --- lifecycle ---
    background: bool = False  # always run as background task when spawned
    initial_prompt: str | None = None  # prepended to the first user turn
    memory: str | None = None  # one of MEMORY_SCOPES
    isolation: str | None = None  # one of ISOLATION_MODES

    # --- metadata ---
    filename: str | None = None  # original filename without .md extension
    base_dir: str | None = None  # directory the agent definition was loaded from
    critical_system_reminder: str | None = None  # short message re-injected at every user turn
    pending_snapshot_update: dict[str, Any] | None = None  # for memory snapshot tracking
    omit_claude_md: bool = False  # skip CLAUDE.md injection for this agent

    # --- Python-specific ---
    permissions: list[str] = Field(default_factory=list)  # extra permission rules
    subagent_type: str = "general-purpose"  # routing key used by the harness
    source: Literal["builtin", "user", "plugin"] = "builtin"
    modes: list[str] = Field(default_factory=list)  # TriMode filters: plan, agent, ask, codebase, governance


# ---------------------------------------------------------------------------
# System-prompt constants (translated from TS built-in agent files)
# ---------------------------------------------------------------------------

_SHARED_AGENT_PREFIX = (
    "You are an agent for Codeless. "
    "Given the user's message, you should use the tools available to complete the task. "
    "Complete the task fully — don't gold-plate, but don't leave it half-done."
)

_SHARED_AGENT_GUIDELINES = """Your strengths:
- Searching for code, configurations, and patterns across large codebases
- Analyzing multiple files to understand system architecture
- Investigating complex questions that require exploring many files
- Performing multi-step research tasks

Guidelines:
- For file searches: search broadly when you don't know where something lives. Use Read when you know the specific file path.
- For analysis: Start broad and narrow down. Use multiple search strategies if the first doesn't yield results.
- Be thorough: Check multiple locations, consider different naming conventions, look for related files.
- NEVER create files unless they're absolutely necessary for achieving your goal. ALWAYS prefer editing an existing file to creating a new one.
- NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested."""

_GENERAL_PURPOSE_SYSTEM_PROMPT = (
    f"{_SHARED_AGENT_PREFIX} When you complete the task, respond with a concise report covering "
    "what was done and any key findings — the caller will relay this to the user, so it only needs "
    f"the essentials.\n\n{_SHARED_AGENT_GUIDELINES}"
)

_EXPLORE_SYSTEM_PROMPT = """You are a file search specialist for Codeless. You excel at thoroughly navigating and exploring codebases.

=== CRITICAL: READ-ONLY MODE - NO FILE MODIFICATIONS ===
This is a READ-ONLY exploration task. You are STRICTLY PROHIBITED from:
- Creating new files (no Write, touch, or file creation of any kind)
- Modifying existing files (no Edit operations)
- Deleting files (no rm or deletion)
- Moving or copying files (no mv or cp)
- Creating temporary files anywhere, including /tmp
- Using redirect operators (>, >>, |) or heredocs to write to files
- Running ANY commands that change system state

Your role is EXCLUSIVELY to search and analyze existing code. You do NOT have access to file editing tools - attempting to edit files will fail.

Your strengths:
- Rapidly finding files using glob patterns
- Searching code and text with powerful regex patterns
- Reading and analyzing file contents

Guidelines:
- Use Glob for broad file pattern matching
- Use Grep for searching file contents with regex
- Use Read when you know the specific file path you need to read
- Use Bash ONLY for read-only operations (ls, git status, git log, git diff, find, cat, head, tail)
- NEVER use Bash for: mkdir, touch, rm, cp, mv, git add, git commit, npm install, pip install, or any file creation/modification
- Adapt your search approach based on the thoroughness level specified by the caller
- Communicate your final report directly as a regular message - do NOT attempt to create files

NOTE: You are meant to be a fast agent that returns output as quickly as possible. In order to achieve this you must:
- Make efficient use of the tools that you have at your disposal: be smart about how you search for files and implementations
- Wherever possible you should try to spawn multiple parallel tool calls for grepping and reading files

Complete the user's search request efficiently and report your findings clearly."""

_PLAN_SYSTEM_PROMPT = """You are a software architect and planning specialist for Codeless operating in Plan mode.

=== SCOPE: ARCHITECTURE & TASK PLANNING ===
Your role is to explore the codebase and design implementation strategies adhering to the ABB framework.
- Explore existing patterns and dependencies.
- Formulate step-by-step implementation strategies with clear dependency tracking.
- Do NOT perform code edits or modify project files outside the task planning domains."""

_VERIFICATION_SYSTEM_PROMPT = """You are a verification specialist. Your job is not to confirm the implementation works — it's to try to break it.

=== CRITICAL: DO NOT MODIFY THE PROJECT ===
You are STRICTLY PROHIBITED from:
- Creating, modifying, or deleting any files IN THE PROJECT DIRECTORY
- Installing dependencies or packages
- Running git write operations (add, commit, push)

Check your ACTUAL available tools. You can run builds, tests, linters, and typechecks to produce a definitive PASS/FAIL verdict.

End with exactly this line:
VERDICT: PASS
or
VERDICT: FAIL
or
VERDICT: PARTIAL"""

_VERIFICATION_CRITICAL_REMINDER = (
    "CRITICAL: This is a VERIFICATION-ONLY task. You CANNOT edit, write, or create files "
    "IN THE PROJECT DIRECTORY (tmp is allowed for ephemeral test scripts). "
    "You MUST end with VERDICT: PASS, VERDICT: FAIL, or VERDICT: PARTIAL."
)

_WORKER_SYSTEM_PROMPT = (
    "You are an implementation-focused worker agent operating within the ABB framework. "
    "Execute the assigned task precisely and efficiently. Write clean, well-structured code "
    "that follows the conventions already present in the codebase. When finished, run relevant "
    "tests and verification, then commit your changes and report the commit hash."
)

_ABB_GOVERNANCE_SYSTEM_PROMPT = """You are an ABB Governance Specialist. Your role is to maintain, update, and evolve the Agent Buildable Base (ABB) governance specifications and rules.

=== WRITE SCOPE: ABB META-SPECIFICATIONS ONLY ===
You may update:
- STACK.md, agent.md, features/, references/, skills/, workflows/, CONVENTIONS.md, CODING_PHILOSOPHY.md, USER_PREFERENCES.md
You are strictly prohibited from modifying:
- Project source code
- Individual subtask execution status

Ensure all updated specification files have their frontmatter version incremented and include an entry in their Changelog."""

_TASK_PLANNER_SYSTEM_PROMPT = """You are a Task Planning Specialist for Codeless operating within the Agent Buildable Base (ABB) governance framework.

=== WRITE SCOPE: tasks/ AND design/ ONLY ===
Your responsibilities:
- Decompose project goals into hierarchical Base Tasks (tasks/base/) and granular Subtasks (tasks/sub/)
- Assign topological dependencies (depends_on)
- Validate frontmatter YAML schema (id, version, status, parent, depends_on, links)
- Assign complexity ratings per the rubric in tasks/tasks.md §5
- Formulate Two-Track verification criteria for each subtask

You are strictly prohibited from modifying project source code."""


# ---------------------------------------------------------------------------
# Built-in agent definitions
# ---------------------------------------------------------------------------

_BUILTIN_AGENTS: list[AgentDefinition] = [
    AgentDefinition(
        name="general-purpose",
        description=(
            "General-purpose agent for researching complex questions, searching for code, "
            "and executing multi-step tasks."
        ),
        tools=["*"],  # all tools
        system_prompt=_GENERAL_PURPOSE_SYSTEM_PROMPT,
        subagent_type="general-purpose",
        source="builtin",
        base_dir="built-in",
        modes=["agent"],
    ),
    AgentDefinition(
        name="Explore",
        description=(
            "Fast agent specialized for exploring codebases. Use this when you need to "
            "quickly find files by patterns, search code for keywords, or answer questions "
            "about the codebase."
        ),
        disallowed_tools=["agent", "file_edit", "file_write", "notebook_edit"],
        system_prompt=_EXPLORE_SYSTEM_PROMPT,
        model="inherit",
        omit_claude_md=True,
        subagent_type="Explore",
        source="builtin",
        base_dir="built-in",
        modes=["ask", "codebase", "agent", "plan", "governance"],
    ),
    AgentDefinition(
        name="Plan",
        description=(
            "Software architect agent for designing implementation plans. Use this when you "
            "need to plan the implementation strategy for a task."
        ),
        disallowed_tools=["agent", "file_edit", "file_write", "notebook_edit"],
        system_prompt=_PLAN_SYSTEM_PROMPT,
        model="inherit",
        omit_claude_md=True,
        subagent_type="Plan",
        source="builtin",
        base_dir="built-in",
        modes=["plan", "agent"],
    ),
    AgentDefinition(
        name="worker",
        description=(
            "Implementation-focused worker agent. Use this for concrete coding tasks: "
            "writing features, fixing bugs, refactoring code, and running tests."
        ),
        tools=None,  # all tools
        system_prompt=_WORKER_SYSTEM_PROMPT,
        subagent_type="worker",
        source="builtin",
        base_dir="built-in",
        modes=["agent"],
    ),
    AgentDefinition(
        name="verification",
        description=(
            "Use this agent to verify that implementation work is correct before reporting "
            "completion. Pass the ORIGINAL user task description, list of files changed, "
            "and approach taken. The agent runs builds, tests, linters, and checks to produce "
            "a PASS/FAIL verdict."
        ),
        disallowed_tools=["agent", "file_edit", "file_write", "notebook_edit"],
        system_prompt=_VERIFICATION_SYSTEM_PROMPT,
        critical_system_reminder=_VERIFICATION_CRITICAL_REMINDER,
        color="red",
        background=True,
        model="inherit",
        subagent_type="verification",
        source="builtin",
        base_dir="built-in",
        modes=["agent", "plan", "governance"],
    ),
    AgentDefinition(
        name="abb-governance",
        description=(
            "ABB Governance specialist agent. Use this agent to explain, update, or extend "
            "the ABB system meta-specifications (STACK.md, agent.md, features/, references/, "
            "workflows/, skills/, conventions) without modifying project code."
        ),
        system_prompt=_ABB_GOVERNANCE_SYSTEM_PROMPT,
        model="inherit",
        color="purple",
        subagent_type="abb-governance",
        source="builtin",
        base_dir="built-in",
        modes=["governance", "agent"],
    ),
    AgentDefinition(
        name="task-planner",
        description=(
            "ABB Task Planning specialist agent. Use this agent to decompose goals into base "
            "and sub tasks per tasks/tasks.md, maintain frontmatter schemas, topological DAG "
            "dependencies, and complexity ratings."
        ),
        system_prompt=_TASK_PLANNER_SYSTEM_PROMPT,
        model="inherit",
        color="cyan",
        subagent_type="task-planner",
        source="builtin",
        base_dir="built-in",
        modes=["plan", "agent"],
    ),
]



def get_builtin_agent_definitions() -> list[AgentDefinition]:
    """Return the built-in agent definitions."""
    return list(_BUILTIN_AGENTS)


# ---------------------------------------------------------------------------
# Markdown / YAML-frontmatter loader
# ---------------------------------------------------------------------------


def _parse_agent_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown file.

    Returns a (frontmatter_dict, body) tuple. Uses ``yaml.safe_load`` for
    proper YAML parsing (supports nested structures for hooks, mcpServers, etc.).
    """
    frontmatter: dict[str, Any] = {}
    body = content

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return frontmatter, body

    end_index: int | None = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = i
            break

    if end_index is None:
        return frontmatter, body

    fm_text = "\n".join(lines[1:end_index])
    try:
        parsed = yaml.safe_load(fm_text)
        if isinstance(parsed, dict):
            frontmatter = parsed
    except yaml.YAMLError:
        # Fall back to simple key:value parsing
        for fm_line in lines[1:end_index]:
            if ":" in fm_line:
                key, _, value = fm_line.partition(":")
                frontmatter[key.strip()] = value.strip().strip("'\"")

    # Body is everything after the closing ---
    body = "\n".join(lines[end_index + 1 :]).strip()
    return frontmatter, body


def _parse_str_list(raw: Any) -> list[str] | None:
    """Parse a comma-separated string or list into a list of strings."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        items = [t.strip() for t in raw.split(",") if t.strip()]
        return items if items else None
    return None


def _parse_positive_int(raw: Any) -> int | None:
    """Parse a positive integer from frontmatter, returning None if invalid."""
    if raw is None:
        return None
    try:
        val = int(raw)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def load_agents_dir(directory: Path) -> list[AgentDefinition]:
    """Load agent definitions from .md files in *directory*.

    Each file should contain YAML frontmatter with at least ``name`` and
    ``description`` fields. The markdown body becomes the ``system_prompt``.

    Supported frontmatter fields (all optional unless noted):

    Required:
    * ``name`` — agent type identifier
    * ``description`` — when-to-use description shown to the spawning agent

    Optional:
    * ``tools`` — comma-separated or YAML list of allowed tool names
    * ``disallowedTools`` / ``disallowed_tools`` — comma-separated or list of disallowed tools
    * ``model`` — model override (e.g. "haiku", "inherit")
    * ``effort`` — "low", "medium", "high", or a positive integer
    * ``permissionMode`` / ``permission_mode`` — one of PERMISSION_MODES
    * ``maxTurns`` / ``max_turns`` — positive integer turn limit
    * ``skills`` — comma-separated or list of skill names
    * ``mcpServers`` / ``mcp_servers`` — list of MCP server references or inline configs
    * ``hooks`` — YAML dict of session-scoped hooks
    * ``color`` — one of AGENT_COLORS
    * ``background`` — true/false; run as background task
    * ``initialPrompt`` / ``initial_prompt`` — string prepended to first user turn
    * ``memory`` — one of MEMORY_SCOPES
    * ``isolation`` — one of ISOLATION_MODES
    * ``omitClaudeMd`` / ``omit_claude_md`` — true/false; skip CLAUDE.md injection
    * ``criticalSystemReminder`` / ``critical_system_reminder`` — re-injected message
    * ``requiredMcpServers`` / ``required_mcp_servers`` — list of required server patterns
    * ``permissions`` — comma-separated extra permission rules (Python-specific)
    * ``subagent_type`` — routing key (Python-specific, defaults to name)
    """
    agents: list[AgentDefinition] = []

    if not directory.is_dir():
        return agents

    for path in sorted(directory.glob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
            frontmatter, body = _parse_agent_frontmatter(content)

            name = str(frontmatter.get("name", "")).strip() or path.stem
            description = str(frontmatter.get("description", "")).strip()
            if not description:
                description = f"Agent: {name}"

            # Unescape literal \n in descriptions from YAML
            description = description.replace("\\n", "\n")

            # --- tools ---
            tools = _parse_str_list(frontmatter.get("tools"))

            # --- disallowed tools ---
            disallowed_raw = frontmatter.get(
                "disallowedTools", frontmatter.get("disallowed_tools")
            )
            disallowed_tools = _parse_str_list(disallowed_raw)

            # --- model ---
            model_raw = frontmatter.get("model")
            model: str | None = None
            if isinstance(model_raw, str) and model_raw.strip():
                trimmed = model_raw.strip()
                model = "inherit" if trimmed.lower() == "inherit" else trimmed

            # --- effort ---
            effort_raw = frontmatter.get("effort")
            effort: str | int | None = None
            if effort_raw is not None:
                if isinstance(effort_raw, int):
                    effort = effort_raw if effort_raw > 0 else None
                elif isinstance(effort_raw, str) and effort_raw in EFFORT_LEVELS:
                    effort = effort_raw
                else:
                    logger.debug("Agent %s: invalid effort %r", name, effort_raw)

            # --- permissionMode ---
            perm_raw = frontmatter.get("permissionMode", frontmatter.get("permission_mode"))
            permission_mode: str | None = None
            if isinstance(perm_raw, str) and perm_raw in PERMISSION_MODES:
                permission_mode = perm_raw
            elif perm_raw is not None:
                logger.debug("Agent %s: invalid permissionMode %r", name, perm_raw)

            # --- maxTurns ---
            max_turns_raw = frontmatter.get("maxTurns", frontmatter.get("max_turns"))
            max_turns = _parse_positive_int(max_turns_raw)
            if max_turns_raw is not None and max_turns is None:
                logger.debug("Agent %s: invalid maxTurns %r", name, max_turns_raw)

            # --- skills ---
            skills_raw = frontmatter.get("skills")
            skills = _parse_str_list(skills_raw) or []

            # --- mcpServers ---
            mcp_raw = frontmatter.get("mcpServers", frontmatter.get("mcp_servers"))
            mcp_servers: list[Any] | None = None
            if isinstance(mcp_raw, list):
                mcp_servers = mcp_raw if mcp_raw else None

            # --- hooks ---
            hooks_raw = frontmatter.get("hooks")
            hooks: dict[str, Any] | None = None
            if isinstance(hooks_raw, dict):
                hooks = hooks_raw

            # --- color ---
            color_raw = frontmatter.get("color")
            color: str | None = None
            if isinstance(color_raw, str) and color_raw in AGENT_COLORS:
                color = color_raw

            # --- background ---
            bg_raw = frontmatter.get("background")
            background = bg_raw is True or bg_raw == "true"

            # --- initialPrompt ---
            ip_raw = frontmatter.get("initialPrompt", frontmatter.get("initial_prompt"))
            initial_prompt: str | None = None
            if isinstance(ip_raw, str) and ip_raw.strip():
                initial_prompt = ip_raw

            # --- memory ---
            memory_raw = frontmatter.get("memory")
            memory: str | None = None
            if isinstance(memory_raw, str) and memory_raw in MEMORY_SCOPES:
                memory = memory_raw
            elif memory_raw is not None:
                logger.debug("Agent %s: invalid memory %r", name, memory_raw)

            # --- isolation ---
            iso_raw = frontmatter.get("isolation")
            isolation: str | None = None
            if isinstance(iso_raw, str) and iso_raw in ISOLATION_MODES:
                isolation = iso_raw
            elif iso_raw is not None:
                logger.debug("Agent %s: invalid isolation %r", name, iso_raw)

            # --- omitClaudeMd ---
            ocm_raw = frontmatter.get("omitClaudeMd", frontmatter.get("omit_claude_md"))
            omit_claude_md = ocm_raw is True or ocm_raw == "true"

            # --- criticalSystemReminder ---
            csr_raw = frontmatter.get(
                "criticalSystemReminder", frontmatter.get("critical_system_reminder")
            )
            critical_system_reminder: str | None = None
            if isinstance(csr_raw, str) and csr_raw.strip():
                critical_system_reminder = csr_raw

            # --- requiredMcpServers ---
            rms_raw = frontmatter.get(
                "requiredMcpServers", frontmatter.get("required_mcp_servers")
            )
            required_mcp_servers = _parse_str_list(rms_raw)

            # --- modes (TriMode filter) ---
            modes_raw = frontmatter.get("modes")
            modes = _parse_str_list(modes_raw) or []

            # --- permissions (Python-specific) ---
            permissions: list[str] = []
            raw_perms = frontmatter.get("permissions", "")
            if raw_perms:
                permissions = [p.strip() for p in str(raw_perms).split(",") if p.strip()]

            agents.append(
                AgentDefinition(
                    name=name,
                    description=description,
                    system_prompt=body or None,
                    tools=tools,
                    disallowed_tools=disallowed_tools,
                    model=model,
                    effort=effort,
                    permission_mode=permission_mode,
                    max_turns=max_turns,
                    skills=skills,
                    mcp_servers=mcp_servers,
                    hooks=hooks,
                    color=color,
                    background=background,
                    initial_prompt=initial_prompt,
                    memory=memory,
                    isolation=isolation,
                    omit_claude_md=omit_claude_md,
                    critical_system_reminder=critical_system_reminder,
                    required_mcp_servers=required_mcp_servers,
                    permissions=permissions,
                    modes=modes,
                    filename=path.stem,
                    base_dir=str(directory),
                    subagent_type=str(frontmatter.get("subagent_type", name)),
                    source="user",
                )
            )

        except Exception:
            logger.debug("Failed to parse agent from %s", path, exc_info=True)
            continue

    return agents


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _get_user_agents_dir() -> Path:
    """Return the user agent definitions directory."""
    return get_config_dir() / "agents"


def get_all_agent_definitions() -> list[AgentDefinition]:
    """Return all agent definitions: built-in + user + plugin.

    Merge order (last writer wins for same ``name``):
    1. Built-in agents
    2. User agents (~/.codeless/agents/)
    3. Plugin agents (loaded from active plugins)

    User definitions override built-ins with the same name; plugin definitions
    override user definitions with the same name.
    """
    agent_map: dict[str, AgentDefinition] = {}

    # 1. Built-ins (lowest priority)
    for agent in get_builtin_agent_definitions():
        agent_map[agent.name] = agent

    # 2. User-defined agents
    user_agents = load_agents_dir(_get_user_agents_dir())
    for agent in user_agents:
        agent_map[agent.name] = agent

    # 3. Plugin agents — loaded lazily to avoid import cycles
    try:
        from codeless.plugins.loader import load_plugins  # noqa: PLC0415
        from codeless.config.settings import load_settings  # noqa: PLC0415

        settings = load_settings()
        import os  # noqa: PLC0415

        cwd = os.getcwd()
        for plugin in load_plugins(settings, cwd):
            if not plugin.enabled:
                continue
            for agent_def in getattr(plugin, "agents", []):
                if isinstance(agent_def, AgentDefinition):
                    agent_map[agent_def.name] = agent_def
    except Exception:
        pass

    return list(agent_map.values())


def get_agent_definition(name: str) -> AgentDefinition | None:
    """Return the agent definition for *name*, or ``None`` if not found."""
    for agent in get_all_agent_definitions():
        if agent.name == name:
            return agent
    return None


def has_required_mcp_servers(agent: AgentDefinition, available_servers: list[str]) -> bool:
    """Return True if the agent's required MCP servers are all available.

    Each pattern in ``required_mcp_servers`` must match (case-insensitive
    substring) at least one server in ``available_servers``.
    """
    if not agent.required_mcp_servers:
        return True
    return all(
        any(pattern.lower() in server.lower() for server in available_servers)
        for pattern in agent.required_mcp_servers
    )


def filter_agents_by_mcp_requirements(
    agents: list[AgentDefinition],
    available_servers: list[str],
) -> list[AgentDefinition]:
    """Return only agents whose required MCP servers are available."""
    return [a for a in agents if has_required_mcp_servers(a, available_servers)]
