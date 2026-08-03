"""
claude_api.py — Claude über die Anthropic-API.

Zweiter Weg der Kette. Auf diesem Rechner meldet der hinterlegte Schlüssel derzeit
„credit balance is too low“ (03.08.2026) — der Weg ist trotzdem fertig eingebaut und
greift ohne jede Änderung, sobald Guthaben vorhanden ist.
"""
from __future__ import annotations

from .. import config, errors

ANZEIGENAME = "Claude-API"


def _sdk():
    try:
        import anthropic
        return anthropic
    except ImportError:
        return None


def bereit() -> tuple[bool, str]:
    if not config.ANTHROPIC_KEY:
        return False, "kein ANTHROPIC_KEY in der .env"
    if _sdk() is None:
        return False, "Paket „anthropic“ nicht installiert"
    return True, ""


def modellname() -> str:
    return config.CLAUDE_API_MODEL


def erzeuge(system: str, auftrag: str, *, zeitlimit: int = 240) -> str:
    anthropic = _sdk()
    if anthropic is None:
        raise errors.KonfigurationsFehler(
            "Das Paket „anthropic“ fehlt.",
            "python -m pip install anthropic", ursprung=ANZEIGENAME)
    if not config.ANTHROPIC_KEY:
        raise errors.ZugangFehler("Kein ANTHROPIC_KEY hinterlegt.",
                                  "Schlüssel in der .env eintragen.", ursprung=ANZEIGENAME)

    klient = anthropic.Anthropic(api_key=config.ANTHROPIC_KEY, timeout=float(zeitlimit),
                                 max_retries=1)
    try:
        antwort = klient.messages.create(
            model=config.CLAUDE_API_MODEL,
            max_tokens=8000,
            system=system or "",
            messages=[{"role": "user", "content": auftrag}],
        )
    except Exception as fehler:
        text = str(fehler)
        klein = text.lower()
        if "credit balance" in klein or "insufficient" in klein or "billing" in klein:
            raise errors.GuthabenFehler(
                "Der Anthropic-Schlüssel hat kein Guthaben.",
                "Unter console.anthropic.com Guthaben aufladen — oder den CLI-Weg über das "
                "Abo nutzen, der kein Guthaben braucht.", ursprung=ANZEIGENAME) from fehler
        if "rate" in klein and "limit" in klein:
            raise errors.NetzFehler("Zu viele Anfragen an die Anthropic-API.",
                                    "Kurz warten.", ursprung=ANZEIGENAME) from fehler
        if "authentication" in klein or "invalid x-api-key" in klein or "401" in klein:
            raise errors.ZugangFehler("Anthropic hat den Schlüssel abgelehnt.",
                                      "ANTHROPIC_KEY in der .env prüfen.",
                                      ursprung=ANZEIGENAME) from fehler
        raise errors.aus_ausnahme(fehler, ursprung=ANZEIGENAME) from fehler

    teile = [stueck.text for stueck in antwort.content
             if getattr(stueck, "type", "") == "text"]
    return "\n".join(teile).strip()
