"""
pipeline.py — der Ablauf von der Eingabe bis zum fertigen Video.

Fünf Blöcke, genau die, die im Dashboard nebeneinanderstehen:

    Briefing  →  Claude  →  Startbild  →  Higgsfield  →  Ausgabe
    prüfen       Drehbuch   je Szene      je Szene       montieren

Jeder Zustandswechsel wird als Ereignis verschickt, damit die Oberfläche den aktiven
Block leuchten lassen und den wandernden Punkt auf die Verbindung schicken kann. Die
Oberfläche fragt nichts ab — sie bekommt gesagt, was passiert.

Zwei Betriebsarten, im Formular umschaltbar:
  * **Einzelclip** — eine Szene, so schnell wie das Modell eben ist.
  * **Storyboard** — mehrere Szenen, danach zu einem Film montiert. Der einzige Weg zu
    Videos über zehn Sekunden, denn kein Higgsfield-Modell liefert längere Clips.

Grundsätzlich gilt: **ein Auftrag zur Zeit.** Zwei gleichzeitige Läufe würden sich um
dieselben Dateien streiten und die Wartezeit beider verdoppeln, ohne dass Higgsfield
schneller würde — dort steht ohnehin eine Warteschlange.

Das heißt aber nicht, dass man dazwischen warten muss: Weitere Aufträge lassen sich
**einreihen** (`einreihen`). Sie stehen als „wartend" im Bestand und starten von selbst,
sobald der vorige fertig ist. Für Serien — fünf TikTok-Clips an einem Nachmittag — ist
das der Unterschied zwischen Zuschauen und Arbeitenlassen.
"""
from __future__ import annotations

import inspect
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import (config, errors, higgsfield, jobstore, library, logbook, media,
               promptsmith, videoquelle)

QUELLE = "Ablauf"


# ── Laufender Auftrag ────────────────────────────────────────────────────────

@dataclass
class Lauf:
    """Der eine Auftrag, der gerade bearbeitet wird."""
    auftrag_id: str
    abbruch: threading.Event
    faden: threading.Thread
    begonnen: float


_sperre = threading.Lock()
_aktuell: Lauf | None = None

#: Wer nach dem laufenden an der Reihe ist. Reine Reihenfolge, keine Vorrechte —
#: wer zuerst kommt, wird zuerst gebaut.
_schlange: list[tuple[str, "Einstellungen"]] = []

#: Wie viele Aufträge höchstens warten dürfen. Die Grenze ist keine Schikane: Jeder
#: Eintrag kostet später echtes Guthaben, und eine Liste, die niemand mehr überblickt,
#: ist der sicherste Weg, versehentlich zwanzig Videos zu bestellen.
MAX_SCHLANGE = 10


def laeuft_gerade() -> str:
    with _sperre:
        return _aktuell.auftrag_id if _aktuell else ""


def warteschlange() -> list[dict]:
    """Die wartenden Aufträge, in der Reihenfolge, in der sie drankommen."""
    with _sperre:
        kennungen = [k for k, _ in _schlange]
    eintraege = []
    for stelle, kennung in enumerate(kennungen, start=1):
        auftrag = jobstore.holen(kennung)
        if auftrag is not None:
            eintraege.append({**auftrag.als_dict(), "platz": stelle})
    return eintraege


def aus_warteschlange(auftrag_id: str) -> bool:
    """Nimmt einen wartenden Auftrag wieder heraus. Den laufenden trifft das nicht —
    dafür gibt es `abbrechen`."""
    with _sperre:
        vorher = len(_schlange)
        _schlange[:] = [(k, e) for k, e in _schlange if k != auftrag_id]
        entfernt = len(_schlange) < vorher
    if entfernt:
        jobstore.aktualisieren(auftrag_id, zustand=jobstore.ABGEBROCHEN,
                               fehler={"meldung": "Vor dem Start aus der Reihe genommen.",
                                       "hinweis": ""})
        logbook.info(QUELLE, "Ein wartender Auftrag wurde aus der Reihe genommen.",
                     job=auftrag_id)
        logbook.ereignis("warteschlange", {"aktion": "entfernt", "auftrag": auftrag_id})
    return entfernt


def abbrechen(auftrag_id: str = "") -> bool:
    """Bricht den laufenden Auftrag ab. Ohne Kennung: was gerade läuft.

    Wartende Aufträge bleiben stehen und kommen danach an die Reihe — wer eine ganze
    Reihe loswerden will, nimmt `warteschlange_leeren`.
    """
    with _sperre:
        if _aktuell is None:
            return False
        if auftrag_id and _aktuell.auftrag_id != auftrag_id:
            return False
        _aktuell.abbruch.set()
        betroffen = _aktuell.auftrag_id
    logbook.warnung(QUELLE, "Abbruch angefordert — laufende Schritte werden beendet.",
                    job=betroffen)
    return True


def warteschlange_leeren() -> int:
    """Nimmt alle wartenden Aufträge heraus. Der laufende bleibt unberührt."""
    with _sperre:
        kennungen = [k for k, _ in _schlange]
        _schlange.clear()
    for kennung in kennungen:
        jobstore.aktualisieren(kennung, zustand=jobstore.ABGEBROCHEN,
                               fehler={"meldung": "Vor dem Start aus der Reihe genommen.",
                                       "hinweis": ""})
    if kennungen:
        logbook.info(QUELLE, f"{len(kennungen)} wartende Auftrag/Aufträge verworfen.")
        logbook.ereignis("warteschlange", {"aktion": "geleert", "anzahl": len(kennungen)})
    return len(kennungen)


# ── Ereignisse an die Oberfläche ─────────────────────────────────────────────

def _block(auftrag_id: str, block: str, zustand: str, text: str = "",
           zusatz: dict | None = None) -> None:
    """Zustand eines Blocks melden: wartend · aktiv · fertig · fehler · uebersprungen."""
    logbook.ereignis("block", {"block": block, "zustand": zustand, "text": text,
                               **(zusatz or {})}, job=auftrag_id)


