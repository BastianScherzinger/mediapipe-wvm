"""
lokal.py — Ollama auf diesem Rechner.

Letzte Rückfallebene: kostenlos, offline, unabhängig von jedem Kontingent. Sie ist der
Grund, warum das Werkzeug auch dann noch einen Prompt schreiben kann, wenn Abo und
Guthaben gleichzeitig erschöpft sind.

Fehlt das eingestellte Modell, wird es auf Wunsch (MPW_LOCAL_AUTOPULL) beim ersten Bedarf
geladen. Das dauert beim ersten Mal einige Minuten — der Fortschritt läuft ins Logbuch,
damit niemand vor einem scheinbar eingefrorenen Fenster sitzt.
"""
from __future__ import annotations

import json
import threading

import httpx

from .. import config, errors, logbook

ANZEIGENAME = "Lokale KI (Ollama)"

_ladesperre = threading.Lock()      # nie zwei Downloads desselben Modells gleichzeitig


def bereit() -> tuple[bool, str]:
    """Läuft der Dienst? Ob das Modell schon da ist, klärt sich beim Aufruf — dort kann
    es geladen werden, hier nicht."""
    try:
        with httpx.Client(timeout=3) as klient:
            antwort = klient.get(f"{config.OLLAMA_URL}/api/tags")
        if antwort.status_code != 200:
            return False, f"Ollama antwortet mit Code {antwort.status_code}"
    except Exception:
        return False, "Ollama läuft nicht (ollama serve)"
    return True, ""


def modellname() -> str:
    return config.LOCAL_MODEL


def vorhandene_modelle() -> list[str]:
    try:
        with httpx.Client(timeout=5) as klient:
            daten = klient.get(f"{config.OLLAMA_URL}/api/tags").json()
        return [m.get("name", "") for m in daten.get("models", []) if m.get("name")]
    except Exception:
        return []


def _modell_da(name: str) -> bool:
    vorhanden = vorhandene_modelle()
    # Ollama führt Modelle mit Kennzeichnung ('qwen2.5:7b'); ohne Angabe gilt ':latest'.
    return any(v == name or v.split(":")[0] == name.split(":")[0] for v in vorhanden)


def modell_laden(name: str) -> None:
    """Lädt ein fehlendes Modell und meldet den Fortschritt ins Logbuch."""
    with _ladesperre:
        if _modell_da(name):
            return
        logbook.info(ANZEIGENAME, f"Lade lokales Modell „{name}“ herunter — "
                                  "das dauert beim ersten Mal einige Minuten.")
        letzte_meldung = -1
        try:
            with httpx.Client(timeout=None) as klient:
                with klient.stream("POST", f"{config.OLLAMA_URL}/api/pull",
                                   json={"name": name, "stream": True}) as strom:
                    if strom.status_code != 200:
                        raise errors.KonfigurationsFehler(
                            f"Ollama lehnt den Download ab (Code {strom.status_code}).",
                            f"Von Hand versuchen: ollama pull {name}", ursprung=ANZEIGENAME)
                    for zeile in strom.iter_lines():
                        if not zeile:
                            continue
                        try:
                            stand = json.loads(zeile)
                        except ValueError:
                            continue
                        gesamt = stand.get("total") or 0
                        fertig = stand.get("completed") or 0
                        if gesamt:
                            anteil = int(fertig * 100 / gesamt)
                            if anteil >= letzte_meldung + 20:      # nicht zuspammen
                                letzte_meldung = anteil
                                logbook.info(ANZEIGENAME, f"Download {anteil} %")
                        if stand.get("error"):
                            raise errors.KonfigurationsFehler(
                                f"Ollama meldet: {stand['error']}",
                                f"Von Hand versuchen: ollama pull {name}",
                                ursprung=ANZEIGENAME)
        except errors.StudioFehler:
            raise
        except Exception as fehler:
            raise errors.KonfigurationsFehler(
                f"Das lokale Modell „{name}“ ließ sich nicht laden.",
                f"Von Hand versuchen: ollama pull {name}",
                ursprung=ANZEIGENAME) from fehler
        logbook.erfolg(ANZEIGENAME, f"Modell „{name}“ ist einsatzbereit.")


def erzeuge(system: str, auftrag: str, *, zeitlimit: int = 240) -> str:
    name = config.LOCAL_MODEL
    if not _modell_da(name):
        if not config.LOCAL_AUTOPULL:
            raise errors.KonfigurationsFehler(
                f"Das lokale Modell „{name}“ ist nicht installiert.",
                f"Entweder „ollama pull {name}“ ausführen oder MPW_LOCAL_AUTOPULL=1 setzen.",
                ursprung=ANZEIGENAME)
        modell_laden(name)

    try:
        with httpx.Client(timeout=float(zeitlimit)) as klient:
            antwort = klient.post(f"{config.OLLAMA_URL}/api/chat", json={
                "model": name,
                "stream": False,
                "messages": ([{"role": "system", "content": system}] if system else [])
                            + [{"role": "user", "content": auftrag}],
                # Wenig Streuung: wir wollen verlässliches JSON, keine Kreativität in der Form.
                "options": {"temperature": 0.4, "num_ctx": 8192},
            })
    except httpx.TimeoutException as fehler:
        raise errors.ZeitFehler(
            f"Die lokale KI hat nach {zeitlimit} Sekunden nicht geantwortet.",
            "Ein kleineres Modell (MPW_LOCAL_MODEL=qwen2.5:3b) ist deutlich schneller.",
            ursprung=ANZEIGENAME) from fehler
    except httpx.HTTPError as fehler:
        raise errors.KonfigurationsFehler(
            "Ollama ist nicht erreichbar.", "Dienst starten: ollama serve",
            ursprung=ANZEIGENAME) from fehler

    if antwort.status_code != 200:
        raise errors.AnbieterFehler(
            f"Ollama antwortet mit Code {antwort.status_code}.",
            config.entschaerfe(antwort.text[:200]), ursprung=ANZEIGENAME)

    try:
        daten = antwort.json()
    except ValueError as fehler:
        raise errors.AnbieterFehler("Ollama hat unlesbar geantwortet.",
                                    ursprung=ANZEIGENAME) from fehler
    return str((daten.get("message") or {}).get("content") or "").strip()
