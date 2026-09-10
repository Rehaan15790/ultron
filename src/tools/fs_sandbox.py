"""Filesystem confinement for Tier 1 tools.

Every path Ultron touches goes through resolve_path(). Nothing else in the
tool layer is permitted to build a Path from user input directly.

The threat model is not just a malicious user - it is the LLM. Deep Core sees
stored memories and its own prior turns, both of which are attacker-influenced,
so a tool argument must be treated as hostile input even when it arrives by way
of the model.
"""
import fnmatch
import os
from pathlib import Path

from src.config import settings


class SandboxError(Exception):
    """Raised when a path is outside the sandbox or otherwise forbidden."""


# Names and patterns that stay unreadable even inside the sandbox root.
# Secrets, private state, and anything that would let Ultron read his own
# credentials back out.
DENIED_NAMES = {
    ".env", ".env.local", ".env.production",
    "ultron_memory.db",
    "id_rsa", "id_ed25519", ".npmrc", ".pypirc", ".netrc",
    "credentials", "credentials.json", "secrets.json",
}

DENIED_PATTERNS = [
    ".env.*", "*.key", "*.pem", "*.pfx", "*.p12",
    "*.db", "*.sqlite", "*.sqlite3",
    "*_secret*", "*secrets*", "*.credentials",
]

# Directories never descended into or read from.
DENIED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".idea", ".vscode",
}

# Extensions treated as binary and refused for reading.
BINARY_EXTENSIONS = {
    ".mp3", ".wav", ".ogg", ".flac", ".mp4", ".avi", ".mov", ".mkv",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svgz",
    ".zip", ".gz", ".tar", ".7z", ".rar", ".bz2", ".xz",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".obj", ".pyd",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".pyc", ".pyo", ".class", ".jar", ".onnx", ".pt", ".safetensors",
}


def sandbox_root() -> Path:
    return Path(settings.TOOL_ROOT).resolve()


def is_denied_name(name: str) -> bool:
    """Cheap name-only check. Public so callers already inside the sandbox can
    filter entries without paying for a full resolve() on each one."""
    lowered = name.lower()
    if lowered in DENIED_NAMES:
        return True
    return any(fnmatch.fnmatch(lowered, pattern) for pattern in DENIED_PATTERNS)


# Backwards-compatible private alias.
_is_denied_name = is_denied_name


def _contains_denied_dir(relative: Path) -> bool:
    return any(part.lower() in DENIED_DIRS for part in relative.parts)


def resolve_path(user_path: str, must_exist: bool = True) -> Path:
    """
    Turn untrusted text into a Path that is provably inside the sandbox.

    Raises SandboxError for: absolute paths, drive letters, UNC paths, traversal
    that escapes the root, symlinks pointing outside, denied directories, and
    denied filenames.
    """
    if not user_path or not user_path.strip():
        raise SandboxError("No path given.")

    candidate = user_path.strip().strip('"').strip("'").replace("\\", "/")

    # Reject anything that names a location rather than a relative path. This
    # is belt and braces - the containment check below is what actually
    # guarantees safety - but it produces a clearer message.
    if candidate.startswith("//") or candidate.startswith("\\\\"):
        raise SandboxError("UNC paths are not permitted.")
    if os.path.isabs(candidate) or (len(candidate) > 1 and candidate[1] == ":"):
        raise SandboxError("Absolute paths are not permitted. Use a path relative to the project.")

    root = sandbox_root()

    # resolve() collapses ".." and follows symlinks, so a link pointing out of
    # the tree lands outside the root and fails the containment check below.
    try:
        resolved = (root / candidate).resolve()
    except (OSError, ValueError) as e:
        raise SandboxError(f"Invalid path: {e}")

    # normcase because Windows paths are case-insensitive; comparing raw
    # strings would let a differently-cased prefix slip past.
    root_cmp = os.path.normcase(str(root))
    resolved_cmp = os.path.normcase(str(resolved))
    if resolved_cmp != root_cmp and not resolved_cmp.startswith(root_cmp + os.sep):
        raise SandboxError("Path is outside the permitted project directory.")

    relative = resolved.relative_to(root) if resolved != root else Path(".")

    if _contains_denied_dir(relative):
        raise SandboxError("That directory is not readable.")
    if resolved != root and _is_denied_name(resolved.name):
        raise SandboxError("That file is not readable.")

    if must_exist and not resolved.exists():
        raise SandboxError("No such file or directory.")

    return resolved


def is_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(4096)
    except OSError:
        return True


def read_text_if_textual(path: Path, max_bytes: int) -> str | None:
    """
    Read a file as text, or return None if it is binary, too large, or
    unreadable. One open() instead of the stat + sniff + reopen dance.
    """
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return None
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
            if b"\x00" in head:
                return None
            rest = f.read(max_bytes - len(head) + 1)
    except OSError:
        return None

    raw = head + rest
    if len(raw) > max_bytes:
        return None
    return raw.decode("utf-8", errors="replace")


def relative_display(path: Path) -> str:
    """Render a path for the user without leaking the absolute filesystem layout."""
    try:
        rel = path.resolve().relative_to(sandbox_root())
        return str(rel).replace("\\", "/") or "."
    except ValueError:
        return path.name


def iter_files(start: Path, max_files: int):
    """Walk the tree under `start`, skipping denied directories and files."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(start):
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in DENIED_DIRS)
        for name in sorted(filenames):
            if _is_denied_name(name):
                continue
            yield Path(dirpath) / name
            count += 1
            if count >= max_files:
                return