def _uebergang(auftrag_id: str, von: str, nach: str) -> None:
    """Der wandernde Punkt auf der Verbindungslinie."""
    logbook.ereignis("uebergang", {"von": von, "nach": nach}, job=auftrag_id)


def _fortschritt(auftrag_id: str, block: str, anteil: float, rest: float = 0.0,
                 text: str = "") -> None:
    logbook.ereignis("fortschritt", {"block": block, "anteil": round(max(0.0, min(1.0, anteil)), 3),
                                     "rest": round(max(0.0, rest)), "text": text},
                     job=auftrag_id)


# ── Einstellungen prüfen ─────────────────────────────────────────────────────

@dataclass
class Einstellungen:
    """Was aus dem Formular kommt — geprüft und zurechtgerückt."""
    briefing: str
    modus: str = "formular"        # formular · frei
    woertlich: bool = False        # nur im Freitext: kein Sprachmodell dazwischen
    szenen: int = 1
    sekunden: int = 5
    videomodell: str = ""
    bildmodell: str = ""
    seitenverhaeltnis: str = "16:9"
    stil: str = ""
    zielgruppe: str = ""
    tonfall: str = ""
    bewegung: str = ""             # Kennung einer Kamerabewegung (nur dop-Modelle)
    weiche_uebergaenge: bool = True
    formate: tuple[str, ...] = ()  # gleich mit erzeugen; sonst später per Klick
    #: Kennung eines gescheiterten Auftrags, dessen Drehbuch, Startbilder und fertige
    #: Szenen übernommen werden sollen. Leer: ein ganz neuer Auftrag.
    wiederholung_von: str = ""
    #: „video“ (Briefing → Higgsfield) oder „webseite“ (Link → TikTok-Werbevideo).
    art: str = "video"
    #: Nur bei `art == "webseite"`: Link und Gestaltungswünsche.
    webseite: dict = field(default_factory=dict)

    def als_dict(self) -> dict:
        return {"briefing": self.briefing, "modus": self.modus, "woertlich": self.woertlich,
                "szenen": self.szenen, "sekunden": self.sekunden,
                "videomodell": self.videomodell, "bildmodell": self.bildmodell,
                "seitenverhaeltnis": self.seitenverhaeltnis, "stil": self.stil,
                "zielgruppe": self.zielgruppe, "tonfall": self.tonfall,
                "bewegung": self.bewegung,
                "weiche_uebergaenge": self.weiche_uebergaenge,
                "formate": list(self.formate),
                "wiederholung_von": self.wiederholung_von,
                "art": self.art, "webseite": dict(self.webseite)}


_SEITENVERHAELTNISSE = ("16:9", "9:16", "1:1", "4:3", "3:4", "2:3", "3:2")


def einstellungen_pruefen(roh: dict) -> Einstellungen:
    """Nimmt die Formulardaten entgegen und macht daraus einen gültigen Auftrag.
    Alles, was fehlt, bekommt einen sinnvollen Wert; alles Unsinnige wird abgelehnt."""
    briefing = str(roh.get("briefing") or "").strip()
    if len(briefing) < 3:
        raise errors.EingabeFehler(
            "Es fehlt die Beschreibung.",
            "Schreiben Sie in einem Satz, was im Video zu sehen sein soll.",
            ursprung=QUELLE)
    if len(briefing) > config.MAX_BRIEFING_CHARS:
        briefing = briefing[:config.MAX_BRIEFING_CHARS]

    videomodell = str(roh.get("videomodell") or config.VIDEO_MODEL).strip()
    if videomodell not in {m["id"] for m in higgsfield.VIDEOMODELLE}:
        videomodell = config.VIDEO_MODEL

    szenen = max(1, min(int(roh.get("szenen") or 1), config.MAX_SCENES))
    sekunden = higgsfield.erlaubte_dauer(videomodell, int(roh.get("sekunden") or 5))

    verhaeltnis = str(roh.get("seitenverhaeltnis") or "16:9")
    if verhaeltnis not in _SEITENVERHAELTNISSE:
        verhaeltnis = "16:9"

    gewuenschte = [f for f in (roh.get("formate") or []) if f in media.FORMATE]

    if str(roh.get("art") or "") == "webseite":
        # Der Link steht an der Stelle des Briefings: Er ist das, woraus das Video entsteht.
        from . import webwerbung
        return webwerbung.einstellungen_pruefen(roh, Einstellungen)

    return Einstellungen(
        briefing=briefing,
        modus="frei" if str(roh.get("modus") or "") == "frei" else "formular",
        woertlich=bool(roh.get("woertlich")),
        szenen=szenen, sekunden=sekunden,
        videomodell=videomodell,
        bildmodell=str(roh.get("bildmodell") or config.IMAGE_MODEL).strip(),
        seitenverhaeltnis=verhaeltnis,
        stil=str(roh.get("stil") or "").strip()[:300],
        zielgruppe=str(roh.get("zielgruppe") or "").strip()[:200],
        tonfall=str(roh.get("tonfall") or "").strip()[:200],
        bewegung=str(roh.get("bewegung") or "").strip()[:64],
        weiche_uebergaenge=roh.get("weiche_uebergaenge", True) is not False,
        formate=tuple(gewuenschte),
        wiederholung_von=str(roh.get("wiederholung_von") or "").strip()[:32],
    )


# ── Auftrag starten ──────────────────────────────────────────────────────────

def _lauf_beginnen(auftrag_id: str, einstellungen: Einstellungen) -> None:
    """Startet den Bearbeitungsfaden. **Nur mit gehaltener `_sperre` aufrufen.**"""
    global _aktuell
    abbruch = threading.Event()
    faden = threading.Thread(target=_bearbeiten, args=(auftrag_id, einstellungen, abbruch),
                             name=f"auftrag-{auftrag_id}", daemon=True)
    _aktuell = Lauf(auftrag_id, abbruch, faden, time.monotonic())
    faden.start()


