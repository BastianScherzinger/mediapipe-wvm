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


def mit_token() -> bool:
    """Läuft die CLI über ein hinterlegtes Abo-Token statt über die Anmeldung des
    Rechners? Für die Anzeige im Selbsttest."""
    return bool(config.CLAUDE_OAUTH_TOKEN)


def _umgebung(mit_token: bool = True) -> dict:
    """Umgebung für den Aufruf.

    Drei Dinge sind hier entscheidend:

    1. Liegt ein Abo-Token in der .env, wird es gesetzt. Damit läuft die CLI auch auf
       einem Rechner, der nie `claude login` gesehen hat — genau das braucht ein Kunde,
       dem das Werkzeug übergeben wird.
    2. Ein API-Schlüssel in der Umgebung muss weg. Sonst nimmt die CLI den API-Weg statt
       der Abo-Anmeldung und scheitert an fehlendem Guthaben, obwohl das Abo trägt.
    3. `mit_token=False` lässt das Token bewusst weg. Das ist der zweite Versuch: Ein
       abgelaufenes oder zurückgezogenes Token in der .env würde sonst die **eigene**
       Anmeldung des Rechners überschreiben und einen funktionierenden Weg zunichte
       machen. Lieber ohne Token noch einmal fragen als grundlos aufgeben.
    """
    umgebung = os.environ.copy()
    umgebung.pop("ANTHROPIC_API_KEY", None)
    umgebung.pop("ANTHROPIC_KEY", None)
    if mit_token and config.CLAUDE_OAUTH_TOKEN:
        umgebung["CLAUDE_CODE_OAUTH_TOKEN"] = config.CLAUDE_OAUTH_TOKEN
    else:
        umgebung.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    return umgebung


#: Textbausteine, an denen ein Anmeldeproblem der CLI zu erkennen ist.
_ANMELDEWORTE = ("not logged in", "login", "unauthorized", "authentication",
                 "oauth", "invalid token", "expired", "revoked", "401")


def _wirkt_wie_anmeldeproblem(text: str) -> bool:
    klein = (text or "").lower()
    return any(wort in klein for wort in _ANMELDEWORTE)


def _einmal(befehl: list[str], auftrag: str, zeitlimit: int, mit_abo_token: bool) -> str:
    """Ein Aufruf der CLI. Wirft einen erklärten Fehler, gibt sonst den Text zurück."""
    try:
        # Der Auftrag geht über die Standardeingabe: robust gegen Länge und Sonderzeichen,
        # was bei der .cmd-Hülle unter Windows sonst zum Problem wird.
        lauf = subprocess.run(
            befehl, input=auftrag, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=zeitlimit,
            env=_umgebung(mit_abo_token),
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
        meldung = config.entschaerfe((lauf.stderr or "").strip()[:300])
        if _wirkt_wie_anmeldeproblem(meldung):
            raise errors.ZugangFehler(
                "Die Claude-CLI ist nicht angemeldet.",
                "Einmal „claude login“ im Terminal ausführen — oder ein gültiges "
                "CLAUDE_CODE_OAUTH_TOKEN in die .env eintragen.", ursprung=ANZEIGENAME)
        raise errors.AnbieterFehler(
            f"Die Claude-CLI hat nichts zurückgegeben (Rückgabewert {lauf.returncode}).",
            meldung or "Keine Fehlermeldung.", ursprung=ANZEIGENAME)

    try:
        daten = json.loads(ausgabe)
    except (ValueError, json.JSONDecodeError):
        return ausgabe          # manche Fassungen liefern direkt den Text

    if daten.get("is_error") or daten.get("subtype") not in (None, "success"):
        grund = config.entschaerfe(
            str(daten.get("result") or daten.get("error") or
                daten.get("subtype") or "")[:300])
        klein = grund.lower()
        if "limit" in klein or "quota" in klein or "usage" in klein:
            raise errors.GuthabenFehler(
                "Das Claude-Abo hat sein Kontingent erreicht.",
                "Bis zur Rückstellung übernimmt die lokale KI — oder später erneut versuchen.",
                ursprung=ANZEIGENAME)
        if _wirkt_wie_anmeldeproblem(grund):
            raise errors.ZugangFehler(
                "Die Claude-CLI ist nicht angemeldet.",
                f"Der Dienst meldet: {grund or 'kein gültiger Zugang'}. Einmal "
                "„claude login“ im Terminal ausführen — oder ein gültiges "
                "CLAUDE_CODE_OAUTH_TOKEN in die .env eintragen.", ursprung=ANZEIGENAME)
        raise errors.AnbieterFehler(
            "Die Claude-CLI meldet einen Fehler.",
            grund or "Keine nähere Angabe.", ursprung=ANZEIGENAME)

    return str(daten.get("result") or "")


def erzeuge(system: str, auftrag: str, *, zeitlimit: int = 240) -> str:
    """Fragt Claude über die CLI.

    Zwei Versuche, und zwar aus einem konkreten Grund: Steht in der .env ein Abo-Token,
    das nicht mehr gilt (abgelaufen, zurückgezogen, oder es gehörte von Anfang an
    jemand anderem), dann **überschreibt** es die Anmeldung des Rechners und macht
    einen Weg kaputt, der ohne .env-Eintrag funktioniert hätte. Genau das kann beim
    Kunden nicht ausgeschlossen werden. Scheitert der erste Versuch am Zugang, wird
    deshalb ohne Token erneut gefragt — dann greift „claude login“ des Benutzers.
    """
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
        return _einmal(befehl, auftrag, zeitlimit, mit_abo_token=True)
    except errors.ZugangFehler:
        if not config.CLAUDE_OAUTH_TOKEN:
            raise                       # es gab kein Token — ein zweiter Versuch ändert nichts
        from .. import logbook
        logbook.warnung(ANZEIGENAME,
                        "Das Abo-Token aus der .env wird nicht angenommen — es wird die "
                        "Anmeldung dieses Rechners versucht.")
        return _einmal(befehl, auftrag, zeitlimit, mit_abo_token=False)
