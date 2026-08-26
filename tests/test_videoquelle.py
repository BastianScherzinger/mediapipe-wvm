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


# ── Modellnamen des Abo-Wegs ─────────────────────────────────────────────────
#
# Der Fehler, an dem die Übergabe am 26.08.2026 gescheitert ist, stand so im
# Logbuch des Kunden:
#
#     Higgsfield hat keine Auftragsnummer zurückgegeben.
#     {'error': 'unknown model "higgsfield-ai/soul/standard"...'}
#
# Ursache: Die Ablaufsteuerung reicht den Modellnamen aus der .env durch, und der
# ist ein Pfad der Platform-API. Der MCP-Dienst des Abos kennt nur kurze
# Kennungen. Diese Tests halten die Übersetzung in beide Richtungen fest.

@pytest.fixture
def ohne_modellliste(monkeypatch):
    """Der Dienst antwortet nicht — dann muss die Übersetzungstabelle tragen."""
    monkeypatch.setattr(higgsfield_mcp, "_MODELLE", {"zeit": 0.0, "liste": []})
    monkeypatch.setattr(higgsfield_mcp, "modellliste", lambda erneuern=False: [])


@pytest.fixture
def mit_modellliste(monkeypatch):
    liste = [{"id": "soul_2", "name": "Soul 2", "art": "image"},
             {"id": "soul_2_turbo", "name": "Soul 2 Turbo", "art": "image"},
             {"id": "kling2_6_pro", "name": "Kling 2.6 Pro", "art": "video"},
             {"id": "hailuo_02_standard", "name": "Hailuo 02", "art": "video"}]
    monkeypatch.setattr(higgsfield_mcp, "modellliste", lambda erneuern=False: list(liste))
    return liste


def test_kein_platformname_verlaesst_je_den_abo_weg(ohne_modellliste):
    """Alles mit Schrägstrich ist ein Platform-Pfad und würde sicher abgewiesen."""
    for wunsch, art in (("higgsfield-ai/soul/standard", "bild"),
                        ("higgsfield-ai/soul/turbo/standard", "bild"),
                        ("kling-video/v2.6/pro/image-to-video", "video"),
                        ("kling-video/v2.1/master/image-to-video", "video"),
                        ("higgsfield-ai/dop/turbo", "video"),
                        ("minimax/hailuo-02/standard/text-to-video", "video"),
                        ("etwas/voellig/unbekanntes", "video"),
                        ("", "bild")):
        aufgeloest = higgsfield_mcp.modell_aufloesen(wunsch, art)
        assert aufgeloest, f"{wunsch} ergab nichts"
        assert "/" not in aufgeloest, f"{wunsch} wurde zu {aufgeloest}"


def test_liste_des_dienstes_schlaegt_die_tabelle(mit_modellliste):
    assert higgsfield_mcp.modell_aufloesen("higgsfield-ai/soul/standard",
                                           "bild") == "soul_2"
    assert higgsfield_mcp.modell_aufloesen("kling-video/v2.6/pro/image-to-video",
                                           "video") == "kling2_6_pro"


def test_bekannter_name_bleibt_unangetastet(mit_modellliste):
    assert higgsfield_mcp.modell_aufloesen("hailuo_02_standard",
                                           "video") == "hailuo_02_standard"


def test_unbekannter_wunsch_landet_bei_der_richtigen_art(mit_modellliste):
    """Kennt der Dienst nichts Ähnliches, muss wenigstens die Art stimmen — ein
    Bildmodell für einen Videoauftrag wäre nur ein anderer Fehler."""
    video = higgsfield_mcp.modell_aufloesen("voellig/anderes/modell", "video")
    assert video in ("kling2_6_pro", "hailuo_02_standard")


def test_fehlertext_findet_die_meldung_des_dienstes():
    assert "unknown model" in higgsfield_mcp._fehlertext(
        {"error": 'unknown model "higgsfield-ai/soul/standard".'})
    assert higgsfield_mcp._fehlertext({"error": {"message": "kaputt"}}) == "kaputt"
    assert higgsfield_mcp._fehlertext({"results": [{"id": "x"}]}) == ""


def test_unbekanntes_modell_wird_als_solches_erkannt():
    assert higgsfield_mcp._unbekanntes_modell(
        {"error": 'unknown model "higgsfield-ai/soul/standard". '
                  "Use models_explore to see available models."})
    assert not higgsfield_mcp._unbekanntes_modell({"error": "not_enough_credits"})


def test_auftragsnummer_wird_ueberall_gefunden():
    assert higgsfield_mcp._auftragsnummer({"results": [{"id": "abc"}]}) == "abc"
    assert higgsfield_mcp._auftragsnummer({"jobId": "def"}) == "def"
    assert higgsfield_mcp._auftragsnummer({"error": "kaputt"}) == ""


def test_klartextfehler_geht_nicht_verloren():
    """Antwortet der Dienst mit `isError` und reinem Text statt JSON, muss die
    Meldung trotzdem ankommen — sonst steht im Logbuch nur „keine Auftragsnummer“."""
    nachrichten = [{"id": 5, "result": {"isError": True, "content": [
        {"type": "text", "text": 'unknown model "x"'}]}}]
    assert higgsfield_mcp._ergebnis(nachrichten, 5) == {"error": 'unknown model "x"'}