def _angenommen_melden(auftrag: jobstore.Auftrag) -> None:
    logbook.ereignis("auftrag", {"aktion": "gestartet", "auftrag": auftrag.als_dict()},
                     job=auftrag.id)
    logbook.info(QUELLE, f"Auftrag angenommen: {auftrag.titel[:60]}", job=auftrag.id)


def starten(roh: dict) -> jobstore.Auftrag:
    """Nimmt einen Auftrag an und startet ihn sofort im Hintergrund.

    Wirft, wenn schon einer läuft. Wer stattdessen anstellen will, nimmt `einreihen` —
    diese Funktion bleibt bewusst die strenge: Sie ist der Weg für alles, was jetzt
    laufen muss oder gar nicht.
    """
    einstellungen = einstellungen_pruefen(roh)

    with _sperre:
        if _aktuell is not None and _aktuell.faden.is_alive():
            laufender = jobstore.holen(_aktuell.auftrag_id)
            noch_offen = (laufender.titel if laufender else "")[:50]
            raise errors.EingabeFehler(
                "Es läuft bereits ein Auftrag.",
                f"{noch_offen} ist noch nicht fertig. Bitte abwarten oder abbrechen.",
                ursprung=QUELLE, details={"laufend": _aktuell.auftrag_id})

        auftrag = jobstore.anlegen(einstellungen.briefing, einstellungen.als_dict())
        _lauf_beginnen(auftrag.id, einstellungen)

    _angenommen_melden(auftrag)
    return auftrag


def einreihen(roh: dict) -> tuple[jobstore.Auftrag, bool]:
    """Nimmt einen Auftrag an — sofort oder als nächsten in der Reihe.

    Zurück kommt der Auftrag und die Auskunft, ob er gleich losgelaufen ist. Die
    Oberfläche braucht beides: Sie sagt entweder „läuft" oder „steht an Platz 2".
    """
    einstellungen = einstellungen_pruefen(roh)

    with _sperre:
        beschaeftigt = _aktuell is not None and _aktuell.faden.is_alive()
        if beschaeftigt and len(_schlange) >= MAX_SCHLANGE:
            raise errors.EingabeFehler(
                f"Es warten bereits {MAX_SCHLANGE} Aufträge.",
                "Bitte erst abwarten — jeder weitere Auftrag kostet Guthaben.",
                ursprung=QUELLE)

        auftrag = jobstore.anlegen(einstellungen.briefing, einstellungen.als_dict())
        if beschaeftigt:
            _schlange.append((auftrag.id, einstellungen))
            platz = len(_schlange)
        else:
            _lauf_beginnen(auftrag.id, einstellungen)
            platz = 0

    if platz:
        logbook.info(QUELLE, f"Auftrag eingereiht (Platz {platz}): "
                             f"{auftrag.titel[:60]}", job=auftrag.id)
        logbook.ereignis("warteschlange", {"aktion": "eingereiht",
                                           "auftrag": auftrag.als_dict(), "platz": platz})
        return auftrag, False

    _angenommen_melden(auftrag)
    return auftrag, True


def wiederholen(auftrag_id: str) -> tuple[jobstore.Auftrag, bool]:
    """Startet einen gescheiterten oder abgebrochenen Auftrag erneut.

    Übernommen werden Drehbuch und Ordner — und damit alles, was dort schon liegt und
    bezahlt ist: fertige Szenen, Startbilder und die Nummern von Aufträgen, die beim
    Dienst noch laufen. Bezahlt wird nur, was wirklich fehlt. Bis zum 10.09.2026 hieß
    „noch einmal versuchen“ für den Kunden: jedes Startbild ein zweites Mal kaufen.
    """
    alt = jobstore.holen(auftrag_id)
    if alt is None:
        raise errors.EingabeFehler("Diesen Auftrag gibt es nicht.", ursprung=QUELLE)
    if alt.zustand not in (jobstore.FEHLER, jobstore.ABGEBROCHEN):
        raise errors.EingabeFehler(
            "Nur gescheiterte oder abgebrochene Aufträge lassen sich wiederholen.",
            "Dieser Auftrag läuft noch oder ist schon fertig.", ursprung=QUELLE)
    roh = dict(alt.einstellungen or {})
    roh["briefing"] = roh.get("briefing") or alt.briefing
    roh["wiederholung_von"] = alt.id
    logbook.info(QUELLE, f"Auftrag wird wiederholt: {alt.titel[:60]}", job=alt.id)
    return einreihen(roh)


def _naechsten_starten() -> None:
    """Holt den nächsten Wartenden herein. **Ohne gehaltene `_sperre` aufrufen.**

    Übersprungen wird, was inzwischen aus der Reihe genommen wurde — sonst liefe ein
    Auftrag an, den der Benutzer längst zurückgezogen hat.
    """
    auftrag = None
    with _sperre:
        if _aktuell is not None and _aktuell.faden.is_alive():
            return
        while _schlange:
            kennung, einstellungen = _schlange.pop(0)
            eintrag = jobstore.holen(kennung)
            if eintrag is None or eintrag.zustand != jobstore.WARTEND:
                continue
            _lauf_beginnen(kennung, einstellungen)
            auftrag = eintrag
            break

    if auftrag is not None:
        logbook.info(QUELLE, f"Nächster Auftrag aus der Reihe: {auftrag.titel[:60]}",
                     job=auftrag.id)
        _angenommen_melden(auftrag)


# ── Der eigentliche Ablauf ───────────────────────────────────────────────────

