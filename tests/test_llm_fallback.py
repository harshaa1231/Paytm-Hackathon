import json

import pytest

import config
from core import llm
from core.schemas import MatchAnswer


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(llm, "_cache", None)
    monkeypatch.setattr(llm, "_memo", {})
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def rules():
    return MatchAnswer(candidate_id=None, confidence=0.0, reason="rules")


def test_network_down_falls_to_rules(monkeypatch):
    def boom(prompt):
        raise llm.ProviderError("down", retryable=True)
    monkeypatch.setattr(llm, "_call_groq", boom)
    monkeypatch.setattr(llm, "_call_gemini", boom)
    res, meta = llm.call("match_name", "p", MatchAnswer, fallback=rules, mode="live")
    assert meta["provider"] == "rules" and res.reason == "rules"
    assert "groq#1" in meta["error"] and "groq#2" in meta["error"] and "gemini" in meta["error"]


def test_groq_429_then_gemini(monkeypatch):
    monkeypatch.setattr(llm, "_call_groq", lambda p: (_ for _ in ()).throw(llm.ProviderError("429", True, 30)))
    monkeypatch.setattr(llm, "_call_gemini", lambda p: '{"candidate_id": "C1", "confidence": 0.8, "reason": "ok"}')
    res, meta = llm.call("match_name", "p", MatchAnswer, fallback=rules, mode="live")
    assert meta["provider"] == "gemini" and res.candidate_id == "C1"
    assert "groq#2" not in meta["error"]          # retry-after 30 s > 5 s: no wait, straight to Gemini


def test_invalid_json_retried_once(monkeypatch):
    calls = []

    def groq(p):
        calls.append(1)
        return "not json" if len(calls) == 1 else '{"candidate_id": null, "confidence": 0.1, "reason": "x"}'
    monkeypatch.setattr(llm, "_call_groq", groq)
    res, meta = llm.call("match_name", "p", MatchAnswer, mode="live")
    assert meta["provider"] == "groq" and len(calls) == 2 and res.candidate_id is None


def test_schema_violation_is_rejected(monkeypatch):
    monkeypatch.setattr(llm, "_call_groq", lambda p: '{"candidate_id": "C1", "confidence": 7}')
    monkeypatch.setattr(llm, "_call_gemini", lambda p: '{"candidate_id": "C1"}')
    res, meta = llm.call("match_name", "p", MatchAnswer, fallback=rules, mode="live")
    assert meta["provider"] == "rules"


def test_record_then_replay_offline(monkeypatch):
    monkeypatch.setattr(llm, "_call_groq", lambda p: '{"candidate_id": "C7", "confidence": 0.9, "reason": "r"}')
    llm.call("match_name", "prompt-x", MatchAnswer, mode="record")
    assert json.loads(config.CACHE_PATH.read_text())
    # replay must never touch the network
    def no_network(p):
        raise AssertionError("network used in replay")
    monkeypatch.setattr(llm, "_call_groq", no_network)
    monkeypatch.setattr(llm, "_call_gemini", no_network)
    monkeypatch.setattr(llm, "_cache", None)
    res, meta = llm.call("match_name", "prompt-x", MatchAnswer, mode="replay")
    assert meta["provider"] == "cache" and res.candidate_id == "C7"
    res, meta = llm.call("match_name", "other prompt", MatchAnswer, fallback=rules, mode="replay")
    assert meta["provider"] == "rules" and "cache miss" in meta["error"]


def test_token_budget(monkeypatch):
    monkeypatch.setattr(llm, "_call_groq", lambda p: (_ for _ in ()).throw(AssertionError("should not call")))
    res, meta = llm.call("match_name", "x" * 10_000, MatchAnswer, fallback=rules, mode="live")
    assert meta["provider"] == "rules" and "budget" in meta["error"]


def test_unknown_task_rejected():
    with pytest.raises(ValueError):
        llm.call("write_ledger", "p", MatchAnswer)


def test_groq_ok_never_calls_gemini(monkeypatch):
    monkeypatch.setattr(llm, "_call_groq", lambda p: '{"candidate_id": "C1", "confidence": 0.9, "reason": "ok"}')
    monkeypatch.setattr(llm, "_call_gemini", lambda p: (_ for _ in ()).throw(AssertionError("gemini called")))
    res, meta = llm.call("match_name", "p-ok", MatchAnswer, fallback=rules, mode="live")
    assert meta["provider"] == "groq" and meta["error"] is None and res.candidate_id == "C1"
