"""
library.py — die Videobibliothek.

Ein Ordner unter `output/` ist ein Video. Darin liegen die Szenenclips, der montierte
Film, das Vorschaubild, alle erzeugten Formatfassungen und ein Begleitzettel mit dem
Briefing und dem Drehbuch.

Die Bibliothek liest diesen Bestand, sagt der Oberfläche, welche Fassungen es schon gibt
und welche fehlen, und erzeugt die fehlenden auf Klick.

**Zur Sicherheit:** Jeder Pfad, der aus der Oberfläche kommt, geht durch
`sicherer_pfad()`. Der Ausgabeordner ist die Grenze — dahinter kommt niemand, auch nicht
mit `..`, einem absoluten Pfad oder einer Verknüpfung. Das Programm läuft zwar nur
lokal, aber eine Anwendung, die beliebige Dateien ausliefert oder löscht, ist auch
lokal keine gute Idee.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

from . import config, errors, logbook, media

QUELLE = "Bibliothek"

_BEGLEITZETTEL = "auftrag.json"
_HAUPTDATEI = "film.mp4"

# Formate werden je Ordner nur einmal gleichzeitig erzeugt — sonst schreiben zwei
# Klicks auf denselben Knopf in dieselbe Datei.
_arbeitssperre = threading.Lock()
_in_arbeit: set[str] = set()


# ── Pfade ────────────────────────────────────────────────────────────────────

def web_pfad(pfad: "str | Path | None") -> str:
    """Wandelt einen Dateipfad in die Form um, unter der die Oberfläche ihn abruft.
    Gibt einen leeren Text zurück, wenn die Datei außerhalb des Ausgabeordners liegt —
    dann wird sie eben nicht ausgeliefert."""
    if not pfad:
        return ""
    try:
        relativ = Path(pfad).resolve().relative_to(config.OUTPUT_DIR.resolve())
    except (ValueError, OSError):
        return ""
    return relativ.as_posix()


def sicherer_pfad(relativ: str) -> Path:
    """Macht aus einer Angabe der Oberfläche einen Pfad innerhalb des Ausgabeordners.

    `resolve()` löst dabei auch Verknüpfungen auf — die Prüfung lässt sich also nicht
    dadurch umgehen, dass im Ausgabeordner eine Verknüpfung nach außen liegt.
    """
    if not relativ or not str(relativ).strip():
        raise errors.EingabeFehler("Es wurde keine Datei angegeben.", ursprung=QUELLE)

    text = str(relativ).replace("\\", "/").strip().lstrip("/")
    wurzel = config.OUTPUT_DIR.resolve()
    try:
        ziel = (wurzel / text).resolve()
    except OSError as fehler:
        raise errors.EingabeFehler("Der Pfad ist ungültig.", ursprung=QUELLE) from fehler

    if ziel != wurzel and wurzel not in ziel.parents:
        logbook.warnung(QUELLE, f"Zugriff außerhalb des Ausgabeordners abgewiesen: {text[:80]}")
        raise errors.EingabeFehler(
            "Diese Datei liegt außerhalb des Videoordners.",
            "Aus Sicherheitsgründen werden nur Dateien unterhalb des Ordners "
            "„output“ ausgeliefert.",
            ursprung=QUELLE)
    return ziel


# ── Begleitzettel ────────────────────────────────────────────────────────────

def begleitzettel_schreiben(ordner: Path, inhalt: dict) -> None:
    try:
        ziel = Path(ordner) / _BEGLEITZETTEL
        vorlaeufig = ziel.with_suffix(".tmp")
        vorlaeufig.write_text(json.dumps(inhalt, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        vorlaeufig.replace(ziel)
    except Exception as fehler:
        logbook.warnung(QUELLE, f"Begleitzettel nicht geschrieben: {type(fehler).__name__}")


#: Wohin der Posting-Zettel geschrieben wird.
_POSTINGZETTEL = "posting.txt"

#: Was zu welchem Bildformat passt — nur als Hinweis auf dem Zettel.
_PLATTFORMEN = {
    "9:16": "TikTok · Instagram Reels · YouTube Shorts · Facebook Reels",
    "3:4": "Instagram Feed (hochkant) · Pinterest",
    "1:1": "Instagram Feed · Facebook Feed · LinkedIn",
    "16:9": "YouTube · Webseite · Präsentation",
    "4:3": "Präsentation · Webseite",
}


def posting_schreiben(ordner: Path, drehbuch, seitenverhaeltnis: str = "") -> dict:
    """Legt neben das Video einen fertigen Zettel zum Veröffentlichen.

    Ein fertiges Video ist nur die halbe Arbeit: Danach fehlen noch Titel, Text und
    Hashtags, und genau daran bleibt der Kunde jedes Mal hängen. Das Sprachmodell hat
    beides ohnehin schon geschrieben — es muss nur an einer Stelle landen, an der man
    es markieren und kopieren kann.

    Zurück kommt der Inhalt auch als Wörterbuch, damit die Oberfläche ihn ohne einen
    zweiten Dateizugriff anzeigen kann.
    """
    hashtags = list(getattr(drehbuch, "hashtags", []) or [])
    inhalt = {
        "titel": drehbuch.titel,
        "text": getattr(drehbuch, "posting", "") or drehbuch.zusammenfassung,
        "hashtags": hashtags,
        "plattformen": _PLATTFORMEN.get(seitenverhaeltnis, ""),
    }

    zeilen = [drehbuch.titel, ""]
    if inhalt["text"]:
        zeilen += [inhalt["text"], ""]
    if hashtags:
        zeilen += [" ".join("#" + w for w in hashtags), ""]
    if inhalt["plattformen"]:
        zeilen += [f"Passt zu: {inhalt['plattformen']}", ""]

    try:
        (Path(ordner) / _POSTINGZETTEL).write_text("\n".join(zeilen), encoding="utf-8")
    except Exception as fehler:
        # Der Zettel ist Beiwerk. Ein fertiges Video daran scheitern zu lassen wäre
        # das falsche Verhältnis.
        logbook.warnung(QUELLE, f"Posting-Zettel nicht geschrieben: {type(fehler).__name__}")

    return inhalt


def begleitzettel_lesen(ordner: Path) -> dict:
    try:
        daten = json.loads((Path(ordner) / _BEGLEITZETTEL).read_text(encoding="utf-8"))
        return daten if isinstance(daten, dict) else {}
    except Exception:
        return {}


# ── Bestand lesen ────────────────────────────────────────────────────────────

def _fassungen(ordner: Path) -> dict:
    """Welche Formatfassungen liegen in diesem Ordner, welche fehlen?"""
    vorhanden: dict[str, dict] = {}
    for kennung, vorgabe in media.FORMATE.items():
        datei = ordner / f"film_{kennung}.{vorgabe.endung}"
        if datei.exists() and datei.stat().st_size > 1024:
            vorhanden[kennung] = {
                "kennung": kennung, "name": vorgabe.name, "kurz": vorgabe.kurz or kennung,
                "datei": web_pfad(datei),
                "mb": round(datei.stat().st_size / 1_048_576, 2),
            }
    return vorhanden


def eintrag(ordner: "str | Path") -> dict | None:
    """Ein Bibliothekseintrag — alles, was die Kachel in der Oberfläche braucht."""
    ordner = Path(ordner)
    film = ordner / _HAUPTDATEI
    if not film.exists():
        return None

    zettel = begleitzettel_lesen(ordner)
    ergebnis = zettel.get("ergebnis") or {}
    statistik = film.stat()

    # Die Angaben aus dem Begleitzettel bevorzugen: sie stammen aus der Erzeugung und
    # kosten keinen ffmpeg-Aufruf. Nur wenn sie fehlen, wird die Datei befragt.
    dauer = float(ergebnis.get("dauer") or 0)
    breite = int(ergebnis.get("breite") or 0)
    hoehe = int(ergebnis.get("hoehe") or 0)
    if dauer <= 0 or breite <= 0:
        gemessen = media.angaben(film)
        dauer, breite, hoehe = gemessen.dauer, gemessen.breite, gemessen.hoehe

    fassungen = _fassungen(ordner)
    poster = ordner / "film_poster.jpg"
    szenen = sorted(ordner.glob("szene_*.mp4"))

    return {
        "ordner": web_pfad(ordner),
        "name": ordner.name,
        "titel": zettel.get("titel") or ordner.name,
        "erstellt": zettel.get("erstellt") or time.strftime(
            "%d.%m.%Y %H:%M", time.localtime(statistik.st_mtime)),
        "zeitstempel": statistik.st_mtime,
        "film": web_pfad(film),
        "poster": web_pfad(poster) if poster.exists() else "",
        "dauer": round(dauer, 1),
        "breite": breite, "hoehe": hoehe,
        "mb": round(statistik.st_size / 1_048_576, 2),
        "szenen": len(szenen),
        "briefing": (zettel.get("briefing") or "")[:400],
        # Titel, Text und Hashtags zum Veröffentlichen. Ältere Videos haben das noch
        # nicht — dann bleibt das Feld leer und die Oberfläche zeigt es gar nicht erst.
        "posting": _posting_aus(zettel, ordner),
        "fassungen": fassungen,
        "fehlende": [{"kennung": k, "name": v.name, "kurz": v.kurz or k,
                      "beschreibung": v.beschreibung}
                     for k, v in media.FORMATE.items() if k not in fassungen
                     and k != "poster"],
        "in_arbeit": ordner.name in _in_arbeit,
    }


def _posting_aus(zettel: dict, ordner: Path) -> dict:
    """Die Veröffentlichungsangaben eines Videos.

    Erste Wahl ist der Begleitzettel — dort steht das Drehbuch. Fehlt er, wird der
    Posting-Zettel gelesen; das trifft Videos, die aus einer älteren Fassung stammen
    oder deren Begleitzettel verloren ging.
    """
    drehbuch = zettel.get("drehbuch") or {}
    ergebnis = zettel.get("ergebnis") or {}
    posting = ergebnis.get("posting") if isinstance(ergebnis.get("posting"), dict) else {}

    text = (posting.get("text") or drehbuch.get("posting") or
            drehbuch.get("zusammenfassung") or "")
    hashtags = posting.get("hashtags") or drehbuch.get("hashtags") or []

    if not text and not hashtags:
        try:
            roh = (ordner / _POSTINGZETTEL).read_text(encoding="utf-8").strip()
        except OSError:
            return {}
        zeilen = [z.strip() for z in roh.splitlines() if z.strip()]
        text = " ".join(z for z in zeilen[1:] if not z.startswith("#")
                        and not z.startswith("Passt zu:"))
        hashtags = [w.lstrip("#") for z in zeilen for w in z.split()
                    if w.startswith("#")]

    if not text and not hashtags:
        return {}
    return {"titel": zettel.get("titel") or "",
            "text": str(text)[:600],
            "hashtags": [str(w)[:40] for w in list(hashtags)[:8]],
            "plattformen": posting.get("plattformen", "")}


def eintraege(grenze: int = 100) -> list[dict]:
    """Alle Videos, das neueste zuerst."""
    gefunden: list[dict] = []
    try:
        ordner_liste = [o for o in config.OUTPUT_DIR.iterdir()
                        if o.is_dir() and not o.name.startswith(".")]
    except OSError:
        return []

    for ordner in sorted(ordner_liste, key=lambda o: o.stat().st_mtime, reverse=True):
        if len(gefunden) >= grenze:
            break
        daten = eintrag(ordner)
        if daten:
            gefunden.append(daten)
    return gefunden


def uebersicht() -> dict:
    liste = eintraege()
    return {
        "anzahl": len(liste),
        "gesamt_mb": round(sum(e["mb"] for e in liste), 1),
        "gesamt_dauer": round(sum(e["dauer"] for e in liste)),
        "videos": liste,
    }


# ── Formate nachträglich erzeugen ────────────────────────────────────────────

def format_nachziehen(ordner_relativ: str, kennung: str) -> dict:
    """Erzeugt eine fehlende Formatfassung. Wird von der Bibliothek aufgerufen, wenn
    jemand auf einen der Formatknöpfe klickt."""
    if kennung not in media.FORMATE:
        raise errors.EingabeFehler(f"Unbekanntes Format: {kennung}",
                                   "Möglich: " + ", ".join(media.FORMATE), ursprung=QUELLE)

    ordner = sicherer_pfad(ordner_relativ)
    if not ordner.is_dir():
        raise errors.EingabeFehler("Diesen Videoordner gibt es nicht.", ursprung=QUELLE)
    film = ordner / _HAUPTDATEI
    if not film.exists():
        raise errors.EingabeFehler(
            "In diesem Ordner liegt kein fertiger Film.",
            "Erwartet wird eine Datei namens film.mp4.", ursprung=QUELLE)

    marke = ordner.name
    with _arbeitssperre:
        if marke in _in_arbeit:
            raise errors.EingabeFehler(
                "Für dieses Video wird gerade schon ein Format erzeugt.",
                "Bitte einen Moment warten.", ursprung=QUELLE)
        _in_arbeit.add(marke)

    try:
        vorgabe = media.FORMATE[kennung]
        ziel = ordner / f"film_{kennung}.{vorgabe.endung}"
        logbook.ereignis("bibliothek", {"grund": "Format wird erzeugt",
                                        "ordner": web_pfad(ordner), "format": kennung})
        media.format_erzeugen(film, ziel, kennung, wie_die_quelle=(kennung == "poster"),
                              melden=lambda a: logbook.ereignis(
                                  "formatfortschritt",
                                  {"ordner": web_pfad(ordner), "format": kennung,
                                   "anteil": round(a, 3)}))
        return {"ok": True, "format": kennung, "datei": web_pfad(ziel),
                "mb": round(ziel.stat().st_size / 1_048_576, 2)}
    finally:
        with _arbeitssperre:
            _in_arbeit.discard(marke)
        logbook.ereignis("bibliothek", {"grund": "Format fertig",
                                        "ordner": web_pfad(ordner)})


def alle_formate_nachziehen(ordner_relativ: str) -> dict:
    """Erzeugt alle noch fehlenden Fassungen auf einmal."""
    ordner = sicherer_pfad(ordner_relativ)
    daten = eintrag(ordner)
    if daten is None:
        raise errors.EingabeFehler("Diesen Videoordner gibt es nicht.", ursprung=QUELLE)

    erzeugt, misslungen = [], []
    for fehlend in daten["fehlende"]:
        try:
            format_nachziehen(ordner_relativ, fehlend["kennung"])
            erzeugt.append(fehlend["kennung"])
        except errors.StudioFehler as fehler:
            misslungen.append({"format": fehlend["kennung"], "grund": fehler.meldung})
    return {"ok": True, "erzeugt": erzeugt, "misslungen": misslungen}


# ── Verwalten ────────────────────────────────────────────────────────────────

def video_loeschen(ordner_relativ: str) -> dict:
    """Löscht einen ganzen Videoordner. Der Aufrufer hat vorher zu fragen — hier wird
    nur ausgeführt."""
    ordner = sicherer_pfad(ordner_relativ)
    if not ordner.is_dir():
        raise errors.EingabeFehler("Diesen Videoordner gibt es nicht.", ursprung=QUELLE)
    if ordner.resolve() == config.OUTPUT_DIR.resolve():
        raise errors.EingabeFehler("Der Ausgabeordner selbst wird nicht gelöscht.",
                                   ursprung=QUELLE)

    name = ordner.name
    shutil.rmtree(ordner)
    logbook.warnung(QUELLE, f"Video gelöscht: {name}")
    logbook.ereignis("bibliothek", {"grund": "gelöscht"})
    return {"ok": True, "geloescht": name}


def video_umbenennen(ordner_relativ: str, neuer_titel: str) -> dict:
    """Ändert den angezeigten Titel. Der Ordnername bleibt, damit keine Verweise
    ins Leere laufen — der Titel steht im Begleitzettel."""
    ordner = sicherer_pfad(ordner_relativ)
    if not ordner.is_dir():
        raise errors.EingabeFehler("Diesen Videoordner gibt es nicht.", ursprung=QUELLE)
    titel = (neuer_titel or "").strip()[:120]
    if not titel:
        raise errors.EingabeFehler("Der Titel darf nicht leer sein.", ursprung=QUELLE)

    zettel = begleitzettel_lesen(ordner)
    zettel["titel"] = titel
    begleitzettel_schreiben(ordner, zettel)
    logbook.info(QUELLE, f"Titel geändert: {titel}")
    logbook.ereignis("bibliothek", {"grund": "umbenannt"})
    return {"ok": True, "titel": titel}


def im_explorer_zeigen(ordner_relativ: str) -> dict:
    """Öffnet den Ordner im Windows-Explorer. Kleine Geste, die im Alltag viel spart —
    von dort kann der Kunde die Datei direkt verschicken."""
    import subprocess
    import sys

    ordner = sicherer_pfad(ordner_relativ)
    if not ordner.exists():
        raise errors.EingabeFehler("Diesen Ordner gibt es nicht.", ursprung=QUELLE)
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(ordner)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(ordner)])
        else:
            subprocess.Popen(["xdg-open", str(ordner)])
    except Exception as fehler:
        raise errors.VerarbeitungsFehler(
            "Der Ordner ließ sich nicht öffnen.", str(fehler)[:200],
            ursprung=QUELLE) from fehler
    return {"ok": True, "ordner": str(ordner)}
