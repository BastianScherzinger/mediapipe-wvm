"""Tests für den Themen- und Argumentkatalog in `app.topics`."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import topics  # noqa: E402


# ── Nachschlagen ─────────────────────────────────────────────────────────────

def test_thema_findet_bekannte_kennung():
    eintrag = topics.thema("werbung")
    assert eintrag is not None
    assert eintrag["kennung"] == "werbung"
    assert eintrag["name"] == "Werbevideo"


def test_thema_liefert_none_bei_unbekannter_kennung():
    assert topics.thema("gibt-es-nicht") is None
    assert topics.thema("") is None


def test_plattform_findet_bekannte_und_lehnt_unbekannte_ab():
    tiktok = topics.plattform("tiktok")
    assert tiktok is not None
    assert tiktok["seitenverhaeltnis"] == "9:16"
    assert tiktok["formate"] == ["hoch"]
    assert topics.plattform("myspace") is None


def test_katalog_enthaelt_alle_vier_bereiche():
    katalog = topics.katalog()
    assert set(katalog) == {"themen", "argumentgruppen", "zusatzfelder", "plattformen"}
    assert katalog["themen"] is topics.THEMEN
    assert katalog["plattformen"] is topics.PLATTFORMEN


# ── Argumente zusammensetzen ─────────────────────────────────────────────────

def test_argument_text_leere_eingabe_ist_leer():
    assert topics.argument_text([]) == ""
    assert topics.argument_text(None) == ""


def test_argument_text_verbindet_texte_mit_komma():
    text = topics.argument_text(["hochwertig", "nacht"])
    assert text == "premium, hochwertig, edel, nachts, künstliches Licht, Neonreflexe"


def test_argument_text_ignoriert_unbekannte_kennungen():
    assert topics.argument_text(["quatsch"]) == ""


def test_argument_text_haelt_katalogreihenfolge_ein():
    vorwaerts = topics.argument_text(["hochwertig", "morgen"])
    rueckwaerts = topics.argument_text(["morgen", "hochwertig"])
    assert vorwaerts == rueckwaerts
    assert vorwaerts.index("premium") < vorwaerts.index("Morgenlicht")


# ── Briefing bauen ───────────────────────────────────────────────────────────

def test_briefing_setzt_den_betreff_in_die_vorlage_ein():
    text = topics.briefing_bauen("gastro", "eine Trattoria", [])
    assert "eine Trattoria" in text
    assert "{betreff}" not in text
    assert "Appetit" in text


def test_briefing_ohne_betreff_nutzt_den_ersatztext():
    text = topics.briefing_bauen("produkt", "   ", [])
    assert "dem angegebenen Thema" in text
    assert "  " not in text


def test_briefing_unbekanntes_thema_gibt_den_betreff_zurueck():
    assert topics.briefing_bauen("unbekannt", "  Ein Thema  ", []) == "Ein Thema"
    assert topics.briefing_bauen("unbekannt", "", []) == ""


def test_briefing_haengt_zusatzfelder_und_anmutung_an():
    text = topics.briefing_bauen(
        "handwerk", "einen Elektrobetrieb", ["ruhig"],
        {"zielgruppe": " Hausbesitzer ", "botschaft": "Photovoltaik lohnt sich"},
    )
    assert "Zielgruppe: Hausbesitzer." in text
    assert "Kernbotschaft: Photovoltaik lohnt sich." in text
    assert "Gewünschte Anmutung: ruhig, entspannt, gelassen." in text


def test_briefing_ohne_argumente_und_zusatz_bleibt_schlicht():
    text = topics.briefing_bauen("marke", "ein Familienunternehmen", [], None)
    assert "Gewünschte Anmutung" not in text
    assert "Zielgruppe" not in text
    assert "Kernbotschaft" not in text
    assert text == text.strip()
