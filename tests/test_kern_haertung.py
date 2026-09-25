"""Tests für die Härtung des Kerns (Durchsicht vom 25.09.2026).

Jeder Test hält einen Befund fest, der vorher im Code stand: ffmpeg, das an seiner
eigenen Fehlerausgabe erstickt; eine Montage, die ein halbes film.mp4 hinterlässt;
Anfragen mit falschen Typen, die als „Unerwarteter Fehler“ endeten; eine Warteschlange,
die sich überholen ließ; eine Wiederholungskette, die Bezahltes vergaß; ein Update, das
einen Prozess startete, der gar nicht laden konnte.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import (config, errors, jobstore, library, media, pipeline,  # noqa: E402
                 server, updater)

HAT_FFMPEG = bool(config.ffmpeg_pfad())


@pytest.fixture
def eigene_datenbank(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    jobstore.einrichten()
    pipeline._aktuell = None
    pipeline._schlange.clear()
    yield tmp_path
    pipeline._schlange.clear()
    laeuft = pipeline._aktuell
    if laeuft is not None:
        laeuft.abbruch.set()
        laeuft.faden.join(timeout=10)
    pipeline._aktuell = None


@pytest.fixture
def besucher(eigene_datenbank):
    anwendung = server.anwendung_bauen()
    anwendung.config.update(TESTING=True)
    with anwendung.test_client() as klient:
        yield klient


# ── ffmpeg ───────────────────────────────────────────────────────────────────

@pytest.mark.skipif(sys.platform == "win32", reason="Attrappe ist ein Shell-Skript")
def test_ffmpeg_erstickt_nicht_an_seiner_fehlerausgabe(tmp_path, monkeypatch):
    """Beschädigte Clips erzeugen seitenweise Dekodierfehler. Früher wurde stderr erst
    am Ende gelesen: ffmpeg blieb beim Schreiben hängen, und weder Abbruch noch
    Zeitlimit kamen je wieder dran."""
    falsch = tmp_path / "ffmpeg"
    falsch.write_text("#!/bin/sh\nhead -c 400000 /dev/zero | tr '\\0' 'x' >&2\nsleep 300\n",
                      encoding="utf-8")
    falsch.chmod(0o755)
    monkeypatch.setattr(config, "ffmpeg_pfad", lambda: str(falsch))
    abbruch = threading.Event()
    threading.Timer(1.0, abbruch.set).start()
    begonnen = time.monotonic()
    with pytest.raises(errors.AbbruchFehler):
        media._ffmpeg(["-i", "x"], beschreibung="Test", abbruch=abbruch)
    assert time.monotonic() - begonnen < 10


@pytest.mark.skipif(sys.platform == "win32", reason="Attrappe ist ein Shell-Skript")
def test_ffmpeg_fehlertext_kommt_trotz_viel_ausgabe_an(tmp_path, monkeypatch):
    falsch = tmp_path / "ffmpeg"
    falsch.write_text("#!/bin/sh\nhead -c 200000 /dev/zero | tr '\\0' 'x' >&2\n"
                      "echo 'Invalid data found' >&2\nexit 1\n", encoding="utf-8")
    falsch.chmod(0o755)
    monkeypatch.setattr(config, "ffmpeg_pfad", lambda: str(falsch))
    with pytest.raises(errors.VerarbeitungsFehler) as fehler:
        media._ffmpeg(["-i", "x"], beschreibung="Test")
    assert "Invalid data found" in fehler.value.hinweis


def test_ffmpeg_wartet_abbrechbar_auf_den_freien_platz(monkeypatch):
    """Belegt eine lange Formaterzeugung ffmpeg, muss „Abbrechen“ trotzdem wirken."""
    monkeypatch.setattr(config, "ffmpeg_pfad", lambda: "ffmpeg")
    media._ffmpeg_schlange.acquire()
    try:
        abbruch = threading.Event()
        threading.Timer(0.5, abbruch.set).start()
        with pytest.raises(errors.AbbruchFehler):
            media._ffmpeg(["-i", "x"], beschreibung="Test", abbruch=abbruch)
    finally:
        media._ffmpeg_schlange.release()


def _clip(ziel: Path, sekunden: int = 2) -> Path:
    ziel.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([config.ffmpeg_pfad(), "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"color=c=blue:s=320x180:d={sekunden}", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(ziel)], check=True, capture_output=True,
                   timeout=120)
    return ziel


@pytest.mark.langsam
@pytest.mark.skipif(not HAT_FFMPEG, reason="ohne ffmpeg nicht prüfbar")
def test_harte_montage_mit_apostroph_im_pfad(tmp_path):
    ordner = tmp_path / "O'Brien" / "output"
    clips = [_clip(ordner / "a.mp4"), _clip(ordner / "b.mp4")]
    film = media.montieren(clips, ordner / "film.mp4", weiche_uebergaenge=False)
    assert media.angaben(film).dauer >= 3


@pytest.mark.skipif(not HAT_FFMPEG, reason="ohne ffmpeg nicht prüfbar")
def test_gescheiterte_montage_hinterlaesst_keinen_halben_film(tmp_path, monkeypatch):
    clips = [_clip(tmp_path / "a.mp4"), _clip(tmp_path / "b.mp4")]

    def kaputt(_clips, ziel, **_k):
        Path(ziel).write_bytes(b"kein video")
    monkeypatch.setattr(media, "_hart_aneinander", kaputt)
    with pytest.raises(errors.StudioFehler):
        media.montieren(clips, tmp_path / "film.mp4", weiche_uebergaenge=False)
    assert not (tmp_path / "film.mp4").exists()


# ── Eingaben ─────────────────────────────────────────────────────────────────

def test_falsche_typen_werden_zu_vorgaben_nicht_zu_abstuerzen():
    e = pipeline.einstellungen_pruefen({"briefing": "Ein Test", "szenen": "drei",
                                        "sekunden": "5s", "formate": 5})
    assert e.szenen == 1 and e.sekunden >= 1 and e.formate == ()
    e = pipeline.einstellungen_pruefen({"briefing": "Ein Test", "formate": "hoch"})
    assert e.formate == ("hoch",)
    e = pipeline.einstellungen_pruefen({"briefing": "Ein Test", "formate": [["hoch"]]})
    assert e.formate == ()
    with pytest.raises(errors.EingabeFehler):
        pipeline.einstellungen_pruefen([1, 2])


def test_server_antwortet_auf_unsinn_mit_400(besucher):
    assert besucher.post("/api/auftrag", json=[1, 2]).status_code == 400
    antwort = besucher.post("/api/briefing", json={"argumente": 5, "thema": "werbung"})
    assert antwort.status_code == 200
    assert besucher.post("/api/bibliothek/loeschen",
                         json={"ordner": "a\x00b", "bestaetigt": True}).status_code == 400
    assert besucher.get("/medien/a%00b").status_code == 400


def test_http_fehler_behalten_ihren_code(besucher):
    antwort = besucher.put("/api/auftrag", json={})
    assert antwort.status_code == 405
    assert antwort.get_json()["ok"] is False


def test_kaputte_herkunft_wird_abgewiesen_nicht_abgestuerzt(besucher):
    antwort = besucher.post("/api/briefing", json={},
                            headers={"Origin": "http://127.0.0.1:abc"})
    assert antwort.status_code == 403


def test_lebenszeichen_nennt_den_start(besucher):
    daten = besucher.get("/api/lebt").get_json()
    assert daten["gestartet"] <= time.time()


# ── Aufträge und Warteschlange ───────────────────────────────────────────────

def test_laufender_auftrag_laesst_sich_nicht_loeschen(besucher, monkeypatch):
    auftrag = jobstore.anlegen("Ein Test", {"briefing": "Ein Test"})
    monkeypatch.setattr(pipeline, "laeuft_gerade", lambda: auftrag.id)
    assert besucher.delete(f"/api/auftrag/{auftrag.id}").status_code == 400
    assert jobstore.holen(auftrag.id) is not None


def test_abmelden_ist_waehrend_eines_auftrags_gesperrt(besucher, monkeypatch):
    monkeypatch.setattr(pipeline, "laeuft_gerade", lambda: "abc")
    assert besucher.post("/api/abo/abmelden").status_code == 400


def test_neustart_verwirft_keine_wartenden(besucher, monkeypatch):
    monkeypatch.setattr(pipeline, "warteschlange", lambda: [{"id": "x"}])
    aufgerufen = []
    monkeypatch.setattr(updater, "neu_starten", lambda *a, **k: aufgerufen.append(1))
    assert besucher.post("/api/neustart").status_code == 400
    assert not aufgerufen


def test_neuer_auftrag_ueberholt_keine_wartenden(eigene_datenbank, monkeypatch):
    """In der Lücke zwischen dem Ende eines Auftrags und dem Nachrücken darf ein neuer
    nicht an den Wartenden vorbei starten."""
    gestartet: list[str] = []

    def beginnen(auftrag_id, _e):
        gestartet.append(auftrag_id)
    monkeypatch.setattr(pipeline, "_lauf_beginnen", beginnen)

    wartend = jobstore.anlegen("Wartet schon", {"briefing": "Wartet schon"})
    pipeline._schlange.append((wartend.id, pipeline.einstellungen_pruefen(
        {"briefing": "Wartet schon"})))

    neu, sofort = pipeline.einreihen({"briefing": "Kommt gerade erst"})
    assert gestartet == [wartend.id], "der Wartende muss zuerst drankommen"
    assert sofort is False
    assert [k for k, _ in pipeline._schlange] == [neu.id]


def test_wiederholung_findet_den_ordner_ueber_die_kette(eigene_datenbank, monkeypatch):
    """A hat Ordner und Drehbuch, B ist gescheitert, ohne je einen Ordner zu bekommen.
    Wird B wiederholt, muss C auf A aufbauen — sonst wird alles neu gekauft."""
    monkeypatch.setattr(pipeline, "_lauf_beginnen", lambda *_a: None)
    a = jobstore.anlegen("Film", {"briefing": "Film"})
    jobstore.aktualisieren(a.id, zustand=jobstore.FEHLER, ordner=str(eigene_datenbank),
                           drehbuch={"titel": "bezahlt"})
    b = jobstore.anlegen("Film", {"briefing": "Film", "wiederholung_von": a.id})
    jobstore.aktualisieren(b.id, zustand=jobstore.ABGEBROCHEN)

    c, _ = pipeline.wiederholen(b.id)
    assert c.einstellungen["wiederholung_von"] == a.id


# ── Bibliothek ───────────────────────────────────────────────────────────────

def test_ordner_eines_laufenden_auftrags_ist_geschuetzt(eigene_datenbank, tmp_path,
                                                         monkeypatch):
    ausgabe = tmp_path / "output"
    (ausgabe / "premium_x").mkdir(parents=True)
    (ausgabe / "premium_x" / "film.mp4").write_bytes(b"x")
    monkeypatch.setattr(config, "OUTPUT_DIR", ausgabe)
    auftrag = jobstore.anlegen("Film", {"briefing": "Film"})
    jobstore.aktualisieren(auftrag.id, zustand=jobstore.LAEUFT,
                           ordner=str(ausgabe / "premium_x"))
    with pytest.raises(errors.EingabeFehler):
        library.video_loeschen("premium_x")
    with pytest.raises(errors.EingabeFehler):
        library.format_nachziehen("premium_x", "hoch")
    assert (ausgabe / "premium_x" / "film.mp4").exists()


# ── Start und Update ─────────────────────────────────────────────────────────

def test_der_tatsaechliche_port_wird_gefunden(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    config.port_merken(7791)
    assert config.bekannte_ports() == [config.PORT, 7791]


class _Git:
    def __init__(self):
        self.aufrufe: list[tuple] = []

    def __call__(self, *argumente, zeitlimit=45):
        self.aufrufe.append(argumente)
        if argumente[:1] == ("rev-parse",) and "HEAD" in argumente:
            return 0, "abc1234def\n"
        if argumente[:2] == ("rev-parse", "--git-dir"):
            return 0, ".git"
        return 0, ""


def test_update_das_nicht_laedt_wird_zurueckgerollt(monkeypatch):
    git = _Git()
    monkeypatch.setattr(updater, "_git", git)
    monkeypatch.setattr(pipeline, "laeuft_gerade", lambda: "")

    def laufen(befehl, **_k):
        if "-c" in befehl:              # der Rauchtest
            return subprocess.CompletedProcess(befehl, 1, "",
                                               "ModuleNotFoundError: No module named 'neu'")
        return subprocess.CompletedProcess(befehl, 0, "", "")
    monkeypatch.setattr(subprocess, "run", laufen)
    neugestartet = []
    monkeypatch.setattr(updater, "neu_starten", lambda *a, **k: neugestartet.append(1))

    with pytest.raises(errors.KonfigurationsFehler) as fehler:
        updater.aktualisieren(neustart=True)
    assert "neu" in fehler.value.hinweis
    assert ("reset", "--hard", "--quiet", "abc1234def") in git.aufrufe
    assert not neugestartet


def test_zwei_updates_gleichzeitig_gehen_nicht(monkeypatch):
    monkeypatch.setattr(pipeline, "laeuft_gerade", lambda: "")
    monkeypatch.setattr(updater, "_git", _Git())
    updater._update_sperre.acquire()
    try:
        with pytest.raises(errors.EingabeFehler):
            updater.aktualisieren(neustart=False)
    finally:
        updater._update_sperre.release()
