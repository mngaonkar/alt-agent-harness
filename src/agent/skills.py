"""Anthropic-style Skills with progressive disclosure.

A skill is a directory containing a SKILL.md whose YAML frontmatter carries
at minimum a `name` and a `description`. Anything else in the directory —
scripts/, references/, assets/ — is bundled context the model may pull in
on demand.

    /skills/sysinfo/
        SKILL.md
        scripts/rss_watch.py

Disclosure levels:

    Level 1  name + description only, injected into the system prompt.
    Level 2  the full SKILL.md body, loaded via the load_skill tool.
    Level 3  bundled files, read individually via read_file / run_script.

Only level 1 is resident, so a large library stays cheap in the prompt.
"""

from .paths import Workspace


def _strip_quotes(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_frontmatter(text):
    """Parse the leading `---` YAML block of a SKILL.md.

    Supports the subset skills actually use: scalar `key: value` pairs,
    inline `[a, b]` lists, and `- item` block lists.

    Returns (metadata_dict, body_text).
    """
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    block = text[text.find("\n", 3) + 1:end]
    body_start = text.find("\n", end + 1)
    body = text[body_start + 1:] if body_start != -1 else ""

    meta = {}
    current_key = None
    for raw in block.split("\n"):
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue

        if line.startswith((" ", "\t")) and line.strip().startswith("- "):
            if current_key:
                meta.setdefault(current_key, [])
                if isinstance(meta[current_key], list):
                    meta[current_key].append(
                        _strip_quotes(line.strip()[2:].strip())
                    )
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        current_key = key

        if not value:
            meta[key] = []
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = [
                _strip_quotes(p.strip()) for p in inner.split(",") if p.strip()
            ] if inner else []
        else:
            meta[key] = _strip_quotes(value)

    return meta, body


class Skill:
    def __init__(self, name, path, description, meta, workspace):
        self.name = name
        self.path = path
        self.description = description
        self.meta = meta
        self.workspace = workspace

    def read(self):
        manifest = self.workspace.to_real(self.path + "/SKILL.md")
        with open(manifest) as f:
            return parse_frontmatter(f.read())[1]

    def files(self, rel="", depth=0):
        found = []
        if depth > 3:
            return found
        vdir = self.path + ("/" + rel if rel else "")
        real = self.workspace.to_real(vdir)
        try:
            entries = sorted(p.name for p in real.iterdir())
        except OSError:
            return found
        for entry in entries:
            child_rel = (rel + "/" + entry) if rel else entry
            child_virtual = vdir.rstrip("/") + "/" + entry
            child_real = self.workspace.to_real(child_virtual)
            if entry == "SKILL.md" and not rel:
                continue
            if child_real.is_dir():
                found.extend(self.files(child_rel, depth + 1))
            else:
                try:
                    size = child_real.stat().st_size
                except OSError:
                    size = 0
                found.append((child_rel, child_virtual, size))
        return found


class SkillRegistry:
    """Discovers skills and renders them at each disclosure level."""

    def __init__(self, workspace, root="/skills"):
        self.workspace = workspace if isinstance(workspace, Workspace) else Workspace(workspace)
        self.root = root.rstrip("/") or "/skills"
        self.skills = {}
        self.discover()

    def discover(self):
        self.skills = {}
        real_root = self.workspace.to_real(self.root)
        if not real_root.is_dir():
            print("[skills] no skills directory at %s" % real_root)
            return self.skills

        for entry in sorted(p.name for p in real_root.iterdir()):
            path = self.root + "/" + entry
            manifest_v = path + "/SKILL.md"
            try:
                real_dir = self.workspace.to_real(path)
                real_manifest = self.workspace.to_real(manifest_v)
            except ValueError:
                continue
            if not real_dir.is_dir() or not real_manifest.is_file():
                continue
            try:
                with open(real_manifest) as f:
                    head = f.read(1536)
                meta, _ = parse_frontmatter(head)
            except Exception as exc:
                print("[skills] failed to index %s: %s" % (entry, exc))
                continue

            name = meta.get("name") or entry
            description = meta.get("description", "")
            if not description:
                print("[skills] %s has no description; skipping" % name)
                continue
            self.skills[name] = Skill(name, path, description, meta, self.workspace)

        print("[skills] loaded %d: %s" % (
            len(self.skills), ", ".join(sorted(self.skills)) or "none"))
        return self.skills

    def get(self, name):
        return self.skills.get(name)

    def catalog(self):
        if not self.skills:
            return "(no skills installed)"
        lines = []
        for name in sorted(self.skills):
            lines.append("- %s: %s" % (name, self.skills[name].description))
        return "\n".join(lines)

    def render(self, name):
        skill = self.get(name)
        if not skill:
            available = ", ".join(sorted(self.skills)) or "none"
            return "No skill named '%s'. Available skills: %s" % (name, available)

        try:
            body = skill.read()
        except Exception as exc:
            return "Failed to read skill '%s': %s" % (name, exc)

        out = ["# Skill: %s\n" % skill.name, body.strip()]
        bundled = skill.files()
        if bundled:
            out.append("\n\n## Bundled files")
            out.append(
                "Read these with read_file, or execute .py scripts with "
                "run_script, using the exact absolute paths below.")
            for rel, full, size in bundled:
                out.append("- %s (%d bytes) -> %s" % (rel, size, full))
        return "\n".join(out)
