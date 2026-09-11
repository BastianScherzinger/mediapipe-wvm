"""Tests für „Webseite → TikTok“: Link prüfen, Konzept, Schnitt und der ganze Auftrag.

Ohne Netz: Die Aufnahme wird durch Bilder ersetzt, die Pillow hier zeichnet, und das
Sprachmodell durch eine feste Antwort. Echt sind Einstellungsprüfung, Konzeptprüfung,
das Motion-Design mit ffmpeg, die Musik, die Ablaufsteuerung und die Bibliothek.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import (config, errors, jobstore, library, media, pipeline,  # noqa: E402
                 webaufnahme, webwerbung, werbeschnitt)

HAT_FFMPEG = bool(config.ffmpeg_pfad())


# ── Link prüfen ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("roh, erwartet", [
    ("meinbetrieb.de", "https://meinbetrieb.de/"),
    ("  https://www.Beispiel.de/leistungen  ", "https://www.Beispiel.de/leistungen"),
    ("http://beispiel.de", "http://beispiel.de/"),
])
def test_adresse_wird_vervollstaendigt(roh, erwartet):
    assert webaufnahme.adresse_normieren(roh) == erwartet


@pytest.mark.parametrize("roh", ["", "   ", "ftp://beispiel.de", "javascript:alert(1)",
                                 "nurwort", "https://"])
def test_unsinnige_adressen_werden_abgelehnt(roh):
    with pytest.raises(errors.EingabeFehler):
        webaufnahme.adresse_normieren(roh)


@pytest.mark.parametrize("adresse", ["http://localhost:7788/", "http://127.0.0.1/",
                                     "http://192.168.1.10/", "http://10.0.0.5/admin"])
def test_adressen_ins_eigene_netz_werden_abgelehnt(adresse):
    """Ein Werkzeug, das lokale Dienste aufruft und fotografiert, gehört nicht auf einen
    Arbeitsrechner — auch nicht aus Versehen."""
    with pytest.raises(errors.EingabeFehler):
        webaufnahme.adresse_pruefen(adresse)


# ── Konzept ──────────────────────────────────────────────────────────────────

TEXTE = {
    "titel": "Elektro Muster GmbH | Photovoltaik in Mannheim",
    "beschreibung": "Ihr Fachbetrieb für Photovoltaik, Speicher und Wallboxen in Mannheim.",
    "marke": "",
    "ueberschriften": ["Menü", "Solarstrom vom eigenen Dach", "Planung aus einer Hand",
                       "Montage in zwei Tagen", "Förderung inklusive", "Kontakt"],
    "knoepfe": ["Menü", "Impressum", "Kostenlos beraten lassen", "Mehr erfahren"],
    "farbe": "rgb(242, 140, 40)",
}


def test_konzept_ohne_sprachmodell_nutzt_die_seite():
    konzept = webwerbung.konzept_selbst(TEXTE, "elektro-muster.de", {})
    assert konzept["marke"] == "Elektro Muster GmbH"
    assert konzept["hook"] == "Solarstrom vom eigenen Dach"
    assert len(konzept["vorteile"]) == 3
    assert "Menü" not in konzept["vorteile"]
    assert konzept["cta"] == "Kostenlos beraten lassen"


def test_vorgegebene_aufforderung_hat_vorrang():
    konzept = webwerbung.konzept_selbst(TEXTE, "x.de", {"cta": "Jetzt anrufen"})
    assert konzept["cta"] == "Jetzt anrufen"


def test_konzept_des_sprachmodells_wird_gekuerzt(monkeypatch):
    antwort = {"marke": "Elektro Muster", "hook": "Warum zahlst du noch deinen Strom "
               "komplett selbst, obwohl die Sonne scheint?",
               "vorteile": ["Planung", "Montage in nur zwei Tagen ohne Stress", ""],
               "cta": "Beratung", "posting": "Text", "hashtags": ["#solar", "pv"]}
    monkeypatch.setattr(webwerbung.llm, "erzeuge",
                        lambda *_a, **_k: webwerbung.llm.Antwort(json.dumps(antwort),
                                                                 "cli", "t", 0.1))
    aufnahme = webaufnahme.Aufnahme(url="https://x.de/", host="x.de", texte=TEXTE)
    konzept = webwerbung.konzept_erstellen(aufnahme, {})
    assert len(konzept["hook"].split()) <= 8
    assert len(konzept["vorteile"]) == 3 and all(konzept["vorteile"])
    assert len(konzept["vorteile"][1].split()) <= 5
    assert konzept["hashtags"] == ["solar", "pv"]


def test_ohne_sprachmodell_bleibt_ein_konzept(monkeypatch):
    def kaputt(*_a, **_k):
        raise errors.AnbieterFehler("kein Modell")

    monkeypatch.setattr(webwerbung.llm, "erzeuge", kaputt)
    aufnahme = webaufnahme.Aufnahme(url="https://x.de/", host="x.de", texte=TEXTE)
    assert webwerbung.konzept_erstellen(aufnahme, {})["quelle"] == "selbst erstellt"


@pytest.mark.parametrize("roh, erwartet", [
    ("rgb(242, 140, 40)", (242, 140, 40)), ("#1E88E5", (30, 136, 229)),
    ("rgb(10, 10, 10)", None), ("#ffffff", None), ("rgb(128,128,128)", None), ("", None)])
def test_nur_brauchbare_markenfarben(roh, erwartet):
    assert webwerbung.farbe_lesen(roh) == erwartet


def test_einstellungen_fuer_webseiten():
    e = pipeline.einstellungen_pruefen({"art": "webseite", "url": "meinbetrieb.de",
                                        "dauer": 17, "stil": "quatsch", "ki_szene": True,
                                        "formate": ["hoch", "quadrat"]})
    assert e.art == "webseite"
    assert e.webseite["url"] == "https://meinbetrieb.de/"
    assert e.webseite["dauer"] in webwerbung.DAUERN
    assert e.webseite["stil"] == "energisch"
    assert e.seitenverhaeltnis == "9:16"
    assert e.formate == ("quadrat",), "9:16 ist der Film selbst"
    # Wiederholen: aus den gespeicherten Einstellungen muss derselbe Auftrag entstehen.
    wieder = pipeline.einstellungen_pruefen(e.als_dict())
    assert wieder.webseite == e.webseite


def test_webseiten_bloecke_passen_zur_oberflaeche():
    assert len(webwerbung.BLOECKE) == 5
    assert all(b in webwerbung.BLOCKNAMEN for b in webwerbung.BLOECKE)


# ── Schnitt und ganzer Auftrag ───────────────────────────────────────────────

def _falsche_aufnahme(ordner: Path) -> webaufnahme.Aufnahme:
    """Eine „Webseite“ aus Pillow: farbige Abschnitte mit Text."""
    ordner.mkdir(parents=True, exist_ok=True)

    def seite(breite, hoehe, name):
        bild = Image.new("RGB", (breite, hoehe), (245, 245, 240))
        z = ImageDraw.Draw(bild)
        for i, y in enumerate(range(0, hoehe, 420)):
            z.rectangle((0, y, breite, y + 380), fill=((40 + i * 37) % 255, 110, 160))
            z.text((60, y + 60), f"Abschnitt {i + 1}", fill=(255, 255, 255))
        pfad = ordner / name
        bild.save(pfad)
        return pfad

    return webaufnahme.Aufnahme(
        url="https://elektro-muster.de/", host="elektro-muster.de",
        start_mobil=seite(1080, 1920, "start.png"),
        streifen_mobil=seite(1080, 5760, "streifen.png"),
        desktop=seite(1440, 900, "desktop.png"), texte=dict(TEXTE))


@pytest.mark.langsam
@pytest.mark.skipif(not HAT_FFMPEG, reason="kein ffmpeg")
def test_werbeschnitt_ergibt_ein_tiktok_video(tmp_path):
    aufnahme = _falsche_aufnahme(tmp_path / "aufnahme")
    konzept = werbeschnitt.Konzept(marke="Elektro Muster", hook="Strom vom eigenen Dach?",
                                   vorteile=["Planung aus einer Hand", "Montage in 2 Tagen",
                                             "Förderung inklusive"],
                                   cta="Kostenlos beraten lassen",
                                   host="elektro-muster.de")
    ziel = tmp_path / "film.mp4"
    anteile = []
    werbeschnitt.rendern(aufnahme, konzept, ziel, dauer=15, melden=anteile.append)
    angaben = media.pruefe_video(ziel)
    assert (angaben.breite, angaben.hoehe) == (1080, 1920)
    assert 13.5 < angaben.dauer < 16.5
    assert angaben.hat_ton, "die Musik muss im Video sein"
    assert anteile and max(anteile) == 1.0


@pytest.mark.langsam
@pytest.mark.skipif(not HAT_FFMPEG, reason="kein ffmpeg")
def test_ki_szene_wird_eingefuegt(tmp_path):
    """Die Gegenprüfung vermutete: Rohbilder ohne Pixelseitenverhältnis und die KI-Szene
    mit `setsar=1` passen im concat-Filter nicht zusammen — und der bezahlte Clip kippt
    den ganzen Auftrag. Hier wird genau dieser Weg gerendert."""
    aufnahme = _falsche_aufnahme(tmp_path / "aufnahme")
    ki = media.platzhalter_clip(tmp_path / "ki.mp4", sekunden=2, breite=720, hoehe=1280)
    konzept = werbeschnitt.Konzept(marke="Test", hook="Ein Test mit KI?",
                                   vorteile=["Eins", "Zwei", "Drei"], cta="Los",
                                   host="test.de")
    ziel = tmp_path / "film.mp4"
    werbeschnitt.rendern(aufnahme, konzept, ziel, dauer=15, ki_clip=ki)
    angaben = media.pruefe_video(ziel)
    assert (angaben.breite, angaben.hoehe) == (1080, 1920)
    assert angaben.dauer > 15.5, "die KI-Szene muss im Film sein"


def test_text_wird_nicht_abgeschnitten():
    """„Python.org“ stand im ersten Entwurf als „Pvthon.ora“ im Bild — die Unterlängen
    fehlten. Das Wortbild muss so hoch sein wie Ober- und Unterlänge zusammen."""
    worte = werbeschnitt._worte_setzen("Python gyp", "schwarz", 110, 900)
    for wort in worte:
        unten = wort.bild.getchannel("A").getbbox()[3]
        assert unten < wort.bild.height - 1, "die Unterlänge reicht bis an den Rand"


def test_musik_hat_die_richtige_laenge(tmp_path):
    import wave
    pfad = werbeschnitt.musik_schreiben(tmp_path / "m.wav", 3.0, "edel", [1.0, 2.0])
    with wave.open(str(pfad)) as datei:
        assert abs(datei.getnframes() / datei.getframerate() - 3.0) < 0.01


@pytest.mark.langsam
@pytest.mark.skipif(not HAT_FFMPEG, reason="kein ffmpeg")
def test_webseiten_auftrag_von_link_bis_bibliothek(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.DATA_DIR.mkdir(parents=True)
    config.OUTPUT_DIR.mkdir(parents=True)
    jobstore.einrichten()
    pipeline._aktuell = None

    pruefung = {"url": "https://elektro-muster.de/", "host": "elektro-muster.de",
                "titel": "Elektro Muster", "dauer_ms": 12}
    monkeypatch.setattr(webaufnahme, "adresse_pruefen", lambda _u: dict(pruefung))
    monkeypatch.setattr(webaufnahme, "aufnehmen",
                        lambda url, ordner, **_k: _falsche_aufnahme(Path(ordner)))

    def kein_modell(*_a, **_k):
        raise errors.AnbieterFehler("kein Modell im Test")

    monkeypatch.setattr(webwerbung.llm, "erzeuge", kein_modell)

    auftrag, sofort = pipeline.einreihen({"art": "webseite", "url": "elektro-muster.de",
                                          "dauer": 15, "stil": "freundlich"})
    assert sofort
    ende = time.monotonic() + 240
    while time.monotonic() < ende:
        fertig = jobstore.holen(auftrag.id)
        if not fertig.laeuft_noch:
            break
        time.sleep(0.3)
    assert fertig.zustand == jobstore.FERTIG, fertig.fehler
    ordner = Path(fertig.ergebnis["ordner"])
    eintrag = library.eintrag(ordner)
    assert eintrag["hoehe"] > eintrag["breite"]
    assert eintrag["posting"]["text"]
    assert (ordner / "film_poster.jpg").exists()
    assert library.begleitzettel_lesen(ordner)["art"] == "webseite"
