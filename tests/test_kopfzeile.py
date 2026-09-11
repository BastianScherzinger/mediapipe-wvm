"""Tests für die Kopfzeile: Beschriftungen und Ampeln.

Der Kunde liest oben rechts ab, ob das Programm arbeiten kann. Zwei Dinge dürfen
deshalb nie verrutschen: die Wörter (er soll sie ohne Erklärung verstehen) und die
Farbe der Higgsfield-Lampe (sie darf nicht grün leuchten, wenn kein Video entstehen
kann — und muss grün werden, sobald das Abo verbunden ist).

Geprüft wird gegen die wirklichen Routen, nicht gegen Nachbauten.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import higgsfield, higgsfield_mcp, server, videoquelle  # noqa: E402


@pytest.fixture
def besucher():
    anwendung = server.anwendung_bauen()
    anwendung.config.update(TESTING=True)
    with anwendung.test_client() as klient:
        yield klient


def _kopf(klient) -> str:
    """Nur der *sichtbare* Text der Kopfzeile — Kennungen wie `id="lampe-ffmpeg"`
    sieht der Kunde nicht und sie dürfen den Test nicht beeinflussen."""
    seite = klient.get("/").get_data(as_text=True)
    kopf = seite.split('<header class="kopf">')[1].split("</header>")[0]
    return " ".join(re.sub(r"<[^>]*>", " ", kopf).split())


# ── Beschriftungen ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("wort", ["Higgsfield", "Drehbuch", "Videoschnitt", "Prüfen",
                                  "Update", "Abo verbinden"])
def test_kopfzeile_spricht_deutsch_und_ohne_fachjargon(besucher, wort):
    assert wort in _kopf(besucher)


@pytest.mark.parametrize("wort", ["Sprachmodell", "ffmpeg", "Selbsttest", "Aktuell"])
def test_alte_missverstaendliche_woerter_sind_verschwunden(besucher, wort):
    """„Sprachmodell“ ließ an Sprachausgabe denken, „Selbsttest“ verstand niemand,
    und „Aktuell“ sah aus wie ein anderer Knopf als „Aktualisierung (3)“."""
    assert wort not in _kopf(besucher)


# ── Ampel ────────────────────────────────────────────────────────────────────

def test_ampel_ist_gruen_wenn_das_abo_verbunden_ist(besucher, monkeypatch):
    monkeypatch.setattr(higgsfield_mcp, "angemeldet", lambda: True)
    daten = besucher.get("/api/start").get_json()["diagnose"]
    higgs = next(b for b in daten["befunde"] if b["name"] == "Higgsfield")
    assert higgs["zustand"] == "ok"


def test_ampel_ist_gelb_bei_leerem_guthaben(besucher, monkeypatch):
    monkeypatch.setattr(higgsfield_mcp, "angemeldet", lambda: False)
    monkeypatch.setattr(higgsfield.client, "guthaben_bekannt",
                        lambda: {"guthaben": False, "zeitpunkt": time.time()})
    daten = besucher.get("/api/start").get_json()["diagnose"]
    higgs = next(b for b in daten["befunde"] if b["name"] == "Higgsfield")
    assert higgs["zustand"] == "warnung"
    # Eine Warnung ist kein Startverbot: das Programm läuft weiter.
    assert daten["startbereit"] is True


def test_fremde_webseite_darf_nichts_ausloesen(besucher):
    """Jede Webseite im Browser des Kunden könnte dem lokalen Server eine POST-Anfrage
    schicken — „Update“, „Neustart“, „Erneut versuchen“. Der Browser nennt dabei seine
    Herkunft; eine fremde wird abgewiesen."""
    fremd = besucher.post("/api/wege-zuruecksetzen",
                          headers={"Origin": "https://boese.example"})
    assert fremd.status_code == 403
    anderer_port = besucher.post("/api/wege-zuruecksetzen",
                                 headers={"Origin": "http://localhost:9999"})
    assert anderer_port.status_code == 403
    eigene = besucher.post("/api/wege-zuruecksetzen", headers={"Origin": "http://localhost"})
    assert eigene.status_code == 200


def test_fremder_hostname_wird_abgewiesen(besucher):
    """Schutz gegen DNS-Rebinding: Nur 127.0.0.1 und localhost sind der eigene Server."""
    assert besucher.get("/api/lebt", base_url="http://boese.example").status_code == 403
    assert besucher.get("/api/lebt").status_code == 200


def test_leeres_guthaben_haelt_das_programm_nicht_auf(besucher, monkeypatch):
    """Nur ein „fehler“ darf `startbereit` kippen. Sonst würde die Oberfläche beim
    Start eine Fehlermeldung zeigen, obwohl nur der Topf leer ist."""
    monkeypatch.setattr(videoquelle, "befund",
                        lambda: {"ok": True, "zustand": "warnung",
                                 "meldung": "leer", "hinweis": ""})
    daten = besucher.get("/api/start").get_json()["diagnose"]
    assert daten["startbereit"] is True
    assert daten["anzahl_fehler"] == 0
