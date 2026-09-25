"""Tests für die Prompt-Schmiede — ohne Netz, mit vorgegebenen Modellantworten."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import errors, llm, promptsmith  # noqa: E402

SAUBER = {
    "titel": "Bäckerei am Morgen",
    "dateiname": "baeckerei_morgen",
    "zusammenfassung": "Ein Morgen in der Backstube.",
    "stil": "warmes Morgenlicht",
    "szenen": [
        {"beschreibung": "Teig wird geknetet",
         "bild_prompt": "Documentary photograph of hands kneading dough, warm light. "
                        "no text, no logos, no watermark",
         "video_prompt": "Slow push-in, one continuous shot"},
        {"beschreibung": "Brot kommt aus dem Ofen",
         "bild_prompt": "Bread pulled from a stone oven, ember glow. "
                        "no text, no logos, no watermark",
         "video_prompt": "Lateral track, one continuous shot"},
    ],
}


def antwort_mit(inhalt: str, weg: str = "cli") -> llm.Antwort:
    return llm.Antwort(text=inhalt, weg=weg, modell="testmodell", dauer=1.0)


@pytest.fixture
def modell_sagt(monkeypatch):
    """Ersetzt das Sprachmodell durch eine feste Antwort."""
    def setzen(*antworten: str):
        rest = list(antworten)

        def gefaelscht(_system, _auftrag, **_kw):
            return antwort_mit(rest.pop(0) if len(rest) > 1 else rest[0])

        monkeypatch.setattr(llm, "erzeuge", gefaelscht)
    return setzen


# ── JSON aus einer Antwort holen ─────────────────────────────────────────────

def test_reines_json():
    assert promptsmith._json_finden('{"a": 1}') == {"a": 1}


def test_json_in_code_auszeichnung():
    assert promptsmith._json_finden('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_mit_hoeflichkeit_davor():
    assert promptsmith._json_finden('Gern! Hier das JSON:\n{"a": 1}\nViel Erfolg!') == {"a": 1}


def test_ueberzaehliges_komma_wird_repariert():
    assert promptsmith._json_finden('{"a": 1, "b": [1, 2,],}') == {"a": 1, "b": [1, 2]}


def test_unbrauchbarer_text_gibt_nichts():
    assert promptsmith._json_finden("Das kann ich leider nicht.") is None
    assert promptsmith._json_finden("") is None


# ── Fremde Feldnamen ─────────────────────────────────────────────────────────

def test_claude_cli_schema_wird_verstanden():
    """Genau die Antwortform, die die Claude-CLI am 03.08.2026 tatsächlich lieferte:
    Kopfdaten unter „projekt", Szenen mit „prompt"/„kamera"/„bewegung_im_bild".
    Ohne Alias-Erkennung landete das im Notbehelf."""
    daten = {
        "projekt": {"titel": "Handwerksbäckerei", "stilrichtung": "dokumentarisch"},
        "szenen": [
            {"nummer": 1, "titel": "Die frühe Stunde",
             "prompt": "A bakery before sunrise, golden light through the window",
             "kamera": "Slow dolly forward, 35mm",
             "bewegung_im_bild": "Flour dust drifting through the light"},
        ],
        "montage": {"uebergaenge": "weich"},
    }
    drehbuch = promptsmith._zu_drehbuch(daten, szenen_soll=1, dauer_soll=5,
                                        briefing="Bäckerei", quelle="Test")
    assert len(drehbuch.szenen) == 1
    szene = drehbuch.szenen[0]
    assert "bakery before sunrise" in szene.bild_prompt
    assert "dolly forward" in szene.video_prompt          # aus „kamera" gebaut
    assert "Flour dust" in szene.video_prompt             # plus „bewegung_im_bild"
    assert drehbuch.titel == "Handwerksbäckerei"          # eine Ebene tiefer gefunden
    assert drehbuch.stil == "dokumentarisch"


def test_englische_feldnamen_gehen_auch():
    daten = {"title": "Test", "scenes": [
        {"description": "x", "image_prompt": "A cat on a wall",
         "motion_prompt": "Slow pan"}]}
    drehbuch = promptsmith._zu_drehbuch(daten, szenen_soll=1, dauer_soll=5,
                                        briefing="b", quelle="T")
    assert drehbuch.szenen[0].bild_prompt.startswith("A cat")
    assert drehbuch.szenen[0].video_prompt == "Slow pan"


def test_reine_textliste_als_szenen():
    daten = {"szenen": ["A red car on a mountain road"]}
    drehbuch = promptsmith._zu_drehbuch(daten, szenen_soll=1, dauer_soll=5,
                                        briefing="b", quelle="T")
    assert "red car" in drehbuch.szenen[0].bild_prompt
    assert drehbuch.szenen[0].video_prompt                # sinnvoll ergänzt


def test_ohne_szenen_wird_abgelehnt():
    with pytest.raises(errors.AnbieterFehler):
        promptsmith._zu_drehbuch({"titel": "x"}, szenen_soll=1, dauer_soll=5,
                                 briefing="b", quelle="T")


# ── Pflichtangaben ergänzen ──────────────────────────────────────────────────

def test_textverbot_wird_immer_angehaengt():
    daten = {"szenen": [{"bild_prompt": "A dog", "video_prompt": "Pan"}]}
    drehbuch = promptsmith._zu_drehbuch(daten, szenen_soll=1, dauer_soll=5,
                                        briefing="b", quelle="T")
    assert "no text" in drehbuch.szenen[0].bild_prompt


def test_fehlender_bildprompt_wird_aus_bewegung_gebaut():
    daten = {"szenen": [{"video_prompt": "Slow orbit around a vintage car"}]}
    drehbuch = promptsmith._zu_drehbuch(daten, szenen_soll=1, dauer_soll=5,
                                        briefing="b", quelle="T")
    assert "vintage car" in drehbuch.szenen[0].bild_prompt


def test_zu_wenige_szenen_werden_ergaenzt(modell_sagt):
    """Der Kunde hat vier Szenen bestellt — er bekommt vier, auch wenn das Modell
    nur zwei liefert."""
    modell_sagt(json.dumps(SAUBER))
    drehbuch = promptsmith.drehbuch_erstellen("Bäckerei", szenen=4, sekunden_je_szene=5)
    assert len(drehbuch.szenen) == 4
    assert [s.nr for s in drehbuch.szenen] == [1, 2, 3, 4]
    assert drehbuch.gesamtdauer == 20


def test_zu_viele_szenen_werden_gekappt():
    viele = {"szenen": [{"bild_prompt": f"Scene {i}", "video_prompt": "Pan"}
                        for i in range(20)]}
    drehbuch = promptsmith._zu_drehbuch(viele, szenen_soll=3, dauer_soll=5,
                                        briefing="b", quelle="T")
    assert len(drehbuch.szenen) == 3


# ── Dateinamen ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("eingabe,erwartet", [
    ("Bäckerei am Morgen", "baeckerei_am_morgen"),
    ("Test / mit \\ Pfad", "test_mit_pfad"),
    ("../../etc/passwd", "etc_passwd"),
    ("   ", "video"),
    ("CON", "con"),
    ("Grüße aus Köln!!!", "gruesse_aus_koeln"),
])
def test_dateiname_wird_unbedenklich(eingabe, erwartet):
    assert promptsmith._saeubere_dateinamen(eingabe) == erwartet


def test_dateiname_enthaelt_nie_pfadtrenner():
    for boese in ("../..", "C:\\Windows\\System32", "a/b/c", "..\\..\\x"):
        ergebnis = promptsmith._saeubere_dateinamen(boese)
        assert "/" not in ergebnis and "\\" not in ergebnis and ".." not in ergebnis


def test_dateiname_bleibt_kurz():
    assert len(promptsmith._saeubere_dateinamen("wort " * 100)) <= 48


# ── Gesamtablauf ─────────────────────────────────────────────────────────────

def test_glatter_durchlauf(modell_sagt):
    modell_sagt(json.dumps(SAUBER))
    drehbuch = promptsmith.drehbuch_erstellen("Bäckerei", szenen=2, sekunden_je_szene=5)
    assert not drehbuch.notbehelf
    assert drehbuch.titel == "Bäckerei am Morgen"
    assert len(drehbuch.szenen) == 2


def test_unbrauchbare_antwort_fuehrt_zum_nachfassen(modell_sagt):
    modell_sagt("Tut mir leid, das geht nicht.", json.dumps(SAUBER))
    drehbuch = promptsmith.drehbuch_erstellen("Bäckerei", szenen=2, sekunden_je_szene=5)
    assert not drehbuch.notbehelf                 # der zweite Anlauf hat geklappt
    assert len(drehbuch.szenen) == 2


def test_notbehelf_wenn_gar_nichts_geht(monkeypatch):
    def faellt_aus(*_a, **_k):
        raise errors.AnbieterFehler("alles tot")
    monkeypatch.setattr(llm, "erzeuge", faellt_aus)

    drehbuch = promptsmith.drehbuch_erstellen("Ein rotes Auto", szenen=3,
                                              sekunden_je_szene=5)
    assert drehbuch.notbehelf
    assert len(drehbuch.szenen) == 3
    assert all(s.bild_prompt and s.video_prompt for s in drehbuch.szenen)
    # Die Kameraführung muss sich unterscheiden, sonst wirken alle Szenen gleich.
    assert len({s.video_prompt for s in drehbuch.szenen}) == 3


def test_notbehelf_uebernimmt_das_briefing(monkeypatch):
    monkeypatch.setattr(llm, "erzeuge",
                        lambda *_a, **_k: (_ for _ in ()).throw(errors.NetzFehler("weg")))
    drehbuch = promptsmith.drehbuch_erstellen("ein blaues Motorrad", szenen=1,
                                              sekunden_je_szene=5)
    assert "blaues Motorrad" in drehbuch.szenen[0].bild_prompt


def test_zu_kurzes_briefing_wird_abgelehnt():
    with pytest.raises(errors.EingabeFehler):
        promptsmith.drehbuch_erstellen("ab", szenen=1)


def test_szenenzahl_wird_begrenzt(modell_sagt):
    modell_sagt(json.dumps(SAUBER))
    drehbuch = promptsmith.drehbuch_erstellen("Bäckerei", szenen=999, sekunden_je_szene=5)
    assert len(drehbuch.szenen) <= 30


def test_dauer_wird_auf_modellwert_gebracht(modell_sagt):
    modell_sagt(json.dumps(SAUBER))
    drehbuch = promptsmith.drehbuch_erstellen(
        "Bäckerei", szenen=1, sekunden_je_szene=7,
        modell="kling-video/v2.6/pro/image-to-video")
    assert drehbuch.szenen[0].dauer == 5            # 7 gibt es dort nicht


# ── Wörtlicher Prompt ────────────────────────────────────────────────────────

def test_woertlicher_prompt_geht_nicht_durchs_modell(monkeypatch):
    def darf_nicht(*_a, **_k):
        raise AssertionError("Bei 'wörtlich' darf kein Sprachmodell gefragt werden.")
    monkeypatch.setattr(llm, "erzeuge", darf_nicht)

    drehbuch = promptsmith.eigenen_prompt_woertlich("A lonely lighthouse at dusk",
                                                    sekunden=5)
    assert drehbuch.szenen[0].bild_prompt == "A lonely lighthouse at dusk"
    assert len(drehbuch.szenen) == 1


def test_woertlicher_prompt_braucht_inhalt():
    with pytest.raises(errors.EingabeFehler):
        promptsmith.eigenen_prompt_woertlich("x")


# ── Spracherkennung ──────────────────────────────────────────────────────────

def test_deutsche_prompts_werden_erkannt():
    assert promptsmith._wirkt_deutsch(
        "Eine Bäckerei mit der Sonne und dem Licht durch das Fenster")
    assert not promptsmith._wirkt_deutsch(
        "Documentary photograph of hands kneading dough in warm morning light")


# ── Hashtags in gespeicherten Drehbüchern ────────────────────────────────────

def test_gespeicherte_hashtags_als_zeichenkette_zerfallen_nicht():
    """`list("solar pv")` ergab früher Einzelbuchstaben als Hashtags."""
    daten = {"titel": "T", "szenen": [{"nr": 1, "bild_prompt": "A cat", "dauer": 5}],
             "hashtags": "#solar, #pv; mannheim"}
    drehbuch = promptsmith.drehbuch_aus_dict(daten)
    assert drehbuch.hashtags == ["solar", "pv", "mannheim"]


def test_gespeicherte_hashtags_ohne_liste_werden_verworfen():
    daten = {"szenen": [{"bild_prompt": "A cat"}], "hashtags": {"a": 1}}
    assert promptsmith.drehbuch_aus_dict(daten).hashtags == []
    daten["hashtags"] = ["solar", "pv"]
    assert promptsmith.drehbuch_aus_dict(daten).hashtags == ["solar", "pv"]
