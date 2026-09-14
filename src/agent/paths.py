"""Map virtual agent paths (/skills, /tmp, …) onto a workspace directory."""

from pathlib import Path


def _posix(path):
    return str(path).replace("\\", "/")


class Workspace:
    """A chroot-like view of the project directory.

    The model always sees POSIX virtual paths rooted at `/`. Those map onto
    files under `root`. Writes and deletes are limited to `/skills/` and
    `/tmp/` so a bad tool call cannot overwrite the harness itself.
    """

    MUTABLE_PREFIXES = ("/skills/", "/tmp/")
    MUTABLE_EXACT = ("/skills", "/tmp")

    def __init__(self, root):
        self.root = Path(root).resolve()

    def normalize(self, vpath):
        if not vpath:
            return "/"
        text = str(vpath).replace("\\", "/")
        if not text.startswith("/"):
            text = "/" + text
        parts = []
        for part in text.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        return "/" + "/".join(parts) if parts else "/"

    def to_real(self, vpath):
        """Resolve a virtual path to a real path, refusing escapes."""
        normalized = self.normalize(vpath)
        rel = normalized.lstrip("/")
        real = (self.root / rel).resolve() if rel else self.root
        if real != self.root and self.root not in real.parents:
            raise ValueError("path escapes workspace: %s" % vpath)
        return real

    def to_virtual(self, real):
        real = Path(real).resolve()
        rel = real.relative_to(self.root)
        as_posix = _posix(rel)
        return "/" if as_posix in (".", "") else "/" + as_posix

    def is_mutable(self, vpath):
        normalized = self.normalize(vpath)
        if normalized in self.MUTABLE_EXACT:
            return True
        return any(
            normalized.startswith(prefix) for prefix in self.MUTABLE_PREFIXES
        )
