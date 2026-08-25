"""ABB Slash Command Pack (Collision-Resolved)."""

from __future__ import annotations

from pathlib import Path

from codeless.abb.drift import feed_drift_to_issues, run_drift_audit
from codeless.abb.hooks.dag_guard import index_tasks
from codeless.abb.hooks.frontmatter import parse_frontmatter
from codeless.abb.permissions import TriMode, get_mode_engine
from codeless.abb.shadow import resolve_abb_workspace
from codeless.abb.verification import (
    execute_verification_manifest_sync,
    parse_verification_manifest,
)
from codeless.commands.registry import CommandContext, CommandRegistry, CommandResult, SlashCommand


async def _plan_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /plan: Enter Plan Mode and load planning context."""
    from codeless.config.settings import load_settings, save_settings
    from codeless.permissions import PermissionChecker, PermissionMode

    mode_arg = args.strip().lower()
    if mode_arg in {"off", "exit"}:
        get_mode_engine().set_mode(TriMode.AGENT)
        settings = load_settings()
        settings.permission.mode = PermissionMode.DEFAULT
        save_settings(settings)
        context.engine.set_permission_checker(PermissionChecker(settings.permission))
        if context.app_state is not None:
            context.app_state.set(permission_mode="AGENT")
        return CommandResult(
            message="Plan mode disabled. Operational mode switched to AGENT.", refresh_runtime=True
        )

    # Entering or updating plan mode
    get_mode_engine().set_mode(TriMode.PLAN)
    settings = load_settings()
    settings.permission.mode = PermissionMode.PLAN
    save_settings(settings)
    context.engine.set_permission_checker(PermissionChecker(settings.permission))
    if context.app_state is not None:
        context.app_state.set(permission_mode="PLAN")

    cwd = Path(context.cwd).resolve()
    abb_ws = resolve_abb_workspace(cwd, auto_init=True)
    planning_workflow = abb_ws / "workflows" / "planning" / "planning.md"

    if mode_arg in {"on", "enter"} or not mode_arg:
        status_msg = "Plan mode enabled.\n📐 Mode: Plan Mode Active.\n"
        if planning_workflow.exists():
            status_msg += f"Loaded workflow: {planning_workflow.name}\n"
        status_msg += "Use `/plan <objective>` to initiate planning for a feature or goal."
        return CommandResult(message=status_msg, refresh_runtime=True)

    status_msg = "📐 Mode: Plan Mode Active.\n"
    if planning_workflow.exists():
        status_msg += f"Loaded workflow: {planning_workflow.name}\n"
    return CommandResult(
        message=f"{status_msg}Objective: {args.strip()}\nProceeding with research and architectural planning.",
        submit_prompt=f"ROUTE: workflows/planning/planning.md\nPlan objective: {args.strip()}",
        refresh_runtime=True,
    )


async def _skills_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /skills: Query standard project skills, upstream builtins, and ABB categorized skills."""
    from codeless.commands.registry import _is_valid_skill_command_name, _skill_command_name
    from codeless.skills import load_skill_registry

    skill_registry = load_skill_registry(
        context.cwd,
        extra_skill_dirs=context.extra_skill_dirs,
        extra_plugin_roots=context.extra_plugin_roots,
    )
    if args.strip():
        skill = skill_registry.get(args.strip())
        if skill is not None:
            return CommandResult(message=skill.content)

    skills = skill_registry.list_skills()
    lines = ["Available skills:"] if skills else ["Available Skills (Built-in + ABB Library):"]
    for skill in skills:
        source = f" [{skill.source}]"
        path = f" {skill.path}" if skill.path else ""
        command_name = _skill_command_name(skill)
        slash = (
            f" /{command_name}"
            if skill.user_invocable and _is_valid_skill_command_name(command_name)
            else ""
        )
        display = f" ({skill.display_name})" if skill.display_name else ""
        lines.append(f"- {command_name}{display}{source}{path}{slash}: {skill.description}")

    cwd = Path(context.cwd).resolve()
    abb_ws = resolve_abb_workspace(cwd, auto_init=True)
    skills_dir = abb_ws / "skills"
    if skills_dir.exists():
        for skill_file in sorted(skills_dir.glob("**/SKILL.md")):
            rel_path = skill_file.relative_to(skills_dir)
            fm, _ = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            skill_id = fm.get("id", skill_file.parent.name)
            if not any(skill_id in line for line in lines):
                lines.append(f"  - {skill_id:<32} ({rel_path})")

    query = args.strip().lower()
    if query:
        filtered = [line for line in lines[1:] if query in line.lower()]
        if filtered:
            return CommandResult(message="Matching Skills:\n" + "\n".join(filtered))
        return CommandResult(message=f"No skills found matching '{args}'.")

    return CommandResult(message="\n".join(lines))


