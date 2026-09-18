from pathlib import Path

from agent.paths import Workspace
from agent.skills import SkillRegistry
from agent.tools import ToolRegistry


def _registry(tmp_path: Path, tavily_key="") -> ToolRegistry:
    (tmp_path / "skills").mkdir(exist_ok=True)
    (tmp_path / "tmp").mkdir(exist_ok=True)
    ws = Workspace(tmp_path)
    skills = SkillRegistry(ws)
    cfg = {
        "tavily_api_key": tavily_key,
        "tavily_max_results": 5,
        "tavily_search_depth": "basic",
        "request_timeout": 10,
    }
    return ToolRegistry(cfg, skills, ws)


def test_unknown_tool(tmp_path):
    reg = _registry(tmp_path)
    assert "no such tool" in reg.invoke("does_not_exist", {})


def test_host_status(tmp_path):
    reg = _registry(tmp_path)
    data = reg.invoke("host_status", {})
    assert "python" in data
    assert "workspace" in data
    assert str(tmp_path) in data


def test_write_read_list_delete_roundtrip(tmp_path):
    reg = _registry(tmp_path)
    out = reg.invoke("write_file", {
        "path": "/tmp/hello.txt",
        "content": "hi there",
    })
    assert out.startswith("Wrote 8 bytes")
    assert reg.invoke("read_file", {"path": "/tmp/hello.txt"}) == "hi there"
    listing = reg.invoke("list_dir", {"path": "/tmp"})
    assert "hello.txt" in listing
    deleted = reg.invoke("delete_file", {"path": "/tmp/hello.txt"})
    assert "Deleted" in deleted
    assert "does not exist" in reg.invoke("delete_file", {"path": "/tmp/hello.txt"})


def test_write_refuses_protected_paths(tmp_path):
    reg = _registry(tmp_path)
    (tmp_path / "src").mkdir()
    out = reg.invoke("write_file", {"path": "/src/main.py", "content": "nope"})
    assert out.startswith("Refused")
    out = reg.invoke("write_file", {"path": "/config.json", "content": "{}"})
    assert out.startswith("Refused")


def test_write_refuses_loose_skill_py(tmp_path):
    reg = _registry(tmp_path)
    out = reg.invoke("write_file", {
        "path": "/skills/oops.py",
        "content": "print('hi')",
    })
    assert "would sit loose" in out


def test_write_refuses_invalid_skill_md(tmp_path):
    reg = _registry(tmp_path)
    out = reg.invoke("write_file", {
        "path": "/skills/demo/SKILL.md",
        "content": "# no frontmatter\n",
    })
    assert "not a valid SKILL.md" in out

    out = reg.invoke("write_file", {
        "path": "/skills/demo/SKILL.md",
        "content": "---\nname: other\ndescription: nope\n---\n\n# x\nbody\n",
    })
    assert "does not match its directory" in out


def test_write_skill_md_reloads_registry(tmp_path):
    reg = _registry(tmp_path)
    content = (
        "---\n"
        "name: demo\n"
        "description: A demo skill for tests.\n"
        "---\n"
        "\n"
        "# Demo\n"
        "Call host_status.\n"
    )
    out = reg.invoke("write_file", {"path": "/skills/demo/SKILL.md", "content": content})
    assert "reloaded the skill registry" in out
    assert "demo" in reg.skills.skills
    rendered = reg.invoke("load_skill", {"name": "demo"})
    assert "Call host_status." in rendered


def test_bundled_file_requires_manifest(tmp_path):
    reg = _registry(tmp_path)
    out = reg.invoke("write_file", {
        "path": "/skills/demo/scripts/run.py",
        "content": "result = 1\n",
    })
    assert "has no SKILL.md yet" in out


def test_run_script_captures_print_and_result(tmp_path):
    reg = _registry(tmp_path)
    (tmp_path / "tmp" / "s.py").write_text(
        "print('hello', args['who'])\n"
        "result = {'n': 3}\n"
    )
    out = reg.invoke("run_script", {"path": "/tmp/s.py", "args": {"who": "world"}})
    assert "hello world" in out
    assert '"n": 3' in out


def test_run_script_can_call_tool(tmp_path):
    reg = _registry(tmp_path)
    (tmp_path / "tmp" / "s.py").write_text(
        "result = tool('host_status', {})\n"
    )
    out = reg.invoke("run_script", {"path": "/tmp/s.py"})
    assert "python" in out


def test_catalog_lists_name_and_description(tmp_path):
    catalog = _registry(tmp_path).catalog()
    assert "- load_skill:" in catalog
    assert "Load the full instructions" in catalog
    assert "web_search" not in catalog
    assert "tavily_search" not in catalog
    with_search = _registry(tmp_path, tavily_key="tvly-test").catalog()
    assert "- tavily_search:" in with_search
    assert "- web_search:" not in with_search


def test_tavily_search_omitted_without_key(tmp_path):
    reg = _registry(tmp_path)
    names = [s["function"]["name"] for s in reg.schemas()]
    assert "tavily_search" not in names
    assert "web_search" not in names


def test_tavily_search_present_with_key(tmp_path):
    reg = _registry(tmp_path, tavily_key="tvly-test")
    names = [s["function"]["name"] for s in reg.schemas()]
    assert "tavily_search" in names
    assert "web_search" not in names


def test_web_search_invoke_alias(tmp_path):
    """Scripts may still call tool('web_search', ...); it is not in schemas."""
    reg = _registry(tmp_path, tavily_key="tvly-test")
    out = reg.invoke("web_search", {"query": ""})
    assert "query is empty" in out or "Search failed" in out
