"""
Der Abo-Weg gegen eine **strenge** Nachbildung des MCP-Dienstes.

Warum es diese Datei gibt: Dreimal ist ein Kundenlauf an einer Form gescheitert, die
die bisherigen Attrappen einfach durchgewinkt haben. `CLAUDE.md` hält die Lehre fest —
*eine Attrappe, die alles annimmt, prüft nichts.* Diese hier nimmt nur an, was die
offizielle Higgsfield-Dokumentation beschreibt, und antwortet auf alles andere mit genau
dem Satz, der am 10.09.2026 im Logbuch des Kunden stand:

    Input validation error: Invalid arguments for tool generate_video: params: Invalid input

Gesprochen wird echtes MCP über HTTP (JSON-RPC, Sitzungskennung, `tools/list`,
`tools/call`) — `_rpc`, `_zerlegen` und `_ergebnis` laufen also unverändert mit. Nur
Anmeldung und Adresse sind ersetzt.

Quellen der nachgebildeten Form (Stand 11.09.2026):
  * github.com/higgsfield-ai/skills — higgsfield-generate/references/media-inputs.md
  * github.com/higgsfield-ai/cli — MODELS.md (Modellkennungen, Formate, Dauern)
  * eigener, erfolgreicher MCP-Aufruf im Skill `3dfig`:
    medias:[{value:"<image-job-id>", role:"start_image"}]
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import errors, higgsfield_mcp  # noqa: E402

FEHLER_VIDEO = ("Input validation error: Invalid arguments for tool generate_video: "
                "params: Invalid input")

#: Was der nachgebildete Dienst je Videomodell annimmt.
MODELLE = {
    "kling2_6": {"formate": ["16:9", "9:16", "1:1"], "dauer": [5, 10],
                 "rollen": ["start_image"]},
    "kling3_0": {"formate": ["16:9", "9:16", "1:1"], "dauer": [5, 10, 15],
                 "rollen": ["start_image", "end_image"]},
}
BILDMODELLE = ["soul_2", "text2image_soul_v2"]


def _videoschema() -> dict:
    """So würde zod das Schema beschreiben: `params` als Vereinigung je Modell."""
    zweige = []
    for modell, angaben in MODELLE.items():
        zweige.append({
            "type": "object",
            "additionalProperties": False,
            "required": ["model", "prompt"],
            "properties": {
                "model": {"const": modell},
                "prompt": {"type": "string"},
                "medias": {"type": "array", "items": {"$ref": "#/definitions/medium"}},
                "aspect_ratio": {"type": "string", "enum": angaben["formate"]},
                "duration": {"type": "integer", "enum": angaben["dauer"]},
                "sound": {"type": "boolean"},
            },
        })
    return {
        "type": "object",
        "required": ["params"],
        "properties": {"params": {"anyOf": zweige + [{"type": "string"}]}},
        "definitions": {"medium": {
            "type": "object", "additionalProperties": False,
            "required": ["value", "role"],
            "properties": {"value": {"type": "string"},
                           "role": {"type": "string",
                                    "enum": ["start_image", "end_image", "image"]}}}},
    }


class Dienst:
    """Zustand des nachgebildeten Dienstes — was bestellt wurde, was abgewiesen."""

    def __init__(self, *, mit_schema: bool = True, weist_alles_ab: bool = False):
        self.mit_schema = mit_schema
        self.weist_alles_ab = weist_alles_ab
        self.aufrufe: list[tuple[str, dict]] = []
        self.angenommen: list[str] = []        # Nummern — jede kostet beim echten Dienst
        self.auftraege: dict[str, dict] = {}
        self.zaehler = 0

    # ── Prüfung wie zod ──────────────────────────────────────────────────────

    @staticmethod
    def video_ok(argumente: dict) -> bool:
        p = argumente.get("params")
        if not isinstance(p, dict) or set(argumente) != {"params"}:
            return False
        angaben = MODELLE.get(p.get("model"))
        if angaben is None or not isinstance(p.get("prompt"), str):
            return False
        erlaubt = {"model", "prompt", "medias", "aspect_ratio", "duration", "sound"}
        if set(p) - erlaubt:
            return False
        if "aspect_ratio" in p and p["aspect_ratio"] not in angaben["formate"]:
            return False
        if "duration" in p and p["duration"] not in angaben["dauer"]:
            return False
        for eintrag in p.get("medias", []):
            if not isinstance(eintrag, dict) or set(eintrag) != {"value", "role"}:
                return False
            if eintrag["role"] not in angaben["rollen"]:
                return False
        return True

    @staticmethod
    def bild_ok(argumente: dict) -> bool:
        p = argumente.get("params")
        return (isinstance(p, dict) and p.get("model") in BILDMODELLE
                and isinstance(p.get("prompt"), str))

    # ── Werkzeuge ────────────────────────────────────────────────────────────

    def werkzeuge(self) -> dict:
        namen = ["generate_image", "generate_video", "job_status", "models_explore"]
        liste = []
        for name in namen:
            eintrag = {"name": name, "description": name}
            if self.mit_schema and name == "generate_video":
                eintrag["inputSchema"] = _videoschema()
            elif self.mit_schema:
                eintrag["inputSchema"] = {"type": "object"}
            liste.append(eintrag)
        return {"tools": liste}

    def rufen(self, name: str, argumente: dict) -> dict:
        self.aufrufe.append((name, json.loads(json.dumps(argumente))))
        if name == "models_explore":
            return self._text("Unbekannte Antwortform ohne Liste.")
        if name == "generate_image":
            if self.weist_alles_ab or not self.bild_ok(argumente):
                return self._fehler("Input validation error: Invalid arguments for tool "
                                    "generate_image: params: Invalid input")
            return self._neu("bild", "https://ablage.test/bild.jpg")
        if name == "generate_video":
            if self.weist_alles_ab or not self.video_ok(argumente):
                return self._fehler(FEHLER_VIDEO)
            medien = argumente["params"].get("medias") or []
            for eintrag in medien:
                if eintrag["value"] not in self.auftraege:
                    return self._fehler("generate_video accepts uploaded media IDs or "
                                        "completed job IDs in params.medias")
            return self._neu("video", "https://ablage.test/clip.mp4")
        if name == "job_status":
            kennung = argumente.get("jobId") or (argumente.get("params") or {}).get("jobId")
            auftrag = self.auftraege.get(kennung)
            if auftrag is None:
                return self._fehler("job not found")
            return self._json({"status": "completed", "result_url": auftrag["url"]})
        return self._fehler(f"unknown tool {name}")

    def _neu(self, art: str, url: str) -> dict:
        self.zaehler += 1
        kennung = f"{art}-{self.zaehler:04d}-0000-0000-000000000000"
        self.auftraege[kennung] = {"art": art, "url": url}
        self.angenommen.append(kennung)
        return self._json({"results": [{"id": kennung}]})

    @staticmethod
    def _json(daten: dict) -> dict:
        return {"content": [{"type": "text", "text": json.dumps(daten)}]}

    @staticmethod
    def _text(text: str) -> dict:
        return {"content": [{"type": "text", "text": text}]}

    @staticmethod
    def _fehler(text: str) -> dict:
        return {"isError": True, "content": [{"type": "text", "text": text}]}


def _server(dienst: Dienst) -> ThreadingHTTPServer:
    class Empfang(BaseHTTPRequestHandler):
        def do_POST(self):                                     # noqa: N802
            laenge = int(self.headers.get("Content-Length") or 0)
            anfrage = json.loads(self.rfile.read(laenge) or b"{}")
            if "id" not in anfrage:                            # Benachrichtigung
                self.send_response(202)
                self.end_headers()
                return
            methode = anfrage.get("method")
            if methode == "initialize":
                ergebnis = {"protocolVersion": "2025-06-18", "capabilities": {}}
            elif methode == "tools/list":
                ergebnis = dienst.werkzeuge()
            elif methode == "tools/call":
                p = anfrage.get("params") or {}
                ergebnis = dienst.rufen(p.get("name", ""), p.get("arguments") or {})
            else:
                ergebnis = {}
            rumpf = json.dumps({"jsonrpc": "2.0", "id": anfrage["id"],
                                "result": ergebnis}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", "sitzung-1")
            self.send_header("Content-Length", str(len(rumpf)))
            self.end_headers()
            self.wfile.write(rumpf)

        def log_message(self, *_a):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Empfang)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def abo(monkeypatch):
    """Liefert eine Fabrik: `abo(mit_schema=..., weist_alles_ab=...)` → Dienst."""
    server_liste: list[ThreadingHTTPServer] = []

    def bauen(**optionen) -> Dienst:
        dienst = Dienst(**optionen)
        server = _server(dienst)
        server_liste.append(server)
        monkeypatch.setattr(higgsfield_mcp, "_MCP_URL",
                            f"http://127.0.0.1:{server.server_address[1]}/mcp")
        return dienst

    monkeypatch.setattr(higgsfield_mcp, "_gueltiges_token", lambda: "test-token")
    monkeypatch.setattr(higgsfield_mcp, "_schemata_ablegen", lambda _a: None)
    monkeypatch.setattr(higgsfield_mcp, "_WERKZEUGE",
                        {"zeit": 0.0, "liste": [], "schemata": {}, "fehlzeit": 0.0})
    monkeypatch.setattr(higgsfield_mcp, "_MODELLE", {"zeit": 0.0, "liste": []})
    monkeypatch.setattr(higgsfield_mcp, "_FORM_GEMERKT", {})
    monkeypatch.setattr(higgsfield_mcp, "_ERSATZ", {})
    monkeypatch.setattr(higgsfield_mcp, "_BILDJOBS", {})
    monkeypatch.setattr(higgsfield_mcp.config, "MAX_RETRIES", 0)
    yield bauen
    for server in server_liste:
        server.shutdown()


# ── Die Attrappe selbst ist streng ───────────────────────────────────────────

def test_die_form_vom_kundenlauf_wird_abgewiesen():
    """Die Gegenprobe zuerst: Was am 10.09.2026 hinausging, muss die Attrappe mit
    genau dem Satz aus dem Logbuch zurückweisen — sonst prüft sie nichts."""
    so_wars = {"params": {"model": "kling2_6_pro", "prompt": "x", "aspect_ratio": "16:9",
                          "count": 1, "medias": ["bild-0001"], "duration": 5}}
    assert Dienst.video_ok(so_wars) is False
    # Und selbst mit der richtigen Kennung trägt die alte `medias`-Form nicht:
    so_wars["params"]["model"] = "kling2_6"
    del so_wars["params"]["count"]
    assert Dienst.video_ok(so_wars) is False
    richtig = {"params": {"model": "kling2_6", "prompt": "x", "aspect_ratio": "16:9",
                          "duration": 5,
                          "medias": [{"value": "bild-0001", "role": "start_image"}]}}
    assert Dienst.video_ok(richtig) is True


# ── Ende zu Ende über echtes MCP ─────────────────────────────────────────────

def test_bild_und_video_mit_schema(abo):
    dienst = abo(mit_schema=True)
    kunde = higgsfield_mcp.HiggsfieldAbo()

    bild = kunde.bild("A bakery at dawn", seitenverhaeltnis="9:16",
                      modell="higgsfield-ai/soul/standard")
    video = kunde.video_aus_bild("Slow push-in", bild.url, dauer=7, seitenverhaeltnis="3:4",
                                 modell="kling-video/v2.6/pro/image-to-video")

    assert video.url.endswith(".mp4")
    videoauftraege = [a for n, a in dienst.aufrufe if n == "generate_video"]
    assert len(videoauftraege) == 1, "mit Schema muss der erste Versuch sitzen"
    params = videoauftraege[0]["params"]
    assert params["model"] == "kling2_6"
    assert params["medias"] == [{"value": bild.request_id, "role": "start_image"}]
    assert params["aspect_ratio"] == "9:16", "3:4 gibt es bei Kling nicht"
    assert params["duration"] in (5, 10)
    assert params.get("sound") is False, "den Ton verwirft die Montage ohnehin"
    assert len(dienst.angenommen) == 2, "genau ein Bild und ein Video"


def test_ohne_schema_traegt_die_dokumentierte_form(abo):
    """Liefert der Dienst kein Schema und keine lesbare Modellliste — der Zustand, in dem
    beim Kunden `kling2_6_pro` hinausging —, muss die dokumentierte Form tragen."""
    dienst = abo(mit_schema=False)
    kunde = higgsfield_mcp.HiggsfieldAbo()

    bild = kunde.bild("Motiv", seitenverhaeltnis="16:9")
    kunde.video_aus_bild("Bewegung", bild.url, dauer=5, seitenverhaeltnis="16:9",
                         modell="kling-video/v2.6/pro/image-to-video")

    video = [a["params"] for n, a in dienst.aufrufe if n == "generate_video"]
    assert video[0]["model"] == "kling2_6"
    assert video[0]["medias"] == [{"value": bild.request_id, "role": "start_image"}]
    assert len(video) == 1
    assert len(dienst.angenommen) == 2


def test_abgewiesene_formen_kosten_nichts_und_beenden_den_lauf(abo):
    """Nimmt der Dienst gar nichts an, darf nichts bestellt sein — und der Fehler muss
    tödlich sein, damit die nächste Szene nicht erst wieder ein Bild bezahlt."""
    from app import pipeline

    dienst = abo(mit_schema=True, weist_alles_ab=True)
    with pytest.raises(errors.KonfigurationsFehler) as info:
        higgsfield_mcp.HiggsfieldAbo().video_aus_text("Bewegung", dauer=5,
                                                      modell="kling3_0")
    assert dienst.angenommen == []
    versuche = [n for n, _ in dienst.aufrufe if n == "generate_video"]
    assert 1 <= len(versuche) <= higgsfield_mcp._MAX_FORMVERSUCHE
    assert "nichts abgerechnet" in info.value.hinweis
    assert isinstance(info.value, pipeline._TOEDLICH)


def test_gemerkte_form_spart_die_zweite_runde(abo):
    """Hat eine Form getragen, beginnt die nächste Szene gleich mit ihr."""
    dienst = abo(mit_schema=False)
    kunde = higgsfield_mcp.HiggsfieldAbo()
    for _ in range(2):
        bild = kunde.bild("Motiv")
        kunde.video_aus_bild("Bewegung", bild.url, dauer=5, modell="kling2_6")
    video = [n for n, _ in dienst.aufrufe if n == "generate_video"]
    assert len(video) == 2


def test_vorpruefung_kostet_nichts_und_waehlt_das_format(abo):
    dienst = abo(mit_schema=True)
    ergebnis = higgsfield_mcp.HiggsfieldAbo().vorpruefen(
        videomodell="kling-video/v2.6/pro/image-to-video",
        bildmodell="higgsfield-ai/soul/standard", seitenverhaeltnis="4:3", dauer=7)
    assert ergebnis["modell"] == "kling2_6"
    assert ergebnis["seitenverhaeltnis"] == "1:1"
    assert ergebnis["dauer"] in (5, 10)
    assert not [n for n, _ in dienst.aufrufe if n.startswith("generate_")], \
        "die Vorprüfung darf nichts bestellen"


def test_vorpruefung_ersetzt_ein_modell_das_der_dienst_nicht_fuehrt(abo):
    abo(mit_schema=True)
    kunde = higgsfield_mcp.HiggsfieldAbo()
    ergebnis = kunde.vorpruefen(videomodell="seedance_2_0", seitenverhaeltnis="9:16",
                                mit_startbild=False)
    assert ergebnis["modell"] in MODELLE
    # Und der Auftrag selbst nimmt dann auch den Ersatz:
    assert higgsfield_mcp.modell_aufloesen("seedance_2_0", "video") == ergebnis["modell"]


def test_bezahlter_auftrag_wird_abgeholt_statt_neu_bestellt(abo):
    dienst = abo(mit_schema=True)
    kunde = higgsfield_mcp.HiggsfieldAbo()
    gemeldet = {}
    bild = kunde.bild("Motiv", gemeldet=lambda k, m: gemeldet.update(bild=k))
    video = kunde.video_aus_bild("Bewegung", bild.url, dauer=5, modell="kling2_6",
                                 gemeldet=lambda k, m: gemeldet.update(video=k))
    vorher = len(dienst.angenommen)

    wieder = higgsfield_mcp.HiggsfieldAbo().video_aus_bild(
        "Bewegung", bild.url, dauer=5, modell="kling2_6", fortsetzen=gemeldet["video"])
    assert wieder.url == video.url
    assert len(dienst.angenommen) == vorher, "nichts darf doppelt bestellt werden"


def test_verlorene_antwort_wird_nie_nachbestellt(abo, monkeypatch):
    """Die Gegenprüfung vom 11.09.2026, schwerster Befund: Der Dienst nimmt den
    Videoauftrag an und rechnet ab, aber die Antwort geht verloren (Zeitlimit, Gateway).
    Früher folgten bis zu drei weitere Bestellungen — jede womöglich bezahlt.

    Nachgestellt ist genau das: Die Anfrage erreicht die Attrappe (und wird dort
    angenommen), erst danach reißt die Leitung.
    """
    import httpx

    dienst = abo(mit_schema=True)
    monkeypatch.setattr(higgsfield_mcp.config, "MAX_RETRIES", 3)
    kunde = higgsfield_mcp.HiggsfieldAbo()
    bild = kunde.bild("Motiv")

    echter = higgsfield_mcp._klient()

    class VerloreneAntwort:
        is_closed = False

        def post(self, adresse, **benannt):
            antwort = echter.post(adresse, **benannt)
            anfrage = benannt.get("json") or {}
            if (anfrage.get("method") == "tools/call"
                    and anfrage["params"]["name"] == "generate_video"):
                raise httpx.ReadTimeout("Antwort unterwegs verloren")
            return antwort

    monkeypatch.setattr(higgsfield_mcp, "_klient", lambda: VerloreneAntwort())
    with pytest.raises(errors.UnklarFehler):
        kunde.video_aus_bild("Bewegung", bild.url, dauer=5, modell="kling2_6")

    videos = [n for n, _ in dienst.aufrufe if n == "generate_video"]
    assert len(videos) == 1, "nach verlorener Antwort darf nichts nachbestellt werden"
    assert sum(1 for k in dienst.angenommen if k.startswith("video")) == 1


def test_moderation_ist_kein_formfehler(abo, monkeypatch):
    """Lehnt der Dienst den Inhalt ab, hilft keine andere Form — und kein anderes Modell."""
    dienst = abo(mit_schema=True)
    monkeypatch.setattr(dienst, "rufen", lambda name, argumente: (
        dienst.aufrufe.append((name, argumente)) or
        Dienst._fehler("Request blocked by content policy (nsfw)")))
    with pytest.raises(errors.InhaltFehler):
        higgsfield_mcp.HiggsfieldAbo().video_aus_text("Bewegung", dauer=5, modell="kling2_6")
    assert len([n for n, _ in dienst.aufrufe if n == "generate_video"]) == 1


def test_verweise_mit_listenindex_werden_aufgeloest():
    """zod-to-json-schema verweist gern auf `#/properties/params/anyOf/0/...`."""
    schema = {"type": "object", "properties": {"params": {"anyOf": [
        {"type": "object", "properties": {
            "model": {"const": "kling2_6"},
            "duration": {"type": "integer", "enum": [5, 10]}}},
        {"type": "object", "properties": {
            "model": {"const": "kling3_0"},
            "duration": {"$ref": "#/properties/params/anyOf/0/properties/duration"}}},
    ]}}}
    form = higgsfield_mcp._form_aus_schema(schema, "kling3_0")
    assert form.werte["duration"] == [5, 10]


def test_nummer_wird_auch_verschachtelt_gefunden():
    nummer = higgsfield_mcp._auftragsnummer
    assert nummer({"job": {"id": "j-1"}}) == "j-1"
    assert nummer({"data": {"results": [{"id": "d-2"}]}}) == "d-2"
    assert nummer({"results": ["r-3"]}) == "r-3"
    assert nummer({"text": "Job 123e4567-e89b-12d3-a456-426614174000 created"}) == \
        "123e4567-e89b-12d3-a456-426614174000"
    assert nummer({"error": "kaputt"}) == ""


def test_werkzeugschema_wird_gelesen(abo):
    abo(mit_schema=True)
    form = higgsfield_mcp.parameterform("generate_video", "kling3_0")
    assert form.bekannt and form.huelle
    assert set(form.modelle) == set(MODELLE)
    assert form.medien_felder == ("value", "role")
    assert "start_image" in form.medien_rollen
    assert form.werte["duration"] == [5, 10, 15]
    assert "medias[" in form.kurz()


def test_zeitmessung_bleibt_im_rahmen(abo):
    """Die Formsuche darf nicht trödeln — ohne Wiederholungen ist sie in Sekunden durch."""
    abo(mit_schema=False, weist_alles_ab=True)
    anfang = time.monotonic()
    with pytest.raises(errors.KonfigurationsFehler):
        higgsfield_mcp.HiggsfieldAbo().bild("Motiv")
    assert time.monotonic() - anfang < 20


# ── Befunde der Prüfung vom 25.09.2026 ───────────────────────────────────────
#
# Jeder Test unten hält einen Befund fest. Keiner spricht mit dem echten Dienst:
# `werkzeug_rufen`, der HTTP-Client oder der Token-Endpunkt sind jeweils ersetzt.

import urllib.parse as _urlparse          # noqa: E402
import urllib.request as _urlrequest      # noqa: E402

from app import config                    # noqa: E402


@pytest.fixture
def ohne_dienst(monkeypatch):
    """Kein Schema, keine Modellliste, keine Wiederholungen, keine Wartezeit."""
    jetzt = time.time()
    monkeypatch.setattr(higgsfield_mcp, "_WERKZEUGE",
                        {"zeit": 0.0, "liste": [], "schemata": {}, "fehlzeit": jetzt})
    monkeypatch.setattr(higgsfield_mcp, "_MODELLE",
                        {"zeit": 0.0, "liste": [], "fehlzeit": jetzt})
    monkeypatch.setattr(higgsfield_mcp, "_FORM_GEMERKT", {})
    monkeypatch.setattr(higgsfield_mcp, "_ERSATZ", {})
    monkeypatch.setattr(higgsfield_mcp, "_BILDJOBS", {})
    monkeypatch.setattr(config, "MAX_RETRIES", 0)
    monkeypatch.setattr(config, "POLL_INTERVAL", 0)


def _falscher_dienst(monkeypatch, bestellung, stand=None):
    """Ersetzt `werkzeug_rufen`; zählt, was hinausgeht."""
    aufrufe: list[tuple[str, dict]] = []

    def rufen(name, argumente, zeitlimit=60):
        aufrufe.append((name, argumente))
        if name.startswith("generate_"):
            return bestellung(argumente) if callable(bestellung) else bestellung
        if name == "job_status":
            return (stand or {"status": "completed",
                              "result_url": "https://ablage.test/clip.mp4"})
        return {}

    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen", rufen)
    return aufrufe


# Befund 1: Antwort ohne Nummer und ohne Fehler → unklar, nie nachbestellen

@pytest.mark.parametrize("antwort", [
    {"status": "queued"},
    {"text": "Job started"},
    {"results": []},
    {},
])
def test_antwort_ohne_nummer_und_ohne_fehler_ist_unklar(monkeypatch, ohne_dienst, antwort):
    from app import pipeline

    aufrufe = _falscher_dienst(monkeypatch, antwort)
    with pytest.raises(errors.UnklarFehler) as info:
        higgsfield_mcp.HiggsfieldAbo().video_aus_text("Bewegung", dauer=5,
                                                      modell="kling2_6")
    assert len([n for n, _ in aufrufe if n == "generate_video"]) == 1, \
        "womöglich angenommen — es darf keine zweite Form hinausgehen"
    assert isinstance(info.value, pipeline._TOEDLICH)


@pytest.mark.parametrize("feld", ["task_id", "taskId", "uuid"])
def test_weitere_nummernfelder_werden_erkannt(monkeypatch, ohne_dienst, feld):
    _falscher_dienst(monkeypatch, {"status": "queued", feld: "t-1"})
    ergebnis = higgsfield_mcp.HiggsfieldAbo().video_aus_text("Bewegung", dauer=5,
                                                             modell="kling2_6")
    assert ergebnis.request_id == "t-1"


# Befund 10: Die Kennung des Startbilds ist nie die Nummer des Videoauftrags

BILD_UUID = "11111111-2222-3333-4444-555555555555"
VIDEO_UUID = "99999999-8888-7777-6666-555555555555"


def test_gesendete_kennung_wird_nicht_als_auftragsnummer_genommen():
    nummer = higgsfield_mcp._auftragsnummer
    text = {"text": f"Using start image {BILD_UUID}, job {VIDEO_UUID} queued"}
    assert nummer(text) == BILD_UUID                       # ohne Ausschluss: falsch
    assert nummer(text, {BILD_UUID}) == VIDEO_UUID
    assert nummer({"text": f"start image {BILD_UUID}"}, {BILD_UUID}) == ""
    assert nummer({"results": [{"id": BILD_UUID}]}, {BILD_UUID}) == ""


def test_video_holt_nicht_das_startbild_ab(monkeypatch, ohne_dienst):
    higgsfield_mcp._bild_merken("https://ablage.test/bild.jpg", BILD_UUID)
    _falscher_dienst(monkeypatch, {"text": f"Accepted media {BILD_UUID}. "
                                           f"Job {VIDEO_UUID} started."})
    ergebnis = higgsfield_mcp.HiggsfieldAbo().video_aus_bild(
        "Bewegung", "https://ablage.test/bild.jpg", dauer=5, modell="kling2_6")
    assert ergebnis.request_id == VIDEO_UUID


def test_nur_das_startbild_im_text_ist_unklar(monkeypatch, ohne_dienst):
    higgsfield_mcp._bild_merken("https://ablage.test/bild.jpg", BILD_UUID)
    aufrufe = _falscher_dienst(monkeypatch, {"text": f"Accepted media {BILD_UUID}."})
    with pytest.raises(errors.UnklarFehler):
        higgsfield_mcp.HiggsfieldAbo().video_aus_bild(
            "Bewegung", "https://ablage.test/bild.jpg", dauer=5, modell="kling2_6")
    assert len([n for n, _ in aufrufe if n == "generate_video"]) == 1


# Befund 13: JSON-RPC „Invalid params“ ist ein Formfehler

def test_rpc_formfehler_wird_zum_fehlertext():
    for fehler in ({"code": -32602, "message": "Bad arguments"},
                   {"code": -32000, "message": "Input validation error: params"}):
        antwort = higgsfield_mcp._ergebnis([{"id": 5, "error": fehler}], 5)
        assert antwort.get("error")
        assert higgsfield_mcp._eingabefehler(antwort)
    with pytest.raises(errors.AnbieterFehler):
        higgsfield_mcp._ergebnis([{"id": 5, "error": {"code": -32603,
                                                     "message": "internal"}}], 5)


def test_rpc_formfehler_loest_die_formsuche_aus(monkeypatch, ohne_dienst):
    higgsfield_mcp._bild_merken("https://ablage.test/bild.jpg", "bild-1")
    versuche = []

    def bestellung(argumente):
        versuche.append(argumente)
        if len(versuche) == 1:
            return higgsfield_mcp._ergebnis(
                [{"id": 5, "error": {"code": -32602, "message": "Invalid params"}}], 5)
        return {"results": [{"id": "video-2"}]}

    _falscher_dienst(monkeypatch, bestellung)
    ergebnis = higgsfield_mcp.HiggsfieldAbo().video_aus_bild(
        "Bewegung", "https://ablage.test/bild.jpg", dauer=5, modell="kling2_6")
    assert ergebnis.request_id == "video-2"
    assert len(versuche) == 2


# Befund 8: Abbruch und Zeitlimit stornieren beim Dienst

def test_abbruch_beim_warten_storniert_den_abo_auftrag(monkeypatch, ohne_dienst):
    signal = threading.Event()

    def stand_und_abbruch():
        signal.set()                      # der Kunde klickt, während der Auftrag läuft
        return {"status": "in_progress"}

    aufrufe: list[str] = []

    def rufen(name, argumente, zeitlimit=60):
        aufrufe.append(name)
        if name == "generate_video":
            return {"results": [{"id": "v-8"}]}
        if name == "job_status":
            return stand_und_abbruch()
        return {}

    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen", rufen)
    with pytest.raises(errors.AbbruchFehler):
        higgsfield_mcp.HiggsfieldAbo().video_aus_text("Bewegung", dauer=5,
                                                      modell="kling2_6", abbruch=signal)
    assert "cancel_job" in aufrufe


def test_zeitlimit_beim_warten_storniert_den_abo_auftrag(monkeypatch, ohne_dienst):
    monkeypatch.setattr(config, "JOB_TIMEOUT", -1)
    aufrufe = _falscher_dienst(monkeypatch, {"results": [{"id": "v-9"}]},
                               stand={"status": "in_progress"})
    with pytest.raises(errors.ZeitFehler):
        higgsfield_mcp.HiggsfieldAbo().video_aus_text("Bewegung", dauer=5,
                                                      modell="kling2_6")
    assert ("cancel_job", {"jobId": "v-9"}) in aufrufe


def test_fehler_beim_stornieren_verdeckt_den_abbruch_nicht(monkeypatch, ohne_dienst):
    monkeypatch.setattr(config, "JOB_TIMEOUT", -1)
    _falscher_dienst(monkeypatch, {"results": [{"id": "v-10"}]})
    monkeypatch.setattr(higgsfield_mcp.HiggsfieldAbo, "abbrechen",
                        lambda self, k: (_ for _ in ()).throw(RuntimeError("kaputt")))
    with pytest.raises(errors.ZeitFehler):
        higgsfield_mcp.HiggsfieldAbo().video_aus_text("Bewegung", dauer=5,
                                                      modell="kling2_6")


def test_stornieren_meldet_den_fehler_des_dienstes(monkeypatch):
    kunde = higgsfield_mcp.HiggsfieldAbo()
    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen",
                        lambda *a, **k: {"error": "job already completed"})
    assert kunde.abbrechen("x") is False
    monkeypatch.setattr(higgsfield_mcp, "werkzeug_rufen",
                        lambda *a, **k: {"status": "cancelled"})
    assert kunde.abbrechen("x") is True


# Befund 9: Die vorgeschlagene Pause des Dienstes ist begrenzt

@pytest.mark.parametrize("vorschlag,erwartet", [
    (5, 5.0), ("7", 7.0), (0, 1.0), (-3, 1.0), (3600, 30.0), (1e308 * 10, None),
    ("bald", None), (None, None), ("", None), ([1], None),
])
def test_abfragepause_ist_robust_und_begrenzt(monkeypatch, vorschlag, erwartet):
    monkeypatch.setattr(config, "POLL_INTERVAL", 4)
    pause = higgsfield_mcp._abfragepause({"poll_after_seconds": vorschlag})
    assert pause == (4.0 if erwartet is None else erwartet)


def test_warten_hoert_sofort_auf_den_abbruch():
    signal = threading.Event()
    signal.set()
    anfang = time.monotonic()
    higgsfield_mcp._schlafen(30, signal)
    assert time.monotonic() - anfang < 1


# Befund 5 und 6: Anmeldung

class _Zuhoerer(higgsfield_mcp.HTTPServer):
    """HTTPServer, der mitschreibt, wie er beendet wird."""
    protokoll: list[str] = []

    def shutdown(self):
        _Zuhoerer.protokoll.append("shutdown")
        super().shutdown()

    def server_close(self):
        _Zuhoerer.protokoll.append("server_close")
        super().server_close()


def _ohne_proxy_abrufen(adresse: str) -> int:
    oeffner = _urlrequest.build_opener(_urlrequest.ProxyHandler({}))
    try:
        with oeffner.open(adresse, timeout=5) as antwort:
            return antwort.status
    except _urlrequest.HTTPError as fehler:
        return fehler.code


def test_gescheiterte_registrierung_haengt_nicht(monkeypatch):
    """`shutdown()` ohne laufendes `serve_forever` wartete ewig — die Anmeldung hing."""
    _Zuhoerer.protokoll = []
    monkeypatch.setattr(higgsfield_mcp, "HTTPServer", _Zuhoerer)
    monkeypatch.setattr(higgsfield_mcp, "_oauth_auskunft", lambda: {
        "authorization_endpoint": "https://anmeldung.test/authorize",
        "token_endpoint": "https://anmeldung.test/token",
        "registration_endpoint": "https://anmeldung.test/register"})

    def scheitern(_adresse):
        raise errors.NetzFehler("Registrierung gescheitert")

    monkeypatch.setattr(higgsfield_mcp, "_registrieren", scheitern)
    ausgang: dict = {}

    def anmelden():
        try:
            higgsfield_mcp._anmelden(False, 5)
        except Exception as fehler:            # noqa: BLE001
            ausgang["fehler"] = fehler

    faden = threading.Thread(target=anmelden, daemon=True)
    faden.start()
    faden.join(timeout=10)
    assert not faden.is_alive(), "die Anmeldung hängt"
    assert isinstance(ausgang.get("fehler"), errors.NetzFehler)
    assert _Zuhoerer.protokoll == ["server_close"]


def test_rueckruf_wertet_nur_den_rueckrufpfad_aus(monkeypatch):
    empfaenger = higgsfield_mcp.HTTPServer(("127.0.0.1", 0),
                                           higgsfield_mcp._RueckrufEmpfaenger)
    monkeypatch.setattr(higgsfield_mcp._RueckrufEmpfaenger, "ergebnis", {})
    monkeypatch.setattr(higgsfield_mcp._RueckrufEmpfaenger, "pfad", "/callback")
    threading.Thread(target=empfaenger.serve_forever, daemon=True).start()
    basis = f"http://127.0.0.1:{empfaenger.server_address[1]}"
    try:
        assert _ohne_proxy_abrufen(basis + "/favicon.ico") == 404
        assert higgsfield_mcp._RueckrufEmpfaenger.ergebnis == {}
        assert _ohne_proxy_abrufen(basis + "/callback?code=erster&state=s1") == 200
        assert _ohne_proxy_abrufen(basis + "/favicon.ico") == 404
        assert _ohne_proxy_abrufen(basis + "/callback?code=zweiter&state=s2") == 200
        ergebnis = higgsfield_mcp._RueckrufEmpfaenger.ergebnis
        assert ergebnis["code"] == "erster", "ein empfangener Code wird nie überschrieben"
        assert ergebnis["state"] == "s1"
    finally:
        empfaenger.shutdown()
        empfaenger.server_close()


@pytest.mark.parametrize("zustand", [None, "falsch"])
def test_rueckruf_ohne_passenden_zustand_wird_abgewiesen(monkeypatch, zustand):
    monkeypatch.setattr(higgsfield_mcp, "_oauth_auskunft", lambda: {
        "authorization_endpoint": "https://anmeldung.test/authorize",
        "token_endpoint": "https://anmeldung.test/token",
        "registration_endpoint": "https://anmeldung.test/register"})
    monkeypatch.setattr(higgsfield_mcp, "_registrieren",
                        lambda _a: {"client_id": "anwendung-1", "client_secret": ""})

    class KeinNetz:
        def __init__(self, *_a, **_k):
            raise AssertionError("der Code darf nicht eingelöst werden")

    monkeypatch.setattr(higgsfield_mcp.httpx, "Client", KeinNetz)
    monkeypatch.setitem(higgsfield_mcp._anmeldung, "url", "")
    ausgang: dict = {}

    def anmelden():
        try:
            higgsfield_mcp._anmelden(False, 10)
        except Exception as fehler:            # noqa: BLE001
            ausgang["fehler"] = fehler

    faden = threading.Thread(target=anmelden, daemon=True)
    faden.start()
    for _ in range(100):
        if higgsfield_mcp._anmeldung["url"]:
            break
        time.sleep(0.05)
    felder = _urlparse.parse_qs(_urlparse.urlparse(higgsfield_mcp._anmeldung["url"]).query)
    rueckruf = felder["redirect_uri"][0].replace("localhost", "127.0.0.1")
    anhang = "?code=abc" + (f"&state={zustand}" if zustand else "")
    assert _ohne_proxy_abrufen(rueckruf + anhang) == 200
    faden.join(timeout=10)
    assert not faden.is_alive()
    assert isinstance(ausgang.get("fehler"), errors.ZugangFehler)


# Befund 7: Token-Erneuerung

class _TokenAntwort:
    def __init__(self, code: int, rumpf):
        self.status_code = code
        self._rumpf = rumpf
        self.text = rumpf if isinstance(rumpf, str) else json.dumps(rumpf)

    def json(self):
        if isinstance(self._rumpf, str):
            return json.loads(self._rumpf)
        return self._rumpf


def _token_endpunkt(monkeypatch, *antworten, verzoegerung: float = 0.0):
    """Ersetzt `httpx.Client` im Modul; gibt die Liste der Token-Anfragen zurück."""
    anfragen: list[dict] = []
    liste = list(antworten)

    class Klient:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def post(self, adresse, data=None, **_k):
            anfragen.append(dict(data or {}))
            time.sleep(verzoegerung)
            return liste.pop(0) if len(liste) > 1 else liste[0]

    monkeypatch.setattr(higgsfield_mcp.httpx, "Client", Klient)
    return anfragen


def _abgelaufene_anmeldung():
    higgsfield_mcp._speichern({"client_id": "c", "access_token": "alt",
                               "refresh_token": "erneuerung-alt",
                               "token_endpoint": "https://anmeldung.test/token",
                               "gueltig_bis": time.time() - 10})


def test_gleichzeitige_erneuerung_fragt_nur_einmal(monkeypatch):
    _abgelaufene_anmeldung()
    anfragen = _token_endpunkt(
        monkeypatch, _TokenAntwort(200, {"access_token": "neu", "expires_in": 3600,
                                         "refresh_token": "erneuerung-neu"}),
        verzoegerung=0.2)
    ergebnisse: list[str] = []
    faeden = [threading.Thread(target=lambda: ergebnisse.append(
        higgsfield_mcp._gueltiges_token())) for _ in range(4)]
    for faden in faeden:
        faden.start()
    for faden in faeden:
        faden.join(timeout=10)
    assert ergebnisse == ["neu"] * 4
    assert len(anfragen) == 1, "rotierende Erneuerung: nur ein Faden darf erneuern"
    assert higgsfield_mcp._laden()["refresh_token"] == "erneuerung-neu"


@pytest.mark.parametrize("code", [429, 500, 502, 503])
def test_gestoerter_token_endpunkt_ist_wiederholbar(monkeypatch, code):
    _abgelaufene_anmeldung()
    _token_endpunkt(monkeypatch, _TokenAntwort(code, "kaputt"))
    with pytest.raises(errors.NetzFehler) as info:
        higgsfield_mcp._gueltiges_token()
    assert info.value.wiederholbar


def test_abgelehnte_erneuerung_ist_ein_zugangsfehler(monkeypatch):
    _abgelaufene_anmeldung()
    _token_endpunkt(monkeypatch, _TokenAntwort(400, {"error": "invalid_grant"}))
    with pytest.raises(errors.ZugangFehler):
        higgsfield_mcp._gueltiges_token()


def test_unlesbare_token_antwort_bricht_nicht_ab(monkeypatch):
    _abgelaufene_anmeldung()
    _token_endpunkt(monkeypatch, _TokenAntwort(200, "<html>kein JSON</html>"))
    with pytest.raises(errors.NetzFehler):
        higgsfield_mcp._gueltiges_token()
    assert higgsfield_mcp._laden()["access_token"] == "alt", "nichts kaputtgespeichert"


def test_unsinniges_expires_in_wird_vertragen(monkeypatch):
    _abgelaufene_anmeldung()
    _token_endpunkt(monkeypatch, _TokenAntwort(200, {"access_token": "neu",
                                                     "expires_in": "bald"}))
    assert higgsfield_mcp._gueltiges_token() == "neu"
    assert higgsfield_mcp._laden()["gueltig_bis"] > time.time()


def test_speichern_hinterlaesst_keine_zwischendatei():
    for nummer in range(3):
        higgsfield_mcp._speichern({"access_token": f"t{nummer}"})
    ordner = higgsfield_mcp._anmeldedatei.parent
    assert not list(ordner.glob("*.tmp"))
    assert higgsfield_mcp._laden()["access_token"] == "t2"


class _RpcAntwort:
    def __init__(self, code: int, ergebnis=None, kennung=None):
        self.status_code = code
        self.headers = {"content-type": "application/json", "mcp-session-id": "s"}
        self.text = json.dumps({"jsonrpc": "2.0", "id": kennung, "result": ergebnis}) \
            if ergebnis is not None else "abgelehnt"


def _rpc_klient(monkeypatch, codes: list[int]):
    """Falscher HTTP-Client für `_rpc`: Eröffnung klappt, der Aufruf antwortet der
    Reihe nach mit `codes`."""
    aufrufe: list[tuple[str, str]] = []

    class Klient:
        is_closed = False

        def post(self, _adresse, headers=None, json=None, **_k):
            methode = (json or {}).get("method", "")
            if methode in ("initialize", "notifications/initialized"):
                return _RpcAntwort(200, {}, (json or {}).get("id"))
            aufrufe.append((methode, headers["Authorization"]))
            code = codes.pop(0) if len(codes) > 1 else codes[0]
            ergebnis = {"structuredContent": {"results": [{"id": "v-401"}]}}
            return _RpcAntwort(code, ergebnis if code == 200 else None, json["id"])

    monkeypatch.setattr(higgsfield_mcp, "_klient", lambda: Klient())
    monkeypatch.setattr(higgsfield_mcp, "_gueltiges_token", lambda: "alt")
    monkeypatch.setattr(higgsfield_mcp, "_token_erneuern", lambda abgelehnt: "neu")
    return aufrufe


@pytest.mark.parametrize("werkzeug", ["job_status", "generate_video"])
def test_401_erneuert_einmal_und_wiederholt(monkeypatch, werkzeug):
    """401 heißt: vor jeder Verarbeitung abgewiesen — auch eine Bestellung ist dann
    nicht angenommen und darf einmal wiederholt werden."""
    aufrufe = _rpc_klient(monkeypatch, [401, 200])
    antwort = higgsfield_mcp.werkzeug_rufen(werkzeug, {"params": {}})
    assert antwort["results"][0]["id"] == "v-401"
    assert [kopf for _m, kopf in aufrufe] == ["Bearer alt", "Bearer neu"]


def test_zweites_401_ist_ein_zugangsfehler(monkeypatch):
    aufrufe = _rpc_klient(monkeypatch, [401])
    with pytest.raises(errors.ZugangFehler):
        higgsfield_mcp.werkzeug_rufen("generate_video", {"params": {}})
    assert len(aufrufe) == 2, "genau eine Wiederholung"


def test_bestellung_mit_5xx_wird_nicht_wiederholt(monkeypatch):
    aufrufe = _rpc_klient(monkeypatch, [502, 200])
    with pytest.raises(errors.UnklarFehler):
        higgsfield_mcp.werkzeug_rufen("generate_video", {"params": {}})
    assert len(aufrufe) == 1


# Befund 15: 403 im Abo nennt nicht den API-Schlüssel

def test_403_im_abo_hat_einen_eigenen_hinweis(monkeypatch):
    _rpc_klient(monkeypatch, [403])
    with pytest.raises(errors.ZugangFehler) as info:
        higgsfield_mcp.werkzeug_rufen("job_status", {})
    assert "HIGGSFIELD_API_KEY" not in info.value.hinweis
    assert "Anmeldung" in info.value.hinweis


# Befund 16: Die Marken der Abo-Anmeldung werden geschwärzt

def test_marken_der_anmeldung_werden_geschwaerzt(monkeypatch):
    monkeypatch.setattr(config, "_WEITERE_GEHEIMNISSE", {})
    marken = {"access_token": "zugriff-" + "a" * 30, "refresh_token": "erneuer-" + "b" * 30,
              "client_secret": "geheim-" + "c" * 30}
    higgsfield_mcp._speichern(marken)
    text = config.entschaerfe("Fehler: " + " ".join(marken.values()))
    for wert in marken.values():
        assert wert not in text

    # Auch was nur von der Platte gelesen wird (Programmstart), zählt.
    monkeypatch.setattr(config, "_WEITERE_GEHEIMNISSE", {})
    higgsfield_mcp._laden()
    assert marken["refresh_token"] not in config.entschaerfe(marken["refresh_token"])


def test_kurze_werte_werden_nicht_gemerkt(monkeypatch):
    monkeypatch.setattr(config, "_WEITERE_GEHEIMNISSE", {})
    config.geheimnis_merken("kurz")
    config.geheimnis_merken("")
    assert config.entschaerfe("kurz") == "kurz"