async def _init_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /init: Run project initialization or refresh stack."""
    from codeless.config.paths import get_project_config_dir

    project_dir = get_project_config_dir(context.cwd)
    created: list[str] = []

    claudemd = Path(context.cwd) / "CLAUDE.md"
    if not claudemd.exists():
        claudemd.write_text(
            "# Project Instructions\n\n"
            "- Use Codeless tools deliberately.\n"
            "- Keep changes minimal and verify with tests when possible.\n",
            encoding="utf-8",
        )
        created.append(str(claudemd.relative_to(Path(context.cwd))))

    for relative, content in (
        (
            project_dir / "README.md",
            "# Project Codeless Config\n\nThis directory stores project-specific Codeless state.\n",
        ),
        (
            project_dir / "memory" / "MEMORY.md",
            "# Project Memory\n\nAdd reusable project knowledge here.\n",
        ),
        (
            project_dir / "plugins" / ".gitkeep",
            "",
        ),
        (
            project_dir / "skills" / ".gitkeep",
            "",
        ),
    ):
        relative.parent.mkdir(parents=True, exist_ok=True)
        if not relative.exists():
            relative.write_text(content, encoding="utf-8")
            created.append(str(relative.relative_to(Path(context.cwd))))

    cwd = Path(context.cwd).resolve()
    abb_ws = resolve_abb_workspace(cwd, auto_init=True)
    stack_file = abb_ws / "STACK.md"

    if created:
        init_summary = "Initialized project files:\n" + "\n".join(f"- {item}" for item in created)
    else:
        init_summary = "Project already initialized for Codeless."

    return CommandResult(
        message=(
            f"{init_summary}\n\n"
            f"🚀 Project Workspace: {cwd.name}\n"
            f"ABB Workspace: {abb_ws}\n"
            f"STACK.md: {'Configured' if stack_file.exists() else 'Missing'}\n"
            "Use `workflows/planning/init_project.md` to bootstrap or refresh stack."
        )
    )


async def _route_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /route: Classify user prompt against router decision tree."""
    prompt = args.strip().lower()
    if not prompt:
        return CommandResult(message="Usage: /route <user prompt or task description>")

    target = "workflows/execution/work_principle.md"
    reason = "Standard task execution"

    if any(k in prompt for k in ["init", "start", "bootstrap", "new project", "setup"]):
        target = "workflows/planning/init_project.md"
        reason = "Project initialization"
    elif any(k in prompt for k in ["plan", "research", "options", "recommend", "design"]):
        target = "workflows/planning/planning.md"
        reason = "Planning & architecture research"
    elif any(k in prompt for k in ["verify", "audit", "test", "check"]):
        target = "workflows/execution/work_verification.md"
        reason = "Quality and work verification"
    elif any(k in prompt for k in ["drift", "recheck", "codebase"]):
        target = "workflows/quality/recheck_codebase.md"
        reason = "Codebase and schema drift check"
    elif any(k in prompt for k in ["skill", "skills", "learn"]):
        target = "workflows/user/find_skills.md"
        reason = "Skill discovery & import"

    return CommandResult(
        message=f"🧭 Router Classification:\n  Primary Workflow: `{target}`\n  Classification Reason: {reason}\n  Contract: Emit `ROUTE: {target}`"
    )


