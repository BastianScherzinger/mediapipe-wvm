"""
logbook.py — Logbuch und Ereignisverteilung.

Ein einziger Kanal für zwei Dinge, die die Oberfläche beide braucht:
  * **Logzeilen** — was ist passiert (für das Logfenster unten)
  * **Ereignisse** — Zustandswechsel der Pipeline (welcher Block leuchtet, Fortschritt,
    wandernder Punkt auf der Verbindung)

Beide landen im selben Verteiler, damit die Oberfläche mit *einer* Verbindung auskommt und
die Reihenfolge garantiert stimmt: ein Ereignis kann nie vor der Logzeile ankommen, die es
erklärt.

Eigenschaften:
  * Thread-sicher — die Pipeline läuft in eigenen Fäden.
  * Abonnenten mit begrenzter Warteschlange: ein hängender Browser-Tab darf den
    Videoauftrag nicht ausbremsen; im Zweifel verliert der Abonnent Zeilen, nie das Programm.
  * Alles, was hier hineingeht, wird von Zugangsdaten befreit.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Iterator

from . import config

# Ebenen in aufsteigender Dringlichkeit. 'erfolg' liegt bewusst neben 'info':
# es ist keine Warnung, soll in der Oberfläche aber grün hervorgehoben werden.
EBENEN = ("debug", "info", "erfolg", "warnung", "fehler")

_VERLAUF_MAX = 600           # so viele Zeilen hält das Programm im Speicher vor
_ABONNENT_MAX = 400          # so viele Nachrichten darf ein Abonnent hinterherhinken

_sperre = threading.Lock()
_verlauf: deque[dict] = deque(maxlen=_VERLAUF_MAX)
_abonnenten: list[queue.Queue] = []
_laufende_nummer = 0
_logdatei_tag = ""
_logdatei = None


# ── Datei-Log ────────────────────────────────────────────────────────────────

def _datei() -> Any:
    """Tagesdatei zum Anhängen. Wechselt automatisch um Mitternacht."""
    global _logdatei, _logdatei_tag
    heute = datetime.now().strftime("%Y-%m-%d")
    if _logdatei is None or _logdatei_tag != heute:
        try:
            if _logdatei is not None:
                _logdatei.close()
        except Exception:
            pass
        try:
            _logdatei = open(config.LOG_DIR / f"studio-{heute}.log", "a",
                             encoding="utf-8", buffering=1)
            _logdatei_tag = heute
        except Exception:
            _logdatei = None       # Ohne Datei läuft das Programm weiter.
    return _logdatei


def _in_datei(eintrag: dict) -> None:
    datei = _datei()
    if datei is None:
        return
    try:
        datei.write("{zeit}  {ebene:<8} {quelle:<12} {text}\n".format(
            zeit=eintrag["zeit"], ebene=eintrag["ebene"].upper(),
            quelle=eintrag["quelle"], text=eintrag["text"]))
    except Exception:
        pass


# ── Verteilung ───────────────────────────────────────────────────────────────

def _sende(nachricht: dict) -> None:
    """Nachricht an alle Abonnenten. Ein voller Abonnent verliert seine ältesten
    Nachrichten, statt den Aufrufer zu blockieren."""
    with _sperre:
        empfaenger = list(_abonnenten)
    for q in empfaenger:
        try:
            q.put_nowait(nachricht)
        except queue.Full:
            try:
                q.get_nowait()          # ältestes verwerfen …
                q.put_nowait(nachricht)  # … und Platz für das neueste schaffen
            except Exception:
                pass


def abonnieren() -> queue.Queue:
    """Neue Warteschlange für einen Ereignisstrom (ein Browser-Tab)."""
    q: queue.Queue = queue.Queue(maxsize=_ABONNENT_MAX)
    with _sperre:
        _abonnenten.append(q)
    return q


def abbestellen(q: queue.Queue) -> None:
    with _sperre:
        if q in _abonnenten:
            _abonnenten.remove(q)


def anzahl_abonnenten() -> int:
    with _sperre:
        return len(_abonnenten)


# ── Öffentliche Schreibfunktionen ────────────────────────────────────────────

def log(ebene: str, quelle: str, text: str, *, details: dict | None = None,
        job: str = "") -> dict:
    """Eine Logzeile schreiben. `quelle` ist der Name des Blocks oder Moduls, der spricht
    ('Claude', 'Higgsfield', 'Formate', 'System') — die Oberfläche gruppiert danach."""
    global _laufende_nummer

    if ebene not in EBENEN:
        ebene = "info"
    jetzt = time.time()
    with _sperre:
        _laufende_nummer += 1
        nummer = _laufende_nummer

    eintrag = {
        "typ": "log",
        "nr": nummer,
        "zeitstempel": jetzt,
        "zeit": datetime.fromtimestamp(jetzt).strftime("%H:%M:%S"),
        "ebene": ebene,
        "quelle": quelle,
        "text": config.entschaerfe(str(text))[:2000],
        "details": details or {},
        "job": job,
    }

    with _sperre:
        _verlauf.append(eintrag)
    _in_datei(eintrag)
    _sende(eintrag)
    return eintrag


def debug(quelle: str, text: str, **kw) -> dict:
    return log("debug", quelle, text, **kw)


def info(quelle: str, text: str, **kw) -> dict:
    return log("info", quelle, text, **kw)


def erfolg(quelle: str, text: str, **kw) -> dict:
    return log("erfolg", quelle, text, **kw)


def warnung(quelle: str, text: str, **kw) -> dict:
    return log("warnung", quelle, text, **kw)


def fehler(quelle: str, text: str, **kw) -> dict:
    return log("fehler", quelle, text, **kw)


def ereignis(name: str, nutzlast: dict | None = None, *, job: str = "") -> dict:
    """Ein Pipeline-Ereignis verteilen. Erscheint nicht im Logfenster, sondern steuert die
    Blockdarstellung. Bekannte Namen:
        block          — Block wechselt den Zustand (wartend/aktiv/fertig/fehler)
        fortschritt    — Anteil und geschätzte Restzeit im aktiven Block
        uebergang      — Punkt wandert von einem Block zum nächsten
        auftrag        — Auftrag angelegt, beendet oder abgebrochen
        bibliothek     — Dateibestand hat sich geändert
        diagnose       — Ergebnis eines Selbsttests
    """
    nachricht = {"typ": "ereignis", "name": name, "zeitstempel": time.time(),
                 "job": job, **(nutzlast or {})}
    _sende(nachricht)
    return nachricht


# ── Lesen ────────────────────────────────────────────────────────────────────

def verlauf(grenze: int = 200, ab_nummer: int = 0, ebene: str = "") -> list[dict]:
    """Die letzten Logzeilen. `ab_nummer` erlaubt einer neu verbundenen Oberfläche,
    genau das nachzuholen, was ihr fehlt."""
    with _sperre:
        zeilen = list(_verlauf)
    if ab_nummer:
        zeilen = [z for z in zeilen if z["nr"] > ab_nummer]
    if ebene in EBENEN:
        ab_hier = EBENEN.index(ebene)
        zeilen = [z for z in zeilen if EBENEN.index(z["ebene"]) >= ab_hier]
    return zeilen[-max(1, min(grenze, _VERLAUF_MAX)):]


def strom(q: queue.Queue, *, taktung: float = 15.0) -> Iterator[str]:
    """Erzeugt den Datenstrom für die Oberfläche im SSE-Format.
    Der regelmäßige Taktschlag hält die Verbindung offen, auch wenn minutenlang nichts
    passiert — sonst kappt sie mancher Zwischenspeicher."""
    yield ": verbunden\n\n"
    while True:
        try:
            nachricht = q.get(timeout=taktung)
        except queue.Empty:
            yield f": takt {int(time.time())}\n\n"
            continue
        if nachricht is None:            # Abschaltsignal
            break
        try:
            yield f"data: {json.dumps(nachricht, ensure_ascii=False)}\n\n"
        except (TypeError, ValueError):
            # Nicht serialisierbare Nutzlast darf den Strom nicht abreißen lassen.
            yield 'data: {"typ":"log","ebene":"warnung","quelle":"System",' \
                  '"text":"Eine Nachricht konnte nicht übertragen werden."}\n\n'


def beenden() -> None:
    """Alle Ströme sauber schließen (beim Herunterfahren)."""
    with _sperre:
        empfaenger = list(_abonnenten)
        _abonnenten.clear()
    for q in empfaenger:
        try:
            q.put_nowait(None)
        except Exception:
            pass
    global _logdatei
    try:
        if _logdatei is not None:
            _logdatei.close()
    except Exception:
        pass
    _logdatei = None