def _bearbeiten(auftrag_id: str, e: Einstellungen, abbruch: threading.Event) -> None:
    """Läuft in einem eigenen Faden. Fängt jeden Fehler ab — ein Absturz hier darf das
    Programm nicht mitreißen und muss im Dashboard sichtbar werden."""
    global _aktuell
    begonnen = time.monotonic()

    try:
        jobstore.aktualisieren(auftrag_id, zustand=jobstore.LAEUFT, block="briefing")
        if e.art == "webseite":
            from . import webwerbung
            bloecke = webwerbung.BLOECKE
        else:
            bloecke = jobstore.BLOECKE
        for block in bloecke:
            _block(auftrag_id, block, "wartend")

        if e.art == "webseite":
            ergebnis = webwerbung.ablauf(auftrag_id, e, abbruch)
        else:
            drehbuch = _schritt_briefing_und_claude(auftrag_id, e, abbruch)
            alt = jobstore.holen(e.wiederholung_von) if e.wiederholung_von else None
            if alt is not None and alt.ordner and Path(alt.ordner).is_dir():
                ordner = Path(alt.ordner)        # dort liegt, was schon bezahlt ist
            else:
                ordner = jobstore.ordner_fuer(jobstore.holen(auftrag_id),
                                              drehbuch.dateiname)
            jobstore.aktualisieren(auftrag_id, ordner=str(ordner), titel=drehbuch.titel,
                                   drehbuch=drehbuch.als_dict())

            szenenclips, ausgefallen = _schritt_bild_und_video(auftrag_id, e, drehbuch,
                                                               ordner, abbruch)
            ergebnis = _schritt_ausgabe(auftrag_id, e, drehbuch, szenenclips, ordner,
                                        abbruch, ausgefallen)

        jobstore.aktualisieren(auftrag_id, zustand=jobstore.FERTIG, block="ausgabe",
                               ergebnis=ergebnis)
        dauer = time.monotonic() - begonnen
        logbook.erfolg(QUELLE, f"Fertig in {int(dauer // 60)} min {int(dauer % 60)} s: "
                               f"{Path(ergebnis['film']).name}", job=auftrag_id)
        logbook.ereignis("auftrag", {"aktion": "fertig", "ergebnis": ergebnis},
                         job=auftrag_id)
        logbook.ereignis("bibliothek", {"grund": "neues Video"})

    except errors.AbbruchFehler:
        jobstore.aktualisieren(auftrag_id, zustand=jobstore.ABGEBROCHEN,
                               fehler={"meldung": "Vom Benutzer abgebrochen.", "hinweis": ""})
        logbook.warnung(QUELLE, "Auftrag abgebrochen.", job=auftrag_id)
        logbook.ereignis("auftrag", {"aktion": "abgebrochen"}, job=auftrag_id)

    except errors.StudioFehler as fehler:
        jobstore.aktualisieren(auftrag_id, zustand=jobstore.FEHLER, fehler=fehler.als_dict())
        logbook.fehler(QUELLE, f"{fehler.meldung} {fehler.hinweis}".strip(), job=auftrag_id)
        _block(auftrag_id, jobstore.holen(auftrag_id).block if jobstore.holen(auftrag_id)
               else "briefing", "fehler", fehler.meldung)
        logbook.ereignis("auftrag", {"aktion": "fehler", "fehler": fehler.als_dict()},
                         job=auftrag_id)

    except Exception as unerwartet:                     # darf nie nach außen dringen
        uebersetzt = errors.aus_ausnahme(unerwartet, ursprung=QUELLE)
        jobstore.aktualisieren(auftrag_id, zustand=jobstore.FEHLER,
                               fehler=uebersetzt.als_dict())
        logbook.fehler(QUELLE, f"Unerwarteter Fehler: {uebersetzt.meldung}", job=auftrag_id)
        logbook.ereignis("auftrag", {"aktion": "fehler", "fehler": uebersetzt.als_dict()},
                         job=auftrag_id)

    finally:
        _DIENST_JE_AUFTRAG.pop(auftrag_id, None)
        with _sperre:
            if _aktuell is not None and _aktuell.auftrag_id == auftrag_id:
                _aktuell = None
        # Außerhalb der Sperre: `_naechsten_starten` nimmt sie selbst, und eine
        # gewöhnliche Sperre lässt sich nicht zweimal nehmen.
        try:
            _naechsten_starten()
        except Exception as fehler:                 # darf diesen Faden nie mitreißen
            # Der eigene Auftrag ist zu diesem Zeitpunkt fertig verbucht. Ein Fehler
            # beim Nachrücken darf ihn nicht nachträglich in einen Absturz verwandeln —
            # er wird gemeldet, und die Reihe wartet auf den nächsten Anstoß.
            logbook.fehler(QUELLE, "Der nächste Auftrag aus der Reihe ließ sich nicht "
                                   f"starten: {type(fehler).__name__}")


def _pruefe_abbruch(abbruch: threading.Event) -> None:
    if abbruch.is_set():
        raise errors.AbbruchFehler("Abgebrochen.", ursprung=QUELLE)


# ── Block 1+2: Briefing prüfen, Drehbuch schreiben ───────────────────────────

