"""Tests für die Wahl der Videoquelle und den Abo-Weg (MCP). Ohne Netz."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, errors, higgsfield, higgsfield_mcp, videoquelle  # noqa: E402


class Weg:
    """Ein Weg, der wahlweise kann oder nicht."""

    def __init__(self, name: str, verfuegbar: bool = True, guthaben: dict | None = None):
        self.name = name
        self.verfuegbar = verfuegbar
        self._guthaben = guthaben

    def selbsttest(self):
        return {"zustand": "bereit" if self.verfuegbar else "aus", "ok": self.verfuegbar,
                "guthaben": "unbekannt", "meldung": "", "hinweis": ""}


class WegMitGedaechtnis(Weg):
    """Wie `Weg`, merkt sich aber wie der Platform-Client den Guthabenstand."""

    def guthaben_bekannt(self):
        return self._guthaben or {}


@pytest.fixture(autouse=True)
def kein_abo(monkeypatch):
    """Standardmäßig ist kein Abo angemeldet — sonst hinge der Test am echten Zustand."""
    monkeypatch.setattr(higgsfield_mcp, "angemeldet", lambda: False)
    monkeypatch.setattr(videoquelle, "_letzter", "")


# ── Auswahl ──────────────────────────────────────────────────────────────────

def test_platform_wird_genommen_wenn_sie_kann(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_CHAIN", ("platform", "demo"))
    monkeypatch.setattr(videoquelle, "_wege",
                        lambda: {"platform": Weg("Platform"), "abo": Weg("Abo", False),
                                 "demo": Weg("Demo")})
    assert videoquelle.aktiv().name == "Platform"


def test_ohne_platform_wird_der_probelauf_genommen(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_CHAIN", ("platform", "demo"))
    monkeypatch.setattr(videoquelle, "_wege",
                        lambda: {"platform": Weg("Platform", False),
                                 "abo": Weg("Abo", False), "demo": Weg("Demo")})
    assert videoquelle.aktiv().name == "Demo"


def test_angemeldetes_abo_draengt_sich_nach_vorn(monkeypatch):
    """Der Abo-Weg steht nicht in der Vorgabekette. Ist er aber angemeldet, ist er der
    einzige mit Guthaben — dann muss er zuerst drankommen, ohne dass jemand die .env
    anfassen muss."""
    monkeypatch.setattr(higgsfield_mcp, "angemeldet", lambda: True)
    monkeypatch.setattr(config, "VIDEO_CHAIN", ("platform", "demo"))
    monkeypatch.setattr(videoquelle, "_wege",
                        lambda: {"platform": Weg("Platform"), "abo": Weg("Abo"),
                                 "demo": Weg("Demo")})
    assert videoquelle.aktiv().name == "Abo"


def test_abo_nur_wenn_angemeldet(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_CHAIN", ("platform", "demo"))
    monkeypatch.setattr(videoquelle, "_wege",
                        lambda: {"platform": Weg("Platform"), "abo": Weg("Abo"),
                                 "demo": Weg("Demo")})
    assert videoquelle.aktiv().name == "Platform"


def test_ohne_jeden_weg_klare_ansage(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_CHAIN", ("platform",))
    monkeypatch.setattr(videoquelle, "_wege",
                        lambda: {"platform": Weg("Platform", False),
                                 "abo": Weg("Abo", False), "demo": Weg("Demo", False)})
    with pytest.raises(errors.KonfigurationsFehler) as info:
        videoquelle.aktiv()
    assert "MPW_VIDEO_CHAIN" in info.value.hinweis


def test_leerer_topf_ueberlaesst_dem_naechsten_weg_den_vortritt(monkeypatch):
    """Ein gültiger Schlüssel auf einem leeren Guthabentopf darf den Auftrag nicht an
    sich reißen — sonst stünde der zweite Eintrag der Kette nur zur Zierde da."""
    monkeypatch.setattr(config, "VIDEO_CHAIN", ("platform", "demo"))
    leer = {"guthaben": False, "zeitpunkt": time.time()}
    monkeypatch.setattr(videoquelle, "_wege",
                        lambda: {"platform": WegMitGedaechtnis("Platform", guthaben=leer),
                                 "abo": Weg("Abo", False), "demo": Weg("Demo")})
    assert videoquelle.aktiv().name == "Demo"


def test_alter_guthabenbefund_sperrt_nicht_fuer_immer(monkeypatch):
    """Wer nachlädt, soll nicht ewig übersprungen werden: nach der Gedächtnisfrist
    wird der Weg wieder probiert."""
    monkeypatch.setattr(config, "VIDEO_CHAIN", ("platform", "demo"))
    alt = {"guthaben": False, "zeitpunkt": time.time() - videoquelle.GEDAECHTNIS - 60}
    monkeypatch.setattr(videoquelle, "_wege",
                        lambda: {"platform": WegMitGedaechtnis("Platform", guthaben=alt),
                                 "abo": Weg("Abo", False), "demo": Weg("Demo")})
    assert videoquelle.aktiv().name == "Platform"


def test_leerer_topf_ohne_ausweg_wird_trotzdem_versucht(monkeypatch):
    """Gibt es keinen zweiten Weg, ist die Fehlermeldung des Dienstes selbst immer noch
    besser als gar kein Versuch."""
    monkeypatch.setattr(config, "VIDEO_CHAIN", ("platform",))
    leer = {"guthaben": False, "zeitpunkt": time.time()}
    monkeypatch.setattr(videoquelle, "_wege",
                        lambda: {"platform": WegMitGedaechtnis("Platform", guthaben=leer),
                                 "abo": Weg("Abo", False), "demo": Weg("Demo", False)})
    assert videoquelle.aktiv().name == "Platform"


# ── Ampel im Kopf ────────────────────────────────────────────────────────────

def test_befund_ist_gruen_wenn_das_abo_verbunden_ist(monkeypatch):
    monkeypatch.setattr(higgsfield_mcp, "angemeldet", lambda: True)
    urteil = videoquelle.befund()
    assert urteil["zustand"] == "ok"
    assert "Abo" in urteil["meldung"]


def test_befund_ist_gelb_bei_leerem_topf(monkeypatch):
    """Die Ampel darf nicht grün leuchten, während nachweislich kein Guthaben da ist —
    sonst fällt es erst mitten im Auftrag auf."""
    monkeypatch.setattr(higgsfield.client, "guthaben_bekannt",
                        lambda: {"guthaben": False, "zeitpunkt": time.time()})
    urteil = videoquelle.befund()
    assert urteil["zustand"] == "warnung"
    assert "Abo verbinden" in urteil["hinweis"]


def test_befund_bleibt_ohne_erfahrung_gruen(monkeypatch):
    """Solange nichts Gegenteiliges bekannt ist, gilt ein hinterlegter Schlüssel als
    in Ordnung — Schwarzmalerei ohne Grund wäre genauso falsch wie Schönfärberei."""
    monkeypatch.setattr(higgsfield.client, "guthaben_bekannt", dict)
    urteil = videoquelle.befund()
    assert urteil["zustand"] == "ok"


def test_befund_meldet_fehler_ohne_jeden_weg(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_CHAIN", ("platform",))
    monkeypatch.setattr(type(higgsfield.client), "verfuegbar", property(lambda self: False))
    urteil = videoquelle.befund()
    assert urteil["zustand"] == "fehler"
    assert urteil["ok"] is False


def test_leere_kette_faellt_auf_platform_zurueck(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_CHAIN", ())
    assert videoquelle._reihenfolge() == ["platform"]


def test_uebersicht_nennt_alle_drei_wege():
    wege = videoquelle.uebersicht()
    assert {w["weg"] for w in wege} == {"platform", "abo", "demo"}
    assert all("meldung" in w for w in wege)


# ── Probelauf ────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not config.ffmpeg_pfad(), reason="kein ffmpeg")
@pytest.mark.langsam
def test_probelauf_erzeugt_ein_echtes_video(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from app import media

    ergebnis = videoquelle.probelauf.video_aus_bild("Test", "", dauer=2)
    datei = Path(ergebnis.url)
    assert datei.exists()
    angaben = media.pruefe_video(datei)
    assert 1.5 < angaben.dauer < 2.5


def test_probelauf_braucht_kein_guthaben():
    pruefung = videoquelle.probelauf.selbsttest()
    assert pruefung["guthaben"] == "nicht nötig"


# ── Abo-Weg ──────────────────────────────────────────────────────────────────

def test_abo_ohne_anmeldung_sagt_es_deutlich(monkeypatch, tmp_path):
    monkeypatch.setattr(higgsfield_mcp, "_anmeldedatei", tmp_path / "abo.json")
    pruefung = higgsfield_mcp.HiggsfieldAbo().selbsttest()
    assert pruefung["ok"] is False
    assert pruefung["zustand"] == "nicht_angemeldet"
    assert "anmelden" in pruefung["hinweis"].lower()


def test_abo_ohne_anmeldung_wirft_beim_auftrag(monkeypatch, tmp_path):
    monkeypatch.setattr(higgsfield_mcp, "_anmeldedatei", tmp_path / "abo.json")
    with pytest.raises(errors.ZugangFehler) as info:
        higgsfield_mcp._gueltiges_token()
    assert "nicht verbunden" in info.value.meldung


def test_gueltiges_token_wird_wiederverwendet(monkeypatch, tmp_path):
    datei = tmp_path / "abo.json"
    monkeypatch.setattr(higgsfield_mcp, "_anmeldedatei", datei)
    higgsfield_mcp._speichern({"access_token": "abc", "refresh_token": "r",
                               "gueltig_bis": time.time() + 3600})
    assert higgsfield_mcp._gueltiges_token() == "abc"


def test_abgelaufenes_token_ohne_erneuerung_wird_gemeldet(monkeypatch, tmp_path):
    monkeypatch.setattr(higgsfield_mcp, "_anmeldedatei", tmp_path / "abo.json")
    higgsfield_mcp._speichern({"access_token": "alt", "gueltig_bis": time.time() - 10})
    with pytest.raises(errors.ZugangFehler) as info:
        higgsfield_mcp._gueltiges_token()
    assert "abgelaufen" in info.value.meldung


def test_anmeldedaten_ueberleben_einen_neustart(tmp_path, monkeypatch):
    """Ohne Dauerhaftigkeit müsste sich der Kunde bei jedem Start neu anmelden.
    Geprüft wird über den Speicher selbst — `angemeldet()` ist im Test ersetzt."""
    monkeypatch.setattr(higgsfield_mcp, "_anmeldedatei", tmp_path / "abo.json")
    higgsfield_mcp._speichern({"refresh_token": "geheim", "access_token": ""})

    assert bool(higgsfield_mcp._laden().get("refresh_token")) is True
    higgsfield_mcp.abmelden()
    assert higgsfield_mcp._laden() == {}


# ── Antworten des MCP-Dienstes auswerten ─────────────────────────────────────

def test_ereignisstrom_wird_zerlegt():
    class Antwort:
        headers = {"content-type": "text/event-stream"}
        text = ('data: {"jsonrpc":"2.0","id":7,"result":{"a":1}}\n\n'
                'data: [DONE]\n\n')

    nachrichten = higgsfield_mcp._zerlegen(Antwort())
    assert len(nachrichten) == 1
    assert nachrichten[0]["id"] == 7


def test_schlichtes_json_wird_zerlegt():
    class Antwort:
        headers = {"content-type": "application/json"}
        text = '{"jsonrpc":"2.0","id":3,"result":{"b":2}}'

    assert higgsfield_mcp._zerlegen(Antwort())[0]["id"] == 3


def test_ergebnis_aus_strukturiertem_inhalt():
    nachrichten = [{"id": 5, "result": {"structuredContent": {"results": [{"id": "x"}]}}}]
    assert higgsfield_mcp._ergebnis(nachrichten, 5)["results"][0]["id"] == "x"


def test_ergebnis_aus_textinhalt():
    nachrichten = [{"id": 5, "result": {"content": [
        {"type": "text", "text": '{"results":[{"id":"y"}]}'}]}}]
    assert higgsfield_mcp._ergebnis(nachrichten, 5)["results"][0]["id"] == "y"


def test_fehler_im_ergebnis_wird_geworfen():
    with pytest.raises(errors.AnbieterFehler):
        higgsfield_mcp._ergebnis([{"id": 5, "error": {"message": "kaputt"}}], 5)


def test_fremde_kennung_wird_uebergangen():
    assert higgsfield_mcp._ergebnis([{"id": 99, "result": {"a": 1}}], 5) == {}


# ── Gleiche Schnittstelle wie der Platform-Client ────────────────────────────

def test_abo_kann_alles_was_die_pipeline_braucht():
    """Die Ablaufsteuerung spricht beide Wege gleich an — fehlt eine Methode, fliegt
    es erst mitten im Auftrag auf."""
    for name in ("bild", "video_aus_bild", "video_aus_text", "herunterladen",
                 "abbrechen", "selbsttest"):
        assert callable(getattr(higgsfield_mcp.client, name)), f"{name} fehlt"
        assert callable(getattr(higgsfield.client, name)), f"{name} fehlt"
        assert callable(getattr(videoquelle.probelauf, name)), f"{name} fehlt"
