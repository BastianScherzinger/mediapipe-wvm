"""
jobstore.py — Aufträge dauerhaft speichern.

Ein Videoauftrag dauert Minuten und kostet Guthaben. Er darf deshalb nicht verschwinden,
nur weil das Fenster geschlossen wurde. Jeder Auftrag liegt in einer SQLite-Datei und
überlebt jeden Neustart.

Eine Besonderheit: Beim Start gilt jeder Auftrag, der noch als „läuft" verzeichnet ist,
als abgebrochen. Er kann nicht mehr laufen — der Faden, der ihn bearbeitet hat, ist mit
dem alten Programmlauf verschwunden. Ohne diese Bereinigung stünden solche Leichen für
immer im Dashboard und würden echte Aufträge blockieren.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import config, logbook

QUELLE = "Aufträge"

# Zustände eines Auftrags.
WARTEND = "wartend"
LAEUFT = "laeuft"
FERTIG = "fertig"
FEHLER = "fehler"
ABGEBROCHEN = "abgebrochen"

#: Reihenfolge der Blöcke im Dashboard — die Oberfläche zeichnet sie genau so.
BLOECKE = ("briefing", "claude", "bild", "video", "ausgabe")

BLOCKNAMEN = {
    "briefing": "Briefing",
    "claude": "Claude",
    "bild": "Startbild",
    "video": "Higgsfield",
    "ausgabe": "Ausgabe",
}

_sperre = threading.Lock()


def _programm_laeuft_bereits() -> bool:
    """Hört schon ein anderer Programmlauf auf dem Port?

    Das ist die einzige verlässliche Auskunft darüber, ob gerade ein Auftrag bearbeitet
    wird: Der Auftrag lebt im Prozess des Servers, nicht in der Datenbank.
    """
    import socket

    for port in config.bekannte_ports():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as verbindung:
            verbindung.settimeout(0.4)
            try:
                if verbindung.connect_ex((config.HOST, port)) == 0:
                    return True
            except OSError:
                continue
    return False


@dataclass
class Auftrag:
    """Ein Videoauftrag in allen seinen Phasen."""
    id: str
    angelegt: float
    geaendert: float
    zustand: str
    block: str = "briefing"
    titel: str = ""
    briefing: str = ""
    einstellungen: dict = field(default_factory=dict)
    drehbuch: dict = field(default_factory=dict)
    ergebnis: dict = field(default_factory=dict)
    fehler: dict = field(default_factory=dict)
    ordner: str = ""

    @property
    def laeuft_noch(self) -> bool:
        return self.zustand in (WARTEND, LAEUFT)

    def als_dict(self) -> dict:
        return {
            "id": self.id, "angelegt": self.angelegt, "geaendert": self.geaendert,
            "zustand": self.zustand, "block": self.block, "titel": self.titel,
            "briefing": self.briefing, "einstellungen": self.einstellungen,
            "drehbuch": self.drehbuch, "ergebnis": self.ergebnis,
            "fehler": self.fehler, "ordner": self.ordner,
            "alter_sekunden": round(time.time() - self.angelegt),
        }


def _verbindung() -> sqlite3.Connection:
    """Eigene Verbindung je Aufruf — SQLite-Verbindungen sind nicht für die gemeinsame
    Nutzung durch mehrere Fäden gedacht, und die Aufrufe hier sind kurz."""
    verbindung = sqlite3.connect(config.DATA_DIR / "auftraege.db", timeout=15)
    verbindung.row_factory = sqlite3.Row
    # Schreiben und Lesen sollen sich nicht gegenseitig blockieren.
    verbindung.execute("PRAGMA journal_mode=WAL")
    return verbindung


def einrichten() -> None:
    """Legt die Tabelle an und räumt Überbleibsel eines abgestürzten Laufs weg."""
    with _sperre, _verbindung() as verbindung:
        verbindung.execute("""
            CREATE TABLE IF NOT EXISTS auftraege (
                id            TEXT PRIMARY KEY,
                angelegt      REAL NOT NULL,
                geaendert     REAL NOT NULL,
                zustand       TEXT NOT NULL,
                block         TEXT NOT NULL DEFAULT 'briefing',
                titel         TEXT NOT NULL DEFAULT '',
                briefing      TEXT NOT NULL DEFAULT '',
                einstellungen TEXT NOT NULL DEFAULT '{}',
                drehbuch      TEXT NOT NULL DEFAULT '{}',
                ergebnis      TEXT NOT NULL DEFAULT '{}',
                fehler        TEXT NOT NULL DEFAULT '{}',
                ordner        TEXT NOT NULL DEFAULT ''
            )""")
        verbindung.execute(
            "CREATE INDEX IF NOT EXISTS idx_angelegt ON auftraege(angelegt DESC)")

        # Leichen aus einem früheren Programmlauf — aber nur, wenn wirklich keiner mehr
        # läuft. Sonst passiert, was am 18.09.2026 passiert ist: Ein zweiter Prozess
        # importiert das Paket (ein Testlauf, ein Prüfbefehl, ein zweiter Start), und
        # dieser Import erklärt den Auftrag, der nebenan gerade seit einer Stunde
        # rechnet, für abgebrochen. Der Faden läuft weiter, die Anzeige sagt das
        # Gegenteil — der schlimmste aller Zustände.
        if _programm_laeuft_bereits():
            return

        gefunden = verbindung.execute(
            "SELECT id FROM auftraege WHERE zustand IN (?, ?)", (WARTEND, LAEUFT)
        ).fetchall()
        if gefunden:
            verbindung.execute(
                "UPDATE auftraege SET zustand=?, geaendert=?, fehler=? "
                "WHERE zustand IN (?, ?)",
                (ABGEBROCHEN, time.time(),
                 json.dumps({"meldung": "Beim Beenden des Programms unterbrochen.",
                             "hinweis": "Der Auftrag kann neu gestartet werden."}),
                 WARTEND, LAEUFT))
            logbook.warnung(QUELLE, f"{len(gefunden)} Auftrag/Aufträge aus einem früheren "
                                    "Programmlauf als abgebrochen vermerkt.")


def _aus_zeile(zeile: sqlite3.Row) -> Auftrag:
    def geladen(text: str) -> dict:
        try:
            wert = json.loads(text or "{}")
            return wert if isinstance(wert, dict) else {}
        except ValueError:
            return {}

    return Auftrag(
        id=zeile["id"], angelegt=zeile["angelegt"], geaendert=zeile["geaendert"],
        zustand=zeile["zustand"], block=zeile["block"], titel=zeile["titel"],
        briefing=zeile["briefing"], einstellungen=geladen(zeile["einstellungen"]),
        drehbuch=geladen(zeile["drehbuch"]), ergebnis=geladen(zeile["ergebnis"]),
        fehler=geladen(zeile["fehler"]), ordner=zeile["ordner"])


def anlegen(briefing: str, einstellungen: dict, titel: str = "") -> Auftrag:
    jetzt = time.time()
    auftrag = Auftrag(
        id=uuid.uuid4().hex[:12], angelegt=jetzt, geaendert=jetzt,
        zustand=WARTEND, block="briefing", titel=titel or briefing[:60],
        briefing=briefing, einstellungen=einstellungen)
    with _sperre, _verbindung() as verbindung:
        verbindung.execute(
            "INSERT INTO auftraege (id, angelegt, geaendert, zustand, block, titel, "
            "briefing, einstellungen, drehbuch, ergebnis, fehler, ordner) "
            "VALUES (?,?,?,?,?,?,?,?,'{}','{}','{}','')",
            (auftrag.id, jetzt, jetzt, auftrag.zustand, auftrag.block, auftrag.titel,
             auftrag.briefing, json.dumps(einstellungen, ensure_ascii=False)))
    return auftrag


def aktualisieren(auftrag_id: str, **felder) -> None:
    """Ändert einzelne Felder. Wörterbücher werden dabei nach JSON gewandelt."""
    erlaubt = {"zustand", "block", "titel", "drehbuch", "ergebnis", "fehler", "ordner"}
    setzen, werte = [], []
    for name, wert in felder.items():
        if name not in erlaubt:
            continue
        setzen.append(f"{name}=?")
        werte.append(json.dumps(wert, ensure_ascii=False)
                     if isinstance(wert, (dict, list)) else wert)
    if not setzen:
        return
    setzen.append("geaendert=?")
    werte.extend([time.time(), auftrag_id])
    with _sperre, _verbindung() as verbindung:
        verbindung.execute(f"UPDATE auftraege SET {', '.join(setzen)} WHERE id=?", werte)


def holen(auftrag_id: str) -> Auftrag | None:
    with _verbindung() as verbindung:
        zeile = verbindung.execute("SELECT * FROM auftraege WHERE id=?",
                                   (auftrag_id,)).fetchone()
    return _aus_zeile(zeile) if zeile else None


def liste(grenze: int = 50, nur_laufende: bool = False) -> list[Auftrag]:
    frage = "SELECT * FROM auftraege"
    werte: list = []
    if nur_laufende:
        frage += " WHERE zustand IN (?, ?)"
        werte += [WARTEND, LAEUFT]
    frage += " ORDER BY angelegt DESC LIMIT ?"
    werte.append(max(1, min(grenze, 500)))
    with _verbindung() as verbindung:
        return [_aus_zeile(z) for z in verbindung.execute(frage, werte).fetchall()]


def laufender() -> Auftrag | None:
    """Der eine Auftrag, der gerade bearbeitet wird — oder nichts."""
    vorhandene = liste(grenze=5, nur_laufende=True)
    return vorhandene[0] if vorhandene else None


def loeschen(auftrag_id: str) -> bool:
    with _sperre, _verbindung() as verbindung:
        ergebnis = verbindung.execute("DELETE FROM auftraege WHERE id=?", (auftrag_id,))
    return ergebnis.rowcount > 0


def aufraeumen(behalten: int = 200) -> int:
    """Hält die Datenbank klein. Löscht nur Einträge, nicht die Videodateien — die
    gehören dem Kunden und werden ausschließlich auf ausdrücklichen Wunsch entfernt."""
    with _sperre, _verbindung() as verbindung:
        ergebnis = verbindung.execute(
            "DELETE FROM auftraege WHERE id NOT IN "
            "(SELECT id FROM auftraege ORDER BY angelegt DESC LIMIT ?)", (behalten,))
    return ergebnis.rowcount


def ordner_fuer(auftrag: Auftrag, dateiname: str) -> Path:
    """Legt den Ausgabeordner an: ein Ordner je Auftrag, mit Datum und sprechendem Namen.
    Die Auftragskennung hinten macht ihn eindeutig, auch bei gleichem Titel."""
    datum = time.strftime("%Y-%m-%d", time.localtime(auftrag.angelegt))
    sauber = (dateiname or "video")[:48]
    ordner = config.OUTPUT_DIR / f"{datum}_{sauber}_{auftrag.id[:6]}"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


einrichten()