async def _goal_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /goal: Display the SRS (system goal) and base task milestones."""
    cwd = Path(context.cwd).resolve()
    abb_ws = resolve_abb_workspace(cwd, auto_init=True)
    goal_file = abb_ws / "tasks" / "goal" / "goal.md"

    if not goal_file.exists():
        return CommandResult(message="No goal.md (SRS) found in active ABB workspace.")

    content = goal_file.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    # Extract title
    title = "System SRS"
    for line in body.splitlines():
        if line.startswith("# "):
            title = line.lstrip("# ").strip()
            break

    status = fm.get("status", "in_progress")
    return CommandResult(
        message=f"🎯 SRS: {title}\nID: {fm.get('id', 'goal_001')} | Version: {fm.get('version', '1.0.0')} | Status: [{status}]\n\n{body[:800]}..."
    )


async def _task_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /task: Display hierarchical task DAG or specific task details."""
    cwd = Path(context.cwd).resolve()
    abb_ws = resolve_abb_workspace(cwd, auto_init=True)
    tasks_dir = abb_ws / "tasks"

    task_index = index_tasks(tasks_dir)
    query = args.strip()

    if query:
        # Search for specific task
        for key, (path, fm) in task_index.items():
            if query.lower() in key.lower():
                body = path.read_text(encoding="utf-8")
                return CommandResult(
                    message=(
                        f"Task: {path.name}\n"
                        f"ID: {fm.get('id')} | Status: [{fm.get('status')}] | Version: {fm.get('version')}\n"
                        f"Parent: {fm.get('parent')} | Depends On: {fm.get('depends_on', [])}\n\n"
                        f"{body[:1000]}"
                    )
                )
        return CommandResult(message=f"No task found matching '{query}'.")

    # Full DAG Summary
    base_dir = tasks_dir / "base"
    sub_dir = tasks_dir / "sub"
    lines = ["📊 ABB Task Hierarchy & DAG:"]

    if base_dir.exists():
        for bfile in sorted(base_dir.glob("*.md")):
            bfm, _ = parse_frontmatter(bfile.read_text(encoding="utf-8"))
            bid = bfm.get("id", bfile.name)
            bstatus = bfm.get("status", "pending")
            b_badge = "✅" if bstatus == "done" else ("⏳" if bstatus == "in_progress" else "⏸️")
            lines.append(f"\n{b_badge} Base Task [{bstatus}]: {bid} ({bfile.name})")

            # Subtasks under this base
            if sub_dir.exists():
                for sfile in sorted(sub_dir.glob("*.md")):
                    sfm, _ = parse_frontmatter(sfile.read_text(encoding="utf-8"))
                    if sfm.get("parent") == bid:
                        sid = sfm.get("id", sfile.name)
                        sstatus = sfm.get("status", "pending")
                        s_badge = (
                            " [x]"
                            if sstatus == "done"
                            else (" [/]" if sstatus == "in_progress" else " [ ]")
                        )
                        deps = sfm.get("depends_on", [])
                        dep_str = f" (depends: {', '.join(deps)})" if deps else ""
                        lines.append(f"   {s_badge} {sid}: {sfile.name}{dep_str}")

    return CommandResult(message="\n".join(lines))


async def _verify_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /verify: Execute Track 1 and Track 2 verification manifests."""
    cwd = Path(context.cwd).resolve()
    abb_ws = resolve_abb_workspace(cwd, auto_init=True)
    stack_file = abb_ws / "STACK.md"
    manifest = parse_verification_manifest(stack_file)

    tracks = (1, 2)
    arg = args.strip()
    if arg == "1":
        tracks = (1,)
    elif arg == "2":
        tracks = (2,)

    report = execute_verification_manifest_sync(manifest, cwd, tracks=tracks)
    if report.success:
        return CommandResult(
            message=f"✅ Verification Passed:\n- Track 1 commands: {len(report.track_1_reports)} passed\n- Track 2 commands: {len(report.track_2_reports)} passed"
        )
    return CommandResult(message=report.format_failure_diagnostic())


async def _drift_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /drift: Perform structural, schema, and specification drift audit."""
    cwd = Path(context.cwd).resolve()
    report = run_drift_audit(cwd)

    feed_issues = "--feed" in args or "--feed-issues" in args or "-f" in args
    extra_msg = ""
    if not report.clean and feed_issues:
        issues_path = feed_drift_to_issues(cwd, report)
        if issues_path:
            extra_msg = f"\n\n📝 Logged findings to: {issues_path.name}"

    return CommandResult(message=report.format_cli() + extra_msg)