def _schritt_briefing_und_claude(auftrag_id: str, e: Einstellungen,
                                 abbruch: threading.Event) -> promptsmith.Drehbuch:
    _block(auftrag_id, "briefing", "aktiv", "Eingaben werden geprüft")
    _pruefe_abbruch(abbruch)

    # Erst prüfen, ob Higgsfield den Auftrag so überhaupt annehmen kann — bevor das
    # Sprachmodell eine Minute arbeitet und lange bevor ein Startbild bezahlt ist.
    dienst = videoquelle.aktiv()
    _DIENST_JE_AUFTRAG[auftrag_id] = dienst
    _vorpruefen(auftrag_id, e, dienst)

    beschreibung = (f"{e.szenen} Szene(n) à {e.sekunden} s"
                    if e.szenen > 1 else f"Einzelclip, {e.sekunden} s")
    logbook.info(QUELLE, f"Briefing angenommen · {beschreibung} · "
                         f"{higgsfield.modell_info(e.videomodell)['name']} · "
                         f"{e.seitenverhaeltnis}", job=auftrag_id)
    _block(auftrag_id, "briefing", "fertig", beschreibung)
    _uebergang(auftrag_id, "briefing", "claude")

    _block(auftrag_id, "claude", "aktiv", "Drehbuch wird geschrieben")
    _fortschritt(auftrag_id, "claude", 0.1, 45, "Sprachmodell arbeitet")
    jobstore.aktualisieren(auftrag_id, block="claude")
    _pruefe_abbruch(abbruch)

    alt = jobstore.holen(e.wiederholung_von) if e.wiederholung_von else None
    uebernommen = promptsmith.drehbuch_aus_dict(alt.drehbuch) if alt is not None else None
    if uebernommen is not None:
        logbook.info(QUELLE, f"Drehbuch „{uebernommen.titel}“ vom letzten Versuch wird "
                             "übernommen — damit passen Startbilder und fertige Szenen "
                             "weiter dazu.", job=auftrag_id)
        _fortschritt(auftrag_id, "claude", 1.0, 0, "übernommen")
        _block(auftrag_id, "claude", "fertig",
               f"{len(uebernommen.szenen)} Szene(n) · übernommen",
               {"drehbuch": uebernommen.als_dict()})
        return uebernommen

    if e.modus == "frei" and e.woertlich:
        drehbuch = promptsmith.eigenen_prompt_woertlich(
            e.briefing, sekunden=e.sekunden, modell=e.videomodell)
    else:
        # Das Bildformat geht mit ans Sprachmodell. Ohne diese Angabe schreibt es
        # Breitbild-Prompts — und ein Panorama sieht im Hochformat aus wie der
        # Ausschnitt aus einem anderen Film.
        drehbuch = promptsmith.drehbuch_erstellen(
            e.briefing, szenen=e.szenen, sekunden_je_szene=e.sekunden,
            stil=e.stil, zielgruppe=e.zielgruppe, tonfall=e.tonfall,
            modell=e.videomodell, seitenverhaeltnis=e.seitenverhaeltnis)

    _pruefe_abbruch(abbruch)
    _fortschritt(auftrag_id, "claude", 1.0, 0, "fertig")
    _block(auftrag_id, "claude", "fertig",
           f"{len(drehbuch.szenen)} Szene(n) · {drehbuch.quelle}",
           {"drehbuch": drehbuch.als_dict()})
    return drehbuch


# ── Block 3+4: Startbilder und Videos ────────────────────────────────────────

def _schritt_bild_und_video(auftrag_id: str, e: Einstellungen,
                            drehbuch: promptsmith.Drehbuch, ordner: Path,
                            abbruch: threading.Event) -> tuple[list[Path], list[str]]:
    """Erzeugt je Szene erst das Startbild und daraus das Video.

    Die Szenen laufen nacheinander, nicht gleichzeitig: Higgsfield rechnet ohnehin in
    einer Warteschlange, und der Fortschritt bleibt so nachvollziehbar — man sieht,
    bei welcher Szene man steht.

    Zurück kommen die fertigen Clips **und** die Liste der Szenen, die es nicht
    geschafft haben. Ein Ausfall beendet den Lauf nicht: Wer für vier von fünf Szenen
    bezahlt hat, soll sie auch bekommen.
    """
    # Einmal je Auftrag festlegen, wer die Bilder und Videos macht — mitten im Lauf
    # zu wechseln würde zu Szenen führen, die nicht zueinander passen. Festgelegt wurde
    # er schon bei der Vorprüfung; nur wer diesen Schritt direkt aufruft, wählt hier.
    dienst = _DIENST_JE_AUFTRAG.get(auftrag_id) or videoquelle.aktiv()

    braucht_bild = higgsfield.braucht_startbild(e.videomodell)
    anzahl = len(drehbuch.szenen)
    clips: list[Path] = []

    if not braucht_bild:
        _block(auftrag_id, "bild", "uebersprungen",
               "Dieses Modell erzeugt direkt aus Text")
        _uebergang(auftrag_id, "claude", "video")
    else:
        _uebergang(auftrag_id, "claude", "bild")

    bilder: dict[int, str] = {}
    verloren: list[str] = []                 # Szenen, die ausgefallen sind
    letzter_fehler: errors.StudioFehler | None = None

    for stelle, szene in enumerate(drehbuch.szenen, start=1):
        _pruefe_abbruch(abbruch)
        try:
            clips.append(_eine_szene(auftrag_id, e, szene, stelle, anzahl, ordner,
                                     dienst, braucht_bild, bilder, abbruch))
        except (errors.AbbruchFehler, *_TOEDLICH):
            # Abbruch ist Absicht. Kein Guthaben, kein Zugang und eine falsche
            # Einstellung treffen jede weitere Szene genauso — Weitermachen ändert
            # daran nichts und kostet nur Zeit.
            raise
        except errors.StudioFehler as fehler:
            # Alles andere trifft **diese** Szene. Die schon fertigen Clips sind
            # bezahlt; sie jetzt wegzuwerfen wäre der teuerste Ausgang von allen.
            # Also: vermerken, weitermachen, am Ende montieren, was da ist.
            verloren.append(f"Szene {stelle}: {fehler.meldung}")
            letzter_fehler = fehler
            logbook.warnung(QUELLE, f"Szene {stelle}/{anzahl} ist ausgefallen "
                                    f"({fehler.meldung}) — der Film entsteht ohne sie.",
                            job=auftrag_id)
            logbook.ereignis("szene_ausgefallen",
                             {"szene": stelle, "grund": fehler.meldung}, job=auftrag_id)

    if not clips:
        # Keine einzige Szene: Dann ist der Auftrag wirklich gescheitert, und der
        # Grund der letzten ist der aussagekräftigste, den es gibt.
        raise letzter_fehler or errors.AnbieterFehler(
            "Es ist keine einzige Szene entstanden.", "Bitte erneut versuchen.",
            ursprung=QUELLE)

    if verloren:
        logbook.warnung(QUELLE, f"{len(clips)} von {anzahl} Szene(n) sind im Film, "
                                f"{len(verloren)} ausgefallen.", job=auftrag_id)

    _fortschritt(auftrag_id, "video", 1.0, 0, "fertig")
    _block(auftrag_id, "video", "fertig", f"{len(clips)} Clip(s)" +
           (f" · {len(verloren)} ausgefallen" if verloren else ""))
    _uebergang(auftrag_id, "video", "ausgabe")
    return clips, verloren


