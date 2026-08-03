"""
run.py — Start des Programms.

Ablauf:
  1. Voraussetzungen prüfen und verständlich melden, was fehlt
  2. freien Port suchen (der eingestellte kann belegt sein)
  3. Server im Hintergrund starten
  4. eigenes Desktop-Fenster öffnen — und wenn das nicht geht, den Browser

Das Programm startet auch dann, wenn etwas fehlt. Ein Werkzeug, das mit einer
Fehlermeldung im Terminal abbricht, ist für den Kunden wertlos; eines, das startet und
im Fenster erklärt, was zu tun ist, hilft ihm weiter.

Aufrufe:
    python run.py                 Desktop-Fenster (Vorgabe)
    python run.py --browser       im Standardbrowser öffnen
    python run.py --kein-fenster  nur Server, nichts öffnen
    python run.py --port 8123     anderer Port
    python run.py --pruefen       nur die Voraussetzungen prüfen und beenden
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser

from app import config, logbook

BALKEN = "═" * 68


def freier_port(wunsch: int, versuche: int = 20) -> int:
    """Erster freier Port ab dem Wunschport. Verhindert den häufigsten Startfehler
    überhaupt: „Port bereits belegt“, weil noch eine alte Sitzung läuft."""
    for versatz in range(versuche):
        port = wunsch + versatz
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as pruefer:
            pruefer.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                pruefer.bind((config.HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"Zwischen {wunsch} und {wunsch + versuche} ist kein Port frei.")


def voraussetzungen_melden() -> bool:
    """Zeigt den Startbericht im Terminal. Gibt zurück, ob alles Wesentliche steht."""
    befunde = config.diagnose()
    print(BALKEN)
    print(f"  {config.APP_NAME} {config.APP_VERSION}")
    print(BALKEN)

    alles_gut = True
    for befund in befunde:
        zeichen = {"ok": "[ok]", "warnung": "[!]", "fehler": "[X]"}.get(befund.zustand, "[?]")
        print(f"  {zeichen:<5} {befund.name:<16} {befund.meldung}")
        if befund.hinweis:
            print(f"        {'':<16} → {befund.hinweis}")
        if befund.zustand == "fehler":
            alles_gut = False

    print(BALKEN)
    if not alles_gut:
        print("  Es fehlt etwas (siehe oben). Das Programm startet trotzdem und")
        print("  zeigt die offenen Punkte im Fenster an.")
        print(BALKEN)
    return alles_gut


def fenster_oeffnen(adresse: str) -> bool:
    """Öffnet das eigene Desktop-Fenster. Gibt zurück, ob es geklappt hat.

    Diese Funktion kehrt erst zurück, wenn das Fenster geschlossen wird — pywebview
    verlangt, dass die Fensterschleife im Hauptfaden läuft.
    """
    try:
        import webview
    except ImportError:
        logbook.warnung("Start", "pywebview fehlt — es wird der Browser geöffnet.")
        return False

    try:
        webview.create_window(
            f"{config.APP_NAME} — KI-Video-Studio",
            adresse,
            width=1560, height=980, min_size=(1180, 760),
            background_color="#0A0B0D",       # kein weißes Aufblitzen beim Start
            text_select=True,
        )
        webview.start()
        return True
    except Exception as fehler:
        logbook.warnung("Start", f"Desktop-Fenster nicht möglich ({type(fehler).__name__}) "
                                 "— es wird der Browser geöffnet.")
        return False


def main() -> int:
    zerleger = argparse.ArgumentParser(description=f"{config.APP_NAME} starten")
    zerleger.add_argument("--browser", action="store_true",
                          help="im Standardbrowser öffnen statt im eigenen Fenster")
    zerleger.add_argument("--kein-fenster", action="store_true",
                          help="nur den Server starten, nichts öffnen")
    zerleger.add_argument("--port", type=int, default=0, help="Port festlegen")
    zerleger.add_argument("--pruefen", action="store_true",
                          help="nur die Voraussetzungen prüfen")
    argumente = zerleger.parse_args()

    if argumente.pruefen:
        return 0 if voraussetzungen_melden() else 1

    voraussetzungen_melden()

    try:
        port = freier_port(argumente.port or config.PORT)
    except RuntimeError as fehler:
        print(f"  [X] {fehler}")
        return 1
    adresse = f"http://{config.HOST}:{port}"

    from app import server
    dienst = threading.Thread(target=server.starten, kwargs={"port": port},
                              name="server", daemon=True)
    dienst.start()

    # Warten, bis der Server wirklich antwortet — sonst zeigt das Fenster beim Öffnen
    # eine Fehlerseite, obwohl gleich darauf alles bereit wäre.
    for _ in range(100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prüfer:
            prüfer.settimeout(0.2)
            if prüfer.connect_ex((config.HOST, port)) == 0:
                break
        time.sleep(0.1)

    print(f"  Bereit: {adresse}")
    print(BALKEN + "\n")

    if argumente.kein_fenster:
        try:
            while dienst.is_alive():
                dienst.join(timeout=1)
        except KeyboardInterrupt:
            print("\n  Beendet.")
        return 0

    if argumente.browser or not config.DESKTOP_WINDOW:
        webbrowser.open(adresse)
    elif not fenster_oeffnen(adresse):
        webbrowser.open(adresse)
    else:
        # Das Fenster wurde geschlossen — damit endet das Programm.
        logbook.info("Start", "Fenster geschlossen, Programm wird beendet.")
        logbook.beenden()
        return 0

    try:
        while dienst.is_alive():
            dienst.join(timeout=1)
    except KeyboardInterrupt:
        print("\n  Beendet.")
    logbook.beenden()
    return 0


if __name__ == "__main__":
    sys.exit(main())
