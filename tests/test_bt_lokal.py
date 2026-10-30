"""Tests für die lokale Rückfallebene (app/llm/lokal.py).

Ohne laufendes Ollama und ohne Netz: Ein kleiner Ersatz für `httpx.Client` liefert
vorgegebene Antworten oder wirft die Fehler, die das Modul unterscheiden muss. Geprüft
wird, was das Modul selbst entscheidet — Modellnamen, die Auswahl der Nachrichten, das
Entfernen von Leerraum und die Übersetzung von Zeit- und HTTP-Fehlern.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, errors  # noqa: E402
from app.llm import lokal  # noqa: E402


class _Antwort:
    def __init__(self, *, status_code: int = 200, daten=None, text: str = ""):
        self.status_code = status_code
        self._daten = daten
        self.text = text

    def json(self):
        if isinstance(self._daten, BaseException):
            raise self._daten
        return self._daten


class _Klient:
    """Steht anstelle von httpx.Client und merkt sich jeden Aufruf."""

    def __init__(self, *, antwort=None, fehler: BaseException | None = None):
        self.antwort = antwort
        self.fehler = fehler
        self.aufrufe: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, adresse: str):
        self.aufrufe.append({"adresse": adresse, "json": None})
        if self.fehler is not None:
            raise self.fehler
        return self.antwort

    def post(self, adresse: str, json=None):
        self.aufrufe.append({"adresse": adresse, "json": json})
        if self.fehler is not None:
            raise self.fehler
        return self.antwort


def _client(monkeypatch, *, antwort=None, fehler=None) -> _Klient:
    klient = _Klient(antwort=antwort, fehler=fehler)
    monkeypatch.setattr(lokal.httpx, "Client", lambda *args, **kwargs: klient)
    return klient


def _kein_netz(*args, **kwargs):
    raise AssertionError("Hier darf keine Verbindung aufgebaut werden.")


def test_modellname_kommt_aus_der_konfiguration(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_MODEL", "qwen2.5:3b")
    assert lokal.modellname() == "qwen2.5:3b"


@pytest.mark.parametrize("vorhanden, gesucht, erwartet", [
    (["qwen2.5:7b"], "qwen2.5:7b", True),
    (["llama3:latest"], "llama3", True),
    (["qwen2.5:7b"], "llama3:8b", False),
    ([], "qwen2.5:7b", False),
])
def test_modell_da_vergleicht_mit_der_vorhandenen_liste(monkeypatch, vorhanden,
                                                        gesucht, erwartet):
    monkeypatch.setattr(lokal, "vorhandene_modelle", lambda: vorhanden)
    assert lokal._modell_da(gesucht) is erwartet


def test_vorhandene_modelle_filtert_leere_namen(monkeypatch):
    _client(monkeypatch, antwort=_Antwort(daten={"models": [
        {"name": "qwen2.5:7b"}, {"name": ""}, {}, {"name": "llama3:latest"}]}))
    assert lokal.vorhandene_modelle() == ["qwen2.5:7b", "llama3:latest"]


def test_vorhandene_modelle_ohne_dienst_ist_leer(monkeypatch):
    _client(monkeypatch, fehler=RuntimeError("Dienst nicht erreichbar"))
    assert lokal.vorhandene_modelle() == []


def test_bereit_meldet_laufenden_dienst(monkeypatch):
    _client(monkeypatch, antwort=_Antwort(status_code=200))
    assert lokal.bereit() == (True, "")


def test_bereit_nennt_den_antwortcode(monkeypatch):
    _client(monkeypatch, antwort=_Antwort(status_code=503))
    bereit, meldung = lokal.bereit()
    assert bereit is False
    assert "503" in meldung


def test_bereit_ohne_dienst_sagt_was_zu_starten_ist(monkeypatch):
    _client(monkeypatch, fehler=RuntimeError("Dienst nicht erreichbar"))
    bereit, meldung = lokal.bereit()
    assert bereit is False
    assert "ollama serve" in meldung


def test_modell_laden_ist_bei_vorhandenem_modell_ruhig(monkeypatch):
    monkeypatch.setattr(lokal, "_modell_da", lambda name: True)
    monkeypatch.setattr(lokal.httpx, "Client", _kein_netz)
    assert lokal.modell_laden("qwen2.5:7b") is None


def test_erzeuge_ohne_modell_und_ohne_autopull_erklaert_was_zu_tun_ist(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_MODEL", "qwen2.5:7b")
    monkeypatch.setattr(config, "LOCAL_AUTOPULL", False)
    monkeypatch.setattr(lokal, "_modell_da", lambda name: False)
    monkeypatch.setattr(lokal.httpx, "Client", _kein_netz)

    with pytest.raises(errors.KonfigurationsFehler) as fehler:
        lokal.erzeuge("", "Schreib etwas.")
    assert "qwen2.5:7b" in fehler.value.meldung
    assert "MPW_LOCAL_AUTOPULL" in fehler.value.hinweis


def test_erzeuge_schickt_systemtext_und_auftrag(monkeypatch):
    monkeypatch.setattr(lokal, "_modell_da", lambda name: True)
    monkeypatch.setattr(config, "LOCAL_MODEL", "qwen2.5:7b")
    klient = _client(monkeypatch, antwort=_Antwort(
        daten={"message": {"content": "  Ergebnis  "}}))

    assert lokal.erzeuge("Vorgabe", "Auftrag") == "Ergebnis"

    assert len(klient.aufrufe) == 1
    aufruf = klient.aufrufe[0]
    assert aufruf["adresse"] == f"{config.OLLAMA_URL}/api/chat"
    assert aufruf["json"]["model"] == "qwen2.5:7b"
    assert aufruf["json"]["stream"] is False
    assert aufruf["json"]["messages"] == [
        {"role": "system", "content": "Vorgabe"},
        {"role": "user", "content": "Auftrag"},
    ]
    assert aufruf["json"]["options"]["temperature"] == 0.4


def test_erzeuge_ohne_systemtext_und_ohne_inhalt(monkeypatch):
    monkeypatch.setattr(lokal, "_modell_da", lambda name: True)
    klient = _client(monkeypatch, antwort=_Antwort(daten={}))

    assert lokal.erzeuge("", "Nur Auftrag") == ""
    assert klient.aufrufe[0]["json"]["messages"] == [
        {"role": "user", "content": "Nur Auftrag"}]


def test_erzeuge_meldet_zeitueberschreitung(monkeypatch):
    monkeypatch.setattr(lokal, "_modell_da", lambda name: True)
    _client(monkeypatch, fehler=lokal.httpx.TimeoutException("zu spät"))

    with pytest.raises(errors.ZeitFehler) as fehler:
        lokal.erzeuge("", "x", zeitlimit=7)
    assert "7 Sekunden" in fehler.value.meldung


def test_erzeuge_meldet_ablehnende_antwort(monkeypatch):
    monkeypatch.setattr(lokal, "_modell_da", lambda name: True)
    _client(monkeypatch, antwort=_Antwort(status_code=500, text="Server kaputt"))

    with pytest.raises(errors.AnbieterFehler) as fehler:
        lokal.erzeuge("", "x")
    assert "500" in fehler.value.meldung


def test_erzeuge_meldet_unlesbare_antwort(monkeypatch):
    monkeypatch.setattr(lokal, "_modell_da", lambda name: True)
    _client(monkeypatch, antwort=_Antwort(daten=ValueError("kein JSON")))

    with pytest.raises(errors.AnbieterFehler) as fehler:
        lokal.erzeuge("", "x")
    assert "unlesbar" in fehler.value.meldung
