"""
media.py — alles, was ffmpeg erledigt: Montage, Formate, Vorschaubilder.

Zwei Aufgaben:

  1. **Montage.** Higgsfield liefert Clips von höchstens zehn Sekunden. Ein 30-Sekunden-
     Werbevideo entsteht deshalb hier: mehrere Szenen werden auf ein gemeinsames Raster
     gebracht (gleiche Auflösung, gleiche Bildrate, gleiches Pixelseitenverhältnis) und
     dann mit weichen Übergängen zusammengesetzt. Ohne diese Vereinheitlichung bricht
     ffmpeg beim Aneinanderhängen ab oder liefert ruckelnde Ergebnisse.

  2. **Formate.** Aus dem fertigen Film entstehen auf Knopfdruck die Fassungen für
     Hochformat, Quadrat, Breitbild, Web, GIF und Vorschaubild.

Warum kein ffprobe: Das mitgelieferte `imageio-ffmpeg` bringt nur ffmpeg mit, kein ffprobe.
Die Dateiangaben werden deshalb aus der Ausgabe von `ffmpeg -i` gelesen — das funktioniert
mit jeder Installation.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import config, errors, logbook

QUELLE = "Formate"

#: Wie lange ein einzelner ffmpeg-Lauf höchstens dauern darf (Sekunden).
_FFMPEG_ZEITLIMIT = 900

#: Dauer der Überblendung zwischen zwei Szenen.
_UEBERBLENDUNG = 0.4

# Nur ein ffmpeg-Lauf gleichzeitig: mehrere parallele Läufe bringen auf einem Arbeitsplatz-
# rechner nichts (ffmpeg lastet die Kerne selbst aus), machen die Oberfläche aber zäh.
_ffmpeg_schlange = threading.Semaphore(1)


# ── Formatvorgaben ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Formatvorgabe:
    kennung: str
    name: str
    beschreibung: str
    breite: int
    hoehe: int
    endung: str = "mp4"
    crf: int = 20              # kleiner = bessere Qualität, größere Datei
    kurz: str = ""             # Beschriftung auf der Bibliothekskachel

    @property
    def verhaeltnis(self) -> float:
        return self.breite / self.hoehe


# Die Kurzform steht hier und wird nicht in der Oberfläche aus dem Namen geraten:
# „16:9 Breitbild“ und „16:9 Web-optimiert“ würden sonst beide zu „16:9“ und wären auf
# der Kachel nicht auseinanderzuhalten.
FORMATE: dict[str, Formatvorgabe] = {
    "hoch": Formatvorgabe("hoch", "9:16 Hochformat",
                          "TikTok, Reels, Shorts — 1080×1920", 1080, 1920,
                          kurz="9:16"),
    "quadrat": Formatvorgabe("quadrat", "1:1 Quadrat",
                             "Instagram- und Facebook-Feed — 1080×1080", 1080, 1080,
                             kurz="1:1"),
    "breit": Formatvorgabe("breit", "16:9 Breitbild",
                           "YouTube, Webseite, Präsentation — 1920×1080", 1920, 1080,
                           kurz="16:9"),
    "web": Formatvorgabe("web", "16:9 Web-optimiert",
                         "Kleine Datei zum Einbetten — 1280×720", 1280, 720, crf=26,
                         kurz="Web"),
    "gif": Formatvorgabe("gif", "GIF-Schleife",
                         "Endlosschleife ohne Ton, erste 8 Sekunden — 640 px breit",
                         640, 360, "gif", kurz="GIF"),
    "poster": Formatvorgabe("poster", "Vorschaubild",
                            "Standbild als JPG — 1920×1080", 1920, 1080, "jpg",
                            kurz="Bild"),
}

#: Diese Formate erzeugt die Bibliothek, wenn nichts anderes gewählt wird.
STANDARDFORMATE = ("hoch", "quadrat", "breit")


# ── ffmpeg aufrufen ──────────────────────────────────────────────────────────

def ffmpeg_vorhanden() -> bool:
    return bool(config.ffmpeg_pfad())


def _ffmpeg(argumente: list[str], *, beschreibung: str,
            abbruch: threading.Event | None = None,
            melden=None, gesamtdauer: float = 0.0) -> None:
    """Führt ffmpeg aus. Meldet den Fortschritt, hört auf einen Abbruchwunsch und
    verwandelt einen Fehlschlag in eine verständliche Meldung.

    Der Fortschritt kommt aus `-progress pipe:1`: ffmpeg schreibt dort fortlaufend die
    bereits verarbeitete Spielzeit, was zusammen mit der bekannten Gesamtdauer einen
    ehrlichen Balken ergibt — geraten wird nichts.
    """
    programm = config.ffmpeg_pfad()
    if not programm:
        raise errors.VerarbeitungsFehler(
            "Es wurde kein ffmpeg gefunden.",
            "python -m pip install imageio-ffmpeg — danach das Programm neu starten.",
            ursprung=QUELLE)

    befehl = [programm, "-hide_banner", "-nostdin", "-y",
              "-loglevel", "error", "-progress", "pipe:1", "-nostats", *argumente]

    with _ffmpeg_schlange:
        begonnen = time.monotonic()
        try:
            lauf = subprocess.Popen(befehl, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace")
        except OSError as fehler:
            raise errors.VerarbeitungsFehler(
                "ffmpeg ließ sich nicht starten.", str(fehler), ursprung=QUELLE) from fehler

        try:
            while True:
                if abbruch is not None and abbruch.is_set():
                    lauf.kill()
                    raise errors.AbbruchFehler(f"{beschreibung} abgebrochen.", ursprung=QUELLE)
                if time.monotonic() - begonnen > _FFMPEG_ZEITLIMIT:
                    lauf.kill()
                    raise errors.ZeitFehler(
                        f"{beschreibung} hat zu lange gedauert und wurde beendet.",
                        "Bei sehr langen Videos hilft eine kleinere Szenenzahl.",
                        ursprung=QUELLE)

                zeile = lauf.stdout.readline() if lauf.stdout else ""
                if not zeile:
                    if lauf.poll() is not None:
                        break
                    time.sleep(0.05)
                    continue

                if melden and gesamtdauer > 0 and zeile.startswith("out_time_ms="):
                    try:
                        mikrosekunden = int(zeile.split("=", 1)[1].strip())
                        melden(min(0.99, (mikrosekunden / 1_000_000) / gesamtdauer))
                    except (ValueError, ZeroDivisionError):
                        pass
        finally:
            try:
                lauf.wait(timeout=10)
            except Exception:
                lauf.kill()

        fehlertext = (lauf.stderr.read() if lauf.stderr else "") or ""

    if lauf.returncode != 0:
        knapp = " ".join(fehlertext.split())[:400]
        raise errors.VerarbeitungsFehler(
            f"{beschreibung} ist fehlgeschlagen.",
            knapp or f"ffmpeg endete mit Rückgabewert {lauf.returncode}.",
            ursprung=QUELLE, details={"rueckgabe": lauf.returncode})

    if melden:
        melden(1.0)


# ── Dateiangaben lesen ───────────────────────────────────────────────────────

_DAUER_MUSTER = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)")
_GROESSE_MUSTER = re.compile(r"[,\s](\d{2,5})x(\d{2,5})[,\s]")
_BILDRATE_MUSTER = re.compile(r"(\d+\.?\d*)\s*fps")


@dataclass
class Videoangaben:
    pfad: Path
    dauer: float = 0.0
    breite: int = 0
    hoehe: int = 0
    bildrate: float = 0.0
    bytes: int = 0
    hat_ton: bool = False

    @property
    def gueltig(self) -> bool:
        return self.dauer > 0.05 and self.breite > 0 and self.hoehe > 0

    def als_dict(self) -> dict:
        return {"dauer": round(self.dauer, 2), "breite": self.breite, "hoehe": self.hoehe,
                "bildrate": round(self.bildrate, 2), "bytes": self.bytes,
                "mb": round(self.bytes / 1_048_576, 2), "hat_ton": self.hat_ton,
                "gueltig": self.gueltig}


def angaben(pfad: "str | Path") -> Videoangaben:
    """Liest Dauer, Auflösung und Bildrate aus der Ausgabe von `ffmpeg -i`.

    `ffmpeg -i` ohne Ausgabedatei endet immer mit einem Fehlercode — das ist normal und
    kein Grund zur Sorge; die gesuchten Angaben stehen trotzdem im Fehlerkanal.
    """
    pfad = Path(pfad)
    ergebnis = Videoangaben(pfad=pfad)
    if not pfad.exists():
        return ergebnis
    ergebnis.bytes = pfad.stat().st_size

    programm = config.ffmpeg_pfad()
    if not programm:
        return ergebnis
    try:
        lauf = subprocess.run([programm, "-hide_banner", "-i", str(pfad)],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)
        text = (lauf.stderr or "") + (lauf.stdout or "")
    except Exception:
        return ergebnis

    treffer = _DAUER_MUSTER.search(text)
    if treffer:
        stunden, minuten, sekunden = treffer.groups()
        ergebnis.dauer = int(stunden) * 3600 + int(minuten) * 60 + float(sekunden)

    # Die erste Auflösungsangabe steht in der Videospur; Vorschaubilder in den
    # Metadaten könnten weitere liefern, deshalb nur der erste Treffer.
    for zeile in text.splitlines():
        if "Video:" in zeile:
            groesse = _GROESSE_MUSTER.search(zeile)
            if groesse:
                ergebnis.breite, ergebnis.hoehe = int(groesse.group(1)), int(groesse.group(2))
            rate = _BILDRATE_MUSTER.search(zeile)
            if rate:
                ergebnis.bildrate = float(rate.group(1))
            break
    ergebnis.hat_ton = "Audio:" in text
    return ergebnis


def pruefe_video(pfad: "str | Path", *, mindestdauer: float = 0.3) -> Videoangaben:
    """Stellt sicher, dass eine Datei ein brauchbares Video ist. Wird nach jedem Schritt
    aufgerufen — eine kaputte Zwischendatei soll auffallen, solange man noch weiß, wo sie
    herkam, und nicht erst beim Kunden im Abspielfenster."""
    daten = angaben(pfad)
    if not daten.gueltig or daten.dauer < mindestdauer:
        raise errors.VerarbeitungsFehler(
            f"Die Datei {Path(pfad).name} ist kein brauchbares Video.",
            f"Erkannt: {daten.dauer:.1f} s, {daten.breite}×{daten.hoehe}. "
            "Meist ein abgebrochener Download — bitte erneut versuchen.",
            ursprung=QUELLE, details=daten.als_dict())
    return daten


# ── Montage ──────────────────────────────────────────────────────────────────

def _normalisieren(quelle: Path, ziel: Path, *, breite: int, hoehe: int, bildrate: int,
                   abbruch: threading.Event | None = None) -> Path:
    """Bringt einen Clip auf das gemeinsame Raster: Zielauflösung mit Beschnitt statt
    Verzerrung, feste Bildrate, quadratische Pixel, tonlos.

    `increase` skaliert auf Überdeckung, `crop` schneidet mittig zu — so bleibt das
    Bildverhältnis erhalten und es entstehen keine schwarzen Ränder."""
    _ffmpeg([
        "-i", str(quelle),
        "-vf", (f"scale={breite}:{hoehe}:force_original_aspect_ratio=increase,"
                f"crop={breite}:{hoehe},fps={bildrate},setsar=1"),
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(ziel),
    ], beschreibung=f"Szene {quelle.stem} anpassen", abbruch=abbruch)
    return ziel


def montieren(clips: list[Path], ziel: Path, *, weiche_uebergaenge: bool = True,
              breite: int = 1920, hoehe: int = 1080, bildrate: int = 30,
              abbruch: threading.Event | None = None, melden=None) -> Path:
    """Setzt mehrere Szenen zu einem Film zusammen.

    Bei einem einzigen Clip wird nur normalisiert — kein unnötiges Neukodieren.
    """
    clips = [Path(c) for c in clips if Path(c).exists()]
    if not clips:
        raise errors.VerarbeitungsFehler(
            "Es gibt keine Szenen zum Zusammensetzen.",
            "Vermutlich sind alle Einzelaufträge fehlgeschlagen.", ursprung=QUELLE)

    ziel = Path(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    arbeitsordner = ziel.parent / f".montage_{ziel.stem}"
    arbeitsordner.mkdir(parents=True, exist_ok=True)

    try:
        logbook.info(QUELLE, f"Setze {len(clips)} Szene(n) zusammen …")
        angepasst: list[Path] = []
        for stelle, clip in enumerate(clips, start=1):
            zwischenziel = arbeitsordner / f"teil_{stelle:02d}.mp4"
            _normalisieren(clip, zwischenziel, breite=breite, hoehe=hoehe,
                           bildrate=bildrate, abbruch=abbruch)
            angepasst.append(zwischenziel)
            if melden:
                melden(0.6 * stelle / len(clips))

        if len(angepasst) == 1:
            shutil.copy2(angepasst[0], ziel)
        elif weiche_uebergaenge:
            _mit_ueberblendung(angepasst, ziel, abbruch=abbruch,
                               melden=lambda a: melden(0.6 + 0.4 * a) if melden else None)
        else:
            _hart_aneinander(angepasst, ziel, abbruch=abbruch,
                             melden=lambda a: melden(0.6 + 0.4 * a) if melden else None)

        daten = pruefe_video(ziel)
        logbook.erfolg(QUELLE, f"Film fertig: {ziel.name} · {daten.dauer:.1f} s · "
                               f"{daten.breite}×{daten.hoehe} · {daten.bytes / 1_048_576:.1f} MB")
        return ziel
    finally:
        shutil.rmtree(arbeitsordner, ignore_errors=True)


def _hart_aneinander(clips: list[Path], ziel: Path,
                     abbruch: threading.Event | None = None, melden=None) -> None:
    """Schnitt auf Schnitt, ohne Überblendung. Weil alle Teile bereits dasselbe Format
    haben, genügt das Kopieren der Spuren — das ist um ein Vielfaches schneller als
    neu zu kodieren."""
    liste = ziel.parent / f".liste_{ziel.stem}.txt"
    # ffmpeg erwartet einfache Anführungszeichen und maskiert solche im Pfad.
    liste.write_text(
        "\n".join(f"file '{c.as_posix()}'" for c in clips), encoding="utf-8")
    try:
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(liste), "-c", "copy", str(ziel)],
                beschreibung="Szenen aneinanderhängen", abbruch=abbruch, melden=melden)
    finally:
        liste.unlink(missing_ok=True)


def _mit_ueberblendung(clips: list[Path], ziel: Path,
                       abbruch: threading.Event | None = None, melden=None) -> None:
    """Weiche Übergänge über den xfade-Filter.

    xfade verbindet immer nur zwei Spuren, deshalb wird eine Kette gebaut. Der
    Versatz jedes Übergangs ist die bis dahin aufgelaufene Spielzeit abzüglich der
    bereits verbrauchten Überblendungen — sonst rutschen die Übergänge auseinander
    und der letzte landet hinter dem Filmende.
    """
    dauern = []
    for clip in clips:
        daten = angaben(clip)
        dauern.append(max(daten.dauer, 0.5))

    # Bei sehr kurzen Clips würde eine feste Überblendung mehr fressen, als der Clip
    # lang ist — dann lieber kürzer überblenden.
    ueberblendung = min(_UEBERBLENDUNG, min(dauern) / 3)
    if ueberblendung < 0.1 or len(clips) > 12:
        # Sehr kurze Szenen oder sehr viele Teile: harter Schnitt ist hier das
        # verlässlichere Ergebnis (lange Filterketten werden fehleranfällig).
        _hart_aneinander(clips, ziel, abbruch=abbruch, melden=melden)
        return

    eingaben: list[str] = []
    for clip in clips:
        eingaben += ["-i", str(clip)]

    filter_teile: list[str] = []
    letzter = "[0:v]"
    versatz = 0.0
    for stelle in range(1, len(clips)):
        versatz += dauern[stelle - 1] - ueberblendung
        marke = f"[v{stelle}]"
        filter_teile.append(
            f"{letzter}[{stelle}:v]xfade=transition=fade:"
            f"duration={ueberblendung:.2f}:offset={versatz:.2f}{marke}")
        letzter = marke

    gesamt = sum(dauern) - ueberblendung * (len(clips) - 1)
    _ffmpeg([*eingaben,
             "-filter_complex", ";".join(filter_teile),
             "-map", letzter,
             "-c:v", "libx264", "-preset", "medium", "-crf", "19",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             str(ziel)],
            beschreibung="Szenen weich überblenden", abbruch=abbruch,
            melden=melden, gesamtdauer=gesamt)


# ── Formate erzeugen ─────────────────────────────────────────────────────────

def format_erzeugen(quelle: "str | Path", ziel: "str | Path", kennung: str,
                    *, abbruch: threading.Event | None = None, melden=None) -> Path:
    """Erzeugt eine Formatfassung. Videoformate werden mittig zugeschnitten statt
    verzerrt oder mit Balken versehen — bei KI-Videos sitzt das Motiv fast immer in
    der Bildmitte, und ein scharfer Anschnitt wirkt hochwertiger als schwarze Ränder."""
    vorgabe = FORMATE.get(kennung)
    if vorgabe is None:
        raise errors.EingabeFehler(f"Unbekanntes Format: {kennung}",
                                   "Möglich sind: " + ", ".join(FORMATE), ursprung=QUELLE)

    quelle, ziel = Path(quelle), Path(ziel)
    if not quelle.exists():
        raise errors.VerarbeitungsFehler(
            f"Die Ausgangsdatei fehlt: {quelle.name}",
            "Wurde sie verschoben oder gelöscht?", ursprung=QUELLE)
    ziel.parent.mkdir(parents=True, exist_ok=True)

    quellangaben = angaben(quelle)
    logbook.info(QUELLE, f"Erzeuge {vorgabe.name} …")

    # In eine Nebendatei schreiben und erst danach umbenennen: bricht der Lauf ab,
    # taucht in der Bibliothek keine halbe Datei auf.
    # Die Endung muss dabei erhalten bleiben — ffmpeg leitet das Ausgabeformat aus ihr
    # ab und bricht sonst mit „Unable to choose an output format“ ab.
    vorlaeufig = ziel.with_name(f"{ziel.stem}.teil{ziel.suffix}")
    try:
        if kennung == "poster":
            _poster(quelle, vorlaeufig, vorgabe, quellangaben, abbruch)
        elif kennung == "gif":
            _gif(quelle, vorlaeufig, vorgabe, quellangaben, abbruch, melden)
        else:
            _videoformat(quelle, vorlaeufig, vorgabe, quellangaben, abbruch, melden)

        if kennung != "poster":
            pruefe_video(vorlaeufig)
        elif vorlaeufig.stat().st_size < 1024:
            raise errors.VerarbeitungsFehler("Das Vorschaubild wurde nicht erzeugt.",
                                             ursprung=QUELLE)

        vorlaeufig.replace(ziel)
    finally:
        if vorlaeufig.exists():
            vorlaeufig.unlink(missing_ok=True)

    logbook.erfolg(QUELLE, f"{vorgabe.name} fertig: {ziel.name} "
                           f"({ziel.stat().st_size / 1_048_576:.1f} MB)")
    return ziel


def _videoformat(quelle: Path, ziel: Path, vorgabe: Formatvorgabe,
                 quellangaben: Videoangaben, abbruch, melden) -> None:
    _ffmpeg([
        "-i", str(quelle),
        "-vf", (f"scale={vorgabe.breite}:{vorgabe.hoehe}:force_original_aspect_ratio=increase,"
                f"crop={vorgabe.breite}:{vorgabe.hoehe},setsar=1"),
        "-c:v", "libx264", "-preset", "medium", "-crf", str(vorgabe.crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        # Ton mitnehmen, falls vorhanden — Higgsfield-Clips haben meist keinen.
        *(["-c:a", "aac", "-b:a", "128k"] if quellangaben.hat_ton else ["-an"]),
        str(ziel),
    ], beschreibung=f"{vorgabe.name} erzeugen", abbruch=abbruch, melden=melden,
        gesamtdauer=quellangaben.dauer)


def _gif(quelle: Path, ziel: Path, vorgabe: Formatvorgabe,
         quellangaben: Videoangaben, abbruch, melden) -> None:
    """GIF in zwei Durchgängen: erst eine eigene Farbtabelle berechnen, dann anwenden.
    Ohne diesen Umweg wird ein GIF aus Videomaterial fleckig und viel zu groß.

    Die Länge wird begrenzt: GIF kennt keine Kompression über Bildgrenzen hinweg, ein
    dreizehn Sekunden langes GIF wog im Versuch fast 10 MB. Acht Sekunden ergeben eine
    brauchbare Schleife in vertretbarer Größe — für alles Längere gibt es die MP4-Fassungen.
    """
    palette = ziel.with_suffix(".palette.png")
    hoechstdauer = min(8.0, quellangaben.dauer or 8.0)
    # Zwölf Bilder je Sekunde ist der übliche Kompromiss aus Flüssigkeit und Dateigröße.
    skalierung = f"fps=12,scale={vorgabe.breite}:-1:flags=lanczos"
    try:
        _ffmpeg(["-t", f"{hoechstdauer:.2f}", "-i", str(quelle),
                 "-vf", f"{skalierung},palettegen=stats_mode=diff", str(palette)],
                beschreibung="GIF-Farbtabelle berechnen", abbruch=abbruch)
        _ffmpeg(["-t", f"{hoechstdauer:.2f}", "-i", str(quelle), "-i", str(palette),
                 "-lavfi", f"{skalierung}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3",
                 "-loop", "0", str(ziel)],
                beschreibung="GIF erzeugen", abbruch=abbruch, melden=melden,
                gesamtdauer=hoechstdauer)
    finally:
        palette.unlink(missing_ok=True)


def _poster(quelle: Path, ziel: Path, vorgabe: Formatvorgabe,
            quellangaben: Videoangaben, abbruch) -> None:
    """Standbild aus dem ersten Drittel — der Anfang eines KI-Clips ist oft noch
    unruhig, das Ende zeigt manchmal schon den Ausblendvorgang."""
    zeitpunkt = max(0.1, min(quellangaben.dauer * 0.33, max(0.1, quellangaben.dauer - 0.2)))
    _ffmpeg(["-ss", f"{zeitpunkt:.2f}", "-i", str(quelle), "-frames:v", "1",
             "-vf", (f"scale={vorgabe.breite}:{vorgabe.hoehe}:"
                     f"force_original_aspect_ratio=increase,"
                     f"crop={vorgabe.breite}:{vorgabe.hoehe}"),
             "-q:v", "3", str(ziel)],
            beschreibung="Vorschaubild erzeugen", abbruch=abbruch)


# ── Platzhalterclip für den Probelauf ────────────────────────────────────────

def platzhalter_clip(ziel: "str | Path", *, sekunden: int = 5, text: str = "",
                     farbe: str = "0x101418", breite: int = 1920, hoehe: int = 1080,
                     abbruch: threading.Event | None = None) -> Path:
    """Erzeugt einen echten Videoclip ohne jeden Netzzugriff.

    Damit lässt sich die gesamte Kette — Montage, Formate, Bibliothek, Oberfläche —
    vollständig prüfen, ohne Guthaben zu verbrauchen. Der Clip ist bewusst als
    Platzhalter erkennbar und wird nie mit einem echten Ergebnis verwechselt.
    """
    ziel = Path(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    beschriftung = (text or "Probelauf")[:70]

    # Bewegung hineinbringen, damit auch Montage und Überblendung realistisch geprüft
    # werden: ein sanft wanderndes Farbverlaufsmuster über einer ruhigen Grundfläche.
    filter_kette = (
        f"color=c={farbe}:s={breite}x{hoehe}:d={sekunden}:r=30[grund];"
        f"life=s={breite // 8}x{hoehe // 8}:mold=10:r=12:ratio=0.1:"
        f"death_color=#1a2430:life_color=#22d3ee,scale={breite}:{hoehe},"
        f"format=yuv420p,colorchannelmixer=aa=0.18[muster];"
        f"[grund][muster]overlay,"
        f"drawbox=x=0:y=ih-120:w=iw:h=120:color=black@0.35:t=fill"
    )
    _ffmpeg(["-f", "lavfi", "-i", filter_kette, "-t", str(sekunden),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
             "-pix_fmt", "yuv420p", str(ziel)],
            beschreibung="Platzhalterclip erzeugen", abbruch=abbruch)
    logbook.debug(QUELLE, f"Platzhalterclip erzeugt: {ziel.name} ({beschriftung})")
    return ziel


# ── Hilfsangaben für die Oberfläche ──────────────────────────────────────────

def formatliste() -> list[dict]:
    return [{"kennung": v.kennung, "name": v.name, "kurz": v.kurz or v.name,
             "beschreibung": v.beschreibung, "breite": v.breite, "hoehe": v.hoehe,
             "endung": v.endung}
            for v in FORMATE.values()]


def selbsttest() -> dict:
    """Ist ffmpeg einsatzbereit? Wird beim Start und im Diagnosebereich aufgerufen."""
    programm = config.ffmpeg_pfad()
    if not programm:
        return {"ok": False, "meldung": "Kein ffmpeg gefunden.",
                "hinweis": "python -m pip install imageio-ffmpeg"}
    try:
        lauf = subprocess.run([programm, "-version"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
        # Die Bannerzeile („ffmpeg version 7.1-essentials_build-www.gyan.dev …“) steht
        # als Hinweis in der Oberfläche. Ungekürzt liest sie sich wie ein Fehler —
        # deshalb nur die Versionsnummer.
        erste = (lauf.stdout or "").splitlines()[0] if lauf.stdout else ""
        treffer = re.search(r"ffmpeg version (\S+)", erste)
        version = treffer.group(1).split("-")[0] if treffer else ""
        return {"ok": lauf.returncode == 0,
                "meldung": (f"Einsatzbereit (ffmpeg {version})." if version
                            else "Einsatzbereit."),
                "pfad": programm, "version": erste, "hinweis": ""}
    except Exception as fehler:
        return {"ok": False, "meldung": f"ffmpeg antwortet nicht: {type(fehler).__name__}",
                "hinweis": "Installation prüfen."}
