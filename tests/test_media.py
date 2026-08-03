"""Tests für das ffmpeg-Modul.

Die schnellen Tests laufen ohne ffmpeg. Die drei echten Durchläufe am Ende erzeugen
tatsächlich Dateien — sie sind mit `langsam` gekennzeichnet und lassen sich mit
`pytest -m "not langsam"` überspringen.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, errors, media  # noqa: E402

HAT_FFMPEG = bool(config.ffmpeg_pfad())
braucht_ffmpeg = pytest.mark.skipif(not HAT_FFMPEG, reason="kein ffmpeg vorhanden")


# ── Formatvorgaben ───────────────────────────────────────────────────────────

def test_alle_gewuenschten_formate_vorhanden():
    """Die vier vom Kunden bestellten Fassungen plus Vorschaubild."""
    for kennung in ("hoch", "quadrat", "breit", "web", "gif", "poster"):
        assert kennung in media.FORMATE


@pytest.mark.parametrize("kennung,breite,hoehe", [
    ("hoch", 1080, 1920),
    ("quadrat", 1080, 1080),
    ("breit", 1920, 1080),
    ("web", 1280, 720),
])
def test_zielaufloesungen_stimmen(kennung, breite, hoehe):
    vorgabe = media.FORMATE[kennung]
    assert (vorgabe.breite, vorgabe.hoehe) == (breite, hoehe)


def test_alle_masse_sind_gerade():
    """H.264 verlangt gerade Kantenlängen — ungerade Werte brechen die Kodierung ab."""
    for vorgabe in media.FORMATE.values():
        assert vorgabe.breite % 2 == 0 and vorgabe.hoehe % 2 == 0


def test_unbekanntes_format_wird_abgelehnt(tmp_path):
    quelle = tmp_path / "x.mp4"
    quelle.write_bytes(b"x" * 2048)
    with pytest.raises(errors.EingabeFehler):
        media.format_erzeugen(quelle, tmp_path / "y.mp4", "gibtsnicht")


def test_fehlende_quelldatei_wird_gemeldet(tmp_path):
    with pytest.raises(errors.VerarbeitungsFehler) as info:
        media.format_erzeugen(tmp_path / "weg.mp4", tmp_path / "y.mp4", "breit")
    assert "fehlt" in info.value.meldung


def test_formatliste_ist_vollstaendig():
    liste = media.formatliste()
    assert len(liste) == len(media.FORMATE)
    assert all({"kennung", "name", "beschreibung", "endung"} <= set(e) for e in liste)


# ── Dateiangaben ─────────────────────────────────────────────────────────────

def test_angaben_zu_fehlender_datei_sind_ungueltig(tmp_path):
    daten = media.angaben(tmp_path / "gibtsnicht.mp4")
    assert not daten.gueltig
    assert daten.dauer == 0


def test_kaputte_datei_faellt_bei_der_pruefung_auf(tmp_path):
    kaputt = tmp_path / "kaputt.mp4"
    kaputt.write_bytes(b"das ist kein video")
    with pytest.raises(errors.VerarbeitungsFehler):
        media.pruefe_video(kaputt)


def test_montage_ohne_clips_wird_abgelehnt(tmp_path):
    with pytest.raises(errors.VerarbeitungsFehler) as info:
        media.montieren([], tmp_path / "film.mp4")
    assert "keine Szenen" in info.value.meldung


def test_montage_ignoriert_fehlende_dateien(tmp_path):
    with pytest.raises(errors.VerarbeitungsFehler):
        media.montieren([tmp_path / "a.mp4", tmp_path / "b.mp4"], tmp_path / "film.mp4")


# ── ffmpeg-Erkennung ─────────────────────────────────────────────────────────

def test_untaugliches_ffmpeg_wird_aussortiert(monkeypatch, tmp_path):
    """Auf dem Entwicklungsrechner lag im Suchpfad eine Hülle namens ffmpeg, die
    `-hide_banner` nicht kannte. Genau das darf nicht ausgewählt werden."""
    hochstapler = tmp_path / "ffmpeg.exe"
    hochstapler.write_bytes(b"nicht wirklich ffmpeg")
    monkeypatch.setattr(config, "_ffmpeg_gemerkt", None)
    monkeypatch.setattr(config.shutil, "which", lambda _n: str(hochstapler))
    monkeypatch.setenv("MPW_FFMPEG", "")

    def probe(befehl, **_kw):
        # Die Hülle scheitert, das mitgelieferte ffmpeg antwortet ordentlich.
        if str(hochstapler) in befehl[0]:
            return subprocess.CompletedProcess(befehl, 1, "", "Unrecognized option")
        return subprocess.CompletedProcess(befehl, 0, "ffmpeg version 7.1", "")

    monkeypatch.setattr(config.subprocess, "run", probe)
    gewaehlt = config.ffmpeg_pfad()
    assert gewaehlt != str(hochstapler)
    monkeypatch.setattr(config, "_ffmpeg_gemerkt", None)      # Zwischenspeicher leeren


def test_ffmpeg_pfad_wird_gemerkt(monkeypatch):
    monkeypatch.setattr(config, "_ffmpeg_gemerkt", "/erfundener/pfad/ffmpeg")
    assert config.ffmpeg_pfad() == "/erfundener/pfad/ffmpeg"
    monkeypatch.setattr(config, "_ffmpeg_gemerkt", None)


# ── Echte Durchläufe ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    if not HAT_FFMPEG:
        pytest.skip("kein ffmpeg")
    ordner = tmp_path_factory.mktemp("clips")
    return media.platzhalter_clip(ordner / "a.mp4", sekunden=2, breite=640, hoehe=360)


@braucht_ffmpeg
@pytest.mark.langsam
def test_platzhalterclip_ist_ein_echtes_video(clip):
    daten = media.pruefe_video(clip)
    assert daten.gueltig
    assert 1.5 < daten.dauer < 2.5
    assert (daten.breite, daten.hoehe) == (640, 360)


@braucht_ffmpeg
@pytest.mark.langsam
def test_montage_kuerzt_um_die_ueberblendungen(tmp_path):
    """Zwei Clips à 2 s mit einer Überblendung ergeben weniger als 4 s — genau darin
    unterscheidet sich die weiche Montage vom harten Schnitt."""
    a = media.platzhalter_clip(tmp_path / "a.mp4", sekunden=2, breite=640, hoehe=360)
    b = media.platzhalter_clip(tmp_path / "b.mp4", sekunden=2, breite=640, hoehe=360)

    weich = media.montieren([a, b], tmp_path / "weich.mp4", weiche_uebergaenge=True,
                            breite=640, hoehe=360)
    hart = media.montieren([a, b], tmp_path / "hart.mp4", weiche_uebergaenge=False,
                           breite=640, hoehe=360)

    dauer_weich = media.angaben(weich).dauer
    dauer_hart = media.angaben(hart).dauer
    assert dauer_weich < dauer_hart
    assert 3.3 < dauer_weich < 4.0
    assert 3.8 < dauer_hart < 4.2


@braucht_ffmpeg
@pytest.mark.langsam
def test_hochformat_hat_genau_die_zielmasse(clip, tmp_path):
    ziel = media.format_erzeugen(clip, tmp_path / "hoch.mp4", "hoch")
    daten = media.angaben(ziel)
    assert (daten.breite, daten.hoehe) == (1080, 1920)
    assert not list(tmp_path.glob("*.teil*"))        # keine Reste
