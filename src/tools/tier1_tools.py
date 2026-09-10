"""Tier 1 tools: read-only filesystem access, confined to settings.TOOL_ROOT.

Every handler receives the raw argument text and must push it through
fs_sandbox.resolve_path() before touching disk. None of these tools write,
delete, move, or execute anything.
"""
import fnmatch
import os

from src.config import settings
from src.tools.registry import registry, Tool
from src.tools.fs_sandbox import (
    DENIED_DIRS,
    SandboxError,
    is_binary,
    is_denied_name,
    iter_files,
    read_text_if_textual,
    relative_display,
    resolve_path,
    sandbox_root,
)

MAX_TREE_DEPTH = 3


def _human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return f"{num_bytes:.0f}{unit}" if unit == "B" else f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f}GB"


def list_files_handler(arg: str) -> str:
    """list: <dir>   - contents of one directory."""
    try:
        target = resolve_path(arg or ".", must_exist=True)
    except SandboxError as e:
        return str(e)

    if target.is_file():
        return f"{relative_display(target)} is a file, not a directory. Size {_human_size(target.stat().st_size)}."

    try:
        entries = sorted(
            target.iterdir(),
            key=lambda p: (p.is_file(), p.name.lower()),
        )
    except OSError as e:
        return f"Could not read that directory: {e}"

    # `target` is already inside the sandbox, so its direct children are too.
    # A name-only check is enough here; re-resolving every entry cost a
    # syscall-heavy resolve() per file for no additional safety.
    lines, shown = [], 0
    for entry in entries:
        if is_denied_name(entry.name) or entry.name.lower() in DENIED_DIRS:
            continue   # hidden rather than advertised as forbidden
        if shown >= settings.FS_MAX_RESULTS:
            lines.append(f"... and more, truncated at {settings.FS_MAX_RESULTS}")
            break
        if entry.is_dir():
            lines.append(f"  {entry.name}/")
        else:
            lines.append(f"  {entry.name}  ({_human_size(entry.stat().st_size)})")
        shown += 1

    if not lines:
        return f"{relative_display(target)} is empty."
    return f"{relative_display(target)}:\n" + "\n".join(lines)


def read_file_handler(arg: str) -> str:
    """read: <file>   - contents of one text file."""
    try:
        target = resolve_path(arg, must_exist=True)
    except SandboxError as e:
        return str(e)

    if target.is_dir():
        return f"{relative_display(target)} is a directory. Use 'list: {relative_display(target)}'."

    size = target.stat().st_size
    if size > settings.FS_MAX_READ_BYTES:
        return (f"{relative_display(target)} is {_human_size(size)}, over the "
                f"{_human_size(settings.FS_MAX_READ_BYTES)} read limit.")
    if is_binary(target):
        return f"{relative_display(target)} is a binary file."

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Could not read that file: {e}"

    lines = text.splitlines()
    truncated = len(lines) > settings.FS_MAX_LINES
    body = "\n".join(lines[:settings.FS_MAX_LINES])
    header = f"{relative_display(target)} ({len(lines)} lines, {_human_size(size)}):"
    if truncated:
        body += f"\n... truncated at {settings.FS_MAX_LINES} of {len(lines)} lines"
    return f"{header}\n{body}"


def find_files_handler(arg: str) -> str:
    """find: <pattern>   - filenames matching a glob, recursively."""
    pattern = (arg or "").strip()
    if not pattern:
        return "Give me a pattern, for example 'find: *.py'."
    if "*" not in pattern and "?" not in pattern:
        pattern = f"*{pattern}*"

    root = sandbox_root()
    matches = []
    for path in iter_files(root, max_files=5000):
        if fnmatch.fnmatch(path.name.lower(), pattern.lower()):
            matches.append(relative_display(path))
            if len(matches) >= settings.FS_MAX_RESULTS:
                break

    if not matches:
        return f"Nothing matches {pattern}."
    header = f"{len(matches)} match(es) for {pattern}:"
    return header + "\n" + "\n".join(f"  {m}" for m in matches)


def search_files_handler(arg: str) -> str:
    """search: <text>   - find that text inside project files."""
    needle = (arg or "").strip()
    if not needle:
        return "Give me something to search for, for example 'search: def process_input'."

    root = sandbox_root()
    needle_lower = needle.lower()
    hits = []

    for path in iter_files(root, max_files=5000):
        # One open() per file: binary sniff, size cap and read combined.
        text = read_text_if_textual(path, settings.FS_MAX_READ_BYTES)
        if text is None:
            continue

        # Cheap whole-file check first; most files do not match at all, and
        # this avoids splitting them into lines.
        if needle_lower not in text.lower():
            continue

        for lineno, line in enumerate(text.splitlines(), 1):
            if needle_lower in line.lower():
                hits.append(f"  {relative_display(path)}:{lineno}: {line.strip()[:120]}")
                if len(hits) >= settings.FS_MAX_RESULTS:
                    break
        if len(hits) >= settings.FS_MAX_RESULTS:
            break

    if not hits:
        return f"No matches for '{needle}'."
    return f"{len(hits)} match(es) for '{needle}':\n" + "\n".join(hits)


def tree_handler(arg: str) -> str:
    """tree: <dir>   - project layout, directories only."""
    try:
        start = resolve_path(arg or ".", must_exist=True)
    except SandboxError as e:
        return str(e)
    if start.is_file():
        return f"{relative_display(start)} is a file, not a directory."

    lines, count = [], 0
    for dirpath, dirnames, _filenames in os.walk(start):
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in DENIED_DIRS)

        relative = os.path.relpath(dirpath, start)
        depth = 0 if relative == "." else len(relative.split(os.sep))

        if depth >= MAX_TREE_DEPTH:
            dirnames[:] = []   # stop descending, but still show this level

        name = relative_display(start) if depth == 0 else os.path.basename(dirpath)
        lines.append("  " * depth + f"{name}/")

        count += 1
        if count >= settings.FS_MAX_RESULTS:
            lines.append("... truncated")
            break

    return "\n".join(lines)


registry.register(Tool("list_files_tool", 1, list_files_handler))
registry.register(Tool("read_file_tool", 1, read_file_handler))
registry.register(Tool("find_files_tool", 1, find_files_handler))
registry.register(Tool("search_files_tool", 1, search_files_handler))
registry.register(Tool("tree_tool", 1, tree_handler))
