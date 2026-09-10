"""Confinement tests for Tier 1 filesystem tools.

These matter more than the feature tests. The tool argument is attacker-
influenced - it can arrive from the user, from a stored memory, or from Deep
Core's own output - so escaping the sandbox must be impossible, not unlikely.
"""
import os
from pathlib import Path

import pytest

import src.main as ultron
from src.config import settings
from src.core.router import ReflexRouter
from src.tools import fs_sandbox
from src.tools.fs_sandbox import SandboxError, resolve_path
from src.tools.registry import registry, gate


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway project tree, so tests never depend on the real repo."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def handler():\n    return 'ultron'\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("line one\nline two\n", encoding="utf-8")
    (tmp_path / ".env").write_text("ELEVENLABS_API_KEY=sk_supersecret\n", encoding="utf-8")
    (tmp_path / "ultron_memory.db").write_bytes(b"\x00SQLite format 3")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (tmp_path / "big.txt").write_text("x" * 200_000, encoding="utf-8")

    outside = tmp_path.parent / "outside_secret.txt"
    outside.write_text("THIS MUST NEVER BE READABLE", encoding="utf-8")

    monkeypatch.setattr(settings, "TOOL_ROOT", tmp_path)
    return tmp_path


# --- Containment ---

@pytest.mark.parametrize("attack", [
    "../outside_secret.txt",
    "../../outside_secret.txt",
    "src/../../outside_secret.txt",
    "./src/../../../outside_secret.txt",
    "..\\outside_secret.txt",
    "src\\..\\..\\outside_secret.txt",
])
def test_traversal_cannot_escape_root(sandbox, attack):
    with pytest.raises(SandboxError):
        resolve_path(attack)


@pytest.mark.parametrize("attack", [
    "C:\\Windows\\System32\\drivers\\etc\\hosts",
    "C:/Users",
    "/etc/passwd",
    "\\\\server\\share\\file.txt",
    "//server/share/file.txt",
])
def test_absolute_and_unc_paths_are_refused(sandbox, attack):
    with pytest.raises(SandboxError):
        resolve_path(attack)


def test_sibling_directory_with_shared_prefix_is_refused(sandbox, monkeypatch):
    """
    A prefix comparison without a separator would let 'projectX' pass as being
    inside 'project'. The separator check is what stops it.
    """
    root = sandbox / "project"
    root.mkdir()
    sibling = sandbox / "project_evil"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("nope", encoding="utf-8")

    monkeypatch.setattr(settings, "TOOL_ROOT", root)
    with pytest.raises(SandboxError):
        resolve_path("../project_evil/secret.txt")


@pytest.mark.skipif(os.name != "nt", reason="Windows path casing")
def test_case_differences_do_not_defeat_containment(sandbox):
    assert resolve_path("SRC/APP.PY").exists()
    with pytest.raises(SandboxError):
        resolve_path("../OUTSIDE_SECRET.TXT")


def test_symlink_pointing_outside_is_refused(sandbox):
    link = sandbox / "escape_link"
    try:
        link.symlink_to(sandbox.parent / "outside_secret.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires privileges on this system")
    with pytest.raises(SandboxError):
        resolve_path("escape_link")


def test_directory_junction_pointing_outside_is_refused(sandbox):
    """
    Junctions need no special privileges on Windows, so this is the escape an
    unprivileged attacker could actually create. resolve() must follow it out
    of the tree and the containment check must then reject it.
    """
    if os.name != "nt":
        pytest.skip("junctions are Windows-only")

    target = sandbox.parent / "outside_dir"
    target.mkdir(exist_ok=True)
    (target / "secret.txt").write_text("MUST NOT BE READABLE", encoding="utf-8")

    junction = sandbox / "escape_junction"
    rc = os.system(f'mklink /J "{junction}" "{target}" >nul 2>&1')
    if rc != 0 or not junction.exists():
        pytest.skip("could not create a junction on this system")

    with pytest.raises(SandboxError):
        resolve_path("escape_junction/secret.txt")
    assert "MUST NOT BE READABLE" not in ultron.process_input("read: escape_junction/secret.txt")


# --- Denylist ---

@pytest.mark.parametrize("denied", [".env", "ultron_memory.db"])
def test_secret_files_are_refused_even_inside_root(sandbox, denied):
    with pytest.raises(SandboxError):
        resolve_path(denied)


def test_git_directory_is_refused(sandbox):
    with pytest.raises(SandboxError):
        resolve_path(".git/config")


def test_read_tool_never_returns_the_api_key(sandbox):
    for attempt in [".env", "./.env", "src/../.env", ".ENV"]:
        assert "sk_supersecret" not in ultron.process_input(f"read: {attempt}")


