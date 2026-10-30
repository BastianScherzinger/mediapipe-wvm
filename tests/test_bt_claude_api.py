"""Tests für app.llm.claude_api.

Nur bestehendes, reines Verhalten. Keine Netzwerkzugriffe.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, errors
from app.llm import claude_api


def test_modellname_gibt_config_wert_zurueck(monkeypatch):
    monkeypatch.setattr(config, "CLAUDE_API_MODEL", "test-modell-xyz")
    assert claude_api.modellname() == "test-modell-xyz"


def test_bereit_ohne_key_ist_nicht_bereit(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_KEY", "")
    # SDK kann vorhanden oder nicht sein, aber ohne Key soll False sein
    ok, meldung = claude_api.bereit()
    assert ok is False
    assert meldung


def test_bereit_mit_key_aber_ohne_sdk(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_KEY", "sk-test")
    monkeypatch.setattr(claude_api, "_sdk", lambda: None)
    ok, meldung = claude_api.bereit()
    assert ok is False
    assert "anthropic" in meldung.lower() or "Paket" in meldung


def test_bereit_mit_key_und_sdk(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_KEY", "sk-test")
    monkeypatch.setattr(claude_api, "_sdk", lambda: object())
    ok, meldung = claude_api.bereit()
    assert ok is True
    assert meldung == ""


def test_erzeuge_ohne_sdk_wirft_konfigurationsfehler(monkeypatch):
    monkeypatch.setattr(claude_api, "_sdk", lambda: None)
    with pytest.raises(errors.KonfigurationsFehler):
        claude_api.erzeuge("system", "auftrag")


def test_erzeuge_ohne_key_wirft_zugangsfehler(monkeypatch):
    class DummySDK:
        pass

    monkeypatch.setattr(claude_api, "_sdk", lambda: DummySDK())
    monkeypatch.setattr(config, "ANTHROPIC_KEY", "")
    with pytest.raises(errors.ZugangFehler):
        claude_api.erzeuge("system", "auftrag")
