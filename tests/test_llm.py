"""Tests für den Claude-CLI-Weg (app/llm/claude_cli.py).

Ohne echte CLI und ohne Netz: Eine kleine Attrappe steht an ihrer Stelle, schreibt auf,
womit sie aufgerufen wurde (Argumente, Standardeingabe, Arbeitsordner), und gibt eine
vorgegebene Antwort zurück. Geprüft wird, was beim Kunden schiefging — der mehrzeilige
Systemtext über die `.cmd`-Hülle, offene Werkzeuge, ein hängendes Zeitlimit und
Antwortformen, die die Hülle nicht kannte.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, errors  # noqa: E402
from app.llm import claude_cli  # noqa: E402

nur_unix = pytest.mark.skipif(sys.platform == "win32", reason="Attrappe ist ein Shell-Skript")


def _attrappe(ordner: Path, ausgabe: str, *, schlafen: int = 0) -> Path:
    """Legt eine CLI-Attrappe an. Sie protokolliert nach `ordner/aufruf.json`."""
    antwortdatei = ordner / "antwort.txt"
    antwortdatei.write_text(ausgabe, encoding="utf-8")
    protokoll = ordner / "aufruf.json"
    skript = ordner / "attrappe.py"
    skript.write_text(
        "import json, os, sys, time\n"
        "eingabe = sys.stdin.read()\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': eingabe, 'cwd': os.getcwd(),\n"
        f"           'inhalt': os.listdir(os.getcwd())}},\n"
        f"          open({str(protokoll)!r}, 'w', encoding='utf-8'))\n"
        f"time.sleep({schlafen})\n"
        f"sys.stdout.write(open({str(antwortdatei)!r}, encoding='utf-8').read())\n",
        encoding="utf-8")
    cli = ordner / "claude"
    # `exec` fehlt bewusst: So hängt der Python-Prozess als Kind unter der Shell —
    # wie Node hinter cmd.exe. Das Zeitlimit muss beide beenden.
    cli.write_text(f"#!/bin/sh\n{sys.executable} {skript} \"$@\"\n", encoding="utf-8")
    cli.chmod(0o755)
    return cli


@pytest.fixture
def cli_ordner(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLAUDE_OAUTH_TOKEN", "")
    monkeypatch.setattr(config, "CLAUDE_CLI_MODEL", "")
    return tmp_path


def _protokoll(ordner: Path) -> dict:
    return json.loads((ordner / "aufruf.json").read_text(encoding="utf-8"))


@nur_unix
def test_systemtext_geht_ueber_die_standardeingabe(cli_ordner, monkeypatch):
    """cmd.exe schneidet ein Argument am ersten Zeilenumbruch ab — also darf keines
    einen enthalten, und der Systemtext muss vollständig über stdin ankommen."""
    cli = _attrappe(cli_ordner, json.dumps({"type": "result", "subtype": "success",
                                            "is_error": False, "result": "Hallo"}))
    monkeypatch.setattr(config, "claude_cli_pfad", lambda: str(cli))
    system = "Zeile eins der Vorgaben.\nZeile zwei: & | < > ^ %\nZeile drei."
    assert claude_cli.erzeuge(system, "Schreib etwas.", zeitlimit=30) == "Hallo"

    aufruf = _protokoll(cli_ordner)
    assert not any("\n" in teil or "\r" in teil for teil in aufruf["argv"])
    assert all(teil.isascii() for teil in aufruf["argv"])
    assert "Zeile drei." in aufruf["stdin"]
    assert "Zeile zwei: & | < > ^ %" in aufruf["stdin"]
    assert "Schreib etwas." in aufruf["stdin"]
    assert aufruf["stdin"].index("Zeile eins") < aufruf["stdin"].index("Schreib etwas.")


@nur_unix
def test_werkzeuge_sind_gesperrt_und_der_ordner_ist_leer(cli_ordner, monkeypatch):
    """Fremder Webseitentext im Auftrag darf die CLI nicht zum Lesen der .env bringen."""
    cli = _attrappe(cli_ordner, json.dumps({"type": "result", "result": "ok"}))
    monkeypatch.setattr(config, "claude_cli_pfad", lambda: str(cli))
    claude_cli.erzeuge("", "x", zeitlimit=30)

    aufruf = _protokoll(cli_ordner)
    argv = aufruf["argv"]
    assert "--disallowedTools" in argv
    gesperrt = argv[argv.index("--disallowedTools") + 1:]
    gesperrt = gesperrt[:next((i for i, t in enumerate(gesperrt) if t.startswith("--")),
                              len(gesperrt))]
    for werkzeug in ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch",
                     "WebSearch", "NotebookEdit"):
        assert werkzeug in gesperrt
    assert int(argv[argv.index("--max-turns") + 1]) <= 2
    assert Path(aufruf["cwd"]).resolve() != config.BASE_DIR.resolve()
    assert aufruf["inhalt"] == []


@nur_unix
def test_zeitlimit_beendet_den_ganzen_prozessbaum(cli_ordner, monkeypatch):
    cli = _attrappe(cli_ordner, "spät", schlafen=60)
    monkeypatch.setattr(config, "claude_cli_pfad", lambda: str(cli))
    begonnen = time.monotonic()
    with pytest.raises(errors.ZeitFehler):
        claude_cli.erzeuge("", "x", zeitlimit=2)
    assert time.monotonic() - begonnen < 20


@nur_unix
@pytest.mark.parametrize("ausgabe, erwartet", [
    # Neuere Fassungen: eine Liste von Ereignissen, das Ergebnis steht im letzten.
    (json.dumps([{"type": "system", "subtype": "init"},
                 {"type": "assistant", "message": {}},
                 {"type": "result", "subtype": "success", "result": "Aus der Liste"}]),
     "Aus der Liste"),
    # JSON ohne Hülle: Das ist schon die Antwort des Modells und bleibt vollständig.
    ('{"szenen": [{"bild_prompt": "A cat"}]}', '{"szenen": [{"bild_prompt": "A cat"}]}'),
    ("Nur Text", "Nur Text"),
])
def test_antworthuelle_in_allen_formen(cli_ordner, monkeypatch, ausgabe, erwartet):
    cli = _attrappe(cli_ordner, ausgabe)
    monkeypatch.setattr(config, "claude_cli_pfad", lambda: str(cli))
    assert claude_cli.erzeuge("", "x", zeitlimit=30) == erwartet


@nur_unix
def test_fehler_in_der_ergebnisliste_wird_erkannt(cli_ordner, monkeypatch):
    cli = _attrappe(cli_ordner, json.dumps([
        {"type": "system"},
        {"type": "result", "subtype": "error_during_execution", "is_error": True,
         "result": "Etwas ging schief"}]))
    monkeypatch.setattr(config, "claude_cli_pfad", lambda: str(cli))
    with pytest.raises(errors.AnbieterFehler):
        claude_cli.erzeuge("", "x", zeitlimit=30)


def test_huelle_lesen_ohne_prozess():
    assert claude_cli._huelle_lesen([{"type": "result", "result": "a"}])["result"] == "a"
    assert claude_cli._huelle_lesen([{"type": "assistant"}]) is None
    assert claude_cli._huelle_lesen({"titel": "x"}) is None
    assert claude_cli._huelle_lesen({"result": "x", "is_error": False})["result"] == "x"
    assert claude_cli._huelle_lesen(42) is None


def test_schutzsatz_der_kommandozeile_uebersteht_cmd():
    """Einzeilig, ASCII, keine Zeichen, die cmd.exe deutet."""
    zeile = claude_cli._SCHUTZ_ZEILE
    assert zeile.isascii() and "\n" not in zeile
    assert not any(zeichen in zeile for zeichen in '&|<>^%"')
