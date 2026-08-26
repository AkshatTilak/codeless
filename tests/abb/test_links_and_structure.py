"""Link and structural consistency validation test."""

import re
from pathlib import Path

from codeless.abb.hooks.frontmatter import parse_frontmatter
from codeless.abb.shadow import resolve_abb_workspace


def _validate_workspace_links(abb_ws: Path) -> tuple[int, int, list[str]]:
    """Validate all relative markdown links inside an ABB workspace directory."""
    broken_links: list[str] = []
    scanned_files = 0
    scanned_links = 0

    for md_file in abb_ws.rglob("*.md"):
        if "_staging" in md_file.parts or ".git" in md_file.parts:
            continue
        # Skip template files with placeholders
        if "_templates" in md_file.parts or "_template" in md_file.parts:
            continue

        scanned_files += 1
        content = md_file.read_text(encoding="utf-8")

        # 1. Check frontmatter links
        fm, _ = parse_frontmatter(content)
        links = fm.get("links", [])
        if isinstance(links, list):
            for link in links:
                link_str = str(link).strip("`'\" ").strip()
                if "<" in link_str or ">" in link_str or not link_str.endswith(".md"):
                    continue
                scanned_links += 1
                target = (md_file.parent / link_str).resolve()
                target_from_root = (abb_ws / link_str).resolve()
                target_template = (abb_ws / "tasks" / "_templates" / Path(link_str).name).resolve()
                if (
                    not target.exists()
                    and not target_from_root.exists()
                    and not target_template.exists()
                ):
                    broken_links.append(
                        f"{md_file.relative_to(abb_ws)} (frontmatter link -> {link_str})"
                    )

        # 2. Check inline markdown links: [text](path.md)
        inline_matches = re.findall(r"\[.*?\]\(([^)#\s]+\.md)(?:#[^)]*)?\)", content)
        for link in inline_matches:
            link_clean = link.strip("`'\" ").strip()
            if (
                link_clean.startswith("http://")
                or link_clean.startswith("https://")
                or "<" in link_clean
                or ">" in link_clean
            ):
                continue
            scanned_links += 1
            target = (md_file.parent / link_clean).resolve()
            target_from_root = (abb_ws / link_clean).resolve()
            target_template = (abb_ws / "tasks" / "_templates" / Path(link_clean).name).resolve()
            if (
                not target.exists()
                and not target_from_root.exists()
                and not target_template.exists()
            ):
                broken_links.append(f"{md_file.relative_to(abb_ws)} (inline link -> {link_clean})")

    return scanned_files, scanned_links, broken_links


def test_validate_all_abb_relative_links():
    """Verify that every relative markdown link in the active or template ABB workspace resolves to a real file."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    local_ws = repo_root / ".codeless" / "abb_workspace"
    template_ws = repo_root / "templates" / "agent_buildable_base"

    if local_ws.exists() and any(local_ws.iterdir()):
        abb_ws = local_ws
    elif template_ws.exists() and any(template_ws.iterdir()):
        abb_ws = template_ws
    else:
        abb_ws = resolve_abb_workspace(repo_root, auto_init=True)

    scanned_files, scanned_links, broken_links = _validate_workspace_links(abb_ws)

    assert len(broken_links) == 0, (
        f"Found {len(broken_links)} broken relative link(s):\n" + "\n".join(broken_links)
    )
    assert scanned_files > 30
    assert scanned_links > 50


def test_validate_template_scaffold_relative_links():
    """Explicitly verify that templates/agent_buildable_base has valid relative links."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    template_ws = repo_root / "templates" / "agent_buildable_base"
    if not template_ws.exists() or not any(template_ws.iterdir()):
        return

    scanned_files, scanned_links, broken_links = _validate_workspace_links(template_ws)
    assert len(broken_links) == 0, (
        f"Found {len(broken_links)} broken relative link(s) in template:\n"
        + "\n".join(broken_links)
    )
    assert scanned_files > 20
    assert scanned_links > 30
