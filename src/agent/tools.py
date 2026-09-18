"""Native tools exposed to the model as OpenAI function definitions.

Skills supply *instructions*; these tools supply *capability*. Anything a skill
tells the model to do ultimately runs through one of the handlers here, which
is what lets new skills be added at runtime without restarting.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import search as _search
from .paths import Workspace
from .skills import parse_frontmatter


def _validate_manifest(content, dir_name):
    """Return a problem description for a SKILL.md, or None when it is valid."""
    if not content.lstrip().startswith("---"):
        return "it has no YAML frontmatter block"
    meta, body = parse_frontmatter(content)
    if not meta.get("name"):
        return "the frontmatter has no 'name' field"
    if not meta.get("description"):
        return ("the frontmatter has no 'description' field, so the skill can "
                "never be selected")
    if meta["name"] != dir_name:
        return ("name '%s' does not match its directory '%s'; they must be "
                "identical" % (meta["name"], dir_name))
    if not body.strip():
        return "it has frontmatter but no instructions after it"
    return None


class ToolRegistry:
    """Holds tool schemas plus their handlers and dispatches model tool calls."""

    def __init__(self, cfg, skills, workspace):
        self.cfg = cfg
        self.skills = skills
        self.workspace = workspace if isinstance(workspace, Workspace) else Workspace(workspace)
        self._handlers = {}
        self._schemas = []
        self.tavily = _search.TavilyClient(cfg)
        self.started_at = time.time()
        self._register_all()

    def add(self, name, description, properties, required, handler):
        self._schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        })
        self._handlers[name] = handler

    def schemas(self):
        return self._schemas

    def catalog(self):
        """Name + description for each registered tool, for /tools and UIs."""
        if not self._schemas:
            return "(no tools registered)"
        lines = []
        for schema in self._schemas:
            fn = schema.get("function") or {}
            name = fn.get("name") or ""
            desc = " ".join((fn.get("description") or "").split())
            if name:
                lines.append("- %s: %s" % (name, desc))
        return "\n".join(lines) if lines else "(no tools registered)"

    def invoke(self, name, arguments):
        handler = self._handlers.get(name)
        if not handler:
            return "Error: no such tool '%s'" % name
        try:
            result = handler(arguments or {})
        except Exception as exc:
            return "Error: %s: %s" % (type(exc).__name__, exc)
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result)
        except Exception:
            return str(result)

    def _register_all(self):
        self.add(
            "load_skill",
            "Load the full instructions for an installed skill. Call this as "
            "soon as a skill's description looks relevant to the request; the "
            "returned text tells you how to complete the task and lists any "
            "bundled files you can read or run.",
            {"name": {"type": "string", "description": "Skill name to load."}},
            ["name"],
            lambda a: self.skills.render(a.get("name", "")),
        )

        self.add(
            "list_skills",
            "List every installed skill with its description. Useful after "
            "creating a new skill to confirm it registered.",
            {}, [],
            lambda a: self.skills.catalog(),
        )

        self.add(
            "list_dir",
            "List files and directories at a virtual path in the workspace "
            "(absolute, e.g. /skills).",
            {"path": {"type": "string", "description": "Absolute virtual path, e.g. /skills"}},
            ["path"],
            self._list_dir,
        )

        self.add(
            "read_file",
            "Read a UTF-8 text file from the workspace.",
            {
                "path": {"type": "string", "description": "Absolute virtual file path."},
                "max_bytes": {"type": "integer", "description": "Cap on bytes read (default 8000)."},
            },
            ["path"],
            self._read_file,
        )

        self.add(
            "write_file",
            "Create or overwrite a text file under /skills/ or /tmp/. Parent "
            "dirs are created automatically. For a new skill write "
            "/skills/<name>/SKILL.md (call load_skill write-skill for format) then "
            "optional scripts/; never a loose .py under /skills/.",
            {
                "path": {"type": "string", "description": "Absolute virtual file path."},
                "content": {"type": "string", "description": "Full file contents."},
            },
            ["path", "content"],
            self._write_file,
        )

        self.add(
            "delete_file",
            "Delete a file or an entire directory tree under /skills/ or "
            "/tmp/. Protected paths (harness code, config.json) cannot be "
            "deleted. After deleting under /skills/, the skill registry is "
            "reloaded.",
            {
                "path": {"type": "string",
                         "description": "Absolute virtual path to a file or directory."},
            },
            ["path"],
            self._delete_file,
        )

        self.add(
            "run_script",
            "Execute a Python .py script that is bundled with a skill (or "
            "drafted under /tmp/). Anything the script prints is returned, as "
            "is the value it assigns to a variable named `result`. Scripts run "
            "with `args`, `cfg`, `time` and `tool` in scope, where "
            "tool('name', {...}) calls any tool listed here.",
            {
                "path": {"type": "string", "description": "Absolute virtual path to a .py file."},
                "args": {"type": "object", "description": "Optional args, available to the script as `args`."},
            },
            ["path"],
            self._run_script,
        )

        self.add(
            "run_bash",
            "Execute a bash or shell command on the host. Captures and returns "
            "standard output, standard error, and exit status. Pagers are "
            "disabled (PAGER=cat). Useful for git, builds, tests, system "
            "inspection, and CLI tools.",
            {
                "command": {"type": "string", "description": "The command line to run."},
                "cwd": {"type": "string", "description": "Directory to run in (defaults to workspace root)."},
                "timeout": {"type": "integer", "description": "Maximum seconds to wait (default 30, max 300)."},
            },
            ["command"],
            self._run_bash,
        )

        # Deliberately not named "sysinfo": a native tool sharing a skill's
        # exact name gets called directly, and the skill's interpretation
        # guidance is never loaded.
        self.add(
            "host_status",
            "Return raw host diagnostic values: OS, Python version, CPU count, "
            "workspace disk usage, process RSS, uptime, and cwd. Values are "
            "unformatted; the sysinfo skill explains how to interpret them.",
            {}, [],
            self._host_status,
        )

        if self.tavily.enabled:
            # Named tavily_search, not web_search: grok-4.6 treats a function
            # called web_search as xAI's built-in server tool, swallows the
            # call, and returns an empty reply (finish_reason=stop).
            self.add(
                "tavily_search",
                "Search the live web via Tavily and get back a short synthesised "
                "answer plus source snippets. Use for anything you cannot know "
                "from this host itself: current events, prices, weather, "
                "documentation, or any fact that may have changed since "
                "training. Prefer this over http_get, which returns raw "
                "unparsed HTML. The tool name is tavily_search; do not call "
                "web_search.",
                {
                    "query": {"type": "string", "description": "The search query."},
                    "max_results": {"type": "integer", "description": "Sources to return, 1-10 (default 5)."},
                    "topic": {"type": "string", "description": "'general' (default) or 'news' for recent events."},
                    "days": {"type": "integer", "description": "With topic='news', how many days back to look."},
                },
                ["query"],
                self._tavily_search,
            )
            self._handlers["web_search"] = self._tavily_search

        self.add(
            "http_get",
            "Fetch a URL from the internet and return the response body as text.",
            {
                "url": {"type": "string", "description": "Full URL including scheme."},
                "max_bytes": {"type": "integer", "description": "Cap on bytes returned (default 4000)."},
            },
            ["url"],
            self._http_get,
        )

    def _list_dir(self, a):
        vpath = a.get("path", "/")
        try:
            real = self.workspace.to_real(vpath)
        except ValueError as exc:
            return "Error: %s" % exc
        if not real.is_dir():
            return "Not a directory: %s" % vpath
        rows = []
        for entry in sorted(p.name for p in real.iterdir()):
            child = real / entry
            if child.is_dir():
                rows.append("%s/" % entry)
            else:
                try:
                    rows.append("%s (%d bytes)" % (entry, child.stat().st_size))
                except OSError:
                    rows.append(entry)
        return "\n".join(rows) if rows else "(empty)"

    def _read_file(self, a):
        vpath = a.get("path", "")
        limit = int(a.get("max_bytes", 8000))
        try:
            real = self.workspace.to_real(vpath)
        except ValueError as exc:
            return "Error: %s" % exc
        if not real.is_file():
            return "Error: not a file: %s" % vpath
        with open(real, "r", encoding="utf-8", errors="replace") as f:
            data = f.read(limit + 1)
        if len(data) > limit:
            return data[:limit] + "\n...[truncated]"
        return data

    def _write_file(self, a):
        vpath = a.get("path", "") or ""
        content = a.get("content", "")
        if not str(vpath).strip():
            return (
                "Error: path is empty. Pass an absolute path such as "
                "/skills/<name>/scripts/foo.py or /tmp/draft.py"
            )
        try:
            normalized = self.workspace.normalize(vpath)
        except Exception:
            return "Error: invalid path %r" % vpath
        if not self.workspace.is_mutable(normalized):
            return (
                "Refused: can only write under /skills/ or /tmp/ "
                "(got %s). Draft under /tmp/ or install under /skills/."
                % normalized
            )
        if content is None:
            content = ""
        if not isinstance(content, str):
            content = str(content)

        root = self.skills.root.rstrip("/") + "/"
        if normalized.startswith(root):
            rel_parts = [p for p in normalized[len(root):].split("/") if p]
            if len(rel_parts) == 1:
                return (
                    "Refused: %s would sit loose in %s and would NOT become a "
                    "skill. A skill must be a directory containing SKILL.md:\n"
                    "  %s<name>/SKILL.md      instructions with YAML "
                    "frontmatter (name, description)\n"
                    "  %s<name>/scripts/*.py  optional code\n"
                    "Call load_skill with name 'write-skill' for the exact "
                    "format, then write to %s<name>/SKILL.md."
                    % (normalized, self.skills.root, root, root, root))
            if rel_parts[-1] == "SKILL.md":
                problem = _validate_manifest(content, rel_parts[0])
                if problem:
                    return (
                        "Refused: %s is not a valid SKILL.md -- %s\n"
                        "It must begin with YAML frontmatter, exactly:\n"
                        "---\n"
                        "name: %s\n"
                        "description: <what it does AND when to use it, "
                        "including words a user would say>\n"
                        "---\n\n"
                        "# <title>\n"
                        "<instructions>\n"
                        % (normalized, problem, rel_parts[0]))
            else:
                manifest = root + rel_parts[0] + "/SKILL.md"
                try:
                    manifest_real = self.workspace.to_real(manifest)
                except ValueError:
                    manifest_real = None
                if manifest_real is None or not manifest_real.is_file():
                    return (
                        "Refused: skill '%s' has no SKILL.md yet, so a bundled "
                        "file cannot be attached to it. Write %s first, then "
                        "add this file. Or draft under /tmp/ until tests pass."
                        % (rel_parts[0], manifest))

        try:
            real = self.workspace.to_real(normalized)
        except ValueError as exc:
            return "Error: %s" % exc
        if real.exists() and real.is_dir():
            return "Error: %s is a directory; write to a file path inside it" % normalized

        try:
            real.parent.mkdir(parents=True, exist_ok=True)
            with open(real, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            return "Error writing %s: %s" % (normalized, exc)

        if normalized.endswith("SKILL.md"):
            self.skills.discover()
            return ("Wrote %d bytes to %s and reloaded the skill registry.\n\n"
                    "If you are still prototyping, test scripts with "
                    "run_script before claiming the skill works. Prefer "
                    "drafting under /tmp/ then copying into "
                    "/skills/<name>/scripts/ once tests pass. To abandon a "
                    "broken skill, delete_file the whole /skills/<name>/ "
                    "directory.\n\n"
                    "Installed skills are now:\n%s"
                    % (len(content), normalized, self.skills.catalog()))
        return "Wrote %d bytes to %s" % (len(content), normalized)

    def _delete_file(self, a):
        vpath = a.get("path", "")
        try:
            normalized = self.workspace.normalize(vpath)
        except Exception:
            return "Error: invalid path %r" % vpath
        if normalized in ("/", "/skills", "/tmp"):
            return "Refused: will not delete the root of %s" % normalized
        if not self.workspace.is_mutable(normalized):
            return (
                "Refused: can only delete under /skills/ or /tmp/ "
                "(got %s)" % normalized)
        try:
            real = self.workspace.to_real(normalized)
        except ValueError as exc:
            return "Error: %s" % exc
        if not real.exists():
            return "Nothing to delete: %s does not exist" % normalized

        try:
            if real.is_dir():
                shutil.rmtree(real)
                kind = "dir"
            else:
                real.unlink()
                kind = "file"
        except OSError as exc:
            return "Error deleting %s: %s" % (normalized, exc)

        skills_root = self.skills.root.rstrip("/")
        if normalized == skills_root or normalized.startswith(skills_root + "/"):
            self.skills.discover()
            return ("Deleted %s (%s) and reloaded the skill registry.\n\n"
                    "Installed skills are now:\n%s"
                    % (normalized, kind, self.skills.catalog()))
        return "Deleted %s (%s)" % (normalized, kind)

    def _run_script(self, a):
        vpath = a.get("path", "")
        if not str(vpath).endswith(".py"):
            return "Error: run_script only executes .py files"
        try:
            real = self.workspace.to_real(vpath)
        except ValueError as exc:
            return "Error: %s" % exc
        try:
            source = real.read_text(encoding="utf-8")
        except OSError as exc:
            return "Error: cannot read %s: %s" % (vpath, exc)

        captured = []

        def _capture(*values, **kwargs):
            sep = kwargs.get("sep", " ")
            captured.append(sep.join(str(v) for v in values))

        namespace = {
            "args": a.get("args") or {},
            "cfg": {k: v for k, v in self.cfg.items()},
            "time": time,
            "os": os,
            "json": json,
            "Path": Path,
            "print": _capture,
            "tool": lambda name, tool_args=None: self.invoke(name, tool_args or {}),
            "result": None,
            "__name__": "__skill__",
        }

        try:
            exec(source, namespace)  # noqa: S102 — intentional skill sandbox
        except Exception as exc:
            return "Script raised %s: %s\n--- output ---\n%s" % (
                type(exc).__name__, exc, "\n".join(captured))

        parts = []
        printed = "\n".join(captured).strip()
        if printed:
            parts.append(printed)
        value = namespace.get("result")
        if value is not None:
            try:
                parts.append("result = " + json.dumps(value))
            except Exception:
                parts.append("result = " + str(value))
        return "\n".join(parts) if parts else "Script finished with no output."

    def _host_status(self, a):
        disk = shutil.disk_usage(self.workspace.root)
        rss = None
        rss_unit = None
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # Linux reports KB; macOS reports bytes.
            rss_unit = "kb" if sys.platform.startswith("linux") else "bytes"
        except Exception:
            pass
        info = {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "system": platform.system(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "cwd": os.getcwd(),
            "workspace": str(self.workspace.root),
            "pid": os.getpid(),
            "uptime_s": int(time.time() - self.started_at),
            "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free,
        }
        if rss is not None:
            info["rss"] = rss
            info["rss_unit"] = rss_unit
        return info

    def _tavily_search(self, a):
        try:
            data = self.tavily.search(
                a.get("query", ""),
                max_results=a.get("max_results"),
                topic=a.get("topic", "general") or "general",
                days=a.get("days"),
            )
        except _search.SearchError as exc:
            return "Search failed: %s" % exc
        return _search.format_results(data)

    def _http_get(self, a):
        url = a.get("url", "")
        if not url:
            return "Error: url is empty"
        limit = int(a.get("max_bytes", 4000))
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "alt-agent-harness/0.1"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                status = resp.status
                ctype = (resp.headers.get("Content-Type") or "").lower()
                raw = resp.read(limit + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            ctype = (exc.headers.get("Content-Type") if exc.headers else "") or ""
            ctype = ctype.lower()
            raw = exc.read(limit + 1)
        except OSError as exc:
            return "Error fetching %s: %s" % (url, exc)

        looks_binary = (
            ctype.startswith("image/")
            or ctype.startswith("audio/")
            or ctype.startswith("video/")
            or ctype.startswith("application/octet")
            or raw[:3] == b"\xff\xd8\xff"
            or raw[:8] == b"\x89PNG\r\n\x1a\n"
        )
        if looks_binary:
            return (
                "HTTP %d\nContent-Type: %s\nBytes read: %d (binary; not shown)\n"
                % (status, ctype or "unknown", len(raw))
            )
        body = raw[:limit].decode("utf-8", "replace")
        if len(raw) > limit:
            body += "\n...[truncated]"
        return "HTTP %d\n%s" % (status, body)

    def _run_bash(self, a):
        command = (a.get("command") or "").strip()
        if not command:
            return "Error: command is required"

        timeout_raw = a.get("timeout", 30)
        try:
            timeout = min(max(int(timeout_raw), 1), 300)
        except (ValueError, TypeError):
            timeout = 30

        cwd_arg = a.get("cwd")
        if not cwd_arg:
            real_cwd = self.workspace.root
        else:
            try:
                if str(cwd_arg).startswith("/"):
                    try:
                        real_cwd = self.workspace.to_real(cwd_arg)
                    except ValueError:
                        real_cwd = Path(cwd_arg).resolve()
                else:
                    real_cwd = (self.workspace.root / cwd_arg).resolve()
            except Exception as exc:
                return "Error: invalid cwd %r: %s" % (cwd_arg, exc)

        if not real_cwd.is_dir():
            return "Error: directory does not exist: %s" % cwd_arg

        env = dict(os.environ)
        env["PAGER"] = "cat"
        env["TERM"] = "dumb"
        env["CI"] = "1"

        shell_path = "/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh"

        try:
            proc = subprocess.run(
                command,
                shell=True,
                executable=shell_path,
                cwd=str(real_cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            msg = "Error: command timed out after %d seconds" % timeout
            parts = [msg]
            if exc.stdout:
                parts.append("STDOUT:\n" + str(exc.stdout).strip())
            if exc.stderr:
                parts.append("STDERR:\n" + str(exc.stderr).strip())
            return "\n".join(parts)
        except Exception as exc:
            return "Error: failed to execute command: %s" % exc

        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()

        max_bytes = 10000
        if len(stdout) > max_bytes:
            stdout = stdout[:max_bytes] + "\n...[truncated]"
        if len(stderr) > max_bytes:
            stderr = stderr[:max_bytes] + "\n...[truncated]"

        parts = []
        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append("STDERR:\n" + stderr)
        if proc.returncode != 0:
            parts.append("[exited with status %d]" % proc.returncode)
        if not parts:
            parts.append("(command completed with no output, exit code 0)")

        return "\n".join(parts)
