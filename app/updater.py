"""
updater.py — Aktualisierung aus dem Git-Repository, mit anschließendem Neustart.

Der Kunde soll neue Fassungen holen können, ohne ein Terminal zu öffnen: ein Knopf im
Dashboard, der den Stand prüft, den neuen Code holt und das Programm neu startet.

Drei Dinge sind dabei wichtig:

  * **Nur vorspulen.** `git pull --ff-only` — es wird nie zusammengeführt und nie etwas
    überschrieben. Gibt es lokale Änderungen, bricht die Aktualisierung mit einer
    verständlichen Meldung ab, statt Arbeit zu vernichten.
  * **Nie mitten in einem Auftrag.** Ein Neustart während einer laufenden Videoerzeugung
    würde Guthaben verbrennen. Der Aufrufer prüft das, und dieses Modul prüft es noch
    einmal selbst.
  * **Der Neustart überlebt den eigenen Tod.** Ein Prozess kann sich nicht selbst neu
    starten. Deshalb wird ein losgelöster Helfer gestartet, der wartet, bis dieser
    Prozess weg ist, und dann das Programm erneut aufruft.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config, errors, logbook

QUELLE = "Aktualisierung"

#: Wie lange ein Git-Aufruf höchstens dauern darf. Ohne Netz hängt `fetch` sonst ewig.
_ZEITLIMIT = 45

#: Ergebnis der letzten Prüfung, damit die Oberfläche nicht bei jedem Blick ins Netz muss.
_stand: dict = {}
_stand_zeit: float = 0.0
_sperre = threading.Lock()

#: Läuft gerade ein Update? Solange nimmt die Ablaufsteuerung keine Aufträge an.
_update_laeuft = threading.Event()
#: Ist ein Update geholt, aber der Neustart aufgeschoben, weil ein Auftrag lief?
_neustart_offen = {"ja": False}


def laeuft() -> bool:
    return _update_laeuft.is_set()


def _playwright_vorhanden() -> bool:
    import importlib.util
    return importlib.util.find_spec("playwright") is not None


def zusatzpakete_nachziehen(im_hintergrund: bool = True) -> bool:
    """Installiert fehlende Zusatzpakete (`requirements-optional.txt`) beim Start.

    **Warum beim Start und nicht nur beim Update:** Das erste Update auf diese Fassung
    führt noch der *alte* Updater aus, und der kennt die Zusatzpakete nicht. Ohne diesen
    Schritt käme Playwright erst mit dem übernächsten Update — bis dahin blieben
    Cookie-Banner im Werbevideo. Höchstens ein Versuch am Tag, im Hintergrund und ohne
    Folgen bei Misserfolg: Ohne Playwright fotografiert Edge direkt.
    """
    datei = config.BASE_DIR / "requirements-optional.txt"
    if not datei.exists() or _playwright_vorhanden():
        return False
    marke = config.DATA_DIR / ".zusatzpakete_versuch"
    try:
        if marke.exists() and time.time() - marke.stat().st_mtime < 24 * 3600:
            return False
        marke.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass

    def arbeiten() -> None:
        logbook.info(QUELLE, "Zusatzpaket für die Webseiten-Aufnahme wird im Hintergrund "
                             "installiert …")
        try:
            lauf = subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                                   "--disable-pip-version-check", "-r", str(datei)],
                                  cwd=str(config.BASE_DIR), capture_output=True, timeout=900)
            if lauf.returncode == 0:
                import importlib
                importlib.invalidate_caches()
                logbook.erfolg(QUELLE, "Zusatzpaket installiert — die Webseiten-Aufnahme "
                                       "klickt jetzt auch Cookie-Banner weg.")
            else:
                logbook.warnung(QUELLE, "Zusatzpaket ließ sich nicht installieren — "
                                        "Webseiten werden direkt mit Edge fotografiert.")
        except Exception as fehler:
            logbook.warnung(QUELLE, f"Zusatzpaket nicht installiert ({type(fehler).__name__})"
                                    " — Webseiten werden direkt mit Edge fotografiert.")

    if im_hintergrund:
        threading.Thread(target=arbeiten, name="zusatzpakete", daemon=True).start()
    else:
        arbeiten()
    return True


def neustart_ausstehend() -> bool:
    return bool(_neustart_offen["ja"])


def _git(*argumente: str, zeitlimit: int = _ZEITLIMIT) -> tuple[int, str]:
    """Führt einen Git-Befehl im Projektordner aus. Gibt (Rückgabewert, Ausgabe)."""
    try:
        lauf = subprocess.run(
            ["git", *argumente],
            cwd=str(config.BASE_DIR), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=zeitlimit,
            # Git darf unter keinen Umständen nach einem Passwort fragen — das würde
            # den Aufruf blockieren, bis das Zeitlimit greift.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
        )
        return lauf.returncode, ((lauf.stdout or "") + (lauf.stderr or "")).strip()
    except FileNotFoundError:
        return -1, "git wurde nicht gefunden"
    except subprocess.TimeoutExpired:
        return -2, f"git hat nach {zeitlimit} Sekunden nicht geantwortet"
    except Exception as fehler:
        return -3, f"{type(fehler).__name__}: {fehler}"


def ist_git_ordner() -> bool:
    code, _ = _git("rev-parse", "--git-dir", zeitlimit=10)
    return code == 0


def _kurzstand() -> dict:
    """Aktueller Stand ohne Netzzugriff."""
    _, beschreibung = _git("log", "-1", "--format=%h %cd", "--date=format:%d.%m.%Y",
                           zeitlimit=10)
    _, zweig = _git("rev-parse", "--abbrev-ref", "HEAD", zeitlimit=10)
    return {"version": beschreibung or "unbekannt", "zweig": zweig or "?"}


def pruefen(mit_netz: bool = True) -> dict:
    """Prüft, ob im Repository neuere Fassungen liegen.

    Rückgabe (immer alle Felder, damit die Oberfläche nichts abfangen muss):
        moeglich   — kann überhaupt aktualisiert werden?
        anzahl     — wie viele neue Änderungen liegen bereit
        zustand    — 'aktuell' | 'verfuegbar' | 'unbekannt' | 'nicht_moeglich'
        meldung    — ein Satz für den Benutzer
    """
    global _stand, _stand_zeit

    if not ist_git_ordner():
        return {"moeglich": False, "anzahl": 0, "zustand": "nicht_moeglich",
                "meldung": "Dieser Ordner ist keine Git-Arbeitskopie.",
                "hinweis": "Aktualisieren geht nur, wenn das Programm mit „git clone“ "
                           "geholt wurde.", **_kurzstand()}

    code, ausgabe = _git("remote", "get-url", "origin", zeitlimit=10)
    if code != 0:
        return {"moeglich": False, "anzahl": 0, "zustand": "nicht_moeglich",
                "meldung": "Es ist kein Repository hinterlegt.",
                "hinweis": "Ohne Fernverweis („origin“) gibt es nichts zu holen.",
                **_kurzstand()}

    if not mit_netz:
        with _sperre:
            if _stand:
                return dict(_stand)

    code, ausgabe = _git("fetch", "--quiet", "origin")
    if code != 0:
        antwort = {"moeglich": True, "anzahl": 0, "zustand": "unbekannt",
                   "meldung": "Der Stand ließ sich nicht abfragen.",
                   "hinweis": config.entschaerfe(ausgabe[:200]) or
                              "Vermutlich keine Internetverbindung.",
                   **_kurzstand()}
        with _sperre:
            _stand, _stand_zeit = antwort, time.monotonic()
        return antwort

    # Wie viele Änderungen liegen vor uns? `@{u}` ist der zugehörige Zweig im Repository.
    code, ausgabe = _git("rev-list", "--count", "HEAD..@{u}", zeitlimit=15)
    if code != 0:
        # Kein zugehöriger Zweig eingerichtet — den Hauptzweig direkt versuchen.
        code, ausgabe = _git("rev-list", "--count", "HEAD..origin/main", zeitlimit=15)
    try:
        anzahl = int((ausgabe or "0").strip().splitlines()[0])
    except (ValueError, IndexError):
        anzahl = 0

    antwort = {
        "moeglich": True,
        "anzahl": anzahl,
        "zustand": "verfuegbar" if anzahl > 0 else "aktuell",
        "meldung": (f"{anzahl} Aktualisierung{'en' if anzahl != 1 else ''} verfügbar."
                    if anzahl else "Das Programm ist auf dem neuesten Stand."),
        "hinweis": "",
        **_kurzstand(),
    }
    with _sperre:
        _stand, _stand_zeit = antwort, time.monotonic()
    return antwort


def _saubere_arbeitskopie() -> tuple[bool, str]:
    """Gibt es lokale Änderungen, die ein Vorspulen verhindern würden?"""
    code, ausgabe = _git("status", "--porcelain", "--untracked-files=no", zeitlimit=15)
    if code != 0:
        return False, "Der Zustand der Arbeitskopie ließ sich nicht prüfen."
    if ausgabe.strip():
        geaendert = [z[3:] for z in ausgabe.splitlines()[:5]]
        return False, ("Es gibt lokale Änderungen: " + ", ".join(geaendert) +
                       ". Sie würden beim Aktualisieren im Weg stehen. Wenn diese "
                       "Änderungen nicht gebraucht werden, im Projektordner einmal "
                       "„git checkout -- .“ ausführen; danach klappt das Update. "
                       "Die .env und die fertigen Videos sind davon nicht betroffen.")
    return True, ""


def aktualisieren(neustart: bool = True) -> dict:
    """Holt den neuen Stand und startet das Programm neu.

    Wirft einen erklärten Fehler, wenn etwas im Weg steht — der Aufrufer reicht die
    Meldung unverändert an die Oberfläche weiter.
    """
    from . import pipeline          # spät geladen, sonst gäbe es einen Ringschluss

    laufend = pipeline.laeuft_gerade()
    if laufend:
        raise errors.EingabeFehler(
            "Es läuft gerade ein Auftrag.",
            "Ein Neustart mitten in der Videoerzeugung würde Guthaben verbrennen. "
            "Bitte warten oder abbrechen.", ursprung=QUELLE)

    if not ist_git_ordner():
        raise errors.KonfigurationsFehler(
            "Dieser Ordner ist keine Git-Arbeitskopie.",
            "Aktualisieren geht nur, wenn das Programm mit „git clone“ geholt wurde.",
            ursprung=QUELLE)

    sauber, grund = _saubere_arbeitskopie()
    if not sauber:
        raise errors.KonfigurationsFehler(
            "Die Aktualisierung wurde nicht durchgeführt.", grund, ursprung=QUELLE)

    _update_laeuft.set()
    try:
        return _aktualisieren(neustart)
    finally:
        _update_laeuft.clear()


def _aktualisieren(neustart: bool) -> dict:
    from . import pipeline

    logbook.info(QUELLE, "Neuer Stand wird geholt …")
    # Ausschließlich vorspulen: nie zusammenführen, nie etwas überschreiben.
    code, ausgabe = _git("pull", "--ff-only", "--quiet")
    if code != 0 and "tracking information" in ausgabe.lower():
        # Der Zweig hat keinen zugehörigen Zweig im Repository. Das kommt vor, wenn die
        # Arbeitskopie nicht durch `git clone` entstanden ist. Dann wird der Hauptzweig
        # ausdrücklich benannt — vorspulen bleibt es trotzdem.
        code, ausgabe = _git("pull", "--ff-only", "--quiet", "origin", "main")
    if code != 0:
        raise errors.AnbieterFehler(
            "Der neue Stand ließ sich nicht holen.",
            config.entschaerfe(ausgabe[:300]) or "Keine nähere Angabe von git.",
            ursprung=QUELLE)

    stand = _kurzstand()
    logbook.erfolg(QUELLE, f"Aktualisiert auf {stand['version']}.")

    # Neue oder geänderte Pakete nachziehen. Schlägt das fehl, ist das kein Grund zum
    # Abbruch — meist ändert sich an den Abhängigkeiten gar nichts.
    logbook.info(QUELLE, "Abhängigkeiten werden geprüft …")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                        "--disable-pip-version-check", "-r", "requirements.txt"],
                       cwd=str(config.BASE_DIR), capture_output=True, timeout=300)
    except Exception as fehler:
        logbook.warnung(QUELLE, f"Pakete nicht geprüft ({type(fehler).__name__}) — "
                                "das Programm startet trotzdem neu.")

    # Zusatzpakete getrennt und ohne Folgen bei Misserfolg: Playwright macht die
    # Webseiten-Aufnahme besser (Cookie-Banner, nachladende Bilder), ist aber nicht
    # nötig — ohne es fotografiert Edge direkt. Stünde es in requirements.txt, könnte
    # ein Rechner, auf dem es sich nicht installieren lässt, gar nichts mehr nachziehen.
    optional = config.BASE_DIR / "requirements-optional.txt"
    if optional.exists():
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                            "--disable-pip-version-check", "-r", str(optional)],
                           cwd=str(config.BASE_DIR), capture_output=True, timeout=600)
        except Exception:
            pass

    if not neustart:
        return {"ok": True, "version": stand["version"], "neustart": False,
                "meldung": f"Aktualisiert auf {stand['version']}."}

    # Noch einmal nachsehen: Paketinstallation kann Minuten dauern. Hat in der Zeit doch
    # ein Auftrag begonnen oder wartet einer, wird der Neustart aufgeschoben — die
    # Ablaufsteuerung holt ihn nach, sobald alles fertig ist.
    if pipeline.laeuft_gerade() or pipeline.warteschlange():
        _neustart_offen["ja"] = True
        logbook.warnung(QUELLE, "Update geholt. Der Neustart folgt, sobald der laufende "
                                "Auftrag fertig ist.")
        return {"ok": True, "version": stand["version"], "neustart": False,
                "meldung": f"Aktualisiert auf {stand['version']}. Der Neustart folgt, "
                           "sobald der laufende Auftrag fertig ist."}

    logbook.info(QUELLE, "Das Programm startet in wenigen Sekunden neu.")
    neu_starten()
    return {"ok": True, "version": stand["version"], "neustart": True,
            "meldung": f"Aktualisiert auf {stand['version']}. Das Programm startet neu."}


def neu_starten(verzoegerung: float = 1.5) -> None:
    """Startet das Programm neu.

    Ein Prozess kann sich nicht selbst wiederbeleben. Es wird deshalb ein losgelöster
    Helfer gestartet, der kurz wartet, bis dieser Prozess beendet ist, und dann das
    Programm erneut aufruft. Der Helfer hängt an keinem Fenster und keiner Konsole —
    sonst würde er mit uns zusammen sterben.
    """
    startbefehl = [sys.executable, str(config.BASE_DIR / "run.py")]
    # Die Aufrufparameter des laufenden Programms übernehmen (etwa --browser).
    startbefehl += [a for a in sys.argv[1:] if a not in ("--pruefen",)]

    # MPW_NEUSTART sagt dem neuen Prozess, dass er nicht auf den alten achten soll —
    # der ist gerade am Beenden und antwortet womöglich noch einen Augenblick.
    helfer = (
        "import os, subprocess, sys, time\n"
        f"time.sleep({max(0.5, verzoegerung)})\n"
        f"subprocess.Popen({startbefehl!r}, cwd={str(config.BASE_DIR)!r}, "
        "env={**os.environ, 'MPW_NEUSTART': '1'})\n"
    )

    losgeloest = 0
    if sys.platform == "win32":
        losgeloest = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008) |
                      getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))

    try:
        subprocess.Popen([sys.executable, "-c", helfer],
                         cwd=str(config.BASE_DIR), creationflags=losgeloest,
                         close_fds=True)
    except Exception as fehler:
        raise errors.VerarbeitungsFehler(
            "Der Neustart ließ sich nicht anstoßen.",
            f"Bitte das Programm von Hand neu starten. ({type(fehler).__name__})",
            ursprung=QUELLE) from fehler

    def beenden():
        time.sleep(max(0.3, verzoegerung - 0.8))
        logbook.beenden()
        # Hart beenden: ein sauberes Herunterfahren würde am wartenden Ereignisstrom
        # und am Fenster hängen bleiben.
        os._exit(0)

    threading.Thread(target=beenden, name="neustart", daemon=True).start()
