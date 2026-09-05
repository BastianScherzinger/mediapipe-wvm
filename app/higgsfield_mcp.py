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
Ereignisstrom. Der Ablauf ähnelt der Platform-API, ist aber **nicht** derselbe:

    tools/call generate_image {params:{model, prompt, aspect_ratio, count}} → results[0].id
    tools/call generate_video {params:{model, prompt, medias:[…], duration}} → results[0].id
    tools/call job_status      {jobId, sync:true, raw_data:true}            → result_url

Der Unterschied in der zweiten Zeile ist teuer bezahlt: `generate_video` nimmt **keine**
Bildadresse (`image_url`), sondern nur Kennungen in `medias`. Wer die Platform-Form
durchreicht, verliert jeden Auftrag — und das Startbild ist zu dem Zeitpunkt schon
erzeugt und bezahlt. Der Abschnitt „Startbilder an das Videomodell übergeben“ weiter
unten erklärt, wie diese Kennung ohne einen einzigen Zusatzaufruf zustande kommt.

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
    """Ein Werkzeug des Dienstes aufrufen."""
    return _rpc("tools/call", {"name": name, "arguments": argumente}, zeitlimit)


def _rpc(methode: str, parameter: dict, zeitlimit: int = 60) -> dict:
    """Ein beliebiger MCP-Aufruf. `tools/call` ist der häufigste, aber nicht der
    einzige: die Werkzeugliste kommt über `tools/list`."""
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
                "jsonrpc": "2.0", "id": kennung, "method": methode,
                "params": parameter})
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


# ── Startbilder an das Videomodell übergeben ─────────────────────────────────
#
# **Der Fehler, an dem der Kundenlauf hing.** `generate_video` nimmt beim MCP-Dienst
# keine Bildadresse entgegen. Er antwortet wörtlich:
#
#     generate_video accepts uploaded media IDs or completed job IDs in
#     params.medias, not raw HTTPS URLs. Import the URL first, then retry
#     generation with the returned media_id.
#
# Mitgeschickt wurde aber `image_url` — die Form der Platform-API. Folge: Das Startbild
# war erzeugt und bezahlt, und der Videoauftrag scheiterte in derselben Sekunde, mit
# einer Meldung, die im Logbuch wie ein Netzproblem aussah.
#
# Der kurze Weg steht in der Meldung selbst: **fertige Auftragsnummern sind erlaubt.**
# Das Startbild stammt aus unserem eigenen `generate_image`-Auftrag, dessen Nummer wir
# kennen — es muss also gar nichts hochgeladen werden. Nur eine Adresse von woanders
# (Platform-Weg, später einmal ein eigenes Bild) wird über das Import-Werkzeug des
# Dienstes eingeführt.

#: Adresse eines erzeugten Bildes → Nummer des Auftrags, der es gemacht hat.
#: Begrenzt, damit ein langer Betrieb keinen Speicher frisst; mehr als die Szenen
#: eines Laufs braucht niemand.
_BILDJOBS: dict[str, str] = {}
_BILDJOBS_MAX = 64
_medien_sperre = threading.Lock()

#: Welche Form `params.medias` angenommen hat: die bloße Kennung oder ein Objekt.
#: Wird beim ersten Erfolg gesetzt — wie `_STANDFORM`, aus demselben Grund.
_MEDIENFORM = {"objekt": False}

#: Nimmt der Dienst Kamerabewegungen entgegen? Beanstandet er sie, bleiben sie weg.
_BEWEGUNGEN = {"mitschicken": True}

#: Gemerkte Werkzeugliste des Dienstes.
_WERKZEUGE: dict = {"zeit": 0.0, "liste": []}

#: Woran ein Werkzeug zum Einführen fremder Adressen erkennbar ist.
#:
#: Bewusst eng: Hier wird ein **unbekanntes** Werkzeug eines kostenpflichtigen Dienstes
#: aufgerufen. „import“ und „upload“ meinen unmissverständlich das Hereinholen von
#: etwas Vorhandenem. „create“ oder „add“ wären zu weit — darunter fiele auch
#: `create_image`, und ein versehentlich ausgelöster Bildauftrag kostet Credits.
_IMPORTWORTE = ("import", "upload")

#: Was trotz eines Importworts nicht angefasst wird.
_TABU = ("generate", "create", "delete", "remove", "cancel", "pay", "purchase")


def _bild_merken(adresse: str, kennung: str) -> None:
    """Merkt sich, aus welchem Auftrag ein Startbild stammt."""
    if not adresse or not kennung:
        return
    with _medien_sperre:
        while len(_BILDJOBS) >= _BILDJOBS_MAX:
            _BILDJOBS.pop(next(iter(_BILDJOBS)))
        _BILDJOBS[adresse] = kennung


