"""Gemeinsame Vorkehrungen für alle Tests.

Kein Test darf vom Zustand des Rechners abhängen, auf dem er läuft — und keiner darf
ihn verändern. Ohne diese Datei schrieben Tests in das echte `data/` (Laufzeiten,
Guthabenstand, Werkzeugbeschreibung), und auf einem Rechner mit hinterlegtem
HIGGSFIELD_API_KEY oder verbundenem Abo gingen Selbsttests wirklich hinaus.

Auch `config.DATA_DIR` und `config.OUTPUT_DIR` zeigen je Test auf einen eigenen
Ordner, mit frisch eingerichtetem Auftragsspeicher. Vorher legten die Premium-Tests ihre
Aufträge im echten `data/auftraege.db` an — im Programm stand danach „Erneut versuchen“
für einen Film, den nie jemand bestellt hatte. Tests, die `DATA_DIR` selbst setzen,
überschreiben diese Vorgabe einfach.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, higgsfield, higgsfield_mcp, jobstore  # noqa: E402


@pytest.fixture(autouse=True)
def higgsfield_abgeschottet(tmp_path_factory, monkeypatch):
    """Eigene Ablage für alles, was die Higgsfield-Module auf die Platte schreiben,
    und kein echter Schlüssel — ein Test, der einen vergisst, landet so bei einer
    klaren Fehlermeldung statt bei einem echten, womöglich bezahlten Aufruf."""
    ablage = tmp_path_factory.mktemp("higgsfield_daten")
    monkeypatch.setattr(higgsfield, "_laufzeiten",
                        higgsfield._Laufzeiten(ablage / "laufzeiten.json"))
    monkeypatch.setattr(higgsfield, "_guthaben",
                        higgsfield._Guthabenstand(ablage / "guthabenstand.json"))
    monkeypatch.setattr(higgsfield_mcp, "_anmeldedatei", ablage / "higgsfield_abo.json")
    monkeypatch.setattr(higgsfield_mcp, "_werkzeugdatei",
                        ablage / "higgsfield_werkzeuge.json")
    monkeypatch.setattr(config, "HIGGSFIELD_API_KEY", "")
    monkeypatch.setattr(higgsfield.client, "api_key", "")
    monkeypatch.delenv("HIGGSFIELD_API_KEY", raising=False)
    yield


@pytest.fixture(autouse=True)
def eigene_ablage(tmp_path_factory, monkeypatch):
    """Eigener Daten- und Ausgabeordner je Test — nie der echte Bestand."""
    wurzel = tmp_path_factory.mktemp("ablage")
    (wurzel / "data").mkdir()
    (wurzel / "output").mkdir()
    monkeypatch.setattr(config, "DATA_DIR", wurzel / "data")
    monkeypatch.setattr(config, "OUTPUT_DIR", wurzel / "output")
    jobstore.einrichten()
    yield