#: Fehler, die nicht eine Szene betreffen, sondern den ganzen Lauf. Bei ihnen ist
#: Weitermachen sinnlos — die nächste Szene liefe in genau dieselbe Wand.
_TOEDLICH = (errors.GuthabenFehler, errors.ZugangFehler, errors.KonfigurationsFehler)

#: Welcher Dienst einen Auftrag ausführt — festgelegt bei der Vorprüfung.
_DIENST_JE_AUFTRAG: dict[str, object] = {}


def _vorpruefen(auftrag_id: str, e: Einstellungen, dienst) -> None:
    """Klärt vor dem ersten bezahlten Schritt, ob der Auftrag so durchgehen kann.

    Zwei Dinge:
      * **Passt das Modell zum Weg?** Kling 3.0 gibt es nur im Abo, die DoP-Modelle nur
        über die Platform-API. Ohne diese Prüfung fiele das erst auf, wenn das erste
        Startbild bezahlt ist.
      * **Was sagt der Dienst selbst?** Der Abo-Weg liest kostenlos sein Schema und
        nennt das Seitenverhältnis und die Dauer, die das Modell wirklich annimmt.
        Montage und Drehbuch richten sich dann danach.
    """
    weg = videoquelle.weg_von(dienst)
    info = higgsfield.modell_info(e.videomodell)
    wege = info.get("wege") or ["platform", "abo"]
    if weg in ("platform", "abo") and weg not in wege:
        andere = "über das Higgsfield-Abo" if "abo" in wege else "über die Platform-API"
        raise errors.KonfigurationsFehler(
            f"„{info.get('name', e.videomodell)}“ gibt es nur {andere}.",
            "Bitte im Formular ein anderes Modell wählen" +
            (" oder oben auf „Abo verbinden“ klicken." if "abo" in wege else "."),
            ursprung=QUELLE)

    pruefen = getattr(dienst, "vorpruefen", None)
    if not callable(pruefen):
        return
    _block(auftrag_id, "briefing", "aktiv", "Higgsfield wird befragt")
    ergebnis = pruefen(videomodell=e.videomodell,
                       bildmodell=e.bildmodell or config.IMAGE_MODEL,
                       seitenverhaeltnis=e.seitenverhaeltnis, dauer=e.sekunden,
                       mit_startbild=higgsfield.braucht_startbild(e.videomodell)) or {}

    format_neu = str(ergebnis.get("seitenverhaeltnis") or "")
    if format_neu and format_neu != e.seitenverhaeltnis:
        logbook.warnung(QUELLE, f"{info.get('name', e.videomodell)} kennt kein "
                                f"{e.seitenverhaeltnis} — das Video entsteht in "
                                f"{format_neu}.", job=auftrag_id)
        e.seitenverhaeltnis = format_neu
    dauer_neu = int(ergebnis.get("dauer") or 0)
    if dauer_neu and dauer_neu != e.sekunden:
        logbook.info(QUELLE, f"Szenenlänge auf {dauer_neu} s angepasst — so lang nimmt "
                             "das Modell sie an.", job=auftrag_id)
        e.sekunden = dauer_neu


def _aufrufen(methode, *argumente, **benannt):
    """Ruft eine Dienstmethode und lässt weg, was sie nicht kennt.

    `gemeldet`, `fortsetzen` und `bild_kennung` sind neu. Ein Dienst, der sie (noch)
    nicht annimmt — eine Attrappe, ein künftiger Weg —, soll trotzdem funktionieren.
    """
    try:
        zeichen = inspect.signature(methode).parameters
    except (TypeError, ValueError):
        return methode(*argumente, **benannt)
    if not any(p.kind == p.VAR_KEYWORD for p in zeichen.values()):
        benannt = {k: v for k, v in benannt.items() if k in zeichen}
    return methode(*argumente, **benannt)


# ── Zwischenstand je Videoordner ─────────────────────────────────────────────
#
# Was schon bezahlt ist, steht hier: Nummer und Adresse jedes Startbilds, die Nummer
# jedes Videoauftrags, sobald der Dienst sie vergibt. Ein Wiederholungslauf liest das
# und bezahlt nichts zweimal — ein fertiger Clip wird übernommen, ein laufender Auftrag
# abgeholt, ein vorhandenes Startbild wiederverwendet.

_ZWISCHENSTAND = "zwischenstand.json"

#: Wie lange ein gemerktes Startbild beim Dienst als verwendbar gilt. Die Adressen der
#: Platform-API laufen irgendwann ab; Auftragsnummern halten länger, aber nicht ewig.
_BILD_HALTBAR = 12 * 3600


def _zwischenstand_lesen(ordner: Path) -> dict:
    try:
        daten = json.loads((Path(ordner) / _ZWISCHENSTAND).read_text(encoding="utf-8"))
        return daten if isinstance(daten, dict) else {}
    except Exception:
        return {}


def _zwischenstand_merken(ordner: Path, stelle: int, weg: str, **felder) -> None:
    try:
        daten = _zwischenstand_lesen(ordner)
        szenen = daten.setdefault("szenen", {})
        eintrag = szenen.setdefault(str(stelle), {})
        eintrag.update(felder)
        eintrag["weg"] = weg
        eintrag["zeit"] = time.time()
        ziel = Path(ordner) / _ZWISCHENSTAND
        vorlaeufig = ziel.with_suffix(".tmp")
        vorlaeufig.write_text(json.dumps(daten, ensure_ascii=False, indent=1),
                              encoding="utf-8")
        vorlaeufig.replace(ziel)
    except Exception as fehler:
        logbook.debug(QUELLE, f"Zwischenstand nicht geschrieben: {type(fehler).__name__}")