async def _feature_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /feature: Inspect or list features."""
    cwd = Path(context.cwd).resolve()
    abb_ws = resolve_abb_workspace(cwd, auto_init=True)
    features_dir = abb_ws / "features"

    if not features_dir.exists():
        return CommandResult(message="No features directory found in active ABB workspace.")

    query = args.strip().lower()
    features = []
    for spec_file in sorted(features_dir.glob("**/spec.md")):
        rel = spec_file.parent.name
        fm, _ = parse_frontmatter(spec_file.read_text(encoding="utf-8"))
        features.append((rel, fm.get("id", rel), fm.get("status", "draft"), spec_file))

    if query:
        for rel, fid, status, spec_file in features:
            if query in rel.lower() or query in fid.lower():
                content = spec_file.read_text(encoding="utf-8")
                return CommandResult(
                    message=f"Feature: {rel} ({fid}) [{status}]\n\n{content[:1200]}"
                )
        return CommandResult(message=f"No feature found matching '{args}'.")

    lines = ["📦 Registered Features:"]
    for rel, fid, status, _ in features:
        lines.append(f"  - {fid:<28} [{status:<11}] -> features/{rel}/spec.md")
    return CommandResult(message="\n".join(lines))


async def _references_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /references: Query the 11-domain memory bank."""
    cwd = Path(context.cwd).resolve()
    abb_ws = resolve_abb_workspace(cwd, auto_init=True)
    ref_dir = abb_ws / "references"

    domains = [
        "code",
        "db",
        "deployment",
        "issues",
        "logic",
        "logs",
        "resource",
        "structure",
        "tests",
        "tooling",
        "user",
    ]
    lines = ["📚 References Memory Bank (11 Domains):"]

    for d in domains:
        d_path = ref_dir / d
        count = len(list(d_path.glob("*.md"))) if d_path.exists() else 0
        lines.append(f"  - references/{d:<14} ({count} documents)")

    return CommandResult(message="\n".join(lines))


async def _checkpoint_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /checkpoint: Snapshot save, restore, list, and inspection."""
    from codeless.abb.checkpoints import (
        create_checkpoint,
        get_checkpoint,
        list_checkpoints,
        restore_checkpoint,
    )

    cwd = Path(context.cwd).resolve()
    parts = args.strip().split()
    subcmd = parts[0].lower() if parts else "list"

    if subcmd in {"save", "create"}:
        name = parts[1] if len(parts) > 1 else None
        desc = " ".join(parts[2:]) if len(parts) > 2 else "Manual checkpoint"
        cp = create_checkpoint(cwd, name=name, description=desc)
        return CommandResult(
            message=f"🛡️ Checkpoint Saved:\n  - ID: `{cp.checkpoint_id}`\n  - Name: `{cp.name}`\n  - Files: {cp.files_count}\n  - Location: {cp.abb_location}"
        )

    if subcmd in {"restore", "revert"}:
        if len(parts) < 2:
            return CommandResult(
                message="⚠️ Usage: `/checkpoint restore <checkpoint_id|name> [--force]`"
            )
        target_id = parts[1]
        force = "--force" in parts or "-f" in parts
        success, msg = restore_checkpoint(cwd, target_id, force=force)
        prefix = "✅" if success else "⚠️"
        return CommandResult(message=f"{prefix} {msg}")

    if subcmd in {"show", "info"}:
        if len(parts) < 2:
            return CommandResult(message="⚠️ Usage: `/checkpoint show <checkpoint_id|name>`")
        target_id = parts[1]
        cp = get_checkpoint(cwd, target_id)
        if not cp:
            return CommandResult(message=f"⚠️ Checkpoint '{target_id}' not found.")
        return CommandResult(
            message=(
                f"🛡️ Checkpoint Details:\n"
                f"  - ID: `{cp.checkpoint_id}`\n"
                f"  - Name: `{cp.name}`\n"
                f"  - Timestamp: {cp.timestamp}\n"
                f"  - Description: {cp.description}\n"
                f"  - Git Commit: {cp.git_commit or 'None'}\n"
                f"  - ABB Location: {cp.abb_location}\n"
                f"  - Files Tracked: {cp.files_count}"
            )
        )

    # Default: list checkpoints
    checkpoints = list_checkpoints(cwd)
    if not checkpoints:
        return CommandResult(
            message="🛡️ Checkpoint Engine: No checkpoints saved yet for this project.\nCreate one with `/checkpoint save [name]`."
        )

    lines = ["🛡️ Saved Checkpoints:"]
    for cp in checkpoints[:10]:
        lines.append(
            f"  - `{cp.checkpoint_id}` [{cp.name}] - {cp.timestamp} ({cp.files_count} files)"
        )
    lines.append(
        "\nCommands: `/checkpoint save [name]`, `/checkpoint restore <id> [--force]`, `/checkpoint show <id>`"
    )
    return CommandResult(message="\n".join(lines))


async def _mode_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /mode: Switch operational mode (plan | agent | ask | codebase)."""
    target = args.strip().lower()
    if target in {"plan", "agent", "ask", "codebase"}:
        from codeless.config.settings import load_settings, save_settings
        from codeless.permissions import PermissionChecker, PermissionMode

        mode_engine = get_mode_engine()
        mode_engine.set_mode(target)

        settings = load_settings()
        settings.permission.mode = (
            PermissionMode.DEFAULT if target == "agent" else PermissionMode.PLAN
        )
        save_settings(settings)
        context.engine.set_permission_checker(PermissionChecker(settings.permission))

        try:
            from codeless.prompts.context import build_runtime_system_prompt

            new_prompt = build_runtime_system_prompt(settings, cwd=context.cwd)
            if hasattr(context.engine, "set_system_prompt"):
                context.engine.set_system_prompt(new_prompt)
        except Exception:
            pass

        if context.app_state is not None:
            context.app_state.set(permission_mode=target.upper())

        return CommandResult(
            message=f"🔄 Operational Mode switched to: {target.upper()}\nDomain write boundary updated.",
            refresh_runtime=True,
        )
    return CommandResult(
        message=(
            "Operational Modes & Domain Write Boundaries:\n"
            "  - `AGENT`    : Unrestricted implementation & verification (Two-Track gate active)\n"
            "  - `PLAN`     : Architecture & task planning (full read/write in ABB; codebase is read-only)\n"
            "  - `ASK`      : Strictly read-only inquiry (all mutating operations blocked)\n"
            "  - `CODEBASE` : Codebase exploration & memory queries (strictly read-only)\n\n"
            "Usage: `/mode <agent|plan|ask|codebase>`"
        )
    )


