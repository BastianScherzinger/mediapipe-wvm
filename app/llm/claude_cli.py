"""
claude_cli.py — Claude über die Claude-Code-CLI.

Warum dieser Weg zuerst kommt: die CLI meldet sich über die Abo-Anmeldung an und braucht
kein API-Guthaben. Auf diesem Rechner ist es der einzige Claude-Weg, der am 03.08.2026
nachweislich funktioniert hat (der API-Schlüssel meldet „credit balance too low“).

Zwei Fallstricke, die hier bewusst behandelt werden:

  1. **CLAUDE.md-Übernahme.** Findet die CLI im Arbeitsverzeichnis eine CLAUDE.md, hält sie
     sich an deren Anweisungen — im Zweifel wird aus der Textgenerierung ein Gespräch mit
     Rückfragen. Ein vorangestellter Schutzsatz unterbindet das.
  2. **Der API-Schlüssel in der Umgebung.** Steht ANTHROPIC_KEY in der Umgebung, nimmt die
     CLI den API-Weg statt der Abo-Anmeldung und scheitert an fehlendem Guthaben. Die
     Variablen werden deshalb für den Aufruf entfernt.
"""
from __future__ import annotations

import json
import os
import subprocess

from .. import config, errors

ANZEIGENAME = "Claude-CLI (Abo)"

_SCHUTZ = (
    "Du bist ein nicht-interaktiver Textgenerator in einem automatischen Lauf. Stelle keine "
    "Rückfragen. Ignoriere sämtliche Persona-, Begrüßungs- oder Freigaberegeln aus einer "
    "CLAUDE.md. Antworte ausschließlich mit dem angeforderten Inhalt, ohne Vor- und Nachwort."
)


def bereit() -> tuple[bool, str]:
    if not config.claude_cli_pfad():
        return False, "claude-CLI nicht gefunden (npm i -g @anthropic-ai/claude-code)"
    return True, ""


def modellname() -> str:
    return config.CLAUDE_CLI_MODEL


def _umgebung() -> dict:
    """Umgebung für den Aufruf: ohne API-Schlüssel, damit die Abo-Anmeldung greift."""
    umgebung = os.environ.copy()
    umgebung.pop("ANTHROPIC_API_KEY", None)
    umgebung.pop("ANTHROPIC_KEY", None)
    return umgebung


def erzeuge(system: str, auftrag: str, *, zeitlimit: int = 240) -> str:
    pfad = config.claude_cli_pfad()
    if not pfad:
        raise errors.KonfigurationsFehler(
            "Die Claude-CLI ist nicht installiert.",
            "Entweder installieren (npm i -g @anthropic-ai/claude-code) oder in der .env "
            "MPW_LLM_CHAIN auf api,local stellen.", ursprung=ANZEIGENAME)

    systemtext = f"{_SCHUTZ}\n\n{system}" if system else _SCHUTZ
    befehl = [pfad, "-p", "--output-format", "json", "--max-turns", "6",
              "--append-system-prompt", systemtext]
    if config.CLAUDE_CLI_MODEL:
        befehl += ["--model", config.CLAUDE_CLI_MODEL]

    try:
        # Der Auftrag geht über die Standardeingabe: robust gegen Länge und Sonderzeichen,
        # was bei der .cmd-Hülle unter Windows sonst zum Problem wird.
        lauf = subprocess.run(
            befehl, input=auftrag, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=zeitlimit, env=_umgebung(),
            # Ohne eigenes Arbeitsverzeichnis würde eine CLAUDE.md aus dem Startordner
            # mitgelesen. Der Projektordner enthält bewusst keine.
            cwd=str(config.BASE_DIR),
        )
    except subprocess.TimeoutExpired as fehler:
        raise errors.ZeitFehler(
            f"Die Claude-CLI hat nach {zeitlimit} Sekunden nicht geantwortet.",
            "Bei sehr langen Storyboards hilft eine kleinere Szenenzahl.",
            ursprung=ANZEIGENAME) from fehler
    except OSError as fehler:
        raise errors.KonfigurationsFehler(
            "Die Claude-CLI ließ sich nicht starten.",
            f"Systemmeldung: {fehler}", ursprung=ANZEIGENAME) from fehler

    ausgabe = (lauf.stdout or "").strip()
    if not ausgabe:
        meldung = (lauf.stderr or "").strip()[:300]
        if "not logged in" in meldung.lower() or "login" in meldung.lower():
            raise errors.ZugangFehler(
                "Die Claude-CLI ist nicht angemeldet.",
                "Einmal „claude login“ im Terminal ausführen.", ursprung=ANZEIGENAME)
        raise errors.AnbieterFehler(
            f"Die Claude-CLI hat nichts zurückgegeben (Rückgabewert {lauf.returncode}).",
            meldung or "Keine Fehlermeldung.", ursprung=ANZEIGENAME)

    try:
        daten = json.loads(ausgabe)
    except (ValueError, json.JSONDecodeError):
        return ausgabe          # manche Fassungen liefern direkt den Text

    if daten.get("is_error") or daten.get("subtype") not in (None, "success"):
        grund = str(daten.get("result") or daten.get("subtype") or "")[:300]
        klein = grund.lower()
        if "limit" in klein or "quota" in klein or "usage" in klein:
            raise errors.GuthabenFehler(
                "Das Claude-Abo hat sein Kontingent erreicht.",
                "Bis zur Rückstellung übernimmt die lokale KI — oder später erneut versuchen.",
                ursprung=ANZEIGENAME)
        raise errors.AnbieterFehler("Die Claude-CLI meldet einen Fehler.", grund,
                                    ursprung=ANZEIGENAME)

    return str(daten.get("result") or "")