def _eine_szene(auftrag_id: str, e: Einstellungen, szene: promptsmith.Szene,
                stelle: int, anzahl: int, ordner: Path, dienst, braucht_bild: bool,
                bilder: dict[int, str], abbruch: threading.Event) -> Path:
    """Eine Szene vom Startbild bis zur geprüften Clipdatei.

    Steht bewusst für sich: Erst dadurch kann der Aufrufer den Ausfall einer einzelnen
    Szene auffangen, ohne die bereits bezahlten Clips mitzureißen.
    """
    weg = videoquelle.weg_von(dienst) or getattr(dienst, "name", "")
    stand = (_zwischenstand_lesen(ordner).get("szenen") or {}).get(str(stelle)) or {}
    gleicher_weg = stand.get("weg") == weg
    frisch = time.time() - float(stand.get("zeit") or 0) < _BILD_HALTBAR
    clippfad = ordner / f"szene_{stelle:02d}.mp4"
    bildpfad = ordner / f"szene_{stelle:02d}_start.jpg"

    # ── Schon fertig? ────────────────────────────────────────────────────
    # Ein Clip aus einem früheren Versuch ist bezahlt und passt zum übernommenen
    # Drehbuch. Ihn neu zu bestellen, wäre Geld für nichts.
    if clippfad.exists():
        try:
            media.pruefe_video(clippfad)
            logbook.info(QUELLE, f"Szene {stelle}/{anzahl} ist vom letzten Versuch fertig "
                                 "— wird übernommen, kostet nichts.", job=auftrag_id)
            if braucht_bild and stelle == anzahl:
                _block(auftrag_id, "bild", "fertig", f"{anzahl} Startbild(er)")
                _uebergang(auftrag_id, "bild", "video")
            return clippfad
        except errors.StudioFehler:
            clippfad.unlink(missing_ok=True)          # kaputt — neu erzeugen

    # ── Startbild ────────────────────────────────────────────────────────
    bild_kennung = ""
    if braucht_bild:
        jobstore.aktualisieren(auftrag_id, block="bild")
        _block(auftrag_id, "bild", "aktiv", f"Szene {stelle} von {anzahl}")

        if (bildpfad.exists() and stand.get("bild_url") and stand.get("bild_job")
                and gleicher_weg and frisch and weg != "demo"):
            bilder[stelle] = stand["bild_url"]
            bild_kennung = str(stand["bild_job"])
            logbook.info("Startbild", f"Szene {stelle}/{anzahl}: Startbild vom letzten "
                                      "Versuch wird wiederverwendet — kostet nichts.",
                         job=auftrag_id)
        else:
            def bildmeldung(anteil, rest, _zustand, _s=stelle):
                gesamt = ((_s - 1) + anteil) / anzahl
                _fortschritt(auftrag_id, "bild", gesamt, rest,
                             f"Szene {_s}/{anzahl}")

            ergebnis = _aufrufen(
                dienst.bild, szene.bild_prompt, seitenverhaeltnis=e.seitenverhaeltnis,
                modell=e.bildmodell or config.IMAGE_MODEL,
                abbruch=abbruch, melden=bildmeldung)
            bilder[stelle] = ergebnis.url
            bild_kennung = str(ergebnis.request_id or "")

            # Herunterladen, damit der Kunde das Startbild behält und die Oberfläche
            # es anzeigen kann — die Adresse beim Anbieter läuft nach kurzer Zeit ab.
            dienst.herunterladen(ergebnis.url, bildpfad, abbruch)
            _zwischenstand_merken(ordner, stelle, weg, bild_url=ergebnis.url,
                                  bild_job=bild_kennung, video_job="")
            logbook.erfolg("Startbild", f"Szene {stelle}/{anzahl} steht "
                                        f"({ergebnis.dauer:.0f} s).", job=auftrag_id)
        logbook.ereignis("startbild", {"szene": stelle,
                                       "datei": library.web_pfad(bildpfad)},
                         job=auftrag_id)

        if stelle == anzahl:
            _fortschritt(auftrag_id, "bild", 1.0, 0, "fertig")
            _block(auftrag_id, "bild", "fertig", f"{anzahl} Startbild(er)")
            _uebergang(auftrag_id, "bild", "video")

    # ── Video ────────────────────────────────────────────────────────────
    _pruefe_abbruch(abbruch)
    jobstore.aktualisieren(auftrag_id, block="video")
    _block(auftrag_id, "video", "aktiv", f"Szene {stelle} von {anzahl}")

    def videomeldung(anteil, rest, zustand, _s=stelle):
        gesamt = ((_s - 1) + anteil) / anzahl
        # Restzeit hochrechnen: die verbleibenden Szenen brauchen etwa so lange
        # wie die aktuelle — das ist ehrlicher als nur die laufende Szene zu zeigen.
        gesamtrest = rest + (anzahl - _s) * (rest / max(anteil, 0.05) if anteil else rest)
        _fortschritt(auftrag_id, "video", gesamt, min(gesamtrest, 3600),
                     f"Szene {_s}/{anzahl} · {zustand}")

    # Das Seitenverhältnis geht an jeden Weg mit. Die Platform-API übergeht es
    # (ihre Videomodelle übernehmen das Format vom Startbild), der Abo-Weg braucht
    # es — dort entstünde sonst ein 16:9-Clip, obwohl Hochformat bestellt war.
    def gemeldet(kennung, _modell, _s=stelle):
        _zwischenstand_merken(ordner, _s, weg, video_job=str(kennung))

    def bestellen(fortsetzen: str):
        # `e.sekunden` statt `szene.dauer`: Die Vorprüfung kann die Länge an das
        # angepasst haben, was das Modell wirklich annimmt.
        dauer = e.sekunden or szene.dauer
        if braucht_bild:
            return _aufrufen(
                dienst.video_aus_bild, szene.video_prompt, bilder[stelle], dauer=dauer,
                modell=e.videomodell,
                bewegungen=[e.bewegung] if e.bewegung else None,
                seitenverhaeltnis=e.seitenverhaeltnis,
                abbruch=abbruch, melden=videomeldung, gemeldet=gemeldet,
                fortsetzen=fortsetzen, bild_kennung=bild_kennung)
        return _aufrufen(
            dienst.video_aus_text, szene.video_prompt, dauer=dauer, modell=e.videomodell,
            seitenverhaeltnis=e.seitenverhaeltnis,
            abbruch=abbruch, melden=videomeldung, gemeldet=gemeldet,
            fortsetzen=fortsetzen)

    offen = str(stand.get("video_job") or "") if gleicher_weg and weg != "demo" else ""
    try:
        ergebnis = bestellen(offen)
    except (errors.AbbruchFehler, *_TOEDLICH):
        raise
    except errors.StudioFehler:
        if not offen:
            raise
        # Der gemerkte Auftrag ist beim Dienst gescheitert oder unbekannt. Dann eben
        # neu bestellen — aber nur dieses eine Mal, und ohne die alte Nummer.
        logbook.warnung(QUELLE, f"Szene {stelle}: der offene Auftrag vom letzten Versuch "
                                "ist nicht mehr abholbar — es wird neu bestellt.",
                        job=auftrag_id)
        _zwischenstand_merken(ordner, stelle, weg, video_job="")
        ergebnis = bestellen("")

    dienst.herunterladen(ergebnis.url, clippfad, abbruch)
    media.pruefe_video(clippfad)
    logbook.erfolg("Higgsfield", f"Szene {stelle}/{anzahl} fertig "
                                 f"({ergebnis.dauer:.0f} s).", job=auftrag_id)
    return clippfad



