"""Tests für den Higgsfield-Client — vollständig ohne Netz, mit Attrappen."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, errors, higgsfield  # noqa: E402


@pytest.fixture(autouse=True)
def eigener_guthabenspeicher(tmp_path, monkeypatch):
    """Jeder Test bekommt einen eigenen Guthabenspeicher.

    Ohne das schreiben Tests, die einen angenommenen Auftrag nachstellen, in den echten
    `data/guthabenstand.json` — und das Dashboard behauptet danach, es sei Guthaben
    vorhanden, obwohl nie ein echter Auftrag lief. Genau das ist einmal passiert.
    """
    monkeypatch.setattr(higgsfield, "_guthaben",
                        higgsfield._Guthabenstand(tmp_path / "guthaben.json"))


@pytest.fixture
def klient(monkeypatch):
    """Client mit erfundenem Schlüssel und beschleunigter Taktung."""
    monkeypatch.setattr(config, "POLL_INTERVAL", 0)
    monkeypatch.setattr(config, "MAX_RETRIES", 2)
    return higgsfield.Higgsfield(api_key="TESTID:TESTGEHEIMNIS")


class Antworten:
    """Gibt vorbereitete Antworten der Reihe nach zurück und zählt die Aufrufe."""

    def __init__(self, *antworten):
        self.antworten = list(antworten)
        self.aufrufe: list[tuple] = []

    def __call__(self, methode, pfad, rumpf=None, *, zeitlimit=0):
        self.aufrufe.append((methode, pfad, rumpf))
        naechste = self.antworten.pop(0) if len(self.antworten) > 1 else self.antworten[0]
        if isinstance(naechste, Exception):
            raise naechste
        return naechste


# ── Clipdauer ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("modell,wunsch,erwartet", [
    ("kling-video/v2.6/pro/image-to-video", 5, 5),
    ("kling-video/v2.6/pro/image-to-video", 7, 5),      # 7 liegt näher an 5 als an 10
    ("kling-video/v2.6/pro/image-to-video", 8, 10),
    ("kling-video/v2.6/pro/image-to-video", 99, 10),
    ("kling-video/v2.6/pro/image-to-video", 1, 5),
    ("minimax/hailuo-02/pro/text-to-video", 10, 6),     # kennt nur 6
    ("minimax/hailuo-02/standard/text-to-video", 9, 10),
    ("unbekannt/modell", 12, 12),                        # unbekannt → unverändert
])
def test_dauer_wird_auf_erlaubten_wert_gebracht(modell, wunsch, erwartet):
    assert higgsfield.erlaubte_dauer(modell, wunsch) == erwartet


def test_dauer_bei_gleichstand_nimmt_den_kuerzeren():
    """7,5 läge genau zwischen 5 und 10 — die günstigere Variante gewinnt."""
    assert higgsfield.erlaubte_dauer("kling-video/v2.6/pro/image-to-video", 7) == 5


def test_startbild_pflicht_richtig_erkannt():
    assert higgsfield.braucht_startbild("kling-video/v2.6/pro/image-to-video")
    assert not higgsfield.braucht_startbild("minimax/hailuo-02/pro/text-to-video")


# ── Ergebnis-URL aus verschiedenen Antwortformen ─────────────────────────────

@pytest.mark.parametrize("antwort", [
    {"result_url": "https://x.de/a.mp4"},
    {"video": {"url": "https://x.de/a.mp4"}},
    {"outputs": [{"url": "https://x.de/a.mp4"}]},
    {"results": ["https://x.de/a.mp4"]},
    {"tief": {"verschachtelt": {"irgendwo": "https://x.de/a.mp4"}}},   # Mustersuche
])
def test_medien_url_wird_gefunden(antwort):
    assert higgsfield.Higgsfield._medien_url(antwort) == "https://x.de/a.mp4"


def test_keine_url_gibt_leeren_text():
    assert higgsfield.Higgsfield._medien_url({"status": "completed"}) == ""


# ── Auftrag anlegen ──────────────────────────────────────────────────────────

def test_auftrag_liefert_kennung(klient, monkeypatch):
    monkeypatch.setattr(klient, "_anfrage", Antworten(
        (200, {"request_id": "abc-123"}, '{"request_id":"abc-123"}')))
    kennung, url = klient.auftrag_erstellen("modell/x", {"prompt": "hallo"})
    assert kennung == "abc-123"
    assert url.endswith("/requests/abc-123/status")


def test_guthabenfehler_wird_nicht_wiederholt(klient, monkeypatch):
    antworten = Antworten((403, {}, '{"detail":"not_enough_credits"}'))
    monkeypatch.setattr(klient, "_anfrage", antworten)
    with pytest.raises(errors.GuthabenFehler):
        klient.auftrag_erstellen("modell/x", {"prompt": "hallo"})
    assert len(antworten.aufrufe) == 1        # genau ein Versuch, kein Nachbohren


def test_serverfehler_wird_wiederholt(klient, monkeypatch):
    antworten = Antworten(
        (503, {}, "kaputt"), (503, {}, "kaputt"),
        (200, {"request_id": "ok-1"}, ""))
    monkeypatch.setattr(klient, "_anfrage", antworten)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    kennung, _ = klient.auftrag_erstellen("modell/x", {"prompt": "hallo"})
    assert kennung == "ok-1"
    assert len(antworten.aufrufe) == 3


def test_wiederholung_gibt_irgendwann_auf(klient, monkeypatch):
    monkeypatch.setattr(klient, "_anfrage", Antworten((500, {}, "kaputt")))
    monkeypatch.setattr("time.sleep", lambda _s: None)
    with pytest.raises(errors.NetzFehler):
        klient.auftrag_erstellen("modell/x", {"prompt": "hallo"})


def test_fehlende_kennung_ist_ein_anbieterfehler(klient, monkeypatch):
    monkeypatch.setattr(klient, "_anfrage", Antworten((200, {"status": "queued"}, "{}")))
    with pytest.raises(errors.AnbieterFehler):
        klient.auftrag_erstellen("modell/x", {"prompt": "hallo"})


def test_ohne_schluessel_klare_ansage(monkeypatch):
    """Ein ausdrücklich leerer Schlüssel darf NICHT auf die Konfiguration zurückfallen —
    sonst würde dieser Test echte Aufrufe gegen die Live-API absetzen."""
    leer = higgsfield.Higgsfield(api_key="")
    assert leer.api_key == ""
    assert not leer.verfuegbar

    def darf_nicht_passieren(*_a, **_k):
        raise AssertionError("Ohne Schlüssel darf keine Netzanfrage entstehen.")

    monkeypatch.setattr(leer, "_anfrage", darf_nicht_passieren)
    with pytest.raises(errors.ZugangFehler) as info:
        leer.auftrag_erstellen("modell/x", {})
    assert ".env" in info.value.hinweis


def test_falsches_schluesselformat_wird_erkannt():
    schief = higgsfield.Higgsfield(api_key="nur-ein-teil-ohne-doppelpunkt")
    assert not schief.verfuegbar
    with pytest.raises(errors.ZugangFehler):
        schief.auftrag_erstellen("modell/x", {})


# ── Warten auf das Ergebnis ──────────────────────────────────────────────────

def test_warten_bis_fertig_meldet_fortschritt(klient, monkeypatch):
    monkeypatch.setattr(klient, "_anfrage", Antworten(
        (200, {"status": "queued"}, ""),
        (200, {"status": "in_progress"}, ""),
        (200, {"status": "completed", "result_url": "https://x.de/v.mp4"}, "")))
    gemeldet: list[tuple] = []
    ergebnis = klient.warten("id-1", "https://api/status", modell="m", art="video",
                             melden=lambda a, r, z: gemeldet.append((a, r, z)))
    assert ergebnis.url == "https://x.de/v.mp4"
    assert gemeldet[-1][0] == 1.0                      # endet bei 100 %
    assert all(0.0 <= a <= 1.0 for a, _r, _z in gemeldet)
    assert gemeldet[0][0] <= 0.15                      # 'queued' bremst die Anzeige


def test_moderation_ist_kein_wiederholbarer_fehler(klient, monkeypatch):
    monkeypatch.setattr(klient, "_anfrage", Antworten((200, {"status": "nsfw"}, "")))
    with pytest.raises(errors.InhaltFehler) as info:
        klient.warten("id-1", "https://api/status", modell="m", art="video")
    assert not info.value.wiederholbar
    assert "erstattet" in info.value.hinweis


def test_fehlgeschlagener_auftrag_nennt_die_begruendung(klient, monkeypatch):
    monkeypatch.setattr(klient, "_anfrage", Antworten(
        (200, {"status": "failed", "error": "Modell überlastet"}, "")))
    with pytest.raises(errors.AnbieterFehler) as info:
        klient.warten("id-1", "https://api/status", modell="m", art="video")
    assert "überlastet" in info.value.hinweis


def test_fertig_ohne_datei_ist_ein_fehler(klient, monkeypatch):
    monkeypatch.setattr(klient, "_anfrage", Antworten((200, {"status": "completed"}, "")))
    with pytest.raises(errors.AnbieterFehler):
        klient.warten("id-1", "https://api/status", modell="m", art="video")


def test_abbruch_storniert_beim_dienst(klient, monkeypatch):
    antworten = Antworten((200, {"status": "in_progress"}, ""))
    monkeypatch.setattr(klient, "_anfrage", antworten)
    signal = threading.Event()
    signal.set()
    with pytest.raises(errors.AbbruchFehler):
        klient.warten("id-1", "https://api/status", modell="m", art="video", abbruch=signal)
    assert any("cancel" in str(pfad) for _m, pfad, _r in antworten.aufrufe)


def test_zeitueberschreitung_storniert_ebenfalls(klient, monkeypatch):
    monkeypatch.setattr(config, "JOB_TIMEOUT", 60)
    antworten = Antworten((200, {"status": "in_progress"}, ""))
    monkeypatch.setattr(klient, "_anfrage", antworten)
    # Uhr vorstellen, statt wirklich zu warten
    zeiten = iter([0.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr("time.monotonic", lambda: next(zeiten, 100.0))
    with pytest.raises(errors.ZeitFehler):
        klient.warten("id-1", "https://api/status", modell="m", art="video")
    assert any("cancel" in str(pfad) for _m, pfad, _r in antworten.aufrufe)


def test_einzelne_gestoerte_abfrage_ist_kein_abbruch(klient, monkeypatch):
    monkeypatch.setattr(klient, "_anfrage", Antworten(
        errors.NetzFehler("kurz weg"),
        (200, {"status": "completed", "result_url": "https://x.de/v.mp4"}, "")))
    ergebnis = klient.warten("id-1", "https://api/status", modell="m", art="video")
    assert ergebnis.url.endswith(".mp4")


def test_unbekannter_auftrag_gilt_als_wartend(klient, monkeypatch):
    """Direkt nach dem Anlegen kann der Auftrag noch nicht überall bekannt sein."""
    monkeypatch.setattr(klient, "_anfrage", Antworten((404, {}, "nicht da")))
    assert klient.status("https://api/status")["status"] == "queued"


# ── Laufzeitgedächtnis ───────────────────────────────────────────────────────

def test_laufzeit_wird_gemittelt(tmp_path):
    speicher = higgsfield._Laufzeiten(tmp_path / "z.json")
    speicher.merken("m", 100.0)
    assert speicher.schaetzung("m", "video") == 100.0
    speicher.merken("m", 200.0)
    assert 100.0 < speicher.schaetzung("m", "video") < 200.0    # gleitend, kein Sprung


def test_unsinnige_laufzeit_wird_verworfen(tmp_path):
    speicher = higgsfield._Laufzeiten(tmp_path / "z.json")
    speicher.merken("m", -5)
    speicher.merken("m", 99999)
    assert speicher.schaetzung("m", "video") == higgsfield._ERFAHRUNG_VORGABE["video"]


def test_laufzeit_ueberlebt_neustart(tmp_path):
    pfad = tmp_path / "z.json"
    higgsfield._Laufzeiten(pfad).merken("m", 42.0)
    assert higgsfield._Laufzeiten(pfad).schaetzung("m", "video") == 42.0


# ── Guthabengedächtnis ───────────────────────────────────────────────────────

def test_guthabenstand_wird_gemerkt(tmp_path):
    stand = higgsfield._Guthabenstand(tmp_path / "g.json")
    assert stand.lesen() == {}
    stand.merken(False, "Test")
    assert stand.lesen()["guthaben"] is False
    assert higgsfield._Guthabenstand(tmp_path / "g.json").lesen()["guthaben"] is False


def test_selbsttest_behauptet_kein_guthaben_ohne_beleg(klient, monkeypatch, tmp_path):
    """Der wichtigste Test dieses Moduls: 422 beweist nur die Anmeldung, nicht das Konto.
    Genau diese Verwechslung hatte die erste Fassung — sie meldete fälschlich 'bereit'."""
    monkeypatch.setattr(higgsfield, "_guthaben", higgsfield._Guthabenstand(tmp_path / "g.json"))
    monkeypatch.setattr(klient, "_anfrage", Antworten((422, {}, '{"detail":[]}')))
    ergebnis = klient.selbsttest()
    assert ergebnis["zustand"] == "zugang_ok"
    assert ergebnis["guthaben"] == "unbekannt"


def test_selbsttest_meldet_leeres_konto(klient, monkeypatch, tmp_path):
    monkeypatch.setattr(higgsfield, "_guthaben", higgsfield._Guthabenstand(tmp_path / "g.json"))
    monkeypatch.setattr(klient, "_anfrage", Antworten(
        (403, {}, '{"detail":"not_enough_credits"}')))
    ergebnis = klient.selbsttest()
    assert ergebnis["guthaben"] == "leer"
    assert not ergebnis["ok"]


def test_auftrag_merkt_sich_den_kontostand(klient, monkeypatch, tmp_path):
    speicher = higgsfield._Guthabenstand(tmp_path / "g.json")
    monkeypatch.setattr(higgsfield, "_guthaben", speicher)
    monkeypatch.setattr(klient, "_anfrage", Antworten((200, {"request_id": "x"}, "")))
    klient.auftrag_erstellen("m", {"prompt": "a"})
    assert speicher.lesen()["guthaben"] is True


# ── Kopfzeilen ───────────────────────────────────────────────────────────────

def test_beide_anmeldeverfahren_werden_mitgeschickt(klient):
    kopf = klient._kopfzeilen()
    assert kopf["Authorization"] == "Key TESTID:TESTGEHEIMNIS"
    assert kopf["hf-api-key"] == "TESTID"
    assert kopf["hf-secret"] == "TESTGEHEIMNIS"
