"""Gemeinsame Vorkehrungen für alle Tests.

Kein Test darf vom Zustand des Rechners abhängen, auf dem er läuft — und keiner darf
ihn verändern. Ohne diese Datei schrieben Tests in das echte `data/` (Laufzeiten,
Guthabenstand, Werkzeugbeschreibung), und auf einem Rechner mit hinterlegtem
HIGGSFIELD_API_KEY oder verbundenem Abo gingen Selbsttests wirklich hinaus.

Umgebogen werden nur die Speicherorte der Higgsfield-Module, nicht `config.DATA_DIR`
selbst: Andere Tests setzen `DATA_DIR` gezielt und verlassen sich darauf.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, higgsfield, higgsfield_mcp  # noqa: E402


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