def _werkzeuge_normieren(antwort) -> list[str]:
    """Macht aus der Antwort von `tools/list` eine schlichte Namensliste."""
    roh = antwort
    if isinstance(roh, dict):
        for schluessel in ("tools", "results", "items", "data"):
            if isinstance(roh.get(schluessel), list):
                roh = roh[schluessel]
                break
        else:
            listen = [w for w in roh.values() if isinstance(w, list)]
            roh = listen[0] if listen else []
    if not isinstance(roh, list):
        return []

    namen: list[str] = []
    for eintrag in roh:
        if isinstance(eintrag, str):
            name = eintrag
        elif isinstance(eintrag, dict):
            name = str(eintrag.get("name") or eintrag.get("id") or "")
        else:
            continue
        name = name.strip()
        if name:
            namen.append(name)
    return namen


def werkzeugliste(erneuern: bool = False) -> list[str]:
    """Die Werkzeuge, die der Abo-Dienst führt. Eine Stunde lang gemerkt.

    Gebraucht wird sie nur, um das Import-Werkzeug für fremde Bildadressen zu finden.
    Scheitert der Abruf, ist das kein Fehler — dann bleibt es beim Rückfall. Ein
    Auftrag darf daran nie scheitern.
    """
    if (not erneuern and _WERKZEUGE["liste"] and
            time.time() - _WERKZEUGE["zeit"] < _MODELLE_FRISCHE):
        return list(_WERKZEUGE["liste"])
    try:
        namen = _werkzeuge_normieren(_rpc("tools/list", {}, zeitlimit=30))
    except Exception:
        namen = []
    if namen:
        _WERKZEUGE.update({"zeit": time.time(), "liste": namen})
        logbook.debug(QUELLE, f"{len(namen)} Werkzeuge beim Abo-Dienst gefunden.")
    return list(namen)


def _importwerkzeuge() -> list[str]:
    """Welche Werkzeuge des Dienstes könnten eine Adresse einführen?

    Kürzere Namen zuerst — `import_media` ist spezifischer als `import_media_batch`.
    """
    treffer = [name for name in werkzeugliste()
               if any(w in name.lower() for w in _IMPORTWORTE)
               and not any(w in name.lower() for w in _TABU)]
    return sorted(treffer, key=len)


def _medienkennung_aus(antwort) -> str:
    """Die Medien-Kennung aus der Antwort eines Import-Werkzeugs, egal wo sie steckt."""
    if not isinstance(antwort, dict):
        return ""
    kandidaten: list[dict] = []
    for schluessel in ("results", "medias", "media", "items", "data"):
        wert = antwort.get(schluessel)
        if isinstance(wert, list) and wert:
            kandidaten.append(wert[0] if isinstance(wert[0], dict) else {"id": wert[0]})
        elif isinstance(wert, dict):
            kandidaten.append(wert)
    kandidaten.append(antwort)

    for eintrag in kandidaten:
        for feld in ("media_id", "mediaId", "id", "jobId", "job_id"):
            wert = eintrag.get(feld)
            if isinstance(wert, (str, int)) and str(wert).strip():
                return str(wert).strip()
    return ""


def _einfuehren(adresse: str) -> str:
    """Führt eine fremde Bildadresse beim Dienst ein und gibt die Medien-Kennung.

    Die Argumentform ist nicht verbürgt, deshalb werden mehrere durchprobiert. Das
    kostet im schlechtesten Fall ein paar vergebliche Aufrufe — aber nur in dem
    seltenen Fall, dass das Bild nicht aus einem eigenen Auftrag stammt.
    """
    werkzeuge = _importwerkzeuge()
    if not werkzeuge:
        return ""
    formen = ({"url": adresse}, {"media_url": adresse}, {"image_url": adresse},
              {"urls": [adresse]})
    for name in werkzeuge:
        for form in formen:
            for argumente in ({"params": form}, form):
                try:
                    antwort = werkzeug_rufen(name, argumente, zeitlimit=90)
                except Exception:
                    continue
                kennung = _medienkennung_aus(antwort)
                if kennung:
                    logbook.debug(QUELLE, f"Startbild über „{name}“ eingeführt.")
                    return kennung
    return ""


