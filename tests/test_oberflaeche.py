"""Tests für die Oberfläche (templates/index.html, static/js).

Ohne Browser: Geprüft wird, dass die Skripte sich übersetzen lassen und dass die
Vorkehrungen gegen die gefundenen Fehler im Code stehen — Doppelklick-Sperre,
Barrierefreiheit, Aufwerten-Knopf, Neustart-Erkennung. Ein Rückbau fällt so auf, bevor
ihn ein Kunde bemerkt.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

BASIS = Path(__file__).resolve().parent.parent
JS = BASIS / "static" / "js"
HTML = (BASIS / "templates" / "index.html").read_text(encoding="utf-8")


def _js(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


class _Elemente(HTMLParser):
    """Sammelt die Attribute aller Elemente mit Kennung."""

    def __init__(self):
        super().__init__()
        self.nach_kennung: dict[str, dict] = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.nach_kennung[a["id"]] = {"tag": tag, **a}


def _elemente() -> dict[str, dict]:
    leser = _Elemente()
    leser.feed(HTML)
    return leser.nach_kennung


@pytest.mark.skipif(not shutil.which("node"), reason="Node ist nicht installiert")
@pytest.mark.parametrize("datei", sorted(p.name for p in JS.glob("*.js")))
def test_skripte_lassen_sich_uebersetzen(datei):
    lauf = subprocess.run(["node", "--check", str(JS / datei)], capture_output=True,
                          text=True, timeout=60)
    assert lauf.returncode == 0, lauf.stderr


# ── Barrierefreiheit ─────────────────────────────────────────────────────────

def test_logbuch_wird_nicht_vorgelesen():
    """Jede Logzeile vorzulesen, übertönte alles andere — das Logbuch ist ein Protokoll."""
    assert "aria-live" not in {k for k in _elemente()["log"]}


@pytest.mark.parametrize("kennung", ["startzeile", "web-zeile", "pr-zeile"])
def test_statuszeilen_sind_als_status_ausgezeichnet(kennung):
    assert _elemente()[kennung].get("role") == "status"


def test_abo_fenster_laesst_sich_schliessen_und_beendet_das_abfragen():
    abo = _js("abo.js")
    assert '"aria-label": "Schließen' in abo
    assert 'addEventListener("close"' in abo
    assert "abfrageBeendet" in abo
    # Die Schleife muss die Marke tatsächlich auswerten.
    schleife = abo[abo.index("while (Date.now() < bis)"):]
    assert "if (abfrageBeendet)" in schleife[:600]


# ── Doppelklick ──────────────────────────────────────────────────────────────

def test_startknoepfe_sind_waehrend_des_sendens_gesperrt():
    start = _js("start.js")
    for knopf in ("#btn-start", "#btn-web-start", "#btn-pr-start"):
        assert knopf in start
        assert knopf.lstrip("#") in _elemente()
    rumpf = start[start.index("async function auftragAbschicken"):]
    rumpf = rumpf[:rumpf.index("\n  }\n") + 4]
    assert "if (sendetGerade) return false;" in rumpf
    assert "finally" in rumpf and "sendetGerade = false" in rumpf
    # Die Rückgabe (angenommen ja/nein) nutzt der Premium-Bereich — sie muss bleiben.
    assert "return true;" in rumpf and "return false;" in rumpf


def test_start_waehrend_laufender_pruefung_wartet_auf_sie():
    webseite = _js("webseite.js")
    assert "laufendePruefung" in webseite
    starten = webseite[webseite.index("async function starten"):]
    assert "await zustand.laufendePruefung" in starten[:400]


# ── Aufwerten ────────────────────────────────────────────────────────────────

def test_premium_kacheln_haben_einen_aufwerten_knopf():
    bibliothek = _js("bibliothek.js")
    assert 'video.art === "premium"' in bibliothek
    assert "/api/premium/aufwerten/" in bibliothek
    assert "maengel" in bibliothek
    assert "MPW.start.angenommen" in bibliothek
    assert re.search(r"angenommen:\s*nachDemAbschicken", _js("start.js"))
    assert 'id="i-stern"' in HTML                     # das verwendete Icon gibt es


# ── Hochladen und Neustart ───────────────────────────────────────────────────

def test_hochladen_laeuft_ueber_die_gemeinsame_fehlerbehandlung():
    premium = _js("premium.js")
    rumpf = premium[premium.index("async function hochladen"):]
    rumpf = rumpf[:rumpf.index("\n  }\n")]
    assert "fetch(" not in rumpf
    assert 'MPW.hole("/api/premium/material"' in rumpf


def test_neustart_wird_an_der_startkennung_erkannt():
    aktualisierung = _js("aktualisierung.js")
    assert "gestartet" in aktualisierung
    assert "warWeg" in aktualisierung                 # Rückfall für ältere Server
    assert "const gesperrt" not in aktualisierung
