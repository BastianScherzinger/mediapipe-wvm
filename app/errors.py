"""
errors.py — Fehler, die ein Mensch versteht.

Der Benutzer dieses Werkzeugs ist kein Entwickler. Ein Traceback hilft ihm nicht; ein Satz,
der sagt *was* passiert ist und *was jetzt zu tun ist*, hilft ihm. Jede Ausnahme in diesem
Programm trägt daher beides mit sich und wird über `als_dict()` unverändert an die
Oberfläche gereicht.

`aus_httpfehler()` übersetzt die tatsächlich beobachteten Antwortcodes der Higgsfield-API
(siehe docs/API_BEFUND.md) in genau diese Sätze.
"""
from __future__ import annotations

from . import config


class StudioFehler(Exception):
    """Basis aller erwarteten Fehler. 'Erwartet' heißt: das Programm weiß, was passiert ist,
    und kann es erklären. Unerwartete Fehler werden erst an der Außengrenze eingefangen."""

    #: Kurzform für die Oberfläche (Farbgebung, Filter)
    art: str = "fehler"
    #: Ist eine Wiederholung sinnvoll? Steuert die automatische Wiederholung.
    wiederholbar: bool = False

    def __init__(self, meldung: str, hinweis: str = "", *, ursprung: str = "",
                 details: dict | None = None):
        # Entschärfen ist Pflicht: Fremdbibliotheken hängen Zugangsdaten gern an ihre Texte.
        self.meldung = config.entschaerfe(meldung)
        self.hinweis = config.entschaerfe(hinweis)
        self.ursprung = ursprung
        self.details = details or {}
        super().__init__(self.meldung)

    def als_dict(self) -> dict:
        return {"fehler": True, "art": self.art, "meldung": self.meldung,
                "hinweis": self.hinweis, "ursprung": self.ursprung,
                "wiederholbar": self.wiederholbar, "details": self.details}

    def __str__(self) -> str:
        return f"{self.meldung} {self.hinweis}".strip()


# ── Konfiguration und Zugänge ────────────────────────────────────────────────

class KonfigurationsFehler(StudioFehler):
    art = "konfiguration"


class ZugangFehler(StudioFehler):
    """Schlüssel fehlt, ist falsch oder wurde abgelehnt."""
    art = "zugang"


class GuthabenFehler(StudioFehler):
    """Zugang gültig, aber kein Kontingent mehr. Kein Wiederholen — das hilft nicht."""
    art = "guthaben"


# ── Ablauf ───────────────────────────────────────────────────────────────────

class NetzFehler(StudioFehler):
    """Verbindung gestört. Vorübergehend, daher wiederholbar."""
    art = "netz"
    wiederholbar = True


class ZeitFehler(StudioFehler):
    """Der Gegenpart hat zu lange gebraucht."""
    art = "zeit"
    wiederholbar = True


class AnbieterFehler(StudioFehler):
    """Der Dienst meldet einen Fehler in unserem Auftrag (falsches Modell, ungültiger Wert)."""
    art = "anbieter"


class UnklarFehler(StudioFehler):
    """Ein Auftrag ist abgeschickt, aber die Antwort kam nicht an — ob der Dienst ihn
    angenommen und abgerechnet hat, ist unbekannt.

    **Nie wiederholen.** Genau hier entstünde sonst ein doppelt bezahlter Auftrag: Die
    Antwort kommt nach 90 Sekunden oder als 502 vom Gateway, obwohl der Dienst längst
    rechnet. Die Ablaufsteuerung beendet den Lauf, statt Szene für Szene weitere
    möglicherweise bezahlte Aufträge ins Leere zu schicken.
    """
    art = "unklar"


class InhaltFehler(StudioFehler):
    """Der Auftrag wurde inhaltlich abgelehnt (Moderation). Wiederholen ist zwecklos,
    der Prompt muss geändert werden."""
    art = "inhalt"


class AbbruchFehler(StudioFehler):
    """Der Benutzer hat abgebrochen. Kein echter Fehler, aber er beendet den Ablauf."""
    art = "abbruch"


class EingabeFehler(StudioFehler):
    """Was aus der Oberfläche kam, ergibt keinen gültigen Auftrag."""
    art = "eingabe"


class VerarbeitungsFehler(StudioFehler):
    """ffmpeg oder eine andere lokale Verarbeitung ist gescheitert."""
    art = "verarbeitung"


# ── Übersetzung von HTTP-Antworten ───────────────────────────────────────────

