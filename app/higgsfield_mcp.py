"""
higgsfield_mcp.py — Higgsfield über den MCP-Dienst, also über die Abo-Credits.

**Warum es diesen zweiten Weg gibt.** Higgsfield führt zwei getrennte Guthaben: die
Credits des Web-Abos (Soul/Plus) und die der Platform-API. Ein Jahresabo füllt den
API-Topf nicht — am 03.08.2026 belegt: derselbe Schlüssel, der `GET /v1/motions` mit 200
beantwortet, bekommt bei jedem Auftrag `403 not_enough_credits`. An die Abo-Credits kommt
man ausschließlich über `mcp.higgsfield.ai`, und der will keine Schlüssel, sondern eine
Anmeldung.

**Wie die Anmeldung abläuft.** Einmalig: Das Programm meldet sich selbst als Anwendung an
(dynamische Registrierung nach RFC 7591), erzeugt eine Anmelde-URL mit PKCE und nimmt den
Rückruf auf einem lokalen Port entgegen. Danach liegt ein Erneuerungstoken auf der Platte,
und alle weiteren Starts laufen ohne Browser.

**Was der Dienst spricht.** MCP über HTTP, Antworten wahlweise als JSON oder als
Ereignisstrom. Der Ablauf ist derselbe wie bei der Platform-API, nur anders verpackt:

    tools/call generate_image {params:{model, prompt, aspect_ratio, count}} → results[0].id
    tools/call job_status      {jobId, sync:true, raw_data:true}            → result_url

Die Schnittstelle nach außen ist absichtlich Zeichen für Zeichen dieselbe wie beim
Platform-Client (`bild`, `video_aus_bild`, `video_aus_text`, `herunterladen`,
`selbsttest`) — die Ablaufsteuerung merkt nicht, mit wem sie spricht.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

from . import config, errors, higgsfield, logbook

QUELLE = "Higgsfield (Abo)"

_ISSUER = "https://mcp.higgsfield.ai"
_MCP_URL = _ISSUER + "/mcp"
_SCOPE = "openid email offline_access"
_PROTOKOLL = "2025-06-18"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# ── Modellnamen: der Abo-Dienst spricht eine andere Sprache ──────────────────
#
# Platform-API und MCP-Dienst benennen dieselben Modelle unterschiedlich. Die
# Platform kennt Pfade wie ``higgsfield-ai/soul/standard``; der MCP-Dienst kennt
# kurze Kennungen ohne Schrägstrich. Reicht man einen Platform-Namen durch,
# antwortet er mit
#
#     unknown model "higgsfield-ai/soul/standard".
#     Use models_explore(action:'list') to see available models.
#
# und der Auftrag ist gescheitert, bevor er begonnen hat. Genau das ist am
# 26.08.2026 beim Kunden passiert: die Ablaufsteuerung reicht den Namen aus der
# .env weiter, und dieser Client hat ihn ungeprüft übernommen.
#
# Zwei Sicherungen übereinander, damit das nicht wiederkommt:
#   1. **Kein Platform-Name geht je hinaus.** Alles mit Schrägstrich wird übersetzt.
#   2. **Der Dienst hat das letzte Wort.** `models_explore` liefert seine eigene
#      Liste; die schlägt jede Tabelle, falls Higgsfield umbenennt oder erweitert.
#
# Die Tabelle ist bewusst eine Kandidatenliste, keine feste Zuordnung: Es wird der
# erste Eintrag genommen, den der Dienst tatsächlich führt.

#: Rückfallnamen, falls `models_explore` nicht antwortet.
_BILDMODELL = "soul_2"
_VIDEOMODELL = "kling2_5_turbo"

#: Platform-Modell → Wunschnamen beim MCP-Dienst, bester zuerst.
_UEBERSETZUNG: dict[str, tuple[str, ...]] = {
    "higgsfield-ai/soul/standard": ("soul_2", "soul", "soul_standard", "soul_1"),
    "higgsfield-ai/soul/turbo/standard": ("soul_2_turbo", "soul_turbo", "soul_2", "soul"),
    "kling-video/v2.6/pro/image-to-video": ("kling2_6_pro", "kling_2_6_pro",
                                            "kling2_5_turbo", "kling3_0_turbo"),
    "kling-video/v2.1/master/image-to-video": ("kling2_1_master", "kling2_1",
                                               "kling2_5_turbo"),
    "kling-video/v2.1/standard/image-to-video": ("kling2_1_standard", "kling2_1",
                                                 "kling2_5_turbo"),
    "higgsfield-ai/dop/turbo": ("dop_turbo", "higgsfield_dop_turbo", "dop"),
    "higgsfield-ai/dop/standard": ("dop_standard", "higgsfield_dop", "dop"),
    "minimax/hailuo-02/standard/text-to-video": ("hailuo_02_standard", "hailuo_02",
                                                 "minimax_hailuo_02"),
    "minimax/hailuo-02/pro/text-to-video": ("hailuo_02_pro", "hailuo_02",
                                            "minimax_hailuo_02"),
}

#: Wortteile, an denen sich ein Bild- von einem Videomodell unterscheiden lässt.
_BILDWORTE = ("soul", "image", "img", "photo", "flux", "seedream", "nano", "banana")
_VIDEOWORTE = ("kling", "video", "hailuo", "dop", "veo", "seedance", "wan", "minimax")

#: Gemerkte Modellliste des Dienstes — einmal je Stunde frisch geholt.
_MODELLE: dict = {"zeit": 0.0, "liste": []}
_MODELLE_FRISCHE = 3600.0

_anmeldedatei = config.DATA_DIR / "higgsfield_abo.json"
_sperre = threading.Lock()
_auskunft: dict = {}


# ── Anmeldedaten auf der Platte ──────────────────────────────────────────────

def _laden() -> dict:
    try:
        return json.loads(_anmeldedatei.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _speichern(daten: dict) -> None:
    try:
        vorlaeufig = _anmeldedatei.with_suffix(".tmp")
        vorlaeufig.write_text(json.dumps(daten, indent=2), encoding="utf-8")
        vorlaeufig.replace(_anmeldedatei)
    except Exception as fehler:
        logbook.warnung(QUELLE, f"Anmeldedaten nicht gespeichert: {type(fehler).__name__}")


def angemeldet() -> bool:
    daten = _laden()
    return bool(daten.get("refresh_token") or daten.get("access_token"))


def abmelden() -> dict:
    try:
        _anmeldedatei.unlink(missing_ok=True)
    except Exception:
        pass
    logbook.info(QUELLE, "Abmeldung abgeschlossen.")
    return {"ok": True}


def _oauth_auskunft() -> dict:
    """Endpunkte des Anmeldedienstes, einmal geholt und dann gemerkt."""
    if _auskunft:
        return _auskunft
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": _UA}) as klient:
            daten = klient.get(f"{_ISSUER}/.well-known/oauth-authorization-server").json()
    except Exception as fehler:
        raise errors.NetzFehler(
            "Der Higgsfield-Anmeldedienst ist nicht erreichbar.",
            "Internetverbindung prüfen.", ursprung=QUELLE) from fehler
    _auskunft.update({
        "authorization_endpoint": daten.get("authorization_endpoint",
                                            f"{_ISSUER}/oauth2/authorize"),
        "token_endpoint": daten.get("token_endpoint", f"{_ISSUER}/oauth2/token"),
        "registration_endpoint": daten.get("registration_endpoint",
                                           f"{_ISSUER}/oauth2/register"),
    })
    return _auskunft


# ── Anmeldung ────────────────────────────────────────────────────────────────

class _RueckrufEmpfaenger(BaseHTTPRequestHandler):
    """Nimmt die Antwort des Anmeldedienstes entgegen. Läuft nur während der Anmeldung."""

    ergebnis: dict = {}

    def do_GET(self):                                    # noqa: N802
        felder = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _RueckrufEmpfaenger.ergebnis = {
            "code": (felder.get("code") or [""])[0],
            "state": (felder.get("state") or [""])[0],
            "fehler": (felder.get("error") or [""])[0],
        }
        geklappt = bool(_RueckrufEmpfaenger.ergebnis["code"])
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        inhalt = ("<h2>Higgsfield verbunden</h2><p>Sie können dieses Fenster schließen "
                  "und zum Programm zurückkehren.</p>" if geklappt else
                  "<h2>Anmeldung fehlgeschlagen</h2><p>Bitte im Programm erneut versuchen.</p>")
        self.wfile.write(
            f"<html><head><meta charset='utf-8'></head>"
            f"<body style='font-family:Segoe UI,sans-serif;background:#0A0B0D;color:#F2F4F7;"
            f"padding:48px'>{inhalt}</body></html>".encode("utf-8"))

    def log_message(self, *_a):                          # Serverprotokoll unterdrücken
        return


def _registrieren(rueckruf_adresse: str) -> dict:
    """Meldet das Programm als Anwendung an. Nachgewiesen funktionsfähig (HTTP 201)."""
    auskunft = _oauth_auskunft()
    try:
        with httpx.Client(timeout=25, headers={"User-Agent": _UA}) as klient:
            antwort = klient.post(auskunft["registration_endpoint"], json={
                "client_name": config.APP_NAME,
                "redirect_uris": [rueckruf_adresse],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": _SCOPE,
            })
    except Exception as fehler:
        raise errors.NetzFehler("Die Anmeldung ließ sich nicht vorbereiten.",
                                "Internetverbindung prüfen.", ursprung=QUELLE) from fehler
    if antwort.status_code not in (200, 201):
        raise errors.AnbieterFehler(
            f"Higgsfield lehnt die Anmeldung ab (Code {antwort.status_code}).",
            config.entschaerfe(antwort.text[:200]), ursprung=QUELLE)
    daten = antwort.json()
    return {"client_id": daten.get("client_id", ""),
            "client_secret": daten.get("client_secret", "")}


def _pkce() -> tuple[str, str]:
    """Nachweis, dass derselbe Absender den Code einlöst, der ihn angefordert hat."""
    pruefwort = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    abdruck = base64.urlsafe_b64encode(
        hashlib.sha256(pruefwort.encode()).digest()).rstrip(b"=").decode()
    return pruefwort, abdruck


#: Zustand der laufenden Anmeldung, damit die Oberfläche zusehen kann.
_anmeldung: dict = {"laeuft": False, "url": "", "ergebnis": None, "seit": 0.0}


def anmeldung_starten(browser_oeffnen: bool = True, wartezeit: int = 300) -> dict:
    """Startet die Anmeldung und gibt sofort die Anmelde-URL zurück.

    Der Rückruf wird im Hintergrund abgewartet; die Oberfläche fragt über
    `anmeldung_stand()` nach. So bleibt das Fenster bedienbar, während der Benutzer
    im Browser bestätigt.
    """
    with _sperre:
        if _anmeldung["laeuft"] and time.monotonic() - _anmeldung["seit"] < wartezeit:
            return {"ok": True, "laeuft": True, "url": _anmeldung["url"]}
        _anmeldung.update({"laeuft": True, "url": "", "ergebnis": None,
                           "seit": time.monotonic()})

    def arbeiten():
        try:
            ergebnis = _anmelden(browser_oeffnen, wartezeit)
        except errors.StudioFehler as fehler:
            ergebnis = {"ok": False, **fehler.als_dict()}
        except Exception as fehler:
            ergebnis = {"ok": False, **errors.aus_ausnahme(fehler, ursprung=QUELLE).als_dict()}
        with _sperre:
            _anmeldung["ergebnis"] = ergebnis
            _anmeldung["laeuft"] = False

    threading.Thread(target=arbeiten, name="hf-abo-anmeldung", daemon=True).start()

    # Kurz auf die URL warten — die Registrierung dauert etwa eine Sekunde.
    for _ in range(80):
        with _sperre:
            if _anmeldung["url"] or not _anmeldung["laeuft"]:
                break
        time.sleep(0.25)
    with _sperre:
        return {"ok": True, "laeuft": _anmeldung["laeuft"], "url": _anmeldung["url"],
                "ergebnis": _anmeldung["ergebnis"]}


def anmeldung_stand() -> dict:
    with _sperre:
        return {"laeuft": _anmeldung["laeuft"], "url": _anmeldung["url"],
                "ergebnis": _anmeldung["ergebnis"], "angemeldet": angemeldet()}


def _anmelden(browser_oeffnen: bool, wartezeit: int) -> dict:
    auskunft = _oauth_auskunft()

    # Lauschen auf dem ersten freien Port aus dem vereinbarten Bereich.
    empfaenger = None
    rueckruf_adresse = ""
    for port in range(8765, 8780):
        try:
            _RueckrufEmpfaenger.ergebnis = {}
            empfaenger = HTTPServer(("127.0.0.1", port), _RueckrufEmpfaenger)
            rueckruf_adresse = f"http://localhost:{port}/callback"
            break
        except OSError:
            continue
    if empfaenger is None:
        raise errors.KonfigurationsFehler(
            "Kein freier Port für die Anmeldung.",
            "Bitte andere Programme schließen und erneut versuchen.", ursprung=QUELLE)

    try:
        anwendung = _registrieren(rueckruf_adresse)
        if not anwendung["client_id"]:
            raise errors.AnbieterFehler("Higgsfield hat keine Kennung vergeben.",
                                        ursprung=QUELLE)

        pruefwort, abdruck = _pkce()
        zustand = secrets.token_urlsafe(16)
        adresse = auskunft["authorization_endpoint"] + "?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": anwendung["client_id"],
            "redirect_uri": rueckruf_adresse, "scope": _SCOPE, "state": zustand,
            "code_challenge": abdruck, "code_challenge_method": "S256",
        })
        with _sperre:
            _anmeldung["url"] = adresse

        threading.Thread(target=empfaenger.serve_forever, daemon=True).start()
        logbook.info(QUELLE, "Anmeldung gestartet — bitte im Browser bestätigen.")
        if browser_oeffnen:
            try:
                webbrowser.open(adresse)
            except Exception:
                pass

        ende = time.time() + wartezeit
        while time.time() < ende:
            if _RueckrufEmpfaenger.ergebnis.get("code") or \
               _RueckrufEmpfaenger.ergebnis.get("fehler"):
                break
            time.sleep(0.4)
        rueckgabe = dict(_RueckrufEmpfaenger.ergebnis)
    finally:
        try:
            empfaenger.shutdown()
        except Exception:
            pass

    if rueckgabe.get("fehler"):
        raise errors.ZugangFehler(f"Higgsfield meldet: {rueckgabe['fehler']}",
                                  "Bitte erneut versuchen.", ursprung=QUELLE)
    if not rueckgabe.get("code"):
        raise errors.ZeitFehler(
            "Die Anmeldung wurde nicht bestätigt.",
            "Der Anmeldelink ist abgelaufen. Bitte erneut auf den Knopf klicken.",
            ursprung=QUELLE)
    if rueckgabe.get("state") and rueckgabe["state"] != zustand:
        raise errors.ZugangFehler(
            "Die Antwort passt nicht zur Anfrage.",
            "Sicherheitsabbruch — bitte erneut versuchen.", ursprung=QUELLE)

    formular = {"grant_type": "authorization_code", "code": rueckgabe["code"],
                "redirect_uri": rueckruf_adresse, "client_id": anwendung["client_id"],
                "code_verifier": pruefwort}
    if anwendung.get("client_secret"):
        formular["client_secret"] = anwendung["client_secret"]
    try:
        with httpx.Client(timeout=25, headers={"User-Agent": _UA}) as klient:
            antwort = klient.post(auskunft["token_endpoint"], data=formular)
    except Exception as fehler:
        raise errors.NetzFehler("Der Abschluss der Anmeldung ist gescheitert.",
                                "Internetverbindung prüfen.", ursprung=QUELLE) from fehler
    if antwort.status_code != 200:
        raise errors.ZugangFehler(
            f"Higgsfield hat die Anmeldung abgelehnt (Code {antwort.status_code}).",
            config.entschaerfe(antwort.text[:200]), ursprung=QUELLE)

    marken = antwort.json()
    _speichern({
        "client_id": anwendung["client_id"],
        "client_secret": anwendung.get("client_secret", ""),
        "access_token": marken.get("access_token", ""),
        "refresh_token": marken.get("refresh_token", ""),
        "gueltig_bis": time.time() + int(marken.get("expires_in", 3600)) - 60,
        "token_endpoint": auskunft["token_endpoint"],
        "angemeldet_am": time.time(),
    })
    logbook.erfolg(QUELLE, "Verbunden — die Abo-Credits sind jetzt nutzbar.")
    return {"ok": True, "meldung": "Higgsfield-Abo verbunden."}


def _gueltiges_token() -> str:
    """Gibt ein brauchbares Zugriffstoken zurück und erneuert es bei Bedarf."""
    daten = _laden()
    if not daten:
        raise errors.ZugangFehler(
            "Das Higgsfield-Abo ist nicht verbunden.",
            "Im Dashboard auf „Higgsfield anmelden“ klicken — einmalig, danach läuft es "
            "von allein.", ursprung=QUELLE)
    if daten.get("access_token") and time.time() < float(daten.get("gueltig_bis", 0)):
        return daten["access_token"]

    erneuerung = daten.get("refresh_token")
    if not erneuerung:
        raise errors.ZugangFehler(
            "Die Anmeldung ist abgelaufen.",
            "Bitte im Dashboard erneut anmelden.", ursprung=QUELLE)

    formular = {"grant_type": "refresh_token", "refresh_token": erneuerung,
                "client_id": daten.get("client_id", "")}
    if daten.get("client_secret"):
        formular["client_secret"] = daten["client_secret"]
    try:
        with httpx.Client(timeout=25, headers={"User-Agent": _UA}) as klient:
            antwort = klient.post(daten.get("token_endpoint") or
                                  _oauth_auskunft()["token_endpoint"], data=formular)
    except Exception as fehler:
        raise errors.NetzFehler("Die Anmeldung ließ sich nicht auffrischen.",
                                "Internetverbindung prüfen.", ursprung=QUELLE) from fehler
    if antwort.status_code != 200:
        raise errors.ZugangFehler(
            "Die Anmeldung ist nicht mehr gültig.",
            "Bitte im Dashboard erneut anmelden.", ursprung=QUELLE)

    marken = antwort.json()
    daten["access_token"] = marken.get("access_token", "")
    daten["gueltig_bis"] = time.time() + int(marken.get("expires_in", 3600)) - 60
    if marken.get("refresh_token"):
        daten["refresh_token"] = marken["refresh_token"]      # Rotation mitmachen
    _speichern(daten)
    return daten["access_token"]


# ── MCP-Aufrufe ──────────────────────────────────────────────────────────────

def _zerlegen(antwort: httpx.Response) -> list:
    """Antwort in Nachrichten zerlegen — der Dienst antwortet mal als JSON, mal als
    Ereignisstrom."""
    if "text/event-stream" in antwort.headers.get("content-type", ""):
        nachrichten = []
        for zeile in antwort.text.splitlines():
            zeile = zeile.strip()
            if zeile.startswith("data:"):
                inhalt = zeile[5:].strip()
                if inhalt and inhalt != "[DONE]":
                    try:
                        nachrichten.append(json.loads(inhalt))
                    except ValueError:
                        pass
        return nachrichten
    try:
        daten = json.loads(antwort.text)
        return daten if isinstance(daten, list) else [daten]
    except ValueError:
        return []


def _kopfzeilen(token: str, sitzung: str = "") -> dict:
    kopf = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": _PROTOKOLL, "User-Agent": _UA}
    if sitzung:
        kopf["Mcp-Session-Id"] = sitzung
    return kopf


def _fehlertext(antwort) -> str:
    """Die Fehlermeldung aus einer Werkzeugantwort — oder leer, wenn keine drinsteht.

    Der MCP-Dienst meldet fachliche Fehler **nicht** als JSON-RPC-Fehler, sondern
    als ganz normales Ergebnis mit einem Feld `error`. Wer nur auf den RPC-Fehler
    schaut, sieht deshalb eine leere Antwort und meldet „keine Auftragsnummer“ —
    genau die nichtssagende Zeile, die beim Kunden im Logbuch stand.
    """
    if isinstance(antwort, dict):
        for schluessel in ("error", "message", "detail", "reason"):
            wert = antwort.get(schluessel)
            if isinstance(wert, str) and wert.strip():
                return wert.strip()[:300]
            if isinstance(wert, dict):
                tiefer = wert.get("message") or wert.get("error")
                if isinstance(tiefer, str) and tiefer.strip():
                    return tiefer.strip()[:300]
    return ""


def _unbekanntes_modell(antwort) -> bool:
    """Sagt der Dienst „unknown model“? Dann hilft nur ein anderer Modellname."""
    text = _fehlertext(antwort).lower()
    return "unknown model" in text or "model not found" in text or            ("model" in text and "available" in text)


def _auftragsnummer(antwort) -> str:
    """Die Auftragsnummer aus einer Werkzeugantwort, egal wo sie steckt."""
    if not isinstance(antwort, dict):
        return ""
    treffer = antwort.get("results") or antwort.get("jobs") or []
    if isinstance(treffer, list) and treffer and isinstance(treffer[0], dict):
        for feld in ("id", "jobId", "job_id", "request_id"):
            wert = treffer[0].get(feld)
            if wert:
                return str(wert)
    for feld in ("id", "jobId", "job_id", "request_id"):
        wert = antwort.get(feld)
        if wert:
            return str(wert)
    return ""


def _stand_abfragen(kennung: str) -> dict:
    """Fragt den Stand eines Auftrags ab.

    Die Argumentform ist nicht verbürgt: `generate_image` will seine Werte in einem
    Feld `params`, `job_status` nimmt sie nach bisheriger Kenntnis direkt. Weil das
    nicht nachgemessen ist, werden beide Formen probiert — und die, die trägt, wird
    gemerkt. Eine falsche Wette hier hätte zur Folge, dass ein längst fertiger
    Auftrag bis zum Zeitlimit als „läuft“ gilt.
    """
    argumente = {"jobId": kennung, "sync": True, "raw_data": True}
    formen = ([argumente, {"params": argumente}] if _STANDFORM["flach"]
              else [{"params": argumente}, argumente])
    letzte: dict = {}
    for stelle, form in enumerate(formen):
        antwort = werkzeug_rufen("job_status", form)
        if isinstance(antwort, dict) and (antwort.get("status") or
                                          isinstance(antwort.get("raw_data"), dict)):
            _STANDFORM["flach"] = (form is argumente)
            return antwort
        letzte = antwort if isinstance(antwort, dict) else {}
        if stelle == 0 and not _fehlertext(letzte):
            break                    # kein Fehler, nur (noch) kein Status — so lassen
    return letzte


#: Welche Argumentform `job_status` angenommen hat. Wird beim ersten Erfolg gesetzt.
_STANDFORM = {"flach": True}


def _ergebnis(nachrichten: list, kennung: int) -> dict:
    """Holt das Ergebnis zur eigenen Anfrage und packt es aus."""
    for nachricht in nachrichten:
        if nachricht.get("id") != kennung:
            continue
        if "error" in nachricht:
            raise errors.AnbieterFehler(
                "Higgsfield meldet einen Fehler.",
                config.entschaerfe(str(nachricht["error"])[:200]), ursprung=QUELLE)
        rueckgabe = nachricht.get("result")
        if isinstance(rueckgabe, dict):
            if isinstance(rueckgabe.get("structuredContent"), dict):
                return rueckgabe["structuredContent"]
            klartext = ""
            for stueck in (rueckgabe.get("content") or []):
                if stueck.get("type") == "text":
                    roh = stueck.get("text", "")
                    try:
                        geparst = json.loads(roh)
                    except ValueError:
                        klartext = klartext or str(roh)[:300]
                        continue
                    if isinstance(geparst, dict):
                        return geparst
                    if isinstance(geparst, list):
                        return {"results": geparst}
            if klartext:
                # Reiner Text statt JSON — bei `isError` ist das die Fehlermeldung,
                # sonst eine Auskunft. So oder so darf sie nicht verlorengehen.
                return {"error": klartext} if rueckgabe.get("isError") else                        {"text": klartext}
            return rueckgabe
    return {}


def werkzeug_rufen(name: str, argumente: dict, zeitlimit: int = 60) -> dict:
    token = _gueltiges_token()
    try:
        with httpx.Client(timeout=zeitlimit, headers={"User-Agent": _UA}) as klient:
            # Sitzung eröffnen — manche Fassungen verlangen das vor jedem Aufruf.
            eroeffnung = klient.post(_MCP_URL, headers=_kopfzeilen(token), json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": _PROTOKOLL, "capabilities": {},
                           "clientInfo": {"name": config.APP_NAME, "version":
                                          config.APP_VERSION}}})
            sitzung = (eroeffnung.headers.get("mcp-session-id") or
                       eroeffnung.headers.get("Mcp-Session-Id") or "")
            try:
                klient.post(_MCP_URL, headers=_kopfzeilen(token, sitzung),
                            json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            except Exception:
                pass

            kennung = secrets.randbelow(1_000_000) + 2
            antwort = klient.post(_MCP_URL, headers=_kopfzeilen(token, sitzung), json={
                "jsonrpc": "2.0", "id": kennung, "method": "tools/call",
                "params": {"name": name, "arguments": argumente}})
    except httpx.TimeoutException as fehler:
        raise errors.ZeitFehler("Higgsfield hat nicht rechtzeitig geantwortet.",
                                "Das Programm versucht es erneut.",
                                ursprung=QUELLE) from fehler
    except httpx.HTTPError as fehler:
        raise errors.NetzFehler("Keine Verbindung zu Higgsfield.",
                                "Internetverbindung prüfen.", ursprung=QUELLE) from fehler

    if antwort.status_code == 401:
        raise errors.ZugangFehler("Die Anmeldung ist abgelaufen.",
                                  "Bitte im Dashboard erneut anmelden.", ursprung=QUELLE)
    if antwort.status_code >= 400:
        raise errors.aus_httpfehler(antwort.status_code, antwort.text, ursprung=QUELLE)
    return _ergebnis(_zerlegen(antwort), kennung)


# ── Welche Modelle kennt der Dienst? ─────────────────────────────────────────

def _modelle_normieren(antwort) -> list[dict]:
    """Macht aus der Antwort von `models_explore` eine schlichte Liste.

    Die Form ist nicht verbürgt — mal eine Liste, mal ein Objekt mit `models`,
    mal Zeichenketten statt Objekten. Statt auf eine Form zu wetten, wird jede
    plausible ausgepackt; was sich nicht auspacken lässt, fällt weg.
    """
    roh = antwort
    if isinstance(roh, dict):
        for schluessel in ("models", "results", "items", "data", "list", "available"):
            if isinstance(roh.get(schluessel), list):
                roh = roh[schluessel]
                break
        else:
            listen = [w for w in roh.values() if isinstance(w, list)]
            roh = listen[0] if listen else []
    if not isinstance(roh, list):
        return []

    liste: list[dict] = []
    for eintrag in roh:
        if isinstance(eintrag, str):
            eintrag = {"id": eintrag}
        if not isinstance(eintrag, dict):
            continue
        kennung = str(eintrag.get("id") or eintrag.get("model") or
                      eintrag.get("name") or eintrag.get("slug") or "").strip()
        if not kennung:
            continue
        liste.append({
            "id": kennung,
            "name": str(eintrag.get("name") or kennung),
            "art": str(eintrag.get("type") or eintrag.get("kind") or
                       eintrag.get("category") or "").lower(),
        })
    return liste


def modellliste(erneuern: bool = False) -> list[dict]:
    """Die Modelle, die der Abo-Dienst wirklich führt. Eine Stunde lang gemerkt.

    Scheitert der Abruf, wird eine leere Liste zurückgegeben — dann greift die
    Übersetzungstabelle. Ein Fehler hier darf niemals einen Auftrag verhindern.
    """
    if not erneuern and _MODELLE["liste"] and             time.time() - _MODELLE["zeit"] < _MODELLE_FRISCHE:
        return list(_MODELLE["liste"])

    liste: list[dict] = []
    for argumente in ({"action": "list"}, {"params": {"action": "list"}}, {}):
        try:
            liste = _modelle_normieren(werkzeug_rufen("models_explore", argumente,
                                                      zeitlimit=30))
        except errors.StudioFehler:
            liste = []
        except Exception:
            liste = []
        if liste:
            break

    if liste:
        _MODELLE.update({"zeit": time.time(), "liste": liste})
        logbook.debug(QUELLE, f"{len(liste)} Modelle beim Abo-Dienst gefunden.")
    return list(liste)


def _teile(name: str) -> list[str]:
    """Zerlegt einen Modellnamen in Wortteile — „kling-video/v2.6/pro“ wird zu
    ['kling','video','v2','6','pro']. Damit lassen sich zwei Benennungen
    vergleichen, ohne dass eine davon die richtige sein muss."""
    return [t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if t]


def _ist_video(kennung: str, art: str = "") -> bool:
    if "video" in art:
        return True
    if "image" in art or "bild" in art:
        return False
    return any(wort in kennung.lower() for wort in _VIDEOWORTE)


def _passt_zur_art(eintrag: dict, art: str) -> bool:
    video = _ist_video(eintrag["id"], eintrag.get("art", ""))
    if art == "video":
        return video
    return not video or any(w in eintrag["id"].lower() for w in _BILDWORTE)


def _aehnlichkeit(kandidat: str, wunsch: list[str]) -> int:
    """Wie viele Wortteile des Wunsches stecken im Kandidaten? Grob, aber genau
    grob genug, um „kling-video/v2.6/pro“ auf „kling2_6_pro“ zu bringen."""
    text = "".join(_teile(kandidat))
    return sum(1 for teil in wunsch if teil and teil in text)


def modell_aufloesen(wunsch: str, art: str) -> str:
    """Übersetzt einen Modellwunsch in einen Namen, den der Abo-Dienst versteht.

    `art` ist „bild“ oder „video“. Die Reihenfolge:
      1. Kennt der Dienst den Namen wörtlich? Dann bleibt er.
      2. Steht er in der Übersetzungstabelle, und kennt der Dienst einen der
         Kandidaten? Dann dieser.
      3. Sonst der ähnlichste Name der richtigen Art aus der Liste des Dienstes.
      4. Ohne Liste: der erste Tabelleneintrag, sonst der Rückfallname.

    Es wird **nie** ein Platform-Name (mit Schrägstrich) hinausgereicht — der
    würde sicher als „unknown model“ abgewiesen.
    """
    wunsch = (wunsch or "").strip()
    rueckfall = _VIDEOMODELL if art == "video" else _BILDMODELL
    bekannt = modellliste()
    kennungen = {e["id"] for e in bekannt}

    if wunsch and wunsch in kennungen:
        return wunsch

    kandidaten = _UEBERSETZUNG.get(wunsch, ())
    for kandidat in kandidaten:
        if kandidat in kennungen:
            return kandidat

    if wunsch and "/" not in wunsch and not bekannt:
        # Kein Platform-Name und keine Liste zum Gegenprüfen: dem Aufrufer glauben.
        return wunsch

    if bekannt:
        passende = [e for e in bekannt if _passt_zur_art(e, art)] or bekannt
        wunschteile = _teile(wunsch) + [t for k in kandidaten for t in _teile(k)]
        bester = max(passende, key=lambda e: _aehnlichkeit(e["id"], wunschteile))
        if _aehnlichkeit(bester["id"], wunschteile) > 0:
            return bester["id"]
        for kandidat in kandidaten:                 # nichts ähnlich: Tabelle blind
            return kandidat
        return passende[0]["id"]

    if kandidaten:
        return kandidaten[0]
    if wunsch and "/" not in wunsch:
        return wunsch
    return rueckfall            # leerer oder unbekannter Platform-Pfad


# ── Derselbe Umgang wie beim Platform-Client ─────────────────────────────────

class HiggsfieldAbo:
    """Gleiche Schnittstelle wie `higgsfield.Higgsfield`, nur über die Abo-Credits."""

    name = "Abo (MCP)"

    @property
    def verfuegbar(self) -> bool:
        return angemeldet()

    @staticmethod
    def _abschicken(werkzeug: str, bauen, modell: str) -> dict:
        """Einen Auftrag mit genau diesem Modellnamen abschicken."""
        return werkzeug_rufen(werkzeug, {"params": bauen(modell)}, zeitlimit=90)

    def _auftrag(self, werkzeug: str, bauen, *, art: str, wunsch: str,
                 abbruch: threading.Event | None, melden) -> higgsfield.Ergebnis:
        """Auftrag abschicken und auf das Ergebnis warten.

        `bauen` ist eine Funktion, die zu einem Modellnamen die Parameter liefert.
        Das ist kein Selbstzweck: Weist der Dienst das Modell ab, muss derselbe
        Auftrag mit einem anderen Namen noch einmal gebaut werden können.
        """
        begonnen = time.monotonic()
        modell = modell_aufloesen(wunsch, art)
        antwort = self._abschicken(werkzeug, bauen, modell)

        kennung = _auftragsnummer(antwort)
        if not kennung and _unbekanntes_modell(antwort):
            # Der Dienst kennt dieses Modell nicht (mehr). Einmal die Liste frisch
            # holen und mit einem Namen wiederholen, den er nachweislich führt —
            # das ist der Fall, an dem die Übergabe am 26.08.2026 gescheitert ist.
            modellliste(erneuern=True)
            zweiter = modell_aufloesen(wunsch, art)
            if zweiter != modell:
                logbook.warnung(QUELLE, f"Modell „{modell}“ ist dem Abo-Dienst unbekannt "
                                        f"— es wird „{zweiter}“ genommen.")
                modell = zweiter
                antwort = self._abschicken(werkzeug, bauen, modell)
                kennung = _auftragsnummer(antwort)

        if not kennung:
            grund = config.entschaerfe(_fehlertext(antwort) or str(antwort)[:200])
            klein = grund.lower()
            if _unbekanntes_modell(antwort):
                raise errors.KonfigurationsFehler(
                    "Higgsfield kennt das eingestellte Modell im Abo nicht.",
                    f"Der Dienst meldet: {grund}. Bitte im Formular ein anderes Modell "
                    "wählen — oder das Programm über „Update“ auf den neuesten Stand "
                    "bringen.", ursprung=QUELLE)
            if "credit" in klein or "quota" in klein or "insufficient" in klein:
                raise errors.GuthabenFehler(
                    "Das Higgsfield-Abo hat keine Credits mehr.",
                    "Unter higgsfield.ai das Guthaben prüfen. Solange erzeugt der "
                    "Probelauf Platzhalterclips.", ursprung=QUELLE)
            raise errors.AnbieterFehler(
                "Higgsfield hat keine Auftragsnummer zurückgegeben.",
                grund, ursprung=QUELLE)

        erwartet = 25.0 if art == "bild" else 150.0
        while True:
            if abbruch is not None and abbruch.is_set():
                raise errors.AbbruchFehler("Auftrag abgebrochen.", ursprung=QUELLE)
            vergangen = time.monotonic() - begonnen
            if vergangen > config.JOB_TIMEOUT:
                raise errors.ZeitFehler(
                    f"Higgsfield ist nach {int(vergangen / 60)} Minuten nicht fertig geworden.",
                    "Bitte mit einer kürzeren Szene erneut versuchen.", ursprung=QUELLE)

            stand = _stand_abfragen(kennung)
            roh = stand.get("raw_data") if isinstance(stand.get("raw_data"), dict) else stand
            zustand = str(roh.get("status") or "").lower()

            # Meldet die Abfrage selbst einen Fehler, hat weiteres Warten keinen Sinn.
            # Ohne diese Prüfung liefe die Schleife bis zum Zeitlimit — der Kunde säße
            # eine Viertelstunde vor einem Auftrag, der längst gescheitert ist.
            if not zustand:
                grund = _fehlertext(stand)
                if grund:
                    raise errors.AnbieterFehler(
                        "Higgsfield kann den Stand des Auftrags nicht mitteilen.",
                        config.entschaerfe(grund), ursprung=QUELLE)

            if zustand in ("completed", "succeeded", "success", "done"):
                adresse = (roh.get("result_url") or roh.get("min_result_url") or
                           higgsfield.Higgsfield._medien_url(roh))
                if not adresse:
                    raise errors.AnbieterFehler(
                        "Higgsfield meldet „fertig“, liefert aber keine Datei.",
                        "Bitte erneut versuchen.", ursprung=QUELLE)
                if melden:
                    melden(1.0, 0.0, "fertig")
                return higgsfield.Ergebnis(str(kennung), modell, adresse,
                                           time.monotonic() - begonnen, roh)
            if zustand == "nsfw":
                raise errors.InhaltFehler(
                    "Higgsfield hat den Inhalt abgelehnt (Moderation).",
                    "Das Guthaben wurde erstattet. Marken, echte Personen und Gewalt "
                    "vermeiden.", ursprung=QUELLE)
            if zustand == "ip_detected":
                raise errors.InhaltFehler(
                    "Higgsfield erkennt geschützte Inhalte im Prompt.",
                    "Marken- und Figurennamen entfernen.", ursprung=QUELLE)
            if zustand in ("failed", "error", "cancelled", "canceled"):
                raise errors.AnbieterFehler(
                    "Higgsfield konnte den Auftrag nicht ausführen.",
                    config.entschaerfe(str(roh.get("error") or zustand)[:200]),
                    ursprung=QUELLE)

            if melden:
                anteil = min(0.95, vergangen / erwartet)
                melden(anteil, max(0.0, erwartet - vergangen), zustand or "läuft")
            time.sleep(float(roh.get("poll_after_seconds") or config.POLL_INTERVAL))

    def bild(self, prompt: str, *, seitenverhaeltnis: str = "16:9", aufloesung: str = "1080p",
             modell: str = "", verbessern: bool = True, saat: int | None = None,
             abbruch: threading.Event | None = None, melden=None) -> higgsfield.Ergebnis:
        def bauen(einstellung: str) -> dict:
            return {"model": einstellung, "prompt": prompt[:config.MAX_PROMPT_CHARS],
                    "aspect_ratio": seitenverhaeltnis, "count": 1}

        return self._auftrag("generate_image", bauen, wunsch=modell or config.IMAGE_MODEL,
                             art="bild", abbruch=abbruch, melden=melden)

    def video_aus_bild(self, prompt: str, bild_url: str, *, dauer: int = 5,
                       modell: str = "", saat: int | None = None,
                       bewegungen: list[str] | None = None,
                       seitenverhaeltnis: str = "16:9",
                       abbruch: threading.Event | None = None,
                       melden=None) -> higgsfield.Ergebnis:
        def bauen(einstellung: str) -> dict:
            parameter = {"model": einstellung, "prompt": prompt[:config.MAX_PROMPT_CHARS],
                         "aspect_ratio": seitenverhaeltnis, "count": 1}
            if bild_url:
                parameter["image_url"] = bild_url
            if dauer:
                parameter["duration"] = int(dauer)
            return parameter

        return self._auftrag("generate_video", bauen, wunsch=modell or config.VIDEO_MODEL,
                             art="video", abbruch=abbruch, melden=melden)

    def video_aus_text(self, prompt: str, *, dauer: int = 6, modell: str = "",
                       seitenverhaeltnis: str = "16:9",
                       abbruch: threading.Event | None = None,
                       melden=None) -> higgsfield.Ergebnis:
        return self.video_aus_bild(prompt, "", dauer=dauer, modell=modell,
                                   seitenverhaeltnis=seitenverhaeltnis,
                                   abbruch=abbruch, melden=melden)

    def herunterladen(self, url, ziel, abbruch=None, melden=None) -> Path:
        # Das Herunterladen unterscheidet sich nicht — den erprobten Weg mitbenutzen.
        return higgsfield.client.herunterladen(url, ziel, abbruch, melden)

    def abbrechen(self, request_id: str) -> bool:
        try:
            werkzeug_rufen("cancel_job", {"jobId": request_id}, zeitlimit=15)
            return True
        except Exception:
            return False

    def selbsttest(self) -> dict:
        if not angemeldet():
            return {"zustand": "nicht_angemeldet", "ok": False, "guthaben": "unbekannt",
                    "meldung": "Das Higgsfield-Abo ist nicht verbunden.",
                    "hinweis": "Einmalig im Dashboard anmelden — danach läuft es von allein."}
        try:
            _gueltiges_token()
        except errors.StudioFehler as fehler:
            return {"zustand": "abgelaufen", "ok": False, "guthaben": "unbekannt",
                    "meldung": fehler.meldung, "hinweis": fehler.hinweis}
        daten = _laden()
        seit = daten.get("angemeldet_am", 0)
        wann = time.strftime("%d.%m.%Y", time.localtime(seit)) if seit else "unbekannt"
        return {"zustand": "bereit", "ok": True, "guthaben": "über das Abo",
                "meldung": f"Abo verbunden (seit {wann}).", "hinweis": ""}


#: Gemeinsame Instanz.
client = HiggsfieldAbo()
