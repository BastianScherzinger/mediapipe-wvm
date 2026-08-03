"""Tests für Auftragsspeicher, Ablaufsteuerung und Bibliothek."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, errors, jobstore, library, media, pipeline  # noqa: E402


@pytest.fixture
def eigene_datenbank(tmp_path, monkeypatch):
    """Eigene Datenbank je Test — sonst schreiben Tests in den echten Bestand."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    jobstore.einrichten()
    yield tmp_path


@pytest.fixture
def eigener_ausgabeordner(tmp_path, monkeypatch):
    ordner = tmp_path / "output"
    ordner.mkdir()
    monkeypatch.setattr(config, "OUTPUT_DIR", ordner)
    return ordner


# ── Einstellungen prüfen ─────────────────────────────────────────────────────

def test_briefing_ist_pflicht():
    with pytest.raises(errors.EingabeFehler):
        pipeline.einstellungen_pruefen({})
    with pytest.raises(errors.EingabeFehler):
        pipeline.einstellungen_pruefen({"briefing": "ab"})


def test_unbekanntes_modell_faellt_auf_die_vorgabe_zurueck():
    e = pipeline.einstellungen_pruefen({"briefing": "Ein Test",
                                        "videomodell": "erfunden/modell"})
    assert e.videomodell == config.VIDEO_MODEL


def test_dauer_wird_dem_modell_angepasst():
    e = pipeline.einstellungen_pruefen({
        "briefing": "Ein Test", "sekunden": 7,
        "videomodell": "kling-video/v2.6/pro/image-to-video"})
    assert e.sekunden == 5              # 7 gibt es bei diesem Modell nicht


def test_szenenzahl_wird_begrenzt():
    e = pipeline.einstellungen_pruefen({"briefing": "Ein Test", "szenen": 9999})
    assert e.szenen <= config.MAX_SCENES
    e = pipeline.einstellungen_pruefen({"briefing": "Ein Test", "szenen": 0})
    assert e.szenen == 1


def test_unsinniges_seitenverhaeltnis_wird_ersetzt():
    e = pipeline.einstellungen_pruefen({"briefing": "Test", "seitenverhaeltnis": "42:7"})
    assert e.seitenverhaeltnis == "16:9"


def test_unbekannte_formate_werden_verworfen():
    e = pipeline.einstellungen_pruefen({"briefing": "Test",
                                        "formate": ["hoch", "quatsch", "gif"]})
    assert set(e.formate) == {"hoch", "gif"}


def test_ueberlanges_briefing_wird_gekuerzt():
    e = pipeline.einstellungen_pruefen({"briefing": "x" * 99999})
    assert len(e.briefing) <= config.MAX_BRIEFING_CHARS


# ── Auftragsspeicher ─────────────────────────────────────────────────────────

def test_auftrag_anlegen_und_wiederfinden(eigene_datenbank):
    auftrag = jobstore.anlegen("Ein Briefing", {"szenen": 3})
    geladen = jobstore.holen(auftrag.id)
    assert geladen is not None
    assert geladen.briefing == "Ein Briefing"
    assert geladen.einstellungen["szenen"] == 3
    assert geladen.zustand == jobstore.WARTEND


def test_woerterbuecher_ueberleben_das_speichern(eigene_datenbank):
    auftrag = jobstore.anlegen("Test", {})
    jobstore.aktualisieren(auftrag.id, drehbuch={"szenen": [{"nr": 1, "text": "ä ö ü"}]})
    geladen = jobstore.holen(auftrag.id)
    assert geladen.drehbuch["szenen"][0]["text"] == "ä ö ü"


def test_unbekannte_felder_werden_ignoriert(eigene_datenbank):
    """Schutz gegen versehentliches Überschreiben — nur bekannte Spalten sind änderbar."""
    auftrag = jobstore.anlegen("Test", {})
    jobstore.aktualisieren(auftrag.id, id="gekapert", angelegt=0)
    assert jobstore.holen(auftrag.id) is not None
    assert jobstore.holen("gekapert") is None


