"""Tests for the hardening and optimisation pass."""
import re
from pathlib import Path

import pytest

import src.main as ultron
from src.config import Settings, settings
from src.core.memory import MemoryManager
from src.core.sessions import SessionStore


INDEX_HTML = Path(__file__).parent.parent / "static" / "index.html"


# --- XSS: untrusted text must never reach innerHTML ---

def test_frontend_never_interpolates_into_innerhtml():
    """
    The HUD renders model output, typed input, and the contents of any file
    read via 'read:'. Interpolating those into innerHTML meant a file
    containing <img src=x onerror=...> ran script as soon as Ultron read it.

    Static assignments of literal markup are fine; interpolation is not.
    """
    html = INDEX_HTML.read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in html.splitlines()
        if "innerHTML" in line and re.search(r"innerHTML\s*=.*\$\{", line)
    ]
    assert not offenders, "interpolated innerHTML found:\n" + "\n".join(offenders)


def test_frontend_uses_textcontent_for_entry_bodies():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "body.textContent = text" in html
    assert "createTextNode" in html


def test_tool_output_reaches_the_client_verbatim(tmp_path, monkeypatch):
    """
    The backend deliberately does not escape markup - escaping belongs at the
    render boundary. This test pins that contract so the frontend fix is
    understood to be the only thing standing between a poisoned file and the
    DOM. If this ever starts failing, the frontend assumption changed too.
    """
    payload = '<img src=x onerror="alert(1)">'
    (tmp_path / "poisoned.txt").write_text(payload, encoding="utf-8")
    monkeypatch.setattr(settings, "TOOL_ROOT", tmp_path)

    result = ultron.process_input("read: poisoned.txt")
    assert payload in result


# --- Sessions ---

def test_sessions_are_isolated():
    store = SessionStore("system")
    store.get("tab_a").add_user_message("only in A")
    assert store.get("tab_b").conversation == []
    assert len(store.get("tab_a").conversation) == 1


def test_same_session_id_returns_the_same_history():
    store = SessionStore("system")
    store.get("tab_a").add_user_message("hello")
    assert len(store.get("tab_a").conversation) == 1


def test_missing_session_id_falls_back_to_default():
    store = SessionStore("system")
    store.get("").add_user_message("hi")
    assert len(store.get("default").conversation) == 1


def test_session_store_evicts_oldest_beyond_capacity():
    store = SessionStore("system", max_sessions=3)
    for i in range(5):
        store.get(f"tab_{i}").add_user_message("x")
    assert len(store) == 3


def test_expired_sessions_are_dropped():
    store = SessionStore("system", ttl_seconds=0)
    store.get("stale").add_user_message("x")
    assert store.get("fresh").conversation == []
    assert len(store) == 1


def test_cli_and_web_do_not_share_a_conversation(monkeypatch):
    monkeypatch.setattr(ultron, "sessions", SessionStore(ultron.SYSTEM_PROMPT))
    ultron.sessions.get("cli").add_user_message("from the terminal")
    assert ultron.sessions.get("tab_1").conversation == []


# --- Memory limits ---

def test_memory_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MEMORY_MAX_FACTS", 5)
    mm = MemoryManager(tmp_path / "capped.db")
    for i in range(12):
        mm.add_memory(f"fact number {i}", "user_provided")

    stored = mm.get_all_memories()
    assert len(stored.splitlines()) - 1 == 5
    assert "fact number 11" in stored     # newest kept
    assert "fact number 0" not in stored  # oldest dropped


def test_overlong_facts_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MEMORY_MAX_FACT_LENGTH", 20)
    mm = MemoryManager(tmp_path / "long.db")
    assert mm.add_memory("x" * 21) is False
    assert mm.add_memory("short enough") is True


def test_blank_facts_are_rejected(tmp_path):
    mm = MemoryManager(tmp_path / "blank.db")
    assert mm.add_memory("   ") is False


# --- Audit rotation ---

def test_audit_handler_rotates():
    from logging.handlers import RotatingFileHandler
    from src.security.audit import audit

    handlers = [h for h in audit.logger.handlers if isinstance(h, RotatingFileHandler)]
    assert handlers, "audit log is not rotating and will grow without bound"
    assert handlers[0].maxBytes > 0
    assert handlers[0].backupCount > 0


# --- Dead code ---

def test_removed_dead_script_stays_removed():
    assert not (Path(__file__).parent.parent / "test_voice.py").exists()


def test_websocket_pushes_telemetry_not_a_bare_heartbeat():
    from fastapi.testclient import TestClient
    from src.server import app

    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            message = ws.receive_json()
    assert message["type"] == "telemetry"
    assert 0 <= message["cpu"] <= 100
    assert 0 < message["ram"] <= 100


# --- Config sanity ---

def test_telemetry_interval_is_not_a_busy_loop():
    assert Settings().TELEMETRY_INTERVAL >= 0.5
