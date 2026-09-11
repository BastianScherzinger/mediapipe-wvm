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

    tools/list                                                            → Schemata
    tools/call generate_image {params:{model, prompt, aspect_ratio, count}} → results[0].id
    tools/call generate_video {params:{model, prompt,
                               medias:[{value:<Bildauftrag>, role:"start_image"}],
                               aspect_ratio, duration}}                  → results[0].id
    tools/call job_status      {jobId, sync:true, raw_data:true}            → result_url

Die zweite Zeile ist dreimal teuer bezahlt worden: erst mit `image_url` (05.09.2026),
dann mit bloßen Kennungen in `medias` und der erfundenen Kennung `kling2_6_pro`
(10.09.2026, „params: Invalid input“). Beide Male war das Startbild schon bezahlt.
Seitdem gilt: **Das Schema aus `tools/list` entscheidet**, die dokumentierte Form ist nur
der Rückfall, und eine Vorprüfung läuft, bevor irgendetwas bezahlt wird. Der Abschnitt
„Das Schema des Dienstes lesen“ weiter unten erklärt, wie.

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
from dataclasses import dataclass, field
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
#:
#: Die Kennungen stammen aus der offiziellen Modellliste der Higgsfield-CLI
#: (`github.com/higgsfield-ai/cli`, MODELS.md, Stand 11.09.2026), die laut Higgsfield
#: dieselbe Medienlogik spiegelt wie der MCP-Dienst. `soul_2` ist zusätzlich beim
#: Kunden belegt: Das Startbild vom 10.09.2026 entstand damit.
_BILDMODELL = "soul_2"
_VIDEOMODELL = "kling2_6"

#: Platform-Modell → Wunschnamen beim MCP-Dienst, bester zuerst.
#:
#: **Der Fehler vom 10.09.2026 steckte auch hier.** Vorne stand `kling2_6_pro` — eine
#: Kennung, die es nie gab. Konnte `models_explore` nicht ausgewertet werden, ging
#: genau dieser Name hinaus, und der Dienst antwortete nur „params: Invalid input“.
#: Die echte Kennung heißt `kling2_6`.
_UEBERSETZUNG: dict[str, tuple[str, ...]] = {
    "higgsfield-ai/soul/standard": ("soul_2", "text2image_soul_v2", "soul"),
    "higgsfield-ai/soul/turbo/standard": ("soul_2", "text2image_soul_v2", "soul"),
    "kling-video/v2.6/pro/image-to-video": ("kling2_6", "kling3_0", "kling3_0_turbo"),
    "kling-video/v2.1/master/image-to-video": ("kling2_6", "kling3_0"),
    "kling-video/v2.1/standard/image-to-video": ("kling3_0_turbo", "kling2_6"),
    "higgsfield-ai/dop/turbo": ("kling3_0_turbo", "kling2_6"),
    "higgsfield-ai/dop/standard": ("kling3_0", "kling2_6"),
    "minimax/hailuo-02/standard/text-to-video": ("minimax_hailuo", "kling3_0_turbo"),
    "minimax/hailuo-02/pro/text-to-video": ("minimax_hailuo", "kling3_0_turbo"),
}

#: Was die Videomodelle des Abos annehmen — aus derselben offiziellen Liste.
#: Dient nur als Rückfall, wenn der Dienst sein Schema nicht preisgibt: Liest das
#: Programm das Schema aus `tools/list`, gilt das Schema.
_ABO_VIDEO: dict[str, dict] = {
    "kling2_6": {"formate": ("16:9", "9:16", "1:1"), "dauer": (5, 10)},
    "kling3_0": {"formate": ("16:9", "9:16", "1:1"), "dauer": (5, 10, 15)},
    "kling3_0_turbo": {"formate": ("16:9", "9:16", "1:1"), "dauer": (5, 10, 15)},
    "seedance_2_0": {"formate": ("16:9", "9:16", "4:3", "3:4", "1:1", "21:9"),
                     "dauer": (5, 10, 15)},
    "veo3_1": {"formate": ("16:9", "9:16"), "dauer": (4, 6, 8)},
    "minimax_hailuo": {"formate": (), "dauer": (6, 10)},
    "wan2_6": {"formate": ("16:9", "9:16", "1:1"), "dauer": (5, 10, 15)},
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
    """Sagt der Dienst „unknown model“? Dann hilft nur ein anderer Modellname.

    Bewusst eng: Früher genügten „model“ und „available“ irgendwo im Text — dann galt
    auch „aspect_ratio 3:4 is not available for this model“ als unbekanntes Modell, und
    der Auftrag wechselte ungefragt auf ein anderes.
    """
    text = _fehlertext(antwort).lower()
    return any(w in text for w in ("unknown model", "model not found", "invalid model",
                                   "unsupported model", "no such model",
                                   "model does not exist", "model is not supported"))


def _inhaltsfehler(antwort) -> bool:
    """Lehnt der Dienst den Inhalt ab (Moderation)? Eine andere Form hilft da nicht."""
    text = _fehlertext(antwort).lower()
    return any(w in text for w in ("nsfw", "moderation", "content policy", "inappropriate",
                                   "ip_detected", "prohibited content", "safety system",
                                   "violates"))


def _tariffehler(antwort) -> bool:
    """Fehlt dem Abo die Berechtigung (Tarif, Freischaltung)? Das trifft jede Szene."""
    text = _fehlertext(antwort).lower()
    return any(w in text for w in ("subscription", "upgrade your plan", "not available on "
                                   "your plan", "plan does not", "requires a paid",
                                   "permission denied", "not authorized", "forbidden"))


_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                   re.IGNORECASE)


def _auftragsnummer(antwort) -> str:
    """Die Auftragsnummer aus einer Werkzeugantwort, egal wo sie steckt.

    Erkannt werden: `results`/`jobs` als Liste von Objekten oder Kennungen, ein
    verschachteltes `job`/`data`/`result`/`generation`, die Kennung auf oberster Ebene —
    und zur Not eine UUID im Klartext der Antwort. Eine übersehene Nummer hieße: Der
    Auftrag läuft und ist bezahlt, aber niemand holt ihn ab.
    """
    if not isinstance(antwort, dict):
        return ""
    felder = ("id", "jobId", "job_id", "request_id", "generation_id")
    for liste in (antwort.get("results"), antwort.get("jobs")):
        if isinstance(liste, list) and liste:
            erstes = liste[0]
            if isinstance(erstes, dict):
                for feld in felder:
                    if erstes.get(feld):
                        return str(erstes[feld])
            elif isinstance(erstes, str) and erstes.strip():
                return erstes.strip()
    for feld in felder:
        if antwort.get(feld) and not isinstance(antwort[feld], (dict, list)):
            return str(antwort[feld])
    for behaelter in ("job", "data", "result", "generation"):
        tiefer = antwort.get(behaelter)
        if isinstance(tiefer, dict):
            gefunden = _auftragsnummer(tiefer)
            if gefunden:
                return gefunden
    if isinstance(antwort.get("text"), str) and not antwort.get("error"):
        treffer = _UUID.search(antwort["text"])
        if treffer:
            return treffer.group(0)
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


