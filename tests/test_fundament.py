"""Tests für Konfiguration, Fehlerübersetzung und Logbuch."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, errors, logbook  # noqa: E402


# ── Konfiguration ────────────────────────────────────────────────────────────

def test_grenzen_werden_eingehalten():
    assert 2 <= config.POLL_INTERVAL <= 30
    assert 60 <= config.JOB_TIMEOUT <= 3600
    assert 1 <= config.MAX_SCENES <= 30


def test_server_hoert_nur_lokal():
    """Sicherheitszusage: das Werkzeug darf nie im Netzwerk erreichbar sein."""
    assert config.HOST == "127.0.0.1"


def test_anbieterkette_ist_nie_leer():
    assert config.LLM_CHAIN
    assert config.VIDEO_CHAIN
    assert all(w in ("cli", "api", "local") for w in config.LLM_CHAIN)


def test_kette_filtert_unsinn(monkeypatch):
    monkeypatch.setenv("MPW_TESTKETTE", "quatsch, api ,api, local")
    assert config._chain("MPW_TESTKETTE", "cli", ("cli", "api", "local")) == ("api", "local")


def test_kette_faellt_auf_vorgabe_zurueck(monkeypatch):
    monkeypatch.setenv("MPW_TESTKETTE", "nur,mist")
    assert config._chain("MPW_TESTKETTE", "cli,local", ("cli", "api", "local")) == ("cli", "local")


def test_zahl_ausserhalb_der_grenzen_wird_gestutzt(monkeypatch):
    monkeypatch.setenv("MPW_TESTZAHL", "99999")
    assert config._int("MPW_TESTZAHL", 5, 1, 10) == 10
    monkeypatch.setenv("MPW_TESTZAHL", "keine zahl")
    assert config._int("MPW_TESTZAHL", 5, 1, 10) == 5


# ── Maskierung ───────────────────────────────────────────────────────────────

def test_maskierung_zeigt_nie_die_mitte():
    geheim = "abcdefghijklmnopqrstuvwxyz0123456789"
    sichtbar = config.masked(geheim)
    assert "ghijklmnopqrst" not in sichtbar
    assert sichtbar.startswith("abcdef")


def test_kurze_werte_werden_ganz_verborgen():
    assert set(config.masked("kurz123")) == {"•"}


def test_entschaerfen_entfernt_beide_teile_eines_schluessels(monkeypatch):
    monkeypatch.setattr(config, "HIGGSFIELD_API_KEY", "AAAAAAAAAAAAAAAA:BBBBBBBBBBBBBBBB")
    text = "Fehler mit AAAAAAAAAAAAAAAA und BBBBBBBBBBBBBBBB im Text"
    sauber = config.entschaerfe(text)
    assert "AAAAAAAAAAAAAAAA" not in sauber
    assert "BBBBBBBBBBBBBBBB" not in sauber


# ── Fehlerübersetzung ────────────────────────────────────────────────────────

def test_guthaben_wird_nicht_als_zugangsproblem_gedeutet():
    f = errors.aus_httpfehler(403, '{"detail":"not_enough_credits"}')
    assert isinstance(f, errors.GuthabenFehler)
    assert not f.wiederholbar          # erneut versuchen hilft nicht
    assert "Guthaben" in f.meldung


def test_echter_zugangsfehler_bleibt_zugangsfehler():
    f = errors.aus_httpfehler(401, '{"detail":"invalid credentials"}')
    assert isinstance(f, errors.ZugangFehler)


def test_serverfehler_ist_wiederholbar():
    assert errors.aus_httpfehler(503, "bad gateway").wiederholbar
    assert errors.aus_httpfehler(429, "too many").wiederholbar


def test_unbekanntes_modell():
    f = errors.aus_httpfehler(404, '{"detail":"model_not_found"}')
    assert isinstance(f, errors.AnbieterFehler)


def test_gesperrtes_modell():
    assert isinstance(errors.aus_httpfehler(423, '{"detail":"model_blocked"}'),
                      errors.ZugangFehler)


def test_fehler_verraet_keine_zugangsdaten(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_KEY", "sk-ant-geheimgeheimgeheim")
    f = errors.StudioFehler("Abgelehnt für sk-ant-geheimgeheimgeheim")
    assert "geheim" not in f.meldung


def test_beliebige_ausnahme_wird_uebersetzt():
    f = errors.aus_ausnahme(TimeoutError("zu spät"))
    assert isinstance(f, errors.ZeitFehler)
    assert f.wiederholbar
    assert isinstance(errors.aus_ausnahme(FileNotFoundError("weg")), errors.VerarbeitungsFehler)


def test_studiofehler_bleibt_unveraendert():
    original = errors.GuthabenFehler("leer")
    assert errors.aus_ausnahme(original) is original


# ── Logbuch ──────────────────────────────────────────────────────────────────

def test_logzeile_erreicht_abonnenten():
    q = logbook.abonnieren()
    try:
        logbook.erfolg("Test", "Eine Meldung")
        nachricht = q.get(timeout=2)
        assert nachricht["typ"] == "log"
        assert nachricht["ebene"] == "erfolg"
        assert nachricht["text"] == "Eine Meldung"
    finally:
        logbook.abbestellen(q)


def test_ereignis_und_log_teilen_sich_den_kanal():
    q = logbook.abonnieren()
    try:
        logbook.info("Test", "zuerst")
        logbook.ereignis("block", {"block": "claude", "zustand": "aktiv"})
        erste, zweite = q.get(timeout=2), q.get(timeout=2)
        assert erste["typ"] == "log"           # Reihenfolge bleibt erhalten
        assert zweite["typ"] == "ereignis"
        assert zweite["block"] == "claude"
    finally:
        logbook.abbestellen(q)


def test_unbekannte_ebene_wird_zu_info():
    assert logbook.log("quatsch", "Test", "x")["ebene"] == "info"


def test_verlauf_liefert_nur_neues():
    erste = logbook.info("Test", "alt")
    logbook.info("Test", "neu")
    neue = logbook.verlauf(ab_nummer=erste["nr"])
    assert all(z["nr"] > erste["nr"] for z in neue)
    assert any(z["text"] == "neu" for z in neue)


def test_langsamer_abonnent_blockiert_das_programm_nicht():
    q = logbook.abonnieren()
    try:
        for i in range(logbook._ABONNENT_MAX + 50):
            logbook.debug("Test", f"Zeile {i}")     # darf nicht hängen
        assert q.qsize() <= logbook._ABONNENT_MAX
    finally:
        logbook.abbestellen(q)


def test_logzeile_wird_entschaerft(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_KEY", "sk-ant-supergeheimersschluessel")
    eintrag = logbook.info("Test", "Schlüssel sk-ant-supergeheimersschluessel benutzt")
    assert "supergeheim" not in eintrag["text"]
