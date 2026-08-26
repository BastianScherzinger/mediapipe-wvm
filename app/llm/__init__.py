"""
llm — Zugang zu Sprachmodellen über eine Kette von Wegen.

Drei Wege, in der Reihenfolge aus `MPW_LLM_CHAIN`:

    cli    Claude über die Claude-Code-CLI. Nutzt die Abo-Anmeldung, braucht kein
           API-Guthaben. Am 03.08.2026 als einziger Weg nachweislich funktionsfähig.
    api    Anthropic-API mit ANTHROPIC_KEY. Greift automatisch, sobald Guthaben da ist.
    local  Ollama auf diesem Rechner. Offline, kostenlos, etwas schwächer — aber es
           läuft immer, und genau darum geht es bei einer Rückfallebene.

Ein Weg, der scheitert, wird für eine Weile gesperrt, damit nicht bei jeder Anfrage
erneut in dieselbe Zeitüberschreitung gelaufen wird. Die Sperre läuft von selbst ab.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .. import config, errors, logbook
from . import claude_api, claude_cli, lokal

QUELLE = "Sprachmodell"

#: Wie lange ein gescheiterter Weg übersprungen wird (Sekunden).
_SPERRDAUER = 300.0

_WEGE = {"cli": claude_cli, "api": claude_api, "local": lokal}

_sperre = threading.Lock()
_gesperrt: dict[str, float] = {}


@dataclass
class Antwort:
    """Was ein Sprachmodell geliefert hat — samt der Frage, wer geliefert hat."""
    text: str
    weg: str
    modell: str
    dauer: float

    @property
    def anzeigename(self) -> str:
        return {"cli": "Claude (Abo)", "api": "Claude (API)",
                "local": f"Lokal ({self.modell})"}.get(self.weg, self.weg)


def _ist_gesperrt(weg: str) -> bool:
    with _sperre:
        bis = _gesperrt.get(weg, 0.0)
        if bis and time.monotonic() < bis:
            return True
        _gesperrt.pop(weg, None)
        return False


def _sperren(weg: str, grund: str) -> None:
    with _sperre:
        _gesperrt[weg] = time.monotonic() + _SPERRDAUER
    logbook.warnung(QUELLE, f"Weg „{weg}“ fällt für {int(_SPERRDAUER / 60)} Minuten aus: {grund}")


def zuruecksetzen() -> None:
    """Alle Sperren aufheben — nach einer Konfigurationsänderung oder auf Knopfdruck."""
    with _sperre:
        _gesperrt.clear()


def verfuegbare_wege() -> list[dict]:
    """Für die Anzeige: welcher Weg kann gerade, und wenn nicht, warum."""
    ergebnis = []
    for name in config.LLM_CHAIN:
        modul = _WEGE.get(name)
        if modul is None:
            continue
        bereit, grund = modul.bereit()
        if bereit and _ist_gesperrt(name):
            bereit, grund = False, "vorübergehend gesperrt nach einem Fehlschlag"
        ergebnis.append({"weg": name, "name": modul.ANZEIGENAME,
                         "bereit": bereit, "grund": grund})
    return ergebnis


def erzeuge(system: str, auftrag: str, *, zeitlimit: int = 240,
            bevorzugt: str = "") -> Antwort:
    """Fragt der Reihe nach die Wege, bis einer antwortet.

    `bevorzugt` stellt einen Weg an den Anfang (für den Test im Einstellungsbereich),
    verwirft die übrigen aber nicht — Ausweichen bleibt immer möglich.
    """
    reihenfolge = list(config.LLM_CHAIN)
    if bevorzugt in reihenfolge:
        reihenfolge.remove(bevorzugt)
        reihenfolge.insert(0, bevorzugt)

    probleme: list[str] = []
    for name in reihenfolge:
        modul = _WEGE.get(name)
        if modul is None:
            continue
        if _ist_gesperrt(name):
            probleme.append(f"{name}: gesperrt nach vorherigem Fehlschlag")
            continue
        bereit, grund = modul.bereit()
        if not bereit:
            probleme.append(f"{name}: {grund}")
            continue

        begonnen = time.monotonic()
        try:
            logbook.debug(QUELLE, f"Frage {modul.ANZEIGENAME} …")
            text = modul.erzeuge(system, auftrag, zeitlimit=zeitlimit)
            if not (text or "").strip():
                raise errors.AnbieterFehler(f"{modul.ANZEIGENAME} hat nichts geantwortet.",
                                            ursprung=QUELLE)
            dauer = time.monotonic() - begonnen
            logbook.erfolg(QUELLE, f"{modul.ANZEIGENAME} hat geantwortet ({dauer:.1f} s).")
            return Antwort(text.strip(), name, modul.modellname(), dauer)

        except errors.StudioFehler as fehler:
            probleme.append(f"{name}: {fehler.meldung}")
            # Zugangs- und Guthabenprobleme ändern sich nicht von selbst — sperren.
            # Ein einzelner Netzhänger dagegen kann beim nächsten Mal weg sein.
            if isinstance(fehler, (errors.ZugangFehler, errors.GuthabenFehler,
                                   errors.KonfigurationsFehler)):
                _sperren(name, f"{fehler.meldung} {fehler.hinweis}".strip())
            else:
                # Der Grund gehört ins Logbuch, nicht nur in die Ausnahme: Beim Kunden
                # stand am 26.08.2026 nur „Die Claude-CLI meldet einen Fehler.“ im Log —
                # ohne den Satz dahinter war nicht zu erkennen, woran es lag.
                logbook.warnung(QUELLE, f"{modul.ANZEIGENAME}: "
                                        f"{fehler.meldung} {fehler.hinweis}".strip() +
                                        " — nächster Weg wird versucht.")
        except Exception as fehler:                       # unerwartet, aber nicht tödlich
            uebersetzt = errors.aus_ausnahme(fehler, ursprung=QUELLE)
            probleme.append(f"{name}: {uebersetzt.meldung}")
            logbook.warnung(QUELLE, f"{modul.ANZEIGENAME} unerwartet gescheitert: "
                                    f"{uebersetzt.meldung}")

    raise errors.AnbieterFehler(
        "Kein Sprachmodell konnte den Prompt schreiben.",
        "Geprüft wurde: " + " · ".join(probleme) + ". "
        "Abhilfe: „claude login“ ausführen, Guthaben aufladen oder Ollama starten "
        "(ollama serve).",
        ursprung=QUELLE, details={"versuche": probleme})
