"""Tests für die Wahl der Videoquelle und den Abo-Weg (MCP). Ohne Netz."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import (config, errors, higgsfield, higgsfield_mcp,  # noqa: E402
                 pipeline, videoquelle)


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
    # Kein Test darf nach `tools/list` fragen — auf einem Rechner mit verbundenem Abo
    # ginge die Frage sonst wirklich hinaus. Die frische Fehlzeit hält die Liste leer.
    monkeypatch.setattr(higgsfield_mcp, "_WERKZEUGE",
                        {"zeit": 0.0, "liste": [], "schemata": {},
                         "fehlzeit": time.time()})
    monkeypatch.setattr(higgsfield_mcp, "_FORM_GEMERKT", {})
    monkeypatch.setattr(higgsfield_mcp, "_ERSATZ", {})


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

def _schluessel_hinterlegt(monkeypatch):
    """Die Ampel-Tests dürfen nicht davon abhängen, ob auf dem Prüfrechner zufällig ein
    Schlüssel in der .env oder eine Abo-Anmeldung in data/ liegt."""
    monkeypatch.setattr(higgsfield_mcp, "angemeldet", lambda: False)
    monkeypatch.setattr(type(higgsfield.client), "verfuegbar", property(lambda self: True))


def test_befund_ist_gruen_wenn_das_abo_verbunden_ist(monkeypatch):
    monkeypatch.setattr(higgsfield_mcp, "angemeldet", lambda: True)
    urteil = videoquelle.befund()
    assert urteil["zustand"] == "ok"
    assert "Abo" in urteil["meldung"]


def test_befund_ist_gelb_bei_leerem_topf(monkeypatch):
    """Die Ampel darf nicht grün leuchten, während nachweislich kein Guthaben da ist —
    sonst fällt es erst mitten im Auftrag auf."""
    _schluessel_hinterlegt(monkeypatch)
    monkeypatch.setattr(higgsfield.client, "guthaben_bekannt",
                        lambda: {"guthaben": False, "zeitpunkt": time.time()})
    urteil = videoquelle.befund()
    assert urteil["zustand"] == "warnung"
    assert "API-Topf ist leer" in urteil["meldung"]
    assert "Abo verbinden" in urteil["hinweis"]


def test_befund_bleibt_ohne_erfahrung_gruen(monkeypatch):
    """Solange nichts Gegenteiliges bekannt ist, gilt ein hinterlegter Schlüssel als
    in Ordnung — Schwarzmalerei ohne Grund wäre genauso falsch wie Schönfärberei."""
    _schluessel_hinterlegt(monkeypatch)
    monkeypatch.setattr(higgsfield.client, "guthaben_bekannt", dict)
    urteil = videoquelle.befund()
    assert urteil["zustand"] == "ok"


def test_befund_meldet_fehler_ohne_jeden_weg(monkeypatch):
    monkeypatch.setattr(higgsfield_mcp, "angemeldet", lambda: False)
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
             {"id": "kling2_6", "name": "Kling 2.6", "art": "video"},
             {"id": "hailuo_02_standard", "name": "Hailuo 02", "art": "video"}]
    monkeypatch.setattr(higgsfield_mcp, "modellliste", lambda erneuern=False: list(liste))
    return liste


def test_kein_platformname_verlaesst_je_den_abo_weg(ohne_modellliste):
    """Alles mit Schrägstrich ist ein Platform-Pfad und würde sicher abgewiesen.

    Geprüft wird über die echten Modellisten der Oberfläche, nicht über eine Abschrift
    davon: Wer ein Modell hinzufügt und die Übersetzung vergisst, soll es hier merken
    und nicht erst beim Kunden.
    """
    kandidaten = ([(m["id"], "video") for m in higgsfield.VIDEOMODELLE] +
                  [(m["id"], "bild") for m in higgsfield.BILDMODELLE] +
                  [(config.VIDEO_MODEL, "video"), (config.IMAGE_MODEL, "bild"),
                   (config.T2V_MODEL, "video"),
                   ("etwas/voellig/unbekanntes", "video"), ("", "bild")])
    assert len(kandidaten) >= 10                 # sonst prüft die Schleife nichts

    for wunsch, art in kandidaten:
        aufgeloest = higgsfield_mcp.modell_aufloesen(wunsch, art)
        assert aufgeloest, f"{wunsch} ergab nichts"
        assert "/" not in aufgeloest, f"{wunsch} wurde zu {aufgeloest}"


def test_liste_des_dienstes_schlaegt_die_tabelle(mit_modellliste):
    assert higgsfield_mcp.modell_aufloesen("higgsfield-ai/soul/standard",
                                           "bild") == "soul_2"
    assert higgsfield_mcp.modell_aufloesen("kling-video/v2.6/pro/image-to-video",
                                           "video") == "kling2_6"


def test_ohne_liste_geht_nie_die_erfundene_kennung_hinaus(ohne_modellliste):
    """Am 10.09.2026 ging ohne Modellliste `kling2_6_pro` hinaus — eine Kennung, die es
    nie gab. Die echte heißt laut offizieller Modellliste `kling2_6`."""
    assert higgsfield_mcp.modell_aufloesen("kling-video/v2.6/pro/image-to-video",
                                           "video") == "kling2_6"
    for kandidaten in higgsfield_mcp._UEBERSETZUNG.values():
        assert "kling2_6_pro" not in kandidaten


def test_bekannter_name_bleibt_unangetastet(mit_modellliste):
    assert higgsfield_mcp.modell_aufloesen("hailuo_02_standard",
                                           "video") == "hailuo_02_standard"


def test_unbekannter_wunsch_landet_bei_der_richtigen_art(mit_modellliste):
    """Kennt der Dienst nichts Ähnliches, muss wenigstens die Art stimmen — ein
    Bildmodell für einen Videoauftrag wäre nur ein anderer Fehler."""
    video = higgsfield_mcp.modell_aufloesen("voellig/anderes/modell", "video")
    assert video in ("kling2_6", "hailuo_02_standard")


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


@pytest.fixture
def bekanntes_startbild(monkeypatch):
    """Ein Startbild, das aus einem eigenen Bildauftrag stammt — der Normalfall.

    Ohne diese Vorgeschichte müsste die Adresse erst beim Dienst eingeführt werden,
    und das ist genau der Weg, den diese Tests nicht meinen.
    """
    monkeypatch.setattr(higgsfield_mcp, "_BILDJOBS", {})
    higgsfield_mcp._bild_merken("https://bild", "bildauftrag-7")
    return "https://bild"


#: Wie das Startbild laut offizieller Doku in `medias` steht.
def _medium(kennung: str) -> list[dict]:
    return [{"value": kennung, "role": "start_image"}]


def test_seitenverhaeltnis_kommt_beim_abo_an(monkeypatch, mit_modellliste,
                                             bekanntes_startbild):
    """Hochformat war bestellt — dann darf nicht 16:9 herauskommen."""
    gesehen = {}

    def gefaelscht(name, argumente, zeitlimit=60):
        if name == "generate_video":
            gesehen.update(argumente["params"])
            return {"results": [{"id": "v1"}]}
        return {"status": "completed", "result_url": "https://x/y.mp4"}

    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen", gefaelscht)
    higgsfield_mcp.HiggsfieldAbo().video_aus_bild(
        "Prompt", bekanntes_startbild, dauer=5,
        modell="kling-video/v2.6/pro/image-to-video", seitenverhaeltnis="9:16")
    assert gesehen["aspect_ratio"] == "9:16"
    assert gesehen["model"] == "kling2_6"


# ── Das Startbild muss beim Videomodell ankommen ─────────────────────────────
#
# Der Abbruch beim Kunden hing an genau einer Zeile: `image_url` statt `medias`.
# Die folgenden Tests halten die Form fest, in beide Richtungen.

def test_startbild_geht_als_medias_hinaus_nie_als_adresse(monkeypatch, mit_modellliste,
                                                          bekanntes_startbild):
    """Der Regressionstest zum Abbruch: `generate_video` bekommt die Auftragsnummer
    des Bildes in `medias` — und unter keinen Umständen eine rohe HTTPS-Adresse."""
    gesehen = {}

    def gefaelscht(name, argumente, zeitlimit=60):
        if name == "generate_video":
            gesehen.update(argumente["params"])
            return {"results": [{"id": "v1"}]}
        return {"status": "completed", "result_url": "https://x/y.mp4"}

    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen", gefaelscht)
    higgsfield_mcp.HiggsfieldAbo().video_aus_bild(
        "Prompt", bekanntes_startbild, dauer=5,
        modell="kling-video/v2.6/pro/image-to-video")

    assert gesehen["medias"] == _medium("bildauftrag-7")
    assert "image_url" not in gesehen
    assert "count" not in gesehen, "`count` kennt generate_video nicht"
    for wert in gesehen.values():
        assert "https://bild" != wert


def test_bildauftrag_wird_fuer_das_video_gemerkt(monkeypatch, mit_modellliste):
    """Erst ein Bild, dann das Video daraus: die Nummer des Bildauftrags muss den
    Weg von selbst finden — sonst müsste die Adresse teuer eingeführt werden."""
    monkeypatch.setattr(higgsfield_mcp, "_BILDJOBS", {})
    gesehen = {}

    def gefaelscht(name, argumente, zeitlimit=60):
        if name == "generate_image":
            return {"results": [{"id": "bild-42"}]}
        if name == "generate_video":
            gesehen.update(argumente["params"])
            return {"results": [{"id": "video-9"}]}
        return {"status": "completed",
                "result_url": "https://ablage/szene1.jpg"}

    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen", gefaelscht)
    dienst = higgsfield_mcp.HiggsfieldAbo()
    bild = dienst.bild("Ein Motiv", modell="higgsfield-ai/soul/standard")
    dienst.video_aus_bild("Bewegung", bild.url, dauer=5,
                          modell="kling-video/v2.6/pro/image-to-video")

    assert gesehen["medias"] == _medium("bild-42")


def test_kundenfehler_invalid_input_fuehrt_zur_naechsten_form(monkeypatch, mit_modellliste,
                                                             bekanntes_startbild):
    """Der Satz aus dem Logbuch vom 10.09.2026 nennt kein Feld. Er muss trotzdem als
    Formfehler erkannt werden — die frühere Prüfung suchte nach „medias“ und übersah ihn."""
    versuche = []

    def gefaelscht(name, argumente, zeitlimit=60):
        if name == "generate_video":
            versuche.append(argumente["params"].get("medias"))
            if len(versuche) == 1:
                return {"error": "Input validation error: Invalid arguments for tool "
                                 "generate_video: params: Invalid input"}
            return {"results": [{"id": "v2"}]}
        return {"status": "completed", "result_url": "https://x/y.mp4"}

    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen", gefaelscht)
    higgsfield_mcp.HiggsfieldAbo().video_aus_bild(
        "Prompt", bekanntes_startbild, dauer=5,
        modell="kling-video/v2.6/pro/image-to-video")

    assert versuche[0] == _medium("bildauftrag-7")
    assert versuche[1] == [{"value": "bildauftrag-7", "role": "image"}]
    assert higgsfield_mcp._FORM_GEMERKT[("generate_video", "kling2_6")] == \
        "doku_rolle_image"                                    # gemerkt fürs nächste Mal


def test_andere_fehler_loesen_keine_formsuche_aus(monkeypatch, mit_modellliste,
                                                  bekanntes_startbild):
    """Nur Formfehler dürfen eine neue Form auslösen. Ein Serverfehler mit Nummer-
    losigkeit wird gemeldet, nicht mit fünf weiteren Aufträgen beantwortet."""
    versuche = []

    def gefaelscht(name, argumente, zeitlimit=60):
        if name == "generate_video":
            versuche.append(1)
            return {"error": "Something went wrong on our side"}
        return {"status": "completed", "result_url": "https://x/y.mp4"}

    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen", gefaelscht)
    with pytest.raises(errors.AnbieterFehler):
        higgsfield_mcp.HiggsfieldAbo().video_aus_bild(
            "Prompt", bekanntes_startbild, dauer=5, modell="kling2_6")
    assert len(versuche) == 1


def test_fremde_adresse_wird_eingefuehrt(monkeypatch, mit_modellliste):
    """Stammt das Bild nicht aus einem eigenen Auftrag, wird es über das
    Import-Werkzeug des Dienstes eingeführt statt roh weitergereicht."""
    monkeypatch.setattr(higgsfield_mcp, "_BILDJOBS", {})
    monkeypatch.setattr(higgsfield_mcp, "_WERKZEUGE",
                        {"zeit": time.time(), "liste": ["job_status", "import_media"]})
    gesehen = {}

    def gefaelscht(name, argumente, zeitlimit=60):
        if name == "import_media":
            return {"media_id": "m-123"}
        if name == "generate_video":
            gesehen.update(argumente["params"])
            return {"results": [{"id": "v3"}]}
        return {"status": "completed", "result_url": "https://x/y.mp4"}

    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen", gefaelscht)
    higgsfield_mcp.HiggsfieldAbo().video_aus_bild(
        "Prompt", "https://fremd/bild.jpg", dauer=5,
        modell="kling-video/v2.6/pro/image-to-video")

    assert gesehen["medias"] == _medium("m-123")


def test_ohne_import_werkzeug_gibt_es_eine_deutsche_meldung(monkeypatch,
                                                            mit_modellliste):
    """Kann die Adresse nicht eingeführt werden, darf der Kunde nicht mit dem
    englischen Rohtext des Dienstes dastehen.

    Und es muss ein **Konfigurations**fehler sein: Der beendet den Lauf sofort. Ein
    Anbieterfehler ließe die Ablaufsteuerung Szene für Szene weitermachen — jede mit
    einem vorher erzeugten und bezahlten Startbild, das nie ein Video wird.
    """
    monkeypatch.setattr(higgsfield_mcp, "_BILDJOBS", {})
    monkeypatch.setattr(higgsfield_mcp, "_WERKZEUGE",
                        {"zeit": time.time(), "liste": ["job_status"]})
    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen",
                        lambda *a, **k: {"results": [{"id": "x"}]})

    with pytest.raises(errors.KonfigurationsFehler) as info:
        higgsfield_mcp.HiggsfieldAbo().video_aus_bild(
            "Prompt", "https://fremd/bild.jpg", dauer=5,
            modell="kling-video/v2.6/pro/image-to-video")
    assert "Startbild" in info.value.meldung
    assert higgsfield_mcp.errors.KonfigurationsFehler in pipeline._TOEDLICH


def test_nur_import_werkzeuge_werden_angefasst():
    """Ein unbekanntes Werkzeug eines kostenpflichtigen Dienstes aufzurufen ist
    riskant. `create_image` darf hier unter keinen Umständen darunterfallen."""
    from app import higgsfield_mcp as m
    erlaubt = ["import_media", "upload_media", "media_import", "upload_image"]
    verboten = ["generate_image", "create_image", "create_media", "add_media",
                "delete_media", "job_status", "models_explore", "cancel_job"]

    def mit(liste):
        m._WERKZEUGE.update({"zeit": time.time(), "liste": liste})
        return m._importwerkzeuge()

    try:
        assert set(mit(erlaubt + verboten)) == set(erlaubt)
        assert mit(verboten) == []
    finally:
        m._WERKZEUGE.update({"zeit": 0.0, "liste": []})


def test_felder_ausserhalb_des_schemas_gehen_nicht_hinaus(monkeypatch, mit_modellliste,
                                                         bekanntes_startbild):
    """Kamerabewegungen und `seed` gehen nur hinaus, wenn das Schema sie nennt. Ein
    unbekanntes Feld ist bei einem strengen Schema ein abgewiesener Auftrag."""
    gesehen = []

    def gefaelscht(name, argumente, zeitlimit=60):
        if name == "generate_video":
            gesehen.append(argumente["params"])
            return {"results": [{"id": "v4"}]}
        return {"status": "completed", "result_url": "https://x/y.mp4"}

    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen", gefaelscht)
    higgsfield_mcp.HiggsfieldAbo().video_aus_bild(
        "Prompt", bekanntes_startbild, dauer=5, bewegungen=["zoom_in"], saat=7,
        modell="kling-video/v2.6/pro/image-to-video")

    assert "motions" not in gesehen[0]
    assert "seed" not in gesehen[0]


def test_werkzeugliste_vertraegt_jede_form():
    """`tools/list` ist nicht verbürgt — was sich nicht auspacken lässt, fällt weg,
    ohne dass ein Auftrag daran scheitert."""
    normieren = higgsfield_mcp._werkzeuge_normieren
    assert normieren({"tools": [{"name": "a"}, {"name": "b"}]}) == ["a", "b"]
    assert normieren(["a", "b"]) == ["a", "b"]
    assert normieren({"results": [{"id": "c"}]}) == ["c"]
    assert normieren("Unsinn") == []
    assert normieren({"nichts": 1}) == []


def test_werkzeugliste_bricht_nie_einen_auftrag_ab(monkeypatch):
    """Antwortet der Dienst nicht, ist das kein Fehler — nur ein leerer Rückfall."""
    monkeypatch.setattr(higgsfield_mcp, "_WERKZEUGE", {"zeit": 0.0, "liste": []})

    def kaputt(*_a, **_k):
        raise RuntimeError("kein Netz")

    monkeypatch.setattr(higgsfield_mcp, "_rpc", kaputt)
    assert higgsfield_mcp.werkzeugliste() == []


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