def test_modelle_normieren_vertraegt_jede_form():
    """Die Form der Modellliste ist nicht verbürgt. Auf eine zu wetten hieße,
    denselben Fehler eine Ebene höher zu wiederholen."""
    erwartet = {"soul_2", "kling2_6_pro"}
    for roh in ({"models": [{"id": "soul_2"}, {"id": "kling2_6_pro"}]},
                [{"id": "soul_2"}, {"id": "kling2_6_pro"}],
                ["soul_2", "kling2_6_pro"],
                {"results": [{"model": "soul_2"}, {"name": "kling2_6_pro"}]}):
        assert {e["id"] for e in higgsfield_mcp._modelle_normieren(roh)} == erwartet
    assert higgsfield_mcp._modelle_normieren("Unsinn") == []
    assert higgsfield_mcp._modelle_normieren({"nichts": 1}) == []


# ── Der Auftrag selbst ───────────────────────────────────────────────────────

def test_bild_schickt_nie_einen_platformnamen(monkeypatch, mit_modellliste):
    """Der eigentliche Regressionstest: was die Ablaufsteuerung hineingibt, darf
    so nicht hinausgehen."""
    gesehen = {}

    def gefaelscht(name, argumente, zeitlimit=60):
        if name == "generate_image":
            gesehen["modell"] = argumente["params"]["model"]
            return {"results": [{"id": "auftrag-1"}]}
        return {"status": "completed", "result_url": "https://x/y.jpg"}

    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen", gefaelscht)
    ergebnis = higgsfield_mcp.HiggsfieldAbo().bild(
        "ein Prompt", modell="higgsfield-ai/soul/standard")
    assert gesehen["modell"] == "soul_2"
    assert ergebnis.url.endswith(".jpg")


def test_unbekanntes_modell_fuehrt_zu_einem_zweiten_versuch(monkeypatch):
    """Weist der Dienst den Namen ab, wird die Liste frisch geholt und einmal mit
    einem Namen wiederholt, den er nachweislich führt."""
    versuche = []

    def gefaelscht(name, argumente, zeitlimit=60):
        if name == "models_explore":
            return {"models": [{"id": "soul_2", "type": "image"}]}
        if name == "generate_image":
            versuche.append(argumente["params"]["model"])
            if len(versuche) == 1:
                return {"error": 'unknown model "erfunden". '
                                 "Use models_explore to see available models."}
            return {"results": [{"id": "auftrag-2"}]}
        return {"status": "completed", "result_url": "https://x/y.jpg"}

    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen", gefaelscht)
    monkeypatch.setattr(higgsfield_mcp, "_MODELLE", {"zeit": time.time(), "liste": [
        {"id": "erfunden", "name": "erfunden", "art": "image"}]})

    ergebnis = higgsfield_mcp.HiggsfieldAbo().bild("ein Prompt", modell="erfunden")
    assert versuche == ["erfunden", "soul_2"]
    assert ergebnis.request_id == "auftrag-2"


def test_leeres_guthaben_im_abo_wird_verstaendlich_gemeldet(monkeypatch,
                                                            ohne_modellliste):
    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen",
                        lambda *a, **k: {"error": "not_enough_credits"})
    with pytest.raises(errors.GuthabenFehler) as info:
        higgsfield_mcp.HiggsfieldAbo().bild("Prompt")
    assert "Abo" in info.value.meldung


def test_unbekanntes_modell_endet_in_einer_deutschen_meldung(monkeypatch,
                                                             ohne_modellliste):
    """Bleibt auch der zweite Versuch erfolglos, darf der Kunde nicht mit einem
    englischen Rohtext dastehen."""
    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen",
                        lambda *a, **k: {"error": 'unknown model "x". '
                                                  "Use models_explore."})
    with pytest.raises(errors.KonfigurationsFehler) as info:
        higgsfield_mcp.HiggsfieldAbo().bild("Prompt")
    assert "Modell" in info.value.meldung


def test_seitenverhaeltnis_kommt_beim_abo_an(monkeypatch, mit_modellliste):
    """Hochformat war bestellt — dann darf nicht 16:9 herauskommen."""
    gesehen = {}

    def gefaelscht(name, argumente, zeitlimit=60):
        if name == "generate_video":
            gesehen.update(argumente["params"])
            return {"results": [{"id": "v1"}]}
        return {"status": "completed", "result_url": "https://x/y.mp4"}

    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen", gefaelscht)
    higgsfield_mcp.HiggsfieldAbo().video_aus_bild(
        "Prompt", "https://bild", dauer=5,
        modell="kling-video/v2.6/pro/image-to-video", seitenverhaeltnis="9:16")
    assert gesehen["aspect_ratio"] == "9:16"
    assert gesehen["model"] == "kling2_6_pro"


def test_alle_videowege_nehmen_dasselbe_seitenverhaeltnis_entgegen():
    """Die Ablaufsteuerung reicht es an jeden Weg durch. Fehlt der Parameter bei
    einem, fliegt es erst mitten im Auftrag auf — und kostet dann Guthaben."""
    import inspect
    for weg in (higgsfield.client, higgsfield_mcp.client, videoquelle.probelauf):
        for methode in ("video_aus_bild", "video_aus_text"):
            zeichen = inspect.signature(getattr(weg, methode)).parameters
            assert "seitenverhaeltnis" in zeichen, f"{weg.name}.{methode}"


def test_video_chain_erlaubt_das_abo():
    """Wer „abo“ in die .env schreibt, soll damit auch etwas bewirken."""
    assert config._chain("GIBTESNICHT", "abo,demo",
                         ("platform", "abo", "demo")) == ("abo", "demo")
