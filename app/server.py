"""
server.py — der lokale Anwendungsserver.

Hört ausschließlich auf 127.0.0.1. Das ist keine Nachlässigkeit, sondern Absicht: das
Werkzeug ist eine Einzelplatzanwendung mit Zugriff auf Zugangsdaten und das Dateisystem
und hat im Netzwerk nichts verloren.

Alle Antworten folgen derselben Form:
    Erfolg   {"ok": true, ...}
    Fehler   {"ok": false, "fehler": true, "meldung": ..., "hinweis": ...}
Die Oberfläche muss deshalb nie einen Ausnahmetext auswerten — sie zeigt `meldung` und
`hinweis` einfach an.
"""
from __future__ import annotations

import mimetypes
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from . import (config, errors, higgsfield, jobstore, library, llm, logbook, media,
               pipeline, topics)

QUELLE = "Server"


def anwendung_bauen() -> Flask:
    app = Flask(__name__,
                static_folder=str(config.STATIC_DIR),
                template_folder=str(config.TEMPLATE_DIR),
                static_url_path="/static")
    app.config["JSON_AS_ASCII"] = False
    # Videos können groß werden; die Oberfläche schickt trotzdem nur kleine Anfragen.
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

    # ── Antworthilfen ────────────────────────────────────────────────────────

    def gut(nutzlast: dict | None = None, code: int = 200):
        return jsonify({"ok": True, **(nutzlast or {})}), code

    def schlecht(fehler: errors.StudioFehler, code: int = 400):
        return jsonify({"ok": False, **fehler.als_dict()}), code

    @app.errorhandler(errors.StudioFehler)
    def studiofehler_behandeln(fehler: errors.StudioFehler):
        # Eingabefehler sind Bedienfehler (400), alles andere ein Betriebsproblem (502).
        code = 400 if isinstance(fehler, errors.EingabeFehler) else 502
        return schlecht(fehler, code)

    @app.errorhandler(404)
    def nicht_gefunden(_e):
        return jsonify({"ok": False, "fehler": True,
                        "meldung": "Diese Adresse gibt es nicht.",
                        "hinweis": ""}), 404

    @app.errorhandler(Exception)
    def unerwartet(fehler: Exception):
        """Letzte Auffanglinie: auch ein Programmierfehler erreicht die Oberfläche als
        verständliche Meldung — und wird protokolliert, damit er auffindbar bleibt."""
        uebersetzt = errors.aus_ausnahme(fehler, ursprung=QUELLE)
        logbook.fehler(QUELLE, f"{request.path}: {uebersetzt.meldung}")
        return schlecht(uebersetzt, 500)

    @app.after_request
    def kopfzeilen(antwort: Response):
        # Die Oberfläche soll immer den aktuellen Stand sehen, nie einen alten aus dem
        # Zwischenspeicher. Für Medien gilt das nicht — die dürfen zwischengespeichert
        # werden, sonst ruckelt das Abspielen.
        if not request.path.startswith("/medien/"):
            antwort.headers["Cache-Control"] = "no-store"
        antwort.headers["X-Content-Type-Options"] = "nosniff"
        antwort.headers["Referrer-Policy"] = "no-referrer"
        return antwort

    # ── Oberfläche ───────────────────────────────────────────────────────────

    @app.get("/")
    def startseite():
        return send_from_directory(config.TEMPLATE_DIR, "index.html")

    # ── Grunddaten ───────────────────────────────────────────────────────────

    @app.get("/api/start")
    def startdaten():
        """Alles, was die Oberfläche einmalig beim Laden braucht."""
        return gut({
            "app": {"name": config.APP_NAME, "version": config.APP_VERSION},
            "diagnose": config.diagnose_kurz(),
            "katalog": topics.katalog(),
            "videomodelle": higgsfield.VIDEOMODELLE,
            "bildmodelle": higgsfield.BILDMODELLE,
            "formate": media.formatliste(),
            "standardformate": list(media.STANDARDFORMATE),
            "bloecke": [{"kennung": b, "name": jobstore.BLOCKNAMEN[b]}
                        for b in jobstore.BLOECKE],
            "grenzen": {"max_szenen": config.MAX_SCENES,
                        "max_briefing": config.MAX_BRIEFING_CHARS},
            "laufender_auftrag": pipeline.laeuft_gerade(),
        })

    @app.get("/api/zustand")
    def zustand():
        """Kurzer Statusbericht — die Oberfläche holt ihn beim Verbinden und nach
        einer Unterbrechung, um sich wieder zu fangen."""
        laufend = jobstore.laufender()
        return gut({
            "laufender_auftrag": pipeline.laeuft_gerade(),
            "auftrag": laufend.als_dict() if laufend else None,
            "letzte": [a.als_dict() for a in jobstore.liste(grenze=8)],
        })

    @app.post("/api/selbsttest")
    def selbsttest():
        """Prüft alle Bausteine — ohne Guthaben zu verbrauchen."""
        ergebnis = {
            "system": config.diagnose_kurz(),
            "higgsfield": higgsfield.client.selbsttest(),
            "ffmpeg": media.selbsttest(),
            "sprachmodelle": llm.verfuegbare_wege(),
        }
        logbook.info(QUELLE, "Selbsttest durchgeführt.")
        logbook.ereignis("diagnose", ergebnis)
        return gut({"ergebnis": ergebnis})

    @app.post("/api/guthaben-pruefen")
    def guthaben_pruefen():
        """Ausdrückliche Guthabenprüfung mit einem echten, sofort stornierten Auftrag.
        Nur auf Knopfdruck — sie kann im schlimmsten Fall ein Bild kosten."""
        ergebnis = higgsfield.client.guthaben_wirklich_pruefen()
        logbook.info(QUELLE, f"Guthabenprüfung: {ergebnis.get('meldung', '')}")
        return gut({"ergebnis": ergebnis})

    @app.post("/api/wege-zuruecksetzen")
    def wege_zuruecksetzen():
        """Hebt die Sperren gescheiterter Sprachmodell-Wege auf."""
        llm.zuruecksetzen()
        logbook.info(QUELLE, "Sperren der Sprachmodell-Wege aufgehoben.")
        return gut({"wege": llm.verfuegbare_wege()})

    # ── Briefing zusammenbauen ───────────────────────────────────────────────

    @app.post("/api/briefing")
    def briefing_vorschau():
        """Baut aus den Formulardaten den Briefingtext — die Oberfläche zeigt ihn an,
        bevor etwas gestartet wird. Kein Rätselraten, was gleich an Claude geht."""
        daten = request.get_json(silent=True) or {}
        text = topics.briefing_bauen(
            str(daten.get("thema") or ""),
            str(daten.get("betreff") or ""),
            list(daten.get("argumente") or []),
            {"zielgruppe": daten.get("zielgruppe"), "botschaft": daten.get("botschaft")})
        return gut({"briefing": text})

    # ── Aufträge ─────────────────────────────────────────────────────────────

    @app.post("/api/auftrag")
    def auftrag_starten():
        daten = request.get_json(silent=True) or {}
        auftrag = pipeline.starten(daten)
        return gut({"auftrag": auftrag.als_dict()}, 202)

    @app.get("/api/auftrag/<kennung>")
    def auftrag_holen(kennung: str):
        auftrag = jobstore.holen(kennung)
        if auftrag is None:
            raise errors.EingabeFehler("Diesen Auftrag gibt es nicht.", ursprung=QUELLE)
        return gut({"auftrag": auftrag.als_dict()})

    @app.post("/api/auftrag/<kennung>/abbrechen")
    def auftrag_abbrechen(kennung: str):
        erfolgreich = pipeline.abbrechen(kennung)
        if not erfolgreich:
            raise errors.EingabeFehler(
                "Dieser Auftrag läuft nicht mehr.",
                "Vermutlich ist er schon fertig oder wurde bereits abgebrochen.",
                ursprung=QUELLE)
        return gut({"abgebrochen": kennung})

    @app.get("/api/auftraege")
    def auftraege_liste():
        grenze = request.args.get("grenze", type=int) or 30
        return gut({"auftraege": [a.als_dict() for a in jobstore.liste(grenze)]})

    @app.delete("/api/auftrag/<kennung>")
    def auftrag_loeschen(kennung: str):
        """Entfernt nur den Eintrag, nie die Videodateien."""
        return gut({"geloescht": jobstore.loeschen(kennung)})

    # ── Logbuch und Ereignisstrom ────────────────────────────────────────────

    @app.get("/api/log")
    def log_holen():
        return gut({"zeilen": logbook.verlauf(
            grenze=request.args.get("grenze", type=int) or 200,
            ab_nummer=request.args.get("ab", type=int) or 0,
            ebene=request.args.get("ebene", type=str) or "")})

    @app.get("/api/strom")
    def ereignisstrom():
        """Der einzige dauerhafte Kanal zur Oberfläche: Logzeilen und Blockereignisse."""
        warteschlange = logbook.abonnieren()

        def erzeugen():
            try:
                yield from logbook.strom(warteschlange)
            finally:
                logbook.abbestellen(warteschlange)

        # Kein „Connection“-Header! Der zählt nach PEP 3333 zu den Verbindungs-Headern,
        # die eine WSGI-Anwendung nicht setzen darf — waitress bricht die Anfrage sonst
        # mit einem AssertionError ab, und damit fiele der gesamte Ereignisstrom aus.
        # Die Verbindung offen zu halten ist ohnehin Sache des Servers, nicht unsere.
        return Response(erzeugen(), mimetype="text/event-stream", headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",      # falls je ein Vorschaltserver dazwischenkommt
        })

    # ── Bibliothek ───────────────────────────────────────────────────────────

    @app.get("/api/bibliothek")
    def bibliothek():
        return gut(library.uebersicht())

    @app.post("/api/bibliothek/format")
    def bibliothek_format():
        daten = request.get_json(silent=True) or {}
        ergebnis = library.format_nachziehen(str(daten.get("ordner") or ""),
                                             str(daten.get("format") or ""))
        return gut(ergebnis)

    @app.post("/api/bibliothek/alle-formate")
    def bibliothek_alle_formate():
        daten = request.get_json(silent=True) or {}
        return gut(library.alle_formate_nachziehen(str(daten.get("ordner") or "")))

    @app.post("/api/bibliothek/umbenennen")
    def bibliothek_umbenennen():
        daten = request.get_json(silent=True) or {}
        return gut(library.video_umbenennen(str(daten.get("ordner") or ""),
                                            str(daten.get("titel") or "")))

    @app.post("/api/bibliothek/loeschen")
    def bibliothek_loeschen():
        """Löscht ein Video mitsamt Ordner. Die Rückfrage stellt die Oberfläche;
        hier muss die Bestätigung ausdrücklich mitgeschickt werden."""
        daten = request.get_json(silent=True) or {}
        if daten.get("bestaetigt") is not True:
            raise errors.EingabeFehler(
                "Das Löschen wurde nicht bestätigt.",
                "Sicherheitsabfrage — es wurde nichts gelöscht.", ursprung=QUELLE)
        return gut(library.video_loeschen(str(daten.get("ordner") or "")))

    @app.post("/api/bibliothek/explorer")
    def bibliothek_explorer():
        daten = request.get_json(silent=True) or {}
        return gut(library.im_explorer_zeigen(str(daten.get("ordner") or "")))

    # ── Medien ausliefern ────────────────────────────────────────────────────

    @app.get("/medien/<path:datei>")
    def medien(datei: str):
        """Liefert Videos und Bilder aus dem Ausgabeordner.

        `conditional=True` schaltet die Unterstützung für Teilbereiche ein — ohne sie
        könnte man im Abspieler nicht vorspulen, weil der Browser dafür Ausschnitte der
        Datei anfordert.
        """
        pfad = library.sicherer_pfad(datei)          # prüft den Ausbruchversuch
        if not pfad.is_file():
            raise errors.EingabeFehler("Diese Datei gibt es nicht.", ursprung=QUELLE)

        typ, _ = mimetypes.guess_type(pfad.name)
        return send_from_directory(
            pfad.parent, pfad.name, mimetype=typ or "application/octet-stream",
            conditional=True, max_age=3600)

    @app.get("/api/herunterladen/<path:datei>")
    def herunterladen(datei: str):
        """Wie /medien, nur als Download statt zum Abspielen im Fenster."""
        pfad = library.sicherer_pfad(datei)
        if not pfad.is_file():
            raise errors.EingabeFehler("Diese Datei gibt es nicht.", ursprung=QUELLE)
        return send_from_directory(pfad.parent, pfad.name, as_attachment=True)

    # ── Betrieb ──────────────────────────────────────────────────────────────

    @app.get("/api/lebt")
    def lebt():
        """Wird vom Starter abgefragt, um zu erkennen, wann der Server bereit ist."""
        return gut({"zeit": time.time(), "version": config.APP_VERSION})

    return app


def starten(host: str = "", port: int = 0, entwicklung: bool = False) -> None:
    """Startet den Server. Im Normalbetrieb über `waitress` — der Entwicklungsserver
    von Flask ist für Dauerbetrieb nicht gedacht und meldet das auch selbst."""
    app = anwendung_bauen()
    host = host or config.HOST
    port = port or config.PORT

    logbook.erfolg(QUELLE, f"{config.APP_NAME} {config.APP_VERSION} läuft auf "
                           f"http://{host}:{port}")
    if entwicklung:
        app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
        return
    try:
        from waitress import serve
        # Mehrere Fäden: der Ereignisstrom hält einen dauerhaft besetzt, und die
        # Oberfläche soll trotzdem antworten.
        serve(app, host=host, port=port, threads=12, channel_timeout=600,
              ident=config.APP_NAME)
    except ImportError:
        logbook.warnung(QUELLE, "waitress fehlt — es läuft der einfache Server.")
        app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