def medienkennung(adresse: str) -> str:
    """Was in `params.medias` gehört, damit das Videomodell das Startbild bekommt.

    Erst der eigene Bildauftrag: dessen Nummer nimmt der Dienst unmittelbar an und
    kostet keinen weiteren Aufruf. Nur eine fremde Adresse muss eingeführt werden.
    """
    adresse = (adresse or "").strip()
    if not adresse:
        return ""

    with _medien_sperre:
        gemerkt = _BILDJOBS.get(adresse, "")
    if gemerkt:
        return gemerkt

    if not adresse.lower().startswith(("http://", "https://")):
        return adresse                      # sieht schon nach einer Kennung aus

    kennung = _einfuehren(adresse)
    if kennung:
        _bild_merken(adresse, kennung)
        return kennung

    # Ausdrücklich ein Konfigurationsfehler, kein Anbieterfehler: Die Ablaufsteuerung
    # bricht dabei den ganzen Lauf ab, statt Szene für Szene weiterzumachen. Genau das
    # ist hier richtig — bei der nächsten Szene stünde dieselbe Wand, und jeder weitere
    # Versuch hätte vorher ein Startbild erzeugt und bezahlt.
    raise errors.KonfigurationsFehler(
        "Das Startbild lässt sich nicht an das Videomodell übergeben.",
        "Higgsfield nimmt im Abo keine Bildadressen entgegen, und ein Werkzeug zum "
        "Einführen war nicht zu finden. Bitte oben auf „Update“ klicken — und wenn es "
        "dann noch klemmt, ein Modell ohne Startbild wählen.", ursprung=QUELLE)


def _medienfehler(antwort) -> bool:
    """Beanstandet der Dienst das Feld `medias`? Dann hilft nur die andere Form."""
    text = _fehlertext(antwort).lower()
    if not text:
        return False
    return "medias" in text or ("media" in text and ("url" in text or " id" in text))


def _bewegungsfehler(antwort) -> bool:
    """Beanstandet der Dienst die Kamerabewegungen? Dann lieber ohne sie."""
    text = _fehlertext(antwort).lower()
    return bool(text) and ("motion" in text or "bewegung" in text)


def _mit_geduld(aufgabe, *, beschreibung: str,
                abbruch: threading.Event | None = None):
    """Führt `aufgabe` aus und wiederholt sie bei vorübergehenden Fehlern.

    Wortgleich zum Vorgehen des Platform-Clients (`_mit_wiederholung`), und aus
    demselben Grund: Netz- und Zeitfehler sind Störungen, keine Urteile. Was nicht
    als `wiederholbar` gilt — kein Guthaben, unbekanntes Modell, abgelehnter Inhalt —
    wird sofort durchgereicht; dort hilft Warten nicht.
    """
    letzter: errors.StudioFehler | None = None
    for versuch in range(config.MAX_RETRIES + 1):
        if abbruch is not None and abbruch.is_set():
            raise errors.AbbruchFehler("Abgebrochen.", ursprung=QUELLE)
        try:
            return aufgabe()
        except errors.StudioFehler as fehler:
            letzter = fehler
            if not fehler.wiederholbar or versuch >= config.MAX_RETRIES:
                raise
            wartezeit = min(2 ** versuch * 2, 20)
            logbook.warnung(QUELLE, f"{beschreibung} fehlgeschlagen ({fehler.meldung}) "
                                    f"— Versuch {versuch + 2} von "
                                    f"{config.MAX_RETRIES + 1} in {wartezeit} s.")
            for _ in range(wartezeit * 2):      # in kleinen Schritten: Abbruch greift sofort
                if abbruch is not None and abbruch.is_set():
                    raise errors.AbbruchFehler("Abgebrochen.", ursprung=QUELLE)
                time.sleep(0.5)
    raise letzter or errors.StudioFehler(f"{beschreibung} fehlgeschlagen.",
                                         ursprung=QUELLE)


# ── Derselbe Umgang wie beim Platform-Client ─────────────────────────────────