async def _stack_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /stack: View STACK.md and verification manifest."""
    cwd = Path(context.cwd).resolve()
    abb_ws = resolve_abb_workspace(cwd, auto_init=True)
    stack_file = abb_ws / "STACK.md"

    if not stack_file.exists():
        return CommandResult(message="No STACK.md found.")
    return CommandResult(message=stack_file.read_text(encoding="utf-8"))


async def _prefs_handler(args: str, context: CommandContext) -> CommandResult:
    """Handle /prefs: View USER_PREFERENCES.md."""
    cwd = Path(context.cwd).resolve()
    abb_ws = resolve_abb_workspace(cwd, auto_init=True)
    prefs_file = abb_ws / "USER_PREFERENCES.md"

    if not prefs_file.exists():
        return CommandResult(message="No USER_PREFERENCES.md found.")
    return CommandResult(message=prefs_file.read_text(encoding="utf-8"))


def register_abb_slash_commands(registry: CommandRegistry) -> None:
    """Register all 14 ABB slash commands with alias resolution."""
    commands = [
        SlashCommand(
            "plan", "Enter Plan Mode and load planning context", _plan_handler, aliases=("p",)
        ),
        SlashCommand(
            "skills",
            "Search and query built-in and ABB skill catalog",
            _skills_handler,
            aliases=("s",),
        ),
        SlashCommand(
            "init",
            "Project initialization and stack verification wizard",
            _init_handler,
            aliases=("i",),
        ),
        SlashCommand(
            "route", "Classify prompt against router decision tree", _route_handler, aliases=("r",)
        ),
        SlashCommand(
            "goal", "Inspect system North Star goal and milestones", _goal_handler, aliases=("g",)
        ),
        SlashCommand(
            "task",
            "Inspect ABB task hierarchy, dependencies, and readiness",
            _task_handler,
            aliases=("t",),
        ),
        SlashCommand(
            "verify",
            "Execute Track 1 and Track 2 verification manifests",
            _verify_handler,
            aliases=("v",),
        ),
        SlashCommand(
            "drift",
            "Audit task frontmatter schemas and codebase consistency",
            _drift_handler,
            aliases=("d",),
        ),
        SlashCommand(
            "feature",
            "Inspect and list system feature specifications",
            _feature_handler,
            aliases=("f",),
        ),
        SlashCommand(
            "references", "Query the 11-domain memory bank", _references_handler, aliases=("ref",)
        ),
        SlashCommand(
            "checkpoint",
            "Snapshot save and restore safety tracking",
            _checkpoint_handler,
            aliases=("cp",),
        ),
        SlashCommand(
            "mode", "Switch operational mode (plan | agent | ask)", _mode_handler, aliases=("m",)
        ),
        SlashCommand(
            "stack",
            "View project stack, tooling, and verification manifest",
            _stack_handler,
            aliases=("st",),
        ),
        SlashCommand(
            "prefs", "View user preferences and conventions", _prefs_handler, aliases=("pr",)
        ),
    ]

    for cmd in commands:
        registry.register(cmd)