def aus_httpfehler(code: int, rumpf: str, *, ursprung: str = "Higgsfield") -> StudioFehler:
    """Wandelt eine abschlägige HTTP-Antwort in einen erklärten Fehler.
    Die Zuordnung stammt aus echten Antworten der Higgsfield-API, nicht aus Vermutungen."""
    text = (rumpf or "")[:600]
    klein = text.lower()

    if code == 403 and "not_enough_credits" in klein:
        return GuthabenFehler(
            "Higgsfield hat kein Guthaben mehr.",
            "Wichtig: Ein Web-Abo (Soul/Plus) füllt den API-Topf nicht — beides sind "
            "getrennte Guthaben. Unter cloud.higgsfield.ai API-Credits aufladen.",
            ursprung=ursprung, details={"code": code})

    if code in (401, 403):
        return ZugangFehler(
            f"Higgsfield hat den Zugang abgelehnt (Code {code}).",
            "HIGGSFIELD_API_KEY in der .env prüfen — erwartet wird das Format ID:SECRET.",
            ursprung=ursprung, details={"code": code})

    if code == 404 and "model_not_found" in klein:
        return AnbieterFehler(
            "Dieses Modell gibt es bei Higgsfield nicht (mehr).",
            "Ein anderes Modell wählen. Die geprüfte Liste steht in docs/API_BEFUND.md.",
            ursprung=ursprung, details={"code": code})

    if code == 423 or "model_blocked" in klein:
        return ZugangFehler(
            "Dieses Modell ist für den verwendeten Zugang gesperrt.",
            "Ein anderes Modell wählen oder den Zugang bei Higgsfield freischalten lassen.",
            ursprung=ursprung, details={"code": code})

    if code in (400, 422):
        # Der Rumpf nennt bei diesen Codes das konkrete Feld — das ist die nützlichste
        # Information, die wir haben, also wird sie durchgereicht statt verschluckt.
        return AnbieterFehler(
            "Higgsfield hat den Auftrag als ungültig zurückgewiesen.",
            f"Rückmeldung des Dienstes: {text}",
            ursprung=ursprung, details={"code": code})

    if code == 429:
        return NetzFehler(
            "Zu viele Anfragen in kurzer Zeit.",
            "Das Programm wartet und versucht es erneut.",
            ursprung=ursprung, details={"code": code})

    if 500 <= code < 600:
        return NetzFehler(
            f"Higgsfield hat einen Serverfehler gemeldet (Code {code}).",
            "Meist vorübergehend — das Programm versucht es erneut.",
            ursprung=ursprung, details={"code": code})

    return AnbieterFehler(
        f"Unerwartete Antwort von Higgsfield (Code {code}).",
        text or "Keine nähere Angabe im Antworttext.",
        ursprung=ursprung, details={"code": code})


def aus_ausnahme(fehler: BaseException, *, ursprung: str = "") -> StudioFehler:
    """Letzte Instanz: irgendeine Ausnahme wird zu einem erklärten Fehler. Wird an der
    Außengrenze benutzt, damit die Oberfläche nie einen nackten Traceback zu sehen
    bekommt — aber die Fehlerart trotzdem stimmt."""
    if isinstance(fehler, StudioFehler):
        return fehler

    name = type(fehler).__name__
    text = config.entschaerfe(str(fehler))[:400]

    if isinstance(fehler, TimeoutError) or "timeout" in name.lower():
        return ZeitFehler("Zeitüberschreitung bei einer Netzanfrage.",
                          "Internetverbindung prüfen. Das Programm versucht es erneut.",
                          ursprung=ursprung)
    if isinstance(fehler, (ConnectionError, OSError)) and "conn" in name.lower():
        return NetzFehler("Keine Verbindung zum Dienst.",
                          "Internetverbindung prüfen.", ursprung=ursprung)
    if isinstance(fehler, FileNotFoundError):
        return VerarbeitungsFehler(f"Datei nicht gefunden: {text}",
                                   "Wurde die Datei verschoben oder gelöscht?",
                                   ursprung=ursprung)
    if isinstance(fehler, PermissionError):
        return VerarbeitungsFehler("Zugriff auf eine Datei verweigert.",
                                   "Läuft die Datei gerade in einem anderen Programm?",
                                   ursprung=ursprung)

    return StudioFehler(f"Unerwarteter Fehler: {name}",
                        text or "Näheres steht im Logbuch.", ursprung=ursprung)