def test_laufende_auftraege_werden_beim_start_bereinigt(eigene_datenbank):
    """Ein Auftrag, der beim Beenden lief, kann nicht weiterlaufen — der Faden ist weg.
    Ohne diese Bereinigung würde er das Dashboard für immer blockieren."""
    auftrag = jobstore.anlegen("Test", {})
    jobstore.aktualisieren(auftrag.id, zustand=jobstore.LAEUFT)
    jobstore.einrichten()                       # entspricht einem Programmneustart
    geladen = jobstore.holen(auftrag.id)
    assert geladen.zustand == jobstore.ABGEBROCHEN
    assert "unterbrochen" in geladen.fehler["meldung"]


def test_liste_zeigt_das_neueste_zuerst(eigene_datenbank):
    erster = jobstore.anlegen("alt", {})
    time.sleep(0.01)
    zweiter = jobstore.anlegen("neu", {})
    liste = jobstore.liste()
    assert liste[0].id == zweiter.id
    assert liste[1].id == erster.id


def test_nur_laufende_filtern(eigene_datenbank):
    fertig = jobstore.anlegen("fertig", {})
    jobstore.aktualisieren(fertig.id, zustand=jobstore.FERTIG)
    offen = jobstore.anlegen("offen", {})
    laufende = jobstore.liste(nur_laufende=True)
    assert [a.id for a in laufende] == [offen.id]
    assert jobstore.laufender().id == offen.id


def test_aufraeumen_behaelt_die_neuesten(eigene_datenbank):
    for i in range(10):
        jobstore.anlegen(f"Auftrag {i}", {})
    entfernt = jobstore.aufraeumen(behalten=3)
    assert entfernt == 7
    assert len(jobstore.liste()) == 3


def test_ordnername_enthaelt_datum_und_kennung(eigene_datenbank, eigener_ausgabeordner):
    auftrag = jobstore.anlegen("Test", {})
    ordner = jobstore.ordner_fuer(auftrag, "mein_video")
    assert ordner.exists()
    assert "mein_video" in ordner.name
    assert auftrag.id[:6] in ordner.name


# ── Doppelstart-Sperre ───────────────────────────────────────────────────────

def test_zweiter_auftrag_wird_abgewiesen(eigene_datenbank, monkeypatch):
    """Zwei gleichzeitige Aufträge würden doppelt Guthaben kosten und sich um dieselben
    Dateien streiten."""
    import threading

    blockade = threading.Event()

    def langsam(*_a, **_k):
        blockade.wait(timeout=5)

    monkeypatch.setattr(pipeline, "_bearbeiten", langsam)
    try:
        pipeline.starten({"briefing": "Der erste Auftrag"})
        with pytest.raises(errors.EingabeFehler) as info:
            pipeline.starten({"briefing": "Der zweite Auftrag"})
        assert "bereits ein Auftrag" in info.value.meldung
    finally:
        blockade.set()
        time.sleep(0.1)
        pipeline._aktuell = None


def test_abbruch_ohne_laufenden_auftrag_ist_harmlos():
    pipeline._aktuell = None
    assert pipeline.abbrechen() is False


# ── Bibliothek: Pfadsicherheit ───────────────────────────────────────────────

@pytest.mark.parametrize("boese", [
    "../../../Windows/System32/drivers/etc/hosts",
    "C:/Windows/win.ini",
    "/etc/passwd",
    "a/../../../geheim.txt",
    "..\\..\\..\\x.txt",
    "....//....//x",
])
def test_ausbruch_aus_dem_ausgabeordner_wird_verhindert(boese, eigener_ausgabeordner):
    try:
        ziel = library.sicherer_pfad(boese)
    except errors.EingabeFehler:
        return                                   # abgewiesen — richtig
    # Falls nicht abgewiesen, muss das Ergebnis trotzdem im Ausgabeordner liegen.
    wurzel = config.OUTPUT_DIR.resolve()
    assert wurzel in ziel.parents or ziel == wurzel


def test_leerer_pfad_wird_abgelehnt():
    for leer in ("", "   ", None):
        with pytest.raises(errors.EingabeFehler):
            library.sicherer_pfad(leer)


def test_gueltiger_pfad_geht_durch(eigener_ausgabeordner):
    ziel = library.sicherer_pfad("2026-08-03_test_abc123/film.mp4")
    assert ziel.name == "film.mp4"
    assert config.OUTPUT_DIR.resolve() in ziel.parents


def test_web_pfad_verweigert_dateien_von_aussen(eigener_ausgabeordner):
    assert library.web_pfad("C:/Windows/win.ini") == ""
    assert library.web_pfad(None) == ""
    drin = config.OUTPUT_DIR / "ordner" / "film.mp4"
    assert library.web_pfad(drin) == "ordner/film.mp4"


