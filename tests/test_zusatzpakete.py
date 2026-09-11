"""Tests für das Nachziehen der Zusatzpakete beim Start. Ohne Netz, ohne pip."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import updater  # noqa: E402


def test_nichts_zu_tun_wenn_playwright_schon_da_ist(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "_playwright_vorhanden", lambda: True)
    monkeypatch.setattr(updater.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(updater.subprocess, "run",
                        lambda *_a, **_k: pytest.fail("pip darf nicht laufen"))
    assert updater.zusatzpakete_nachziehen(im_hintergrund=False) is False


def test_hoechstens_ein_versuch_am_tag(monkeypatch, tmp_path):
    """Das erste Update führt der alte Updater aus — er kennt die Zusatzpakete nicht.
    Deshalb zieht der Start sie nach. Aber nicht bei jedem Start erneut: Ein Rechner, auf
    dem pip scheitert, soll nicht jedes Mal minutenlang im Hintergrund arbeiten."""
    monkeypatch.setattr(updater, "_playwright_vorhanden", lambda: False)
    monkeypatch.setattr(updater.config, "DATA_DIR", tmp_path)
    aufrufe: list[list[str]] = []
    monkeypatch.setattr(updater.subprocess, "run",
                        lambda befehl, **_k: aufrufe.append(befehl) or
                        SimpleNamespace(returncode=1))

    assert updater.zusatzpakete_nachziehen(im_hintergrund=False) is True
    assert updater.zusatzpakete_nachziehen(im_hintergrund=False) is False
    assert len(aufrufe) == 1
    assert aufrufe[0][-1].endswith("requirements-optional.txt")
