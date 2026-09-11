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
