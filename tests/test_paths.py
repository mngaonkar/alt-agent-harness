import pytest

from agent.paths import Workspace


def test_normalize_and_escape(tmp_path):
    ws = Workspace(tmp_path)
    assert ws.normalize("skills/foo") == "/skills/foo"
    assert ws.normalize("/skills/../tmp/x") == "/tmp/x"
    assert ws.normalize("/skills/foo/../..") == "/"
    assert ws.normalize("/skills/foo/../../etc/passwd") == "/etc/passwd"


def test_to_real_stays_in_workspace(tmp_path):
    ws = Workspace(tmp_path)
    real = ws.to_real("/skills/demo/SKILL.md")
    assert real == (tmp_path / "skills" / "demo" / "SKILL.md").resolve()
    # Even after .. normalization, the path must still resolve under root.
    # /etc/passwd normalizes to /etc/passwd, which is under the virtual root
    # as <workspace>/etc/passwd — not the host /etc/passwd.
    escaped = ws.to_real("/etc/passwd")
    assert escaped == (tmp_path / "etc" / "passwd").resolve()
    assert tmp_path in escaped.parents or escaped.parent == tmp_path


def test_to_real_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / "outside-secret"
    outside.write_text("nope")
    (tmp_path / "tmp").mkdir()
    link = tmp_path / "tmp" / "link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("cannot create symlink")
    ws = Workspace(tmp_path)
    with pytest.raises(ValueError, match="escapes workspace"):
        ws.to_real("/tmp/link")


def test_is_mutable():
    ws = Workspace(".")
    assert ws.is_mutable("/skills")
    assert ws.is_mutable("/skills/foo/SKILL.md")
    assert ws.is_mutable("/tmp/draft.py")
    assert not ws.is_mutable("/src/main.py")
    assert not ws.is_mutable("/config.json")
    assert not ws.is_mutable("/")