# ── Bibliothek: Bestand ──────────────────────────────────────────────────────

def test_leere_bibliothek(eigener_ausgabeordner):
    assert library.uebersicht()["anzahl"] == 0


def test_ordner_ohne_film_wird_uebergangen(eigener_ausgabeordner):
    (config.OUTPUT_DIR / "leer").mkdir()
    assert library.eintrag(config.OUTPUT_DIR / "leer") is None
    assert library.uebersicht()["anzahl"] == 0


def test_eintrag_nennt_fehlende_fassungen(eigener_ausgabeordner):
    ordner = config.OUTPUT_DIR / "2026-08-03_test_abc"
    ordner.mkdir()
    (ordner / "film.mp4").write_bytes(b"x" * 5000)
    library.begleitzettel_schreiben(ordner, {
        "titel": "Mein Video",
        "ergebnis": {"dauer": 12.5, "breite": 1920, "hoehe": 1080}})
    (ordner / "film_hoch.mp4").write_bytes(b"x" * 5000)

    daten = library.eintrag(ordner)
    assert daten["titel"] == "Mein Video"
    assert daten["dauer"] == 12.5
    assert "hoch" in daten["fassungen"]
    fehlend = {f["kennung"] for f in daten["fehlende"]}
    assert "quadrat" in fehlend and "breit" in fehlend
    assert "poster" not in fehlend               # das Vorschaubild ist kein Zielformat


def test_zu_kleine_datei_gilt_nicht_als_fassung(eigener_ausgabeordner):
    ordner = config.OUTPUT_DIR / "test2"
    ordner.mkdir()
    (ordner / "film.mp4").write_bytes(b"x" * 5000)
    (ordner / "film_hoch.mp4").write_bytes(b"x" * 10)      # angefangen, nicht fertig
    assert "hoch" not in library.eintrag(ordner)["fassungen"]


def test_begleitzettel_uebersteht_beschaedigung(eigener_ausgabeordner):
    ordner = config.OUTPUT_DIR / "test3"
    ordner.mkdir()
    (ordner / "auftrag.json").write_text("{kaputt", encoding="utf-8")
    assert library.begleitzettel_lesen(ordner) == {}


def test_format_nachziehen_prueft_den_ordner(eigener_ausgabeordner):
    with pytest.raises(errors.EingabeFehler):
        library.format_nachziehen("gibtsnicht", "hoch")
    with pytest.raises(errors.EingabeFehler):
        library.format_nachziehen("gibtsnicht", "quatschformat")


def test_ausgabeordner_selbst_kann_nicht_geloescht_werden(eigener_ausgabeordner):
    with pytest.raises(errors.EingabeFehler):
        library.video_loeschen("")
    with pytest.raises(errors.EingabeFehler):
        library.video_loeschen(".")


def test_umbenennen_aendert_nur_den_titel(eigener_ausgabeordner):
    ordner = config.OUTPUT_DIR / "test4"
    ordner.mkdir()
    (ordner / "film.mp4").write_bytes(b"x" * 5000)
    library.video_umbenennen("test4", "Neuer Titel")
    assert ordner.exists()                        # Ordner bleibt, Verweise halten
    assert library.eintrag(ordner)["titel"] == "Neuer Titel"


def test_leerer_titel_wird_abgelehnt(eigener_ausgabeordner):
    ordner = config.OUTPUT_DIR / "test5"
    ordner.mkdir()
    (ordner / "film.mp4").write_bytes(b"x" * 5000)
    with pytest.raises(errors.EingabeFehler):
        library.video_umbenennen("test5", "   ")


# ── Blöcke ───────────────────────────────────────────────────────────────────

def test_bloecke_sind_die_fuenf_aus_der_oberflaeche():
    assert jobstore.BLOECKE == ("briefing", "claude", "bild", "video", "ausgabe")
    assert all(b in jobstore.BLOCKNAMEN for b in jobstore.BLOECKE)


def test_formate_der_bibliothek_kennt_die_pipeline():
    """Was die Pipeline gleich miterzeugen kann, muss die Bibliothek auch nachziehen
    können — sonst gäbe es Formate, die nur auf einem Weg entstehen."""
    for kennung in media.STANDARDFORMATE:
        assert kennung in media.FORMATE
