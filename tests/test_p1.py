import pytest
from src.security.sanitizer import InputSanitizer, SanitizationError
from src.core.router import ReflexRouter
from src.core.history import HistoryManager
from src.tools.registry import registry, gate, Tool
from src.config import settings

# 1. Sanitizer Tests
def test_sanitizer_strips_invisible_chars():
    # \u202e is Right-to-Left Override, \u200b is Zero Width Space
    text, tokens = InputSanitizer.sanitize("h\u202eell\u200bo")
    assert text == "hello"
    assert tokens == ["hello"]

def test_sanitizer_strips_control_chars():
    text, tokens = InputSanitizer.sanitize("help\x07\x08") # Bell and Backspace
    assert text == "help"

def test_sanitizer_rejects_too_long():
    with pytest.raises(SanitizationError):
        InputSanitizer.sanitize("a" * (settings.MAX_RAW_LENGTH + 1))

# 2. Router Tests
def test_router_exact_match():
    assert ReflexRouter.route(["system", "status"]) == "system_status_tool"
    assert ReflexRouter.route(["time"]) == "time_tool"

def test_router_rejects_fuzzy_match():
    # "open notepad" is NOT in the allowed list, so it must return None
    assert ReflexRouter.route(["open", "notepad"]) is None
    assert ReflexRouter.route(["what", "time", "is", "it"]) is None

# 3. History Manager Tests
def test_history_keeps_system_prompt_first():
    hm = HistoryManager("You are ULTRON.")
    hm.add_user_message("hello")
    messages = hm.get_messages()
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "You are ULTRON."
    assert messages[1]["role"] == "user"

# 4. Permission Gate Tests
def test_gate_allows_tier_0():
    tool = Tool("test_t0", 0, lambda: "ok")
    assert gate.check(tool) is True

def test_gate_denies_tier_1():
    tool = Tool("test_t1", 1, lambda: "ok")
    assert gate.check(tool) is False

# 5. Registry Safety Tests
def test_no_forbidden_tools_in_registry():
    # P1 must NOT have open, launch, exec, or shell tools
    for name in registry._tools.keys():
        assert "open" not in name
        assert "launch" not in name
        assert "shell" not in name
        assert "exec" not in name