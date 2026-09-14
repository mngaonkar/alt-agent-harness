from pathlib import Path

from agent.paths import Workspace
from agent.skills import SkillRegistry, parse_frontmatter


def test_parse_frontmatter_scalars_and_body():
    text = (
        "---\n"
        "name: demo\n"
        "description: A demo skill.\n"
        "version: 1.0.0\n"
        "---\n"
        "\n"
        "# Demo\n"
        "Do the thing.\n"
    )
    meta, body = parse_frontmatter(text)
    assert meta["name"] == "demo"
    assert meta["description"] == "A demo skill."
    assert meta["version"] == "1.0.0"
    assert body.strip().startswith("# Demo")


def test_parse_frontmatter_lists():
    text = (
        "---\n"
        "name: demo\n"
        "tags: [a, b]\n"
        "items:\n"
        "  - one\n"
        "  - two\n"
        "---\n"
        "body\n"
    )
    meta, body = parse_frontmatter(text)
    assert meta["tags"] == ["a", "b"]
    assert meta["items"] == ["one", "two"]
    assert body.strip() == "body"


def test_parse_frontmatter_no_header():
    meta, body = parse_frontmatter("# just a file\n")
    assert meta == {}
    assert body.startswith("# just")


def _write_skill(root: Path, name: str, description: str, extra_body="Use the tool."):
    d = root / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: %s\ndescription: %s\n---\n\n# %s\n%s\n"
        % (name, description, name, extra_body)
    )
    return d


def test_registry_indexes_name_and_description(tmp_path):
    _write_skill(tmp_path, "alpha", "The alpha skill.")
    _write_skill(tmp_path, "beta", "The beta skill.")
    # No description → skipped
    bad = tmp_path / "skills" / "broken"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: broken\n---\n\n# Broken\n")

    ws = Workspace(tmp_path)
    registry = SkillRegistry(ws)
    assert set(registry.skills) == {"alpha", "beta"}
    catalog = registry.catalog()
    assert "- alpha: The alpha skill." in catalog
    assert "- beta: The beta skill." in catalog
    assert "broken" not in catalog


def test_bundled_repo_skills_index():
    repo = Path(__file__).resolve().parents[1]
    registry = SkillRegistry(Workspace(repo))
    assert set(registry.skills) >= {"sysinfo", "websearch", "write-skill"}
    rendered = registry.render("sysinfo")
    assert "host_status" in rendered
    assert "/skills/sysinfo/scripts/rss_watch.py" in rendered


def test_render_includes_body_and_bundled_files(tmp_path):
    d = _write_skill(tmp_path, "demo", "A demo.")
    scripts = d / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text("result = 1\n")

    registry = SkillRegistry(Workspace(tmp_path))
    rendered = registry.render("demo")
    assert "# Skill: demo" in rendered
    assert "Use the tool." in rendered
    assert "/skills/demo/scripts/run.py" in rendered
    assert registry.render("missing").startswith("No skill named")
