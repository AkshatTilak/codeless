"""Tests for ABB Skill Bridge and dual-format YAML index parsing."""

from pathlib import Path

from codeless.abb.shadow import bootstrap_workspace
from codeless.skills import load_skill_registry
from codeless.skills.loader import load_abb_skills, parse_abb_skills_index


def test_parse_abb_skills_index_yaml_block(tmp_path: Path):
    """Test parsing machine-readable YAML block from skills.md."""
    skills_md = tmp_path / "skills.md"
    content = """---
version: 2.0.0
id: skills
---
# Skills

## 3. Index

| Skill | Path | Purpose |
|---|---|---|
| Practice TDD | practice/tdd/SKILL.md | TDD cycle |

```yaml
skills:
  - name: practice_tdd
    path: practice/tdd/SKILL.md
    description: Red-green-refactor test cycle
    version: 1.0.0
    aliases: ["practice/tdd", "tdd"]
  - name: qa_backend
    path: qa/backend/SKILL.md
    description: Quality assurance for backend
    version: 1.0.0
```
"""
    skills_md.write_text(content, encoding="utf-8")
    entries = parse_abb_skills_index(skills_md)
    assert len(entries) == 2
    assert entries[0]["name"] == "practice_tdd"
    assert entries[0]["path"] == "practice/tdd/SKILL.md"
    assert entries[0]["aliases"] == ["practice/tdd", "tdd"]
    assert entries[1]["name"] == "qa_backend"


def test_load_abb_skills_from_workspace(tmp_path: Path):
    """Test loading nested ABB skills into SkillDefinition models."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    ws_path, _ = bootstrap_workspace(project_root, location="local")

    skills = load_abb_skills(project_root)
    names = [s.name for s in skills]
    assert len(skills) > 0
    # Check that practice_tdd or qa_backend or manage_skills is loaded
    assert any("tdd" in name.lower() for name in names) or any(
        "qa" in name.lower() for name in names
    )

    # Check source attribute
    for s in skills:
        assert s.source == "abb"
        assert s.path is not None
        assert Path(s.path).exists()


def test_load_skill_registry_includes_abb_skills(tmp_path: Path, monkeypatch):
    """Test load_skill_registry includes both bundled, user, and ABB skills."""
    project_root = tmp_path / "project_reg"
    project_root.mkdir()
    monkeypatch.setenv("CODELESS_CONFIG_DIR", str(tmp_path / "config"))
    bootstrap_workspace(project_root, location="local")

    registry = load_skill_registry(cwd=project_root)
    skill_names = [s.name for s in registry.list_skills()]

    # Bundled skills present
    assert "simplify" in skill_names
    # ABB skills present
    assert any(
        "tdd" in s.lower() or "qa" in s.lower() or "manage" in s.lower() for s in skill_names
    )