class HiggsfieldAbo:
    """Gleiche Schnittstelle wie `higgsfield.Higgsfield`, nur über die Abo-Credits."""

    name = "Abo (MCP)"

    @property
    def verfuegbar(self) -> bool:
        return angemeldet()

    @staticmethod
    def _abschicken(werkzeug: str, bauen, modell: str,
                    abbruch: threading.Event | None = None) -> dict:
        """Einen Auftrag mit genau diesem Modellnamen abschicken.

        Mit derselben Geduld wie beim Platform-Weg: Ein Netzhänger auf dem Weg zum
        Dienst ist kein Grund, einen Auftrag zu verlieren. Ohne diese Wiederholung
        war der Abo-Weg der einzige, der bei der kleinsten Störung sofort aufgab.
        """
        return _mit_geduld(lambda: werkzeug_rufen(werkzeug, {"params": bauen(modell)},
                                                  zeitlimit=90),
                           beschreibung=f"Auftrag an {modell}", abbruch=abbruch)

    def _auftrag(self, werkzeug: str, bauen, *, art: str, wunsch: str,
                 abbruch: threading.Event | None, melden) -> higgsfield.Ergebnis:
        """Auftrag abschicken und auf das Ergebnis warten.

        `bauen` ist eine Funktion, die zu einem Modellnamen die Parameter liefert.
        Das ist kein Selbstzweck: Weist der Dienst das Modell ab, muss derselbe
        Auftrag mit einem anderen Namen noch einmal gebaut werden können.
        """
        begonnen = time.monotonic()
        modell = modell_aufloesen(wunsch, art)
        antwort = self._abschicken(werkzeug, bauen, modell, abbruch)

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
                antwort = self._abschicken(werkzeug, bauen, modell, abbruch)
                kennung = _auftragsnummer(antwort)

        if not kennung and _medienfehler(antwort):
            # Der Dienst beanstandet `params.medias`. Es gibt genau zwei gebräuchliche
            # Formen — die bloße Kennung und ein Objekt mit `id`. Die andere probieren
            # und die tragende merken, damit der nächste Auftrag gleich sitzt.
            _MEDIENFORM["objekt"] = not _MEDIENFORM["objekt"]
            logbook.warnung(QUELLE, "Higgsfield beanstandet die Form des Startbildes "
                                    "— es wird die andere versucht.")
            antwort = self._abschicken(werkzeug, bauen, modell, abbruch)
            kennung = _auftragsnummer(antwort)
            if not kennung:
                _MEDIENFORM["objekt"] = not _MEDIENFORM["objekt"]

        if not kennung and _bewegungsfehler(antwort):
            # Kamerabewegungen kennt nicht jedes Modell. Sie sind Beiwerk — ein Auftrag
            # darf nicht daran scheitern, also ohne sie noch einmal.
            _BEWEGUNGEN["mitschicken"] = False
            logbook.warnung(QUELLE, "Higgsfield nimmt die Kamerabewegung nicht an "
                                    "— der Clip entsteht ohne sie.")
            antwort = self._abschicken(werkzeug, bauen, modell, abbruch)
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
        gestoert = 0
        while True:
            if abbruch is not None and abbruch.is_set():
                raise errors.AbbruchFehler("Auftrag abgebrochen.", ursprung=QUELLE)
            vergangen = time.monotonic() - begonnen
            if vergangen > config.JOB_TIMEOUT:
                raise errors.ZeitFehler(
                    f"Higgsfield ist nach {int(vergangen / 60)} Minuten nicht fertig geworden.",
                    "Bitte mit einer kürzeren Szene erneut versuchen.", ursprung=QUELLE)

            try:
                stand = _stand_abfragen(kennung)
                gestoert = 0
            except errors.StudioFehler as fehler:
                # Der Auftrag läuft beim Dienst weiter und ist längst bezahlt. Eine
                # einzelne gestörte Abfrage darf ihn nicht wegwerfen — erst eine Serie
                # ist ein Problem. (Beim Platform-Weg war das immer so; hier fehlte es.)
                gestoert += 1
                if not fehler.wiederholbar or gestoert > config.MAX_RETRIES + 2:
                    raise
                logbook.debug(QUELLE, f"Standsabfrage gestört ({fehler.art}) — weiter.")
                time.sleep(config.POLL_INTERVAL)
                continue

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
                if art == "bild":
                    # Die Nummer dieses Auftrags ist genau das, was der Videoauftrag
                    # gleich in `params.medias` braucht. Ohne dieses Merken müsste die
                    # Adresse hinterher umständlich wieder eingeführt werden.
                    _bild_merken(str(adresse), str(kennung))
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
        # Die Medien-Kennung wird **vor** dem Auftrag geholt: `bauen` kann für einen
        # zweiten Versuch erneut aufgerufen werden, und ein zweiter Import würde dann
        # ein zweites Mal Aufwand kosten.
        medien = medienkennung(bild_url) if bild_url else ""

        def bauen(einstellung: str) -> dict:
            parameter = {"model": einstellung, "prompt": prompt[:config.MAX_PROMPT_CHARS],
                         "aspect_ratio": seitenverhaeltnis, "count": 1}
            if medien:
                # **Kein `image_url`.** Der Dienst weist rohe Adressen ab; er will die
                # Kennung eines Mediums oder eines fertigen Auftrags in `medias`.
                parameter["medias"] = ([{"id": medien, "type": "image"}]
                                       if _MEDIENFORM["objekt"] else [medien])
            if dauer:
                parameter["duration"] = int(dauer)
            if bewegungen and _BEWEGUNGEN["mitschicken"]:
                # Wie bei der Platform-API: Objekte, keine bloßen Zeichenketten.
                parameter["motions"] = [{"id": k} for k in bewegungen if k]
            if saat and saat >= 1:
                parameter["seed"] = int(saat)
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