def test_search_tool_never_surfaces_the_api_key(sandbox):
    assert "sk_supersecret" not in ultron.process_input("search: ELEVENLABS_API_KEY")


def test_find_tool_does_not_list_denied_files(sandbox):
    result = ultron.process_input("find: *")
    assert ".env" not in result
    assert "ultron_memory.db" not in result


def test_list_tool_hides_denied_entries(sandbox):
    result = ultron.process_input("list: .")
    assert ".env" not in result
    assert "notes.txt" in result


# --- Reading behaviour ---

def test_read_returns_file_contents(sandbox):
    result = ultron.process_input("read: src/app.py")
    assert "def handler" in result
    assert "src/app.py" in result


def test_read_refuses_oversized_files(sandbox):
    result = ultron.process_input("read: big.txt")
    assert "limit" in result.lower()


def test_read_refuses_binary(sandbox):
    (sandbox / "blob.png").write_bytes(b"\x89PNG\x00\x00binary")
    assert "binary" in ultron.process_input("read: blob.png").lower()


def test_read_missing_file_is_a_clean_message(sandbox):
    result = ultron.process_input("read: nope.txt")
    assert "No such file" in result
    assert "Tool execution failed" not in result


def test_errors_do_not_leak_absolute_paths(sandbox):
    """Error text must not disclose where the project lives on disk."""
    for probe in ["read: ../outside_secret.txt", "read: C:/Windows/win.ini", "read: .env"]:
        assert str(sandbox) not in ultron.process_input(probe)


# --- Search and find ---

def test_search_finds_text_with_line_numbers(sandbox):
    result = ultron.process_input("search: ultron")
    assert "src/app.py:2" in result


def test_find_matches_glob(sandbox):
    result = ultron.process_input("find: *.py")
    assert "src/app.py" in result


def test_find_bare_word_becomes_a_substring_match(sandbox):
    assert "notes.txt" in ultron.process_input("find: notes")


# --- tree ---

def test_tree_shows_real_directory_names_at_increasing_indent(sandbox):
    """
    The first implementation computed depth wrongly and printed './' for every
    directory at every level. Assert real names and real nesting.
    """
    (sandbox / "src" / "nested").mkdir()
    lines = ultron.process_input("tree:").splitlines()

    assert lines[0] == "./"
    assert any(line == "  src/" for line in lines), lines
    assert any(line == "    nested/" for line in lines), lines
    assert not any(line.strip() == "./" for line in lines[1:]), "root marker repeated"


def test_tree_excludes_denied_directories(sandbox):
    assert ".git" not in ultron.process_input("tree:")


def test_tree_of_a_file_is_a_clean_message(sandbox):
    assert "not a directory" in ultron.process_input("tree: notes.txt")


def test_tree_cannot_escape_the_sandbox(sandbox):
    result = ultron.process_input("tree: ..")
    assert result == "Path is outside the permitted project directory."
    # The sibling directory holding outside_secret.txt must not be enumerated.
    assert "outside_secret" not in result


# --- Routing and policy ---

def test_bare_verb_does_not_trigger_a_file_tool():
    """'read me a poem' is conversation, not a file read."""
    assert ReflexRouter.route_command("read me a poem") is None
    assert ReflexRouter.route_command("search for meaning") is None


def test_command_grammar_parses_verb_and_argument():
    assert ReflexRouter.route_command("read: src/main.py") == ("read_file_tool", "src/main.py")
    assert ReflexRouter.route_command("TREE:") == ("tree_tool", "")


def test_memory_commands_still_win_over_file_commands(sandbox):
    """'remember:' is handled before routing and must not be shadowed."""
    assert "Memory updated" in ultron.process_input("remember: test fact")


def test_tier_1_tools_are_registered_at_tier_1():
    for name in ["list_files_tool", "read_file_tool", "find_files_tool",
                 "search_files_tool", "tree_tool"]:
        assert registry.get_tool(name).tier == 1


def test_disabling_tier_1_blocks_every_file_tool(sandbox, monkeypatch):
    """The permission gate, not the router, is the enforcement point."""
    monkeypatch.setattr(settings, "ALLOWED_TIERS", [0])
    for command in ["read: src/app.py", "list: .", "find: *.py", "search: ultron", "tree:"]:
        assert ultron.process_input(command) == "Action denied by security policy."
    # Tier 0 still works.
    assert "percent" in ultron.process_input("cpu")


def test_no_write_or_execute_tools_exist():
    """Tier 1 is read-only. Nothing here may mutate or run anything."""
    forbidden = ("write", "delete", "remove", "exec", "shell", "run", "move", "rename")
    for name in registry._tools:
        assert not any(word in name for word in forbidden), name
