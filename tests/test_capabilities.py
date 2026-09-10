"""The capability block Deep Core is told about must match reality.

Asked to create a file, the model used to confidently report having created
one - the tool layer refused correctly, but nothing in the model's context
said what it could actually do, so it improvised. These tests cover the
deterministic half of the fix: what we tell the model. Model output itself is
non-deterministic and is not asserted on here.
"""
import pytest

import src.main as ultron
from src.config import settings
from src.core.router import ReflexRouter
from src.tools.registry import registry, gate, Tool


def test_block_lists_every_permitted_command():
    block = ultron._capability_block()
    for verb in ReflexRouter.COMMAND_PREFIXES:
        assert f"{verb}:" in block, f"{verb}: missing from capability block"


def test_block_states_the_absence_of_write_and_execute():
    block = ultron._capability_block().lower()
    for forbidden in ["create", "write", "edit", "rename", "move", "delete"]:
        assert forbidden in block, f"block never mentions inability to {forbidden}"
    assert "read-only" in block
    assert "no ability" in block


def test_block_forbids_claiming_completed_actions():
    block = ultron._capability_block().lower()
    assert "never claim to have performed an action" in block


def test_block_drops_commands_when_their_tier_is_disabled(monkeypatch):
    """
    Turning off Tier 1 must remove the file commands from what the model is
    told, otherwise it will offer capabilities the gate then refuses.
    """
    monkeypatch.setattr(settings, "ALLOWED_TIERS", [0])
    block = ultron._capability_block()
    for verb in ["read:", "list:", "find:", "search:", "tree:"]:
        assert verb not in block
    assert "none" in block


def test_block_tracks_newly_registered_tools(monkeypatch):
    """Built from the registry, so it cannot drift as tools are added."""
    monkeypatch.setitem(ReflexRouter.COMMAND_PREFIXES, "diagnose", "diagnose_tool")
    registry.register(Tool("diagnose_tool", 0, lambda text: "ok"))
    try:
        assert "diagnose:" in ultron._capability_block()
    finally:
        registry._tools.pop("diagnose_tool", None)


def test_system_context_carries_capabilities_and_memory(monkeypatch, tmp_path):
    from src.core.memory import MemoryManager

    mm = MemoryManager(tmp_path / "m.db")
    mm.add_memory("the user prefers terse answers", "user_provided")
    monkeypatch.setattr(ultron, "memory", mm)

    context = ultron.build_system_context()
    assert "YOUR ACTUAL CAPABILITIES" in context
    assert "terse answers" in context
    # Capabilities come first so they are not buried under a long fact list.
    assert context.index("YOUR ACTUAL CAPABILITIES") < context.index("terse answers")


def test_system_context_works_with_no_memories(monkeypatch, tmp_path):
    from src.core.memory import MemoryManager

    monkeypatch.setattr(ultron, "memory", MemoryManager(tmp_path / "empty.db"))
    context = ultron.build_system_context()
    assert "YOUR ACTUAL CAPABILITIES" in context
    assert "KNOWN FACTS" not in context


def test_can_use_is_side_effect_free(monkeypatch):
    """can_use() feeds the prompt on every turn; it must not spam the audit log."""
    events = []
    monkeypatch.setattr(ultron.audit, "log_event", lambda e, d: events.append(e))

    tool = registry.get_tool("read_file_tool")
    gate.can_use(tool)
    assert events == []

    gate.check(tool)
    assert events, "check() must still audit"


def test_no_write_capable_tool_is_reachable():
    """Backstop: if a mutating tool is ever added, it must not be permitted."""
    for name, tool in registry._tools.items():
        if any(w in name for w in ("write", "create", "delete", "exec", "shell", "run")):
            assert not gate.can_use(tool), f"{name} is reachable under current policy"