# ── Block 5: Montage und Ausgabe ─────────────────────────────────────────────

def _schritt_ausgabe(auftrag_id: str, e: Einstellungen, drehbuch: promptsmith.Drehbuch,
                     clips: list[Path], ordner: Path, abbruch: threading.Event,
                     ausgefallen: list[str] | None = None) -> dict:
    jobstore.aktualisieren(auftrag_id, block="ausgabe")
    _block(auftrag_id, "ausgabe", "aktiv",
           "Szenen werden zusammengesetzt" if len(clips) > 1 else "Video wird abgelegt")
    _pruefe_abbruch(abbruch)

    film = ordner / "film.mp4"
    # Das bestellte Format geht mit: Es entscheidet nur, wenn sich am Material nichts
    # messen lässt — aber dann entscheidet es richtig, statt auf Breitbild zu raten.
    media.montieren(clips, film, weiche_uebergaenge=e.weiche_uebergaenge,
                    seitenverhaeltnis=e.seitenverhaeltnis, abbruch=abbruch,
                    melden=lambda a: _fortschritt(auftrag_id, "ausgabe", a * 0.8, 0,
                                                  "Montage"))

    # Ein Vorschaubild entsteht immer — die Bibliothek braucht es für die Kachel.
    poster = ordner / "film_poster.jpg"
    try:
        media.format_erzeugen(film, poster, "poster", wie_die_quelle=True,
                              abbruch=abbruch)
    except errors.StudioFehler as fehler:
        logbook.warnung(QUELLE, f"Vorschaubild nicht erzeugt: {fehler.meldung}",
                        job=auftrag_id)
        poster = None

    _fortschritt(auftrag_id, "ausgabe", 0.85, 0, "Formate")
    erzeugte: dict[str, str] = {}
    for kennung in e.formate:
        _pruefe_abbruch(abbruch)
        try:
            vorgabe = media.FORMATE[kennung]
            ziel = ordner / f"film_{kennung}.{vorgabe.endung}"
            media.format_erzeugen(film, ziel, kennung, abbruch=abbruch)
            erzeugte[kennung] = library.web_pfad(ziel)
        except errors.AbbruchFehler:
            raise
        except errors.StudioFehler as fehler:
            # Ein misslungenes Zusatzformat darf den fertigen Film nicht entwerten.
            logbook.warnung(QUELLE, f"Format {kennung} nicht erzeugt: {fehler.meldung}",
                            job=auftrag_id)

    angaben = media.angaben(film)
    ergebnis = {
        "film": str(film),
        "film_web": library.web_pfad(film),
        "poster": library.web_pfad(poster) if poster else "",
        "ordner": str(ordner),
        "dauer": angaben.dauer,
        "breite": angaben.breite,
        "hoehe": angaben.hoehe,
        "bytes": angaben.bytes,
        "szenen": len(clips),
        "formate": erzeugte,
        "titel": drehbuch.titel,
        # Ausgefallene Szenen gehören ins Ergebnis, nicht nur ins Logbuch: Die
        # Bibliothek soll den Film als vollständig oder als lückenhaft zeigen können.
        "ausgefallen": list(ausgefallen or []),
    }

    # Der Posting-Zettel: Titel, Bildunterschrift und Hashtags zum Kopieren. Ein
    # fertiges Video nützt wenig, wenn danach noch die Textarbeit ansteht — und beim
    # Hochladen auf TikTok will genau das in einem Zug erledigt sein.
    ergebnis["posting"] = library.posting_schreiben(ordner, drehbuch, e.seitenverhaeltnis)

    # Begleitzettel im Ordner: wer das Video in einem Jahr wiederfindet, soll wissen,
    # woraus es entstanden ist.
    library.begleitzettel_schreiben(ordner, {
        "titel": drehbuch.titel,
        "erstellt": time.strftime("%d.%m.%Y %H:%M"),
        "briefing": e.briefing,
        "einstellungen": e.als_dict(),
        "drehbuch": drehbuch.als_dict(),
        "ergebnis": {k: v for k, v in ergebnis.items() if k != "formate"},
    })

    _fortschritt(auftrag_id, "ausgabe", 1.0, 0, "fertig")
    _block(auftrag_id, "ausgabe", "fertig",
           f"{angaben.dauer:.0f} s · {angaben.bytes / 1_048_576:.1f} MB")
    return ergebnis