_klient_gemerkt: httpx.Client | None = None
_klient_sperre = threading.Lock()


def _klient() -> httpx.Client:
    """Ein gemeinsamer HTTP-Client für alle Aufrufe.

    Einen Client zu bauen kostet unter Windows gut eine halbe Sekunde (Zertifikate
    laden). Bei einem Auftrag mit Modellauflösung, Schemaabruf und Standsabfragen
    kamen so leicht Minuten zusammen. httpx-Clients dürfen von mehreren Fäden
    gleichzeitig benutzt werden.
    """
    global _klient_gemerkt
    with _klient_sperre:
        if _klient_gemerkt is None or _klient_gemerkt.is_closed:
            _klient_gemerkt = httpx.Client(timeout=60, headers={"User-Agent": _UA})
        return _klient_gemerkt


def werkzeug_rufen(name: str, argumente: dict, zeitlimit: int = 60) -> dict:
    """Ein Werkzeug des Dienstes aufrufen."""
    return _rpc("tools/call", {"name": name, "arguments": argumente}, zeitlimit)


def _rpc(methode: str, parameter: dict, zeitlimit: int = 60) -> dict:
    """Ein beliebiger MCP-Aufruf. `tools/call` ist der häufigste, aber nicht der
    einzige: die Werkzeugliste kommt über `tools/list`."""
    token = _gueltiges_token()
    klient = _klient()
    try:
        # Sitzung eröffnen — manche Fassungen verlangen das vor jedem Aufruf.
        eroeffnung = klient.post(_MCP_URL, headers=_kopfzeilen(token), timeout=zeitlimit,
                                 json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": _PROTOKOLL, "capabilities": {},
                       "clientInfo": {"name": config.APP_NAME, "version":
                                      config.APP_VERSION}}})
        sitzung = (eroeffnung.headers.get("mcp-session-id") or
                   eroeffnung.headers.get("Mcp-Session-Id") or "")
        try:
            klient.post(_MCP_URL, headers=_kopfzeilen(token, sitzung), timeout=zeitlimit,
                        json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception:
            pass

    except httpx.TimeoutException as fehler:
        raise errors.ZeitFehler("Higgsfield hat nicht rechtzeitig geantwortet.",
                                "Das Programm versucht es erneut.",
                                ursprung=QUELLE) from fehler
    except httpx.HTTPError as fehler:
        raise errors.NetzFehler("Keine Verbindung zu Higgsfield.",
                                "Internetverbindung prüfen.", ursprung=QUELLE) from fehler

    # Der eigentliche Aufruf. Bei einem bestellenden Werkzeug ist ein Fehler **nach**
    # dem Absenden kein Netzproblem, sondern eine offene Frage: Der Auftrag kann längst
    # angenommen und bezahlt sein. Dann wird nicht wiederholt (`UnklarFehler`). Nur ein
    # Fehler beim Verbindungsaufbau beweist, dass nichts angekommen ist.
    bestellend = (methode == "tools/call" and
                  str(parameter.get("name", "")).startswith(("generate_", "create_")))
    kennung = secrets.randbelow(1_000_000) + 2
    try:
        antwort = klient.post(_MCP_URL, headers=_kopfzeilen(token, sitzung),
                              timeout=zeitlimit, json={
            "jsonrpc": "2.0", "id": kennung, "method": methode,
            "params": parameter})
    except (httpx.ConnectError, httpx.ConnectTimeout) as fehler:
        raise errors.NetzFehler("Keine Verbindung zu Higgsfield.",
                                "Internetverbindung prüfen.", ursprung=QUELLE) from fehler
    except httpx.HTTPError as fehler:
        if bestellend:
            raise _unklar(type(fehler).__name__) from fehler
        if isinstance(fehler, httpx.TimeoutException):
            raise errors.ZeitFehler("Higgsfield hat nicht rechtzeitig geantwortet.",
                                    "Das Programm versucht es erneut.",
                                    ursprung=QUELLE) from fehler
        raise errors.NetzFehler("Keine Verbindung zu Higgsfield.",
                                "Internetverbindung prüfen.", ursprung=QUELLE) from fehler

    if antwort.status_code == 401:
        raise errors.ZugangFehler("Die Anmeldung ist abgelaufen.",
                                  "Bitte im Dashboard erneut anmelden.", ursprung=QUELLE)
    if bestellend and antwort.status_code >= 500 and antwort.status_code != 503:
        raise _unklar(f"Code {antwort.status_code}")
    if antwort.status_code >= 400:
        raise errors.aus_httpfehler(antwort.status_code, antwort.text, ursprung=QUELLE)
    return _ergebnis(_zerlegen(antwort), kennung)


def _unklar(grund: str) -> errors.UnklarFehler:
    return errors.UnklarFehler(
        "Higgsfield hat auf den Auftrag nicht geantwortet — ob er angenommen wurde, "
        "ist unklar.",
        "Es wird nicht automatisch neu bestellt, damit nichts doppelt bezahlt wird. Bitte "
        "unter higgsfield.ai bei den letzten Erzeugungen nachsehen und dann „Erneut "
        f"versuchen“ klicken. (Technischer Grund: {grund})", ursprung=QUELLE)


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
    # Nach einem leeren Ergebnis eine Minute Ruhe: sonst fragte jede Modellauflösung —
    # also jede Szene und jeder Formversuch — dreimal vergeblich nach.
    if not erneuern and not _MODELLE["liste"] and \
            time.time() - float(_MODELLE.get("fehlzeit") or 0) < _WERKZEUGE_PAUSE:
        return []

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
    else:
        _MODELLE["fehlzeit"] = time.time()
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
    grob genug, um „kling-video/v2.6/pro“ auf „kling2_6“ zu bringen."""
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
    if _ERSATZ.get((wunsch, art)):
        # Die Vorprüfung hat festgestellt, dass der Dienst den Wunsch nicht führt, und
        # einen Ersatz gewählt. Dabei bleibt es für diesen Lauf.
        return _ERSATZ[(wunsch, art)]
    rueckfall = _VIDEOMODELL if art == "video" else _BILDMODELL
    bekannt = modellliste()
    if not bekannt:
        # `models_explore` hat nichts Brauchbares geliefert. Das Schema des Werkzeugs
        # zählt die Modelle oft selbst auf — kostenlos und verbindlicher als jede Tabelle.
        werkzeug = "generate_video" if art == "video" else "generate_image"
        try:
            aus_schema = parameterform(werkzeug).modelle
        except Exception:
            aus_schema = ()
        bekannt = [{"id": m, "name": m, "art": art} for m in aus_schema]
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

#: Gemerkte Werkzeugliste des Dienstes, samt Eingabeschemata.
_WERKZEUGE: dict = {"zeit": 0.0, "liste": [], "schemata": {}, "fehlzeit": 0.0}

#: So lange wird nach einem gescheiterten `tools/list` nicht erneut gefragt. Ohne diese
#: Pause fragte jede Modellauflösung wieder nach — bei einem hängenden Dienst also
#: jede einzelne Szene ein halbe Minute lang.
_WERKZEUGE_PAUSE = 60.0

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
    if (not erneuern and not _WERKZEUGE["liste"] and
            time.time() - float(_WERKZEUGE.get("fehlzeit") or 0) < _WERKZEUGE_PAUSE):
        return []
    try:
        antwort = _rpc("tools/list", {}, zeitlimit=30)
    except Exception:
        antwort = {}
    namen = _werkzeuge_normieren(antwort)
    if not namen:
        _WERKZEUGE["fehlzeit"] = time.time()
    if namen:
        _WERKZEUGE.update({"zeit": time.time(), "liste": namen,
                           "schemata": _schemata_aus(antwort)})
        logbook.debug(QUELLE, f"{len(namen)} Werkzeuge beim Abo-Dienst gefunden.")
        _schemata_ablegen(antwort)
    return list(namen)


def _schemata_aus(antwort) -> dict[str, dict]:
    """Name → Eingabeschema aus der Antwort von `tools/list`."""
    roh = antwort.get("tools") if isinstance(antwort, dict) else antwort
    schemata: dict[str, dict] = {}
    for eintrag in roh if isinstance(roh, list) else []:
        if isinstance(eintrag, dict) and eintrag.get("name"):
            schema = eintrag.get("inputSchema") or eintrag.get("input_schema") or {}
            if isinstance(schema, dict):
                schemata[str(eintrag["name"])] = schema
    return schemata


def _schemata_ablegen(antwort) -> None:
    """Legt die Werkzeugbeschreibung des Dienstes in `data/` ab.

    Nur für die Fehlersuche: Am 26.08. und am 10.09.2026 hing je ein Kundenlauf an
    einer Form, die sich von außen nicht messen ließ. Mit dieser Datei auf dem
    Kundenrechner steht die Antwort beim nächsten Mal schwarz auf weiß da. Sie enthält
    keine Zugangsdaten — nur, was der Dienst über seine Werkzeuge sagt.
    """
    try:
        ziel = config.DATA_DIR / "higgsfield_werkzeuge.json"
        ziel.write_text(json.dumps(antwort, ensure_ascii=False, indent=1)[:2_000_000],
                        encoding="utf-8")
    except Exception:
        pass


def werkzeugschema(name: str) -> dict:
    """Das Eingabeschema eines Werkzeugs — oder leer, wenn der Dienst keins nennt."""
    werkzeugliste()
    return dict((_WERKZEUGE.get("schemata") or {}).get(name) or {})


def _importwerkzeuge() -> list[str]:
    """Welche Werkzeuge des Dienstes könnten eine Adresse einführen?

    Kürzere Namen zuerst — `import_media` ist spezifischer als `import_media_batch`.
    """
    treffer = [name for name in werkzeugliste()
               if any(w in name.lower() for w in _IMPORTWORTE)
               and not any(w in name.lower() for w in _TABU)]
    return sorted(treffer, key=len)


# ── Das Schema des Dienstes lesen ────────────────────────────────────────────
#
# **Warum das hier steht.** Zweimal ist ein Kundenlauf an einer Form gescheitert, die
# von außen nicht zu messen war (`mcp.higgsfield.ai` beantwortet ohne Anmeldung alles
# mit 401). Beim dritten Mal — am 10.09.2026 — hieß die Antwort nur noch
#
#     Invalid arguments for tool generate_video: params: Invalid input
#
# und nannte nicht einmal das Feld. Der Dienst beschreibt seine Werkzeuge aber selbst:
# `tools/list` liefert zu jedem ein JSON-Schema, und dieser Aufruf kostet nichts. Mit
# angemeldetem Abo liest das Programm deshalb das Schema und baut die Parameter danach,
# statt eine Form zu raten. Die Vorgaben weiter unten gelten nur, wenn kein Schema kommt.
#
# Ein von zod erzeugtes Schema kann Verweise (`$ref`), Vereinigungen (`anyOf`, `oneOf`)
# und Verschmelzungen (`allOf`) enthalten. Die Helfer lösen alle drei auf und liefern
# schlichte Objektzweige, aus denen sich Felder, erlaubte Werte und die Form von
# `medias` ablesen lassen.

def _verweis(schema, wurzel: dict):
    """Löst `{"$ref": "#/definitions/X"}` auf — auch Verweise mit Listenindex
    (`#/properties/params/anyOf/0/…`, so erzeugt zod-to-json-schema sie) und die
    Maskierungen `~0`/`~1`. Unbekanntes bleibt, wie es ist."""
    tiefe = 0
    while isinstance(schema, dict) and isinstance(schema.get("$ref"), str) and tiefe < 20:
        ziel = wurzel
        pfad = schema["$ref"]
        if not pfad.startswith("#"):
            return schema
        for teil in pfad.lstrip("#").strip("/").split("/"):
            if not teil:
                continue
            teil = urllib.parse.unquote(teil).replace("~1", "/").replace("~0", "~")
            if isinstance(ziel, dict):
                ziel = ziel.get(teil)
            elif isinstance(ziel, list) and teil.isdigit() and int(teil) < len(ziel):
                ziel = ziel[int(teil)]
            else:
                ziel = None
        if not isinstance(ziel, dict):
            return schema
        schema = ziel
        tiefe += 1
    return schema


def _objektzweige(schema, wurzel: dict, tiefe: int = 0) -> list[dict]:
    """Alle Objektformen, die ein Schema zulässt — Vereinigungen aufgeklappt."""
    schema = _verweis(schema, wurzel)
    if not isinstance(schema, dict) or tiefe > 8:
        return []
    for schluessel in ("anyOf", "oneOf"):
        if isinstance(schema.get(schluessel), list):
            zweige: list[dict] = []
            for teil in schema[schluessel]:
                zweige += _objektzweige(teil, wurzel, tiefe + 1)
            return zweige
    if isinstance(schema.get("allOf"), list):
        verschmolzen: dict = {"type": "object", "properties": {}, "required": []}
        for teil in schema["allOf"]:
            for zweig in _objektzweige(teil, wurzel, tiefe + 1)[:1]:
                verschmolzen["properties"].update(zweig.get("properties") or {})
                verschmolzen["required"] += list(zweig.get("required") or [])
        return [verschmolzen]
    if schema.get("type") == "object" or isinstance(schema.get("properties"), dict):
        return [schema]
    return []


def _erlaubte_werte(schema, wurzel: dict) -> list:
    """Die festen Werte eines Feldes (`enum`, `const`, Vereinigung aus beidem)."""
    schema = _verweis(schema, wurzel)
    if not isinstance(schema, dict):
        return []
    if "const" in schema:
        return [schema["const"]]
    if isinstance(schema.get("enum"), list):
        return list(schema["enum"])
    werte: list = []
    for schluessel in ("anyOf", "oneOf"):
        for teil in schema.get(schluessel) or []:
            werte += _erlaubte_werte(teil, wurzel)
    return werte


def _bereich(schema, wurzel: dict) -> tuple[float, float] | None:
    """Unter- und Obergrenze eines Zahlenfeldes, falls das Schema eine nennt."""
    schema = _verweis(schema, wurzel)
    if not isinstance(schema, dict):
        return None
    unten = schema.get("minimum", schema.get("exclusiveMinimum"))
    oben = schema.get("maximum", schema.get("exclusiveMaximum"))
    if isinstance(unten, (int, float)) or isinstance(oben, (int, float)):
        return (float(unten if isinstance(unten, (int, float)) else 0),
                float(oben if isinstance(oben, (int, float)) else 3600))
    return None


@dataclass
class Parameterform:
    """Was das Schema über die Parameter eines Werkzeugs sagt — für ein Modell."""
    huelle: bool = True                 # stehen die Werte in `params` oder direkt?
    felder: tuple[str, ...] = ()        # erlaubte Feldnamen (leer: unbekannt)
    pflicht: tuple[str, ...] = ()
    modelle: tuple[str, ...] = ()       # Modellkennungen, die das Schema aufzählt
    werte: dict = field(default_factory=dict)      # Feld → erlaubte Werte
    bereiche: dict = field(default_factory=dict)   # Feld → (unten, oben)
    medien_felder: tuple[str, ...] = ()            # Felder eines `medias`-Eintrags
    medien_rollen: tuple[str, ...] = ()
    medien_text: bool = False           # `medias` als bloße Zeichenketten
    bekannt: bool = False               # stammt das aus einem echten Schema?

    def kurz(self) -> str:
        """Eine Zeile fürs Logbuch — genug, um beim nächsten Mal nicht zu raten."""
        if not self.bekannt:
            return "kein Schema vom Dienst"
        teile = []
        for name in self.felder:
            if name == "medias":
                inneres = ("Text" if self.medien_text else
                           "{" + ", ".join(self.medien_felder) + "}")
                rollen = f" Rollen {'/'.join(self.medien_rollen)}" if self.medien_rollen else ""
                teile.append(f"medias[{inneres}{rollen}]")
            elif self.werte.get(name) and name != "model":
                teile.append(f"{name}∈{'/'.join(str(w) for w in self.werte[name][:8])}")
            else:
                teile.append(name)
        return ("params{" if self.huelle else "{") + ", ".join(teile) + "}"


def parameterform(werkzeug: str, modell: str = "") -> Parameterform:
    """Liest aus dem Schema des Dienstes, welche Form `werkzeug` für `modell` will.

    Ohne Schema (Dienst antwortet nicht, Werkzeug unbekannt) kommt eine leere Form mit
    `bekannt=False` zurück — dann greifen die Vorgaben. Diese Funktion wirft nie.
    """
    try:
        schema = werkzeugschema(werkzeug)
    except Exception:
        schema = {}
    return _form_aus_schema(schema, modell)


def _form_aus_schema(schema: dict, modell: str = "") -> Parameterform:
    if not isinstance(schema, dict) or not schema:
        return Parameterform()
    wurzel = schema
    oben = (_objektzweige(schema, wurzel) or [{}])[0]
    eigenschaften = oben.get("properties") or {}

    # Nur ein Schema, das Felder nennt, sagt etwas über die Hülle. Ein nacktes
    # `{"type": "object"}` darf nicht dazu führen, dass `params` wegfällt — die Hülle
    # ist beim Kunden für `generate_image` belegt.
    if "params" in eigenschaften:
        huelle = True
    elif "model" in eigenschaften or "prompt" in eigenschaften:
        huelle = False
    else:
        return Parameterform()
    zweige = (_objektzweige(eigenschaften["params"], wurzel) if huelle
              else _objektzweige(schema, wurzel))
    if not zweige:
        return Parameterform(huelle=huelle, bekannt=huelle)

    # Alle Modellkennungen einsammeln, die das Schema irgendwo aufzählt.
    alle_modelle: list[str] = []
    for zweig in zweige:
        for wert in _erlaubte_werte((zweig.get("properties") or {}).get("model"), wurzel):
            if isinstance(wert, str) and wert not in alle_modelle:
                alle_modelle.append(wert)

    # Der Zweig, der zum Modell passt — sonst einer ohne Modellvorgabe, sonst der erste.
    passend = None
    for zweig in zweige:
        erlaubt = _erlaubte_werte((zweig.get("properties") or {}).get("model"), wurzel)
        if modell and modell in erlaubt:
            passend = zweig
            break
    if passend is None:
        passend = next((z for z in zweige if not _erlaubte_werte(
            (z.get("properties") or {}).get("model"), wurzel)), zweige[0])

    felder = passend.get("properties") or {}
    form = Parameterform(huelle=huelle, felder=tuple(felder),
                         pflicht=tuple(passend.get("required") or ()),
                         modelle=tuple(alle_modelle), bekannt=True)
    for name, teil in felder.items():
        werte = _erlaubte_werte(teil, wurzel)
        if werte:
            form.werte[name] = werte
        bereich = _bereich(teil, wurzel)
        if bereich:
            form.bereiche[name] = bereich

    if "medias" in felder:
        liste = _verweis(felder["medias"], wurzel)
        for kandidat in _objektzweige(liste, wurzel) or [liste]:
            if isinstance(kandidat, dict) and kandidat.get("items") is not None:
                liste = kandidat
                break
        eintrag = _verweis((liste or {}).get("items") if isinstance(liste, dict) else {},
                           wurzel)
        objekte = _objektzweige(eintrag, wurzel)
        if objekte:
            innen = objekte[0].get("properties") or {}
            form.medien_felder = tuple(innen)
            rollen: list = []
            for objekt in objekte:
                rollen += _erlaubte_werte((objekt.get("properties") or {}).get("role"),
                                          wurzel)
            form.medien_rollen = tuple(dict.fromkeys(str(r) for r in rollen))
        elif isinstance(eintrag, dict) and eintrag.get("type") == "string":
            form.medien_text = True
    return form


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


def _guthabenfehler(antwort) -> bool:
    text = _fehlertext(antwort).lower()
    return any(w in text for w in ("credit", "quota", "insufficient", "balance"))


def _eingabefehler(antwort) -> bool:
    """Weist der Dienst die **Form** des Auftrags zurück?

    Das ist der einzige Fall, in dem eine andere Form probiert werden darf: Die
    Schemaprüfung läuft vor jeder Abrechnung, ein abgewiesener Auftrag kostet nichts.
    Genau so sah der Abbruch am 10.09.2026 aus — „params: Invalid input“. Die frühere
    Prüfung suchte nach „medias“ im Text und hat ihn deshalb nicht erkannt.
    """
    text = _fehlertext(antwort).lower()
    if not text or _guthabenfehler(antwort):
        return False
    return any(w in text for w in (
        "invalid", "validation", "expected", "required", "unrecognized", "not one of",
        "must be", "unknown param", "unsupported", "not allowed", "not supported",
        "medias", "params", "schema", "enum"))


#: Welche Parameterform bei einem Werkzeug und Modell getragen hat. Die nächste Szene
#: beginnt dann gleich mit ihr, statt die abgewiesenen Formen noch einmal zu probieren.
_FORM_GEMERKT: dict[tuple[str, str], str] = {}

#: Wunsch → Ersatzmodell, wenn die Vorprüfung ein Modell beim Dienst nicht fand.
_ERSATZ: dict[tuple[str, str], str] = {}

#: So viele Formen werden je Auftrag höchstens probiert. Abgewiesene Formen kosten
#: nichts, aber irgendwann ist klar, dass es nicht an der Form liegt.
_MAX_FORMVERSUCHE = 10


def _bruch(verhaeltnis: str) -> float:
    links, _, rechts = str(verhaeltnis or "").partition(":")
    try:
        return float(links) / float(rechts)
    except (ValueError, ZeroDivisionError):
        return 0.0


def format_waehlen(erlaubt, wunsch: str) -> str:
    """Das erlaubte Seitenverhältnis, das dem Wunsch am nächsten kommt.

    Leer heißt: Das Modell kennt kein `aspect_ratio` — dann wird es nicht geschickt.
    Kling nimmt nur 16:9, 9:16 und 1:1; wer 3:4 bestellt, bekommt 9:16 statt eines
    abgewiesenen Auftrags.
    """
    kandidaten = [str(w) for w in (erlaubt or []) if _bruch(str(w))]
    if not kandidaten:
        return ""
    if wunsch in kandidaten:
        return wunsch
    ziel = _bruch(wunsch) or 16 / 9
    return min(kandidaten, key=lambda w: abs(_bruch(w) - ziel))


def dauer_waehlen(erlaubt, bereich, wunsch: int) -> int:
    """Die erlaubte Clipdauer, die dem Wunsch am nächsten kommt."""
    zahlen = [int(w) for w in (erlaubt or []) if isinstance(w, (int, float))
              or str(w).isdigit()]
    if zahlen:
        return min(zahlen, key=lambda w: (abs(w - wunsch), w))
    if bereich:
        return int(max(bereich[0], min(bereich[1], wunsch)))
    return int(wunsch)


def _medieneintrag(form: "Parameterform", kennung: str, rolle: str = "start_image"):
    """Ein Eintrag für `medias` — so, wie das Schema ihn beschreibt."""
    if form.medien_text:
        return kennung
    felder = form.medien_felder
    wertfeld = next((f for f in ("value", "id", "media_id", "job_id") if f in felder),
                    "value")
    rollen = form.medien_rollen
    gewaehlt = next((r for r in (rolle, "start_image", "image", "first_frame")
                     if r in rollen), rollen[0] if rollen else rolle)
    eintrag = {wertfeld: kennung}
    if "role" in felder or not felder:
        eintrag["role"] = gewaehlt
    return eintrag


def _ohne_ton(form: "Parameterform", parameter: dict) -> None:
    """Schaltet den Ton ab, wo das Modell es anbietet.

    Die Montage verwirft den Ton ohnehin, und bei manchen Modellen kostet er extra.
    Nur Felder, die das Schema nennt — ein unbekanntes Feld wäre ein abgewiesener Auftrag.
    """
    for feld in ("sound", "generate_audio"):
        if feld not in form.felder:
            continue
        erlaubt = form.werte.get(feld) or []
        if "off" in erlaubt:
            parameter[feld] = "off"
        elif not erlaubt or False in erlaubt:
            parameter[feld] = False


def _videoformen(modell: str, prompt: str, medien: str, dauer: int, verhaeltnis: str,
                 bewegungen, saat) -> list[tuple[str, dict]]:
    """Die Parameterformen für `generate_video`, beste zuerst.

    1. **Aus dem Schema des Dienstes** — wenn er eins liefert, ist das die Wahrheit.
    2. **Nach der offiziellen Doku** — `medias: [{value, role: "start_image"}]`, so
       dokumentiert im Skill-Repository von Higgsfield und in eigenen erfolgreichen
       Aufrufen über den MCP-Dienst (Skill `3dfig`, Rhein-Neckar).
    3. **Abwandlungen davon** — andere Rolle, ohne Seitenverhältnis.
    4. **Die Form bis zum 10.09.2026** — nur noch als letzter Versuch.
    """
    form = parameterform("generate_video", modell)
    grund = {"model": modell, "prompt": prompt[:config.MAX_PROMPT_CHARS]}
    formen: list[tuple[str, dict]] = []

    if form.bekannt and form.felder:
        parameter = {k: v for k, v in grund.items() if k in form.felder or k == "model"}
        if medien and "medias" in form.felder:
            parameter["medias"] = [_medieneintrag(form, medien)]
        if "duration" in form.felder:
            parameter["duration"] = dauer_waehlen(form.werte.get("duration"),
                                                  form.bereiche.get("duration"), dauer)
        if "aspect_ratio" in form.felder and verhaeltnis:
            gewaehlt = format_waehlen(form.werte.get("aspect_ratio"), verhaeltnis) \
                if form.werte.get("aspect_ratio") else verhaeltnis
            if gewaehlt:
                parameter["aspect_ratio"] = gewaehlt
        _ohne_ton(form, parameter)
        if bewegungen and "motions" in form.felder:
            parameter["motions"] = [{"id": k} for k in bewegungen if k]
        if saat and saat >= 1 and "seed" in form.felder:
            parameter["seed"] = int(saat)
        formen.append(("schema", parameter))

    tabelle = _ABO_VIDEO.get(modell, {})
    fb_dauer = dauer_waehlen(tabelle.get("dauer"), None, dauer)
    fb_format = (format_waehlen(tabelle["formate"], verhaeltnis) if "formate" in tabelle
                 else verhaeltnis)

    def mit(**zusatz) -> dict:
        teil = dict(grund)
        teil.update({k: v for k, v in zusatz.items() if v not in (None, "")})
        return teil

    if medien:
        formen += [
            ("doku", mit(medias=[{"value": medien, "role": "start_image"}],
                         aspect_ratio=fb_format, duration=fb_dauer)),
            ("doku_rolle_image", mit(medias=[{"value": medien, "role": "image"}],
                                     aspect_ratio=fb_format, duration=fb_dauer)),
            ("doku_ohne_format", mit(medias=[{"value": medien, "role": "start_image"}],
                                     duration=fb_dauer)),
            ("kennung_als_text", mit(medias=[medien], aspect_ratio=fb_format,
                                     duration=fb_dauer)),
        ]
    else:
        formen += [("doku", mit(aspect_ratio=fb_format, duration=fb_dauer)),
                   ("doku_ohne_format", mit(duration=fb_dauer))]
    return _einmalig(formen)


def _bildformen(modell: str, prompt: str, verhaeltnis: str) -> list[tuple[str, dict]]:
    """Die Parameterformen für `generate_image`.

    Vorne steht die Form, mit der beim Kunden am 10.09.2026 das Startbild entstand —
    sie hat nachweislich getragen und wird nicht angetastet. Das Schema kommt danach.
    """
    grund = {"model": modell, "prompt": prompt[:config.MAX_PROMPT_CHARS]}
    formen = [("belegt", {**grund, "aspect_ratio": verhaeltnis, "count": 1})]
    form = parameterform("generate_image", modell)
    if form.bekannt and form.felder:
        parameter = dict(grund)
        if "aspect_ratio" in form.felder:
            parameter["aspect_ratio"] = (format_waehlen(form.werte["aspect_ratio"],
                                                        verhaeltnis)
                                         if form.werte.get("aspect_ratio") else verhaeltnis)
        if "count" in form.felder:
            parameter["count"] = 1
        formen.append(("schema", parameter))
    formen.append(("ohne_anzahl", {**grund, "aspect_ratio": verhaeltnis}))
    return _einmalig(formen)


def _einmalig(formen: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    gesehen: set[str] = set()
    ergebnis = []
    for bezeichnung, parameter in formen:
        schluessel = json.dumps(parameter, sort_keys=True, ensure_ascii=False)
        if schluessel not in gesehen:
            gesehen.add(schluessel)
            ergebnis.append((bezeichnung, parameter))
    return ergebnis


def _alternativen(wunsch: str, art: str, schon: list[str]) -> list[str]:
    """Andere Modelle derselben Art, falls der Dienst das gewählte nicht nimmt."""
    kandidaten = list(_UEBERSETZUNG.get(wunsch, ()))
    kandidaten += ([_VIDEOMODELL, "kling3_0", "kling3_0_turbo"] if art == "video"
                   else [_BILDMODELL, "text2image_soul_v2"])
    try:
        modellliste(erneuern=True)
        kandidaten.insert(0, modell_aufloesen(wunsch, art))
    except Exception:
        pass
    return [k for k in dict.fromkeys(kandidaten) if k and "/" not in k and k not in schon]


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
    def _abschicken(werkzeug: str, argumente: dict, modell: str,
                    abbruch: threading.Event | None = None) -> dict:
        """Einen Auftrag in genau dieser Form abschicken.

        Mit derselben Geduld wie beim Platform-Weg: Ein Netzhänger auf dem Weg zum
        Dienst ist kein Grund, einen Auftrag zu verlieren. Ohne diese Wiederholung
        war der Abo-Weg der einzige, der bei der kleinsten Störung sofort aufgab.
        """
        return _mit_geduld(lambda: werkzeug_rufen(werkzeug, argumente, zeitlimit=90),
                           beschreibung=f"Auftrag an {modell}", abbruch=abbruch)

    def _einreichen(self, werkzeug: str, formen_bauen, *, art: str, wunsch: str,
                    abbruch: threading.Event | None) -> tuple[str, str]:
        """Reicht den Auftrag ein und gibt (Auftragsnummer, Modell) zurück.

        Probiert der Reihe nach die Formen, die `formen_bauen(modell)` liefert — aber
        **nur**, solange der Dienst die Form zurückweist. Das kostet nichts: Die
        Schemaprüfung läuft vor der Abrechnung. Jeder andere Fehler beendet die Suche
        sofort. Und sobald eine Nummer zurückkommt, wird nichts mehr abgeschickt — ein
        zweiter angenommener Auftrag wäre ein doppelt bezahlter.

        Weist der Dienst alle Formen eines Modells zurück oder kennt er das Modell
        nicht, kommt einmal ein anderes Modell derselben Art an die Reihe.
        """
        modelle = [modell_aufloesen(wunsch, art)]
        protokoll: list[str] = []
        versuche = 0
        nur_formfehler = True
        unbekannt = False
        letzter_grund = ""
        stelle = 0

        while stelle < len(modelle) and versuche < _MAX_FORMVERSUCHE:
            modell = modelle[stelle]
            formen = formen_bauen(modell)
            gemerkt = _FORM_GEMERKT.get((werkzeug, modell))
            formen.sort(key=lambda f: f[0] != gemerkt)
            huelle = True
            schema = parameterform(werkzeug, modell)
            if schema.bekannt:
                huelle = schema.huelle

            modellwechsel = False
            for bezeichnung, parameter in formen:
                if versuche >= _MAX_FORMVERSUCHE:
                    break
                versuche += 1
                argumente = {"params": parameter} if huelle else parameter
                antwort = self._abschicken(werkzeug, argumente, modell, abbruch)
                kennung = _auftragsnummer(antwort)
                if kennung:
                    _FORM_GEMERKT[(werkzeug, modell)] = bezeichnung
                    if protokoll:
                        logbook.info(QUELLE, f"{werkzeug}: angenommen mit Modell „{modell}“ "
                                             f"in der Form „{bezeichnung}“ (nach "
                                             f"{len(protokoll)} abgewiesenen Formen).")
                    return str(kennung), modell

                grund = config.entschaerfe(_fehlertext(antwort) or str(antwort)[:200])
                letzter_grund = grund
                protokoll.append(f"{modell}/{bezeichnung}: {grund[:160]}")
                logbook.debug(QUELLE, f"{werkzeug} abgewiesen ({modell}/{bezeichnung}): "
                                      f"{grund[:300]}")

                if _guthabenfehler(antwort):
                    raise errors.GuthabenFehler(
                        "Das Higgsfield-Abo hat keine Credits mehr.",
                        "Unter higgsfield.ai das Guthaben prüfen. Solange erzeugt der "
                        "Probelauf Platzhalterclips.", ursprung=QUELLE)
                if _inhaltsfehler(antwort):
                    raise errors.InhaltFehler(
                        "Higgsfield hat den Inhalt abgelehnt (Moderation).",
                        f"Der Dienst meldet: {grund[:200]}. Marken, echte Personen und "
                        "Gewalt vermeiden.", ursprung=QUELLE)
                if _tariffehler(antwort):
                    raise errors.ZugangFehler(
                        "Das Higgsfield-Abo erlaubt diesen Auftrag nicht.",
                        f"Der Dienst meldet: {grund[:200]}. Unter higgsfield.ai den Tarif "
                        "prüfen oder ein anderes Modell wählen.", ursprung=QUELLE)
                if _unbekanntes_modell(antwort):
                    unbekannt = True
                    modellwechsel = True
                    break
                if not grund.strip() or grund.strip() in ("{}", "None"):
                    # Kein Fehlertext und keine erkennbare Nummer: Der Auftrag kann
                    # angenommen sein, ohne dass wir ihn verfolgen können. Weitere Szenen
                    # würden genauso ins Leere laufen — also den ganzen Lauf beenden.
                    logbook.warnung(QUELLE, "Antwort ohne erkennbare Auftragsnummer: " +
                                    config.entschaerfe(json.dumps(antwort,
                                                                  ensure_ascii=False))[:800])
                    raise errors.UnklarFehler(
                        "Higgsfield hat geantwortet, aber keine Auftragsnummer genannt.",
                        "Ob der Auftrag angenommen wurde, ist unklar — es wird nichts "
                        "nachbestellt. Die Antwort steht im Logbuch; bitte oben auf "
                        "„Update“ klicken.", ursprung=QUELLE)
                if not _eingabefehler(antwort):
                    nur_formfehler = False
                    raise errors.AnbieterFehler(
                        "Higgsfield hat keine Auftragsnummer zurückgegeben.",
                        grund, ursprung=QUELLE)
            else:
                modellwechsel = True       # alle Formen dieses Modells abgewiesen

            if modellwechsel and len(modelle) == 1:
                for ersatz in _alternativen(wunsch, art, modelle)[:2]:
                    modelle.append(ersatz)
                if len(modelle) > 1:
                    logbook.warnung(QUELLE, f"Higgsfield nimmt „{modell}“ in keiner Form an "
                                            f"— es wird „{modelle[1]}“ versucht.")
            stelle += 1

        # Nichts hat getragen. Ausdrücklich ein Konfigurationsfehler: Die Ablauf-
        # steuerung beendet dann den ganzen Lauf, statt für jede weitere Szene erst ein
        # neues Startbild zu bezahlen, das dann an derselben Stelle hängen bleibt.
        logbook.warnung(QUELLE, "Abgewiesene Formen: " + " | ".join(protokoll)[:1500])
        logbook.warnung(QUELLE, "Schema des Dienstes: " +
                        parameterform(werkzeug, modelle[0]).kurz()[:600])
        if unbekannt:
            raise errors.KonfigurationsFehler(
                "Higgsfield kennt das eingestellte Modell im Abo nicht.",
                f"Der Dienst meldet: {letzter_grund[:300]}. Bitte im Formular ein anderes "
                "Modell wählen — oder oben auf „Update“ klicken.", ursprung=QUELLE)
        raise errors.KonfigurationsFehler(
            "Higgsfield nimmt den Auftrag in keiner bekannten Form an.",
            f"Der Dienst meldet: {letzter_grund[:300]}. Es wurde nichts abgerechnet. Die "
            "Einzelheiten stehen im Logbuch — bitte oben auf „Update“ klicken; bleibt es "
            "dabei, das Logbuch kopieren und weitergeben.", ursprung=QUELLE)

    def _auftrag(self, werkzeug: str, formen_bauen, *, art: str, wunsch: str,
                 abbruch: threading.Event | None, melden,
                 gemeldet=None, fortsetzen: str = "") -> higgsfield.Ergebnis:
        """Auftrag abschicken und auf das Ergebnis warten.

        `formen_bauen` liefert zu einem Modellnamen die Parameterformen. Das ist kein
        Selbstzweck: Weist der Dienst Form oder Modell ab, muss derselbe Auftrag anders
        gebaut werden können.

        `gemeldet(kennung, modell)` erfährt die Auftragsnummer, sobald sie feststeht —
        die Ablaufsteuerung schreibt sie in den Zwischenstand. `fortsetzen` nimmt eine
        solche Nummer entgegen und wartet auf diesen Auftrag, statt neu zu bestellen:
        Ein Auftrag, der beim Dienst schon läuft oder fertig ist, ist bezahlt.
        """
        begonnen = time.monotonic()
        if fortsetzen:
            kennung, modell = fortsetzen, modell_aufloesen(wunsch, art)
            logbook.info(QUELLE, "Ein bereits bezahlter Auftrag wird abgeholt statt neu "
                                 "bestellt.")
        else:
            kennung, modell = self._einreichen(werkzeug, formen_bauen, art=art,
                                               wunsch=wunsch, abbruch=abbruch)
            if gemeldet:
                try:
                    gemeldet(kennung, modell)
                except Exception:
                    pass

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
                    # „not found“ heißt: Diesen Auftrag gibt es beim Dienst nicht (mehr).
                    # Nur dann darf ein Wiederholungslauf neu bestellen — bei jeder anderen
                    # Meldung kann der Auftrag noch laufen und bezahlt sein.
                    endgueltig = any(w in grund.lower() for w in ("not found", "unknown job",
                                                                  "does not exist"))
                    raise errors.AnbieterFehler(
                        "Higgsfield kann den Stand des Auftrags nicht mitteilen.",
                        config.entschaerfe(grund), ursprung=QUELLE,
                        details={"endzustand": "unbekannt"} if endgueltig else {})

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
                    ursprung=QUELLE, details={"endzustand": zustand})

            if melden:
                anteil = min(0.95, vergangen / erwartet)
                melden(anteil, max(0.0, erwartet - vergangen), zustand or "läuft")
            time.sleep(float(roh.get("poll_after_seconds") or config.POLL_INTERVAL))

    def bild(self, prompt: str, *, seitenverhaeltnis: str = "16:9", aufloesung: str = "1080p",
             modell: str = "", verbessern: bool = True, saat: int | None = None,
             abbruch: threading.Event | None = None, melden=None,
             gemeldet=None, fortsetzen: str = "") -> higgsfield.Ergebnis:
        return self._auftrag(
            "generate_image",
            lambda einstellung: _bildformen(einstellung, prompt, seitenverhaeltnis),
            wunsch=modell or config.IMAGE_MODEL, art="bild", abbruch=abbruch,
            melden=melden, gemeldet=gemeldet, fortsetzen=fortsetzen)

    def video_aus_bild(self, prompt: str, bild_url: str, *, dauer: int = 5,
                       modell: str = "", saat: int | None = None,
                       bewegungen: list[str] | None = None,
                       seitenverhaeltnis: str = "16:9",
                       abbruch: threading.Event | None = None,
                       melden=None, gemeldet=None, fortsetzen: str = "",
                       bild_kennung: str = "") -> higgsfield.Ergebnis:
        # Die Medien-Kennung wird **vor** dem Auftrag geholt: die Formen werden für
        # jeden Versuch neu gebaut, und ein zweiter Import würde doppelt Aufwand kosten.
        # **Kein `image_url`.** Der Dienst weist rohe Adressen ab; er will die Kennung
        # eines Mediums oder eines fertigen Auftrags in `medias`.
        if bild_kennung and bild_url:
            _bild_merken(bild_url, bild_kennung)
        medien = "" if fortsetzen else (medienkennung(bild_url) if bild_url else "")

        return self._auftrag(
            "generate_video",
            lambda einstellung: _videoformen(einstellung, prompt, medien, int(dauer or 5),
                                             seitenverhaeltnis, bewegungen, saat),
            wunsch=modell or config.VIDEO_MODEL, art="video", abbruch=abbruch,
            melden=melden, gemeldet=gemeldet, fortsetzen=fortsetzen)

    def video_aus_text(self, prompt: str, *, dauer: int = 6, modell: str = "",
                       seitenverhaeltnis: str = "16:9",
                       abbruch: threading.Event | None = None,
                       melden=None, gemeldet=None,
                       fortsetzen: str = "") -> higgsfield.Ergebnis:
        return self.video_aus_bild(prompt, "", dauer=dauer, modell=modell,
                                   seitenverhaeltnis=seitenverhaeltnis,
                                   abbruch=abbruch, melden=melden, gemeldet=gemeldet,
                                   fortsetzen=fortsetzen)

    def vorpruefen(self, *, videomodell: str, bildmodell: str = "",
                   seitenverhaeltnis: str = "", dauer: int = 5,
                   mit_startbild: bool = True) -> dict:
        """Prüft **vor** dem ersten bezahlten Schritt, ob der Auftrag so durchgehen kann.

        Kostet nichts: gelesen wird nur die Werkzeugbeschreibung des Dienstes. Findet
        sich das Modell dort nicht, wird ein verfügbares derselben Art gewählt — oder,
        wenn es keins gibt, abgebrochen, bevor ein Startbild bezahlt ist. Genau das
        fehlte am 05.09. und am 10.09.2026: beide Male war das Bild schon bezahlt.

        Zurück kommen das Modell, das tatsächlich genommen wird, und das passende
        Seitenverhältnis — die Ablaufsteuerung montiert dann auch in diesem Format.
        """
        _gueltiges_token()
        namen = werkzeugliste(erneuern=True)
        if not namen:
            logbook.warnung(QUELLE, "Die Werkzeugbeschreibung des Abo-Dienstes war nicht "
                                    "lesbar — es wird nach den dokumentierten Vorgaben "
                                    "gearbeitet.")
            modell = modell_aufloesen(videomodell, "video")
            tabelle = _ABO_VIDEO.get(modell, {})
            return {"modell": modell, "schema": "",
                    "seitenverhaeltnis": (format_waehlen(tabelle.get("formate"),
                                                         seitenverhaeltnis)
                                          or seitenverhaeltnis),
                    "dauer": dauer_waehlen(tabelle.get("dauer"), None, dauer)}

        fehlend = [w for w in ("generate_video", "job_status") +
                   (("generate_image",) if mit_startbild else ()) if w not in namen]
        if fehlend:
            raise errors.KonfigurationsFehler(
                "Das Higgsfield-Abo bietet gerade nicht alles an, was ein Video braucht.",
                f"Es fehlt: {', '.join(fehlend)}. Bitte später erneut versuchen oder oben "
                "auf „Update“ klicken.", ursprung=QUELLE)

        ergebnis = {}
        for art, wunsch in (("video", videomodell), ("bild", bildmodell)):
            if art == "bild" and not (mit_startbild and wunsch):
                continue
            werkzeug = "generate_video" if art == "video" else "generate_image"
            _ERSATZ.pop((wunsch, art), None)
            modell = modell_aufloesen(wunsch, art)
            form = parameterform(werkzeug, modell)
            if form.bekannt and form.modelle and modell not in form.modelle:
                ersatz = next((m for m in _alternativen(wunsch, art, [modell])
                               if m in form.modelle), "")
                if not ersatz:
                    raise errors.KonfigurationsFehler(
                        f"Higgsfield bietet das Modell „{modell}“ im Abo nicht an.",
                        "Verfügbar sind: " + ", ".join(form.modelle[:12]) + ". Bitte im "
                        "Formular ein anderes Modell wählen.", ursprung=QUELLE)
                logbook.warnung(QUELLE, f"„{modell}“ führt der Abo-Dienst nicht — es wird "
                                        f"„{ersatz}“ genommen.")
                _ERSATZ[(wunsch, art)] = ersatz
                modell = ersatz
                form = parameterform(werkzeug, modell)
            if art == "video":
                logbook.info(QUELLE, f"Videomodell „{modell}“ · Schema: {form.kurz()}")
                if mit_startbild and form.bekannt and form.felder and \
                        "medias" not in form.felder:
                    logbook.warnung(QUELLE, "Das Videoschema nennt kein Feld „medias“ — "
                                            "das Startbild kommt womöglich nicht an.")
                tabelle = _ABO_VIDEO.get(modell, {})
                formate = form.werte.get("aspect_ratio") or tabelle.get("formate")
                ergebnis.update({
                    "modell": modell, "schema": form.kurz(),
                    "seitenverhaeltnis": (format_waehlen(formate, seitenverhaeltnis)
                                          if formate else seitenverhaeltnis),
                    "dauer": dauer_waehlen(form.werte.get("duration") or
                                           tabelle.get("dauer"),
                                           form.bereiche.get("duration"), dauer)})
            else:
                ergebnis["bildmodell"] = modell
        return ergebnis

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
        # Die Werkzeugbeschreibung kostet nichts und sagt, ob ein Videoauftrag in der
        # erwarteten Form überhaupt möglich ist — genau das, woran es bisher hing.
        namen = werkzeugliste()
        if not namen:
            zusatz = " Werkzeugliste gerade nicht lesbar."
        else:
            form = parameterform("generate_video", modell_aufloesen(config.VIDEO_MODEL,
                                                                    "video"))
            zusatz = (f" {len(namen)} Werkzeuge, Videoschema gelesen."
                      if form.bekannt else f" {len(namen)} Werkzeuge.")
        return {"zustand": "bereit", "ok": True, "guthaben": "über das Abo",
                "meldung": f"Abo verbunden (seit {wann}).{zusatz}", "hinweis": ""}


#: Gemeinsame Instanz.
client = HiggsfieldAbo()
