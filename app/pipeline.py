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

import threading
import time
from dataclasses import dataclass
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

    def als_dict(self) -> dict:
        return {"briefing": self.briefing, "modus": self.modus, "woertlich": self.woertlich,
                "szenen": self.szenen, "sekunden": self.sekunden,
                "videomodell": self.videomodell, "bildmodell": self.bildmodell,
                "seitenverhaeltnis": self.seitenverhaeltnis, "stil": self.stil,
                "zielgruppe": self.zielgruppe, "tonfall": self.tonfall,
                "bewegung": self.bewegung,
                "weiche_uebergaenge": self.weiche_uebergaenge,
                "formate": list(self.formate)}


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
        for block in jobstore.BLOECKE:
            _block(auftrag_id, block, "wartend")

        drehbuch = _schritt_briefing_und_claude(auftrag_id, e, abbruch)
        ordner = jobstore.ordner_fuer(jobstore.holen(auftrag_id), drehbuch.dateiname)
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

    beschreibung = (f"{e.szenen} Szene(n) à {e.sekunden} s"
                    if e.szenen > 1 else f"Einzelclip, {e.sekunden} s")
    logbook.info(QUELLE, f"Briefing angenommen · {beschreibung} · "
                         f"{higgsfield.modell_info(e.videomodell)['name']}", job=auftrag_id)
    _block(auftrag_id, "briefing", "fertig", beschreibung)
    _uebergang(auftrag_id, "briefing", "claude")

    _block(auftrag_id, "claude", "aktiv", "Drehbuch wird geschrieben")
    _fortschritt(auftrag_id, "claude", 0.1, 45, "Sprachmodell arbeitet")
    jobstore.aktualisieren(auftrag_id, block="claude")
    _pruefe_abbruch(abbruch)

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
    # zu wechseln würde zu Szenen führen, die nicht zueinander passen.
    dienst = videoquelle.aktiv()

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


def _eine_szene(auftrag_id: str, e: Einstellungen, szene: promptsmith.Szene,
                stelle: int, anzahl: int, ordner: Path, dienst, braucht_bild: bool,
                bilder: dict[int, str], abbruch: threading.Event) -> Path:
    """Eine Szene vom Startbild bis zur geprüften Clipdatei.

    Steht bewusst für sich: Erst dadurch kann der Aufrufer den Ausfall einer einzelnen
    Szene auffangen, ohne die bereits bezahlten Clips mitzureißen.
    """
    # ── Startbild ────────────────────────────────────────────────────────
    if braucht_bild:
        jobstore.aktualisieren(auftrag_id, block="bild")
        _block(auftrag_id, "bild", "aktiv", f"Szene {stelle} von {anzahl}")

        def bildmeldung(anteil, rest, _zustand, _s=stelle):
            gesamt = ((_s - 1) + anteil) / anzahl
            _fortschritt(auftrag_id, "bild", gesamt, rest,
                         f"Szene {_s}/{anzahl}")

        ergebnis = dienst.bild(
            szene.bild_prompt, seitenverhaeltnis=e.seitenverhaeltnis,
            modell=e.bildmodell or config.IMAGE_MODEL,
            abbruch=abbruch, melden=bildmeldung)
        bilder[stelle] = ergebnis.url

        # Herunterladen, damit der Kunde das Startbild behält und die Oberfläche
        # es anzeigen kann — die Adresse beim Anbieter läuft nach kurzer Zeit ab.
        bildpfad = ordner / f"szene_{stelle:02d}_start.jpg"
        dienst.herunterladen(ergebnis.url, bildpfad, abbruch)
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
    if braucht_bild:
        ergebnis = dienst.video_aus_bild(
            szene.video_prompt, bilder[stelle], dauer=szene.dauer,
            modell=e.videomodell,
            bewegungen=[e.bewegung] if e.bewegung else None,
            seitenverhaeltnis=e.seitenverhaeltnis,
            abbruch=abbruch, melden=videomeldung)
    else:
        ergebnis = dienst.video_aus_text(
            szene.video_prompt, dauer=szene.dauer, modell=e.videomodell,
            seitenverhaeltnis=e.seitenverhaeltnis,
            abbruch=abbruch, melden=videomeldung)

    clippfad = ordner / f"szene_{stelle:02d}.mp4"
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
