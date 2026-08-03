"""Tests für die Aktualisierung. Kein Netz, kein echter Neustart."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, errors, pipeline, updater  # noqa: E402


class GitAttrappe:
    """Gibt für jeden Git-Aufruf eine vorbereitete Antwort."""

    def __init__(self, antworten: dict):
        self.antworten = antworten
        self.aufrufe: list[tuple] = []

    def __call__(self, *argumente, zeitlimit=45):
        self.aufrufe.append(argumente)
        for schluessel, wert in self.antworten.items():
            if schluessel in " ".join(argumente):
                return wert
        return (0, "")


@pytest.fixture(autouse=True)
def kein_laufender_auftrag(monkeypatch):
    monkeypatch.setattr(pipeline, "laeuft_gerade", lambda: "")


# ── Prüfen ───────────────────────────────────────────────────────────────────

def test_ohne_git_ordner_keine_aktualisierung(monkeypatch):
    monkeypatch.setattr(updater, "_git", GitAttrappe({"rev-parse": (128, "not a git repo")}))
    stand = updater.pruefen()
    assert stand["moeglich"] is False
    assert stand["zustand"] == "nicht_moeglich"
    assert stand["anzahl"] == 0


def test_ohne_fernverweis_keine_aktualisierung(monkeypatch):
    monkeypatch.setattr(updater, "_git", GitAttrappe({
        "rev-parse": (0, ".git"),
        "remote get-url": (2, "No such remote"),
    }))
    stand = updater.pruefen()
    assert stand["moeglich"] is False


def test_aktueller_stand(monkeypatch):
    monkeypatch.setattr(updater, "_git", GitAttrappe({
        "rev-parse --git-dir": (0, ".git"),
        "remote get-url": (0, "https://github.com/x/y.git"),
        "fetch": (0, ""),
        "rev-list": (0, "0"),
        "log -1": (0, "abc1234 03.08.2026"),
        "rev-parse --abbrev-ref": (0, "main"),
    }))
    stand = updater.pruefen()
    assert stand["zustand"] == "aktuell"
    assert stand["anzahl"] == 0
    assert "neuesten Stand" in stand["meldung"]


def test_aktualisierungen_werden_gezaehlt(monkeypatch):
    monkeypatch.setattr(updater, "_git", GitAttrappe({
        "rev-parse --git-dir": (0, ".git"),
        "remote get-url": (0, "https://github.com/x/y.git"),
        "fetch": (0, ""),
        "rev-list": (0, "3"),
        "log -1": (0, "abc1234 03.08.2026"),
        "rev-parse --abbrev-ref": (0, "main"),
    }))
    stand = updater.pruefen()
    assert stand["zustand"] == "verfuegbar"
    assert stand["anzahl"] == 3
    assert "3 Aktualisierungen" in stand["meldung"]


def test_eine_einzelne_aktualisierung_heisst_nicht_aktualisierungen(monkeypatch):
    monkeypatch.setattr(updater, "_git", GitAttrappe({
        "rev-parse --git-dir": (0, ".git"),
        "remote get-url": (0, "url"),
        "fetch": (0, ""),
        "rev-list": (0, "1"),
    }))
    assert "1 Aktualisierung verfügbar" in updater.pruefen()["meldung"]


def test_ohne_netz_bleibt_der_zustand_unbekannt(monkeypatch):
    monkeypatch.setattr(updater, "_git", GitAttrappe({
        "rev-parse --git-dir": (0, ".git"),
        "remote get-url": (0, "url"),
        "fetch": (128, "could not resolve host github.com"),
    }))
    stand = updater.pruefen()
    assert stand["zustand"] == "unbekannt"
    assert stand["moeglich"] is True          # es liegt nicht am Programm
    assert stand["anzahl"] == 0


def test_unlesbare_anzahl_wird_zu_null(monkeypatch):
    monkeypatch.setattr(updater, "_git", GitAttrappe({
        "rev-parse --git-dir": (0, ".git"),
        "remote get-url": (0, "url"),
        "fetch": (0, ""),
        "rev-list": (0, "kaputt"),
    }))
    assert updater.pruefen()["anzahl"] == 0


# ── Durchführen ──────────────────────────────────────────────────────────────

def test_kein_neustart_waehrend_ein_auftrag_laeuft(monkeypatch):
    """Der wichtigste Schutz: ein Neustart mitten im Lauf würde Guthaben verbrennen."""
    monkeypatch.setattr(pipeline, "laeuft_gerade", lambda: "abc123")
    with pytest.raises(errors.EingabeFehler) as info:
        updater.aktualisieren()
    assert "läuft gerade ein Auftrag" in info.value.meldung


def test_lokale_aenderungen_verhindern_die_aktualisierung(monkeypatch):
    monkeypatch.setattr(updater, "_git", GitAttrappe({
        "rev-parse --git-dir": (0, ".git"),
        "status --porcelain": (0, " M app/config.py\n M run.py"),
    }))
    with pytest.raises(errors.KonfigurationsFehler) as info:
        updater.aktualisieren(neustart=False)
    assert "app/config.py" in info.value.hinweis


def test_gescheitertes_holen_wird_gemeldet(monkeypatch):
    monkeypatch.setattr(updater, "_git", GitAttrappe({
        "rev-parse --git-dir": (0, ".git"),
        "status --porcelain": (0, ""),
        "pull": (1, "fatal: Not possible to fast-forward"),
    }))
    with pytest.raises(errors.AnbieterFehler) as info:
        updater.aktualisieren(neustart=False)
    assert "fast-forward" in info.value.hinweis


def test_erfolgreiche_aktualisierung_ohne_neustart(monkeypatch):
    monkeypatch.setattr(updater, "_git", GitAttrappe({
        "rev-parse --git-dir": (0, ".git"),
        "status --porcelain": (0, ""),
        "pull": (0, ""),
        "log -1": (0, "def5678 03.08.2026"),
        "rev-parse --abbrev-ref": (0, "main"),
    }))
    # Die Paketprüfung darf nicht wirklich laufen.
    monkeypatch.setattr(subprocess, "run",
                        lambda *_a, **_k: subprocess.CompletedProcess([], 0, "", ""))
    ergebnis = updater.aktualisieren(neustart=False)
    assert ergebnis["ok"] is True
    assert "def5678" in ergebnis["version"]


def test_nur_vorspulen_niemals_zusammenfuehren(monkeypatch):
    """Sicherheitszusage: es darf nie ein Merge entstehen, der lokale Arbeit umschreibt."""
    attrappe = GitAttrappe({
        "rev-parse --git-dir": (0, ".git"),
        "status --porcelain": (0, ""),
        "pull": (0, ""),
    })
    monkeypatch.setattr(updater, "_git", attrappe)
    monkeypatch.setattr(subprocess, "run",
                        lambda *_a, **_k: subprocess.CompletedProcess([], 0, "", ""))
    updater.aktualisieren(neustart=False)

    pull = [a for a in attrappe.aufrufe if a and a[0] == "pull"]
    assert pull, "es muss ein pull abgesetzt worden sein"
    assert "--ff-only" in pull[0]


def test_fehlgeschlagene_paketpruefung_bricht_nicht_ab(monkeypatch):
    """Wenn pip klemmt, soll trotzdem der neue Code aktiv werden."""
    monkeypatch.setattr(updater, "_git", GitAttrappe({
        "rev-parse --git-dir": (0, ".git"),
        "status --porcelain": (0, ""),
        "pull": (0, ""),
        "log -1": (0, "abc 03.08.2026"),
    }))

    def pip_faellt_aus(*_a, **_k):
        raise OSError("pip nicht gefunden")

    monkeypatch.setattr(subprocess, "run", pip_faellt_aus)
    assert updater.aktualisieren(neustart=False)["ok"] is True


# ── Echtes Repository ────────────────────────────────────────────────────────

def test_dieser_ordner_ist_eine_arbeitskopie():
    """Ohne Git-Arbeitskopie wäre die Aktualisierung beim Kunden nicht möglich."""
    assert updater.ist_git_ordner()


def test_kurzstand_liefert_eine_version():
    stand = updater._kurzstand()
    assert stand["version"] and stand["version"] != "unbekannt"
