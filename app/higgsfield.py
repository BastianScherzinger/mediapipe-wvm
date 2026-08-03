"""
higgsfield.py — Client für die Higgsfield-Platform-API.

Baut ausschließlich auf Verhalten, das am 03.08.2026 mit echten Aufrufen belegt wurde
(docs/API_BEFUND.md):

    POST {basis}/{modellpfad}        → {"request_id": ..., "status": "queued"}
    GET  {basis}/requests/{id}/status → {"status": ..., Medien-URLs bei completed}
    POST {basis}/requests/{id}/cancel → 202, nur solange "queued"

Was dieses Modul zusätzlich leistet:
  * **Restzeit** — aus gemessenen Laufzeiten je Modell, nicht geraten. Die Messwerte
    überleben Programmneustarts in data/laufzeiten.json.
  * **Wiederholung** — nur bei vorübergehenden Fehlern (Netz, 5xx, 429) und nur so oft,
    wie die Konfiguration erlaubt. Guthaben- und Inhaltsfehler werden nie wiederholt.
  * **Abbruch** — jeder wartende Aufruf hört auf ein Abbruch-Signal und storniert den
    Auftrag beim Dienst, damit kein Guthaben für ein Ergebnis verbrannt wird, das
    niemand mehr sehen will.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import config, errors, logbook

QUELLE = "Higgsfield"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Endzustände laut API-Befund.
_FERTIG = ("completed",)
_GESCHEITERT = ("failed", "error")
_ABGELEHNT = ("nsfw",)
_ABGEBROCHEN = ("canceled", "cancelled")

_MEDIEN_MUSTER = re.compile(r'https?://[^\s"\'\\<>]+?\.(?:mp4|mov|webm|jpg|jpeg|png|webp)',
                            re.IGNORECASE)

# Vorgabewerte für die Restzeit, bis eigene Messwerte vorliegen (Sekunden).
_ERFAHRUNG_VORGABE = {"bild": 25.0, "video": 150.0}


# ── Laufzeitgedächtnis ───────────────────────────────────────────────────────

class _Laufzeiten:
    """Merkt sich, wie lange ein Modell tatsächlich braucht, und schätzt daraus die
    Restzeit. Gleitender Mittelwert: neue Messungen zählen mehr als alte, ohne dass ein
    einzelner Ausreißer die Schätzung ruiniert."""

    def __init__(self, pfad: Path):
        self._pfad = pfad
        self._sperre = threading.Lock()
        self._werte: dict[str, float] = {}
        try:
            self._werte = json.loads(pfad.read_text(encoding="utf-8"))
        except Exception:
            self._werte = {}

    def schaetzung(self, modell: str, art: str) -> float:
        with self._sperre:
            wert = self._werte.get(modell)
        return float(wert) if wert else _ERFAHRUNG_VORGABE.get(art, 90.0)

    def merken(self, modell: str, sekunden: float) -> None:
        if sekunden <= 0 or sekunden > 3600:
            return
        with self._sperre:
            alt = self._werte.get(modell)
            self._werte[modell] = sekunden if alt is None else alt * 0.7 + sekunden * 0.3
            try:
                tmp = self._pfad.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._werte, indent=2), encoding="utf-8")
                tmp.replace(self._pfad)      # atomar: nie eine halb geschriebene Datei
            except Exception:
                pass


_laufzeiten = _Laufzeiten(config.DATA_DIR / "laufzeiten.json")


# ── Guthabengedächtnis ───────────────────────────────────────────────────────
# Die API hat keinen Endpunkt für den Kontostand, und ein Probeauftrag mit leerem Rumpf
# taugt nicht dafür: die Schemaprüfung läuft VOR der Guthabenprüfung, ein leerer Rumpf
# bekommt also immer 422 — auch bei leerem Konto. Belegt am 03.08.2026: leerer Rumpf → 422,
# derselbe Zugang mit gültigem Rumpf → 403 not_enough_credits.
#
# Deshalb lernt das Programm den Stand aus echten Aufträgen und merkt ihn sich. Das ist
# ehrlicher als eine Schätzung und kostet nichts.

class _Guthabenstand:
    def __init__(self, pfad: Path):
        self._pfad = pfad
        self._sperre = threading.Lock()
        try:
            self._stand: dict = json.loads(pfad.read_text(encoding="utf-8"))
        except Exception:
            self._stand = {}

    def lesen(self) -> dict:
        with self._sperre:
            return dict(self._stand)

    def merken(self, vorhanden: bool, bemerkung: str = "") -> None:
        with self._sperre:
            self._stand = {"guthaben": bool(vorhanden), "zeitpunkt": time.time(),
                           "bemerkung": bemerkung[:200]}
            try:
                tmp = self._pfad.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._stand, indent=2), encoding="utf-8")
                tmp.replace(self._pfad)
            except Exception:
                pass


_guthaben = _Guthabenstand(config.DATA_DIR / "guthabenstand.json")


# ── Ergebnis ─────────────────────────────────────────────────────────────────

@dataclass
class Ergebnis:
    """Ein fertiger Auftrag."""
    request_id: str
    modell: str
    url: str                     # URL des erzeugten Mediums
    dauer: float                 # tatsächliche Laufzeit in Sekunden
    rohantwort: dict

    def als_dict(self) -> dict:
        return {"request_id": self.request_id, "modell": self.modell,
                "url": self.url, "dauer": round(self.dauer, 1)}


# ── Client ───────────────────────────────────────────────────────────────────

class Higgsfield:
    """Zustandsloser Client. Mehrere Aufträge dürfen parallel laufen; der einzige
    gemeinsame Zustand ist das Laufzeitgedächtnis, und das ist abgesichert."""

    def __init__(self, api_key: str | None = None, basis: str | None = None):
        # `None` heißt „nimm die Konfiguration“, `""` heißt ausdrücklich „kein Schlüssel“.
        # Ohne diese Unterscheidung ließe sich kein schlüsselloser Client bauen — und ein
        # Test, der genau das prüfen will, würde unbemerkt echte Aufrufe absetzen.
        self.api_key = (config.HIGGSFIELD_API_KEY if api_key is None else api_key).strip()
        self.basis = (config.HF_BASE if basis is None else basis).rstrip("/")

    # ── Grundlagen ───────────────────────────────────────────────────────────

    @property
    def verfuegbar(self) -> bool:
        """Ist überhaupt ein plausibler Schlüssel hinterlegt? Sagt nichts über Guthaben."""
        return bool(self.api_key) and ":" in self.api_key

    def _kopfzeilen(self, mit_inhaltstyp: bool = True) -> dict:
        """Beide belegten Auth-Varianten gleichzeitig — die API akzeptiert jede für sich,
        und so bleibt der Client von einer einseitigen Änderung unberührt."""
        schluessel_id, _, geheim = self.api_key.partition(":")
        kopf = {
            "Authorization": f"Key {self.api_key}",
            "hf-api-key": schluessel_id,
            "hf-secret": geheim,
            "Accept": "application/json",
            "User-Agent": _UA,
        }
        if mit_inhaltstyp:
            kopf["Content-Type"] = "application/json"
        return kopf

    def _pruefe_schluessel(self) -> None:
        if not self.api_key:
            raise errors.ZugangFehler(
                "Kein Higgsfield-Schlüssel hinterlegt.",
                "HIGGSFIELD_API_KEY in der .env eintragen (Format ID:SECRET).",
                ursprung=QUELLE)
        if ":" not in self.api_key:
            raise errors.ZugangFehler(
                "Der Higgsfield-Schlüssel hat ein unerwartetes Format.",
                "Erwartet wird ID:SECRET, wie unter cloud.higgsfield.ai/api-keys erzeugt.",
                ursprung=QUELLE)

    def _anfrage(self, methode: str, pfad: str, rumpf: dict | None = None,
                 *, zeitlimit: int = 0) -> tuple[int, dict, str]:
        """Eine HTTP-Anfrage. Gibt (Code, geparster Rumpf, Rohtext) zurück und wirft nur
        bei Netzproblemen — Fehlercodes werden vom Aufrufer bewertet, weil deren Bedeutung
        vom Zusammenhang abhängt."""
        url = pfad if pfad.startswith("http") else f"{self.basis}/{pfad.lstrip('/')}"
        grenze = zeitlimit or config.HTTP_TIMEOUT
        try:
            with httpx.Client(timeout=grenze, follow_redirects=True) as klient:
                if methode == "GET":
                    antwort = klient.get(url, headers=self._kopfzeilen(False))
                else:
                    antwort = klient.post(url, headers=self._kopfzeilen(),
                                          json=rumpf if rumpf is not None else {})
        except httpx.TimeoutException as fehler:
            raise errors.ZeitFehler(
                f"Higgsfield hat innerhalb von {grenze} Sekunden nicht geantwortet.",
                "Meist vorübergehend — das Programm versucht es erneut.",
                ursprung=QUELLE, details={"url": pfad}) from fehler
        except httpx.HTTPError as fehler:
            raise errors.NetzFehler(
                "Keine Verbindung zu Higgsfield.",
                "Internetverbindung prüfen.",
                ursprung=QUELLE, details={"grund": type(fehler).__name__}) from fehler

        text = antwort.text or ""
        try:
            daten = antwort.json() if text.strip() else {}
        except (ValueError, json.JSONDecodeError):
            daten = {}
        return antwort.status_code, daten if isinstance(daten, dict) else {"inhalt": daten}, text

    def _mit_wiederholung(self, aufgabe, *, beschreibung: str, abbruch: threading.Event | None = None):
        """Führt `aufgabe` aus und wiederholt sie bei vorübergehenden Fehlern mit wachsender
        Wartezeit. Ein Abbruchwunsch beendet die Schleife sofort."""
        letzter: errors.StudioFehler | None = None
        for versuch in range(config.MAX_RETRIES + 1):
            if abbruch is not None and abbruch.is_set():
                raise errors.AbbruchFehler("Abgebrochen.", ursprung=QUELLE)
            try:
                return aufgabe()
            except errors.StudioFehler as fehler:
                letzter = fehler
                if not fehler.wiederholbar or versuch >= config.MAX_RETRIES:
                    raise
                wartezeit = min(2 ** versuch * 2, 20)
                logbook.warnung(
                    QUELLE,
                    f"{beschreibung} fehlgeschlagen ({fehler.meldung}) — "
                    f"Versuch {versuch + 2} von {config.MAX_RETRIES + 1} in {wartezeit} s.")
                # In kleinen Schritten warten, damit ein Abbruch sofort greift.
                for _ in range(wartezeit * 2):
                    if abbruch is not None and abbruch.is_set():
                        raise errors.AbbruchFehler("Abgebrochen.", ursprung=QUELLE)
                    time.sleep(0.5)
        raise letzter or errors.StudioFehler(f"{beschreibung} fehlgeschlagen.", ursprung=QUELLE)

    # ── Aufträge ─────────────────────────────────────────────────────────────

    def auftrag_erstellen(self, modell: str, rumpf: dict,
                          abbruch: threading.Event | None = None) -> tuple[str, str]:
        """Legt einen Auftrag an. Gibt (request_id, status_url) zurück."""
        self._pruefe_schluessel()

        def einmal():
            code, daten, text = self._anfrage("POST", modell, rumpf)
            if code >= 400:
                # Jeder echte Auftrag ist zugleich die einzige verlässliche Auskunft über
                # den Kontostand — also wird sie festgehalten.
                if code == 403 and "not_enough_credits" in (text or "").lower():
                    _guthaben.merken(False, "Auftrag mit 403 abgelehnt")
                raise errors.aus_httpfehler(code, text, ursprung=QUELLE)
            _guthaben.merken(True, f"Auftrag an {modell} angenommen")
            kennung = daten.get("request_id") or daten.get("id") or daten.get("generation_id")
            if not kennung:
                raise errors.AnbieterFehler(
                    "Higgsfield hat keine Auftragsnummer zurückgegeben.",
                    f"Antwort des Dienstes: {text[:200]}", ursprung=QUELLE)
            return str(kennung), str(daten.get("status_url") or
                                     f"{self.basis}/requests/{kennung}/status")

        kennung, status_url = self._mit_wiederholung(
            einmal, beschreibung=f"Auftrag an {modell}", abbruch=abbruch)
        logbook.info(QUELLE, f"Auftrag angelegt · {modell}", details={"request_id": kennung})
        return kennung, status_url

    def status(self, status_url: str) -> dict:
        """Fragt den Stand ab. Wirft nur bei echten Problemen — ein 404 direkt nach dem
        Anlegen kann vorkommen, weil der Auftrag noch nicht überall bekannt ist."""
        code, daten, text = self._anfrage("GET", status_url, zeitlimit=20)
        if code == 404:
            return {"status": "queued", "_hinweis": "noch nicht bekannt"}
        if code >= 400:
            raise errors.aus_httpfehler(code, text, ursprung=QUELLE)
        return daten

    def abbrechen(self, request_id: str) -> bool:
        """Storniert einen wartenden Auftrag. Schlägt das fehl, ist das kein Beinbruch —
        der Auftrag läuft dann eben zu Ende, und das Ergebnis wird verworfen."""
        try:
            code, _, _ = self._anfrage("POST", f"requests/{request_id}/cancel", {},
                                       zeitlimit=15)
            geschafft = code in (200, 202, 204)
            logbook.info(QUELLE, "Auftrag storniert." if geschafft else
                         f"Stornierung nicht möglich (Code {code}) — Auftrag läuft aus.",
                         details={"request_id": request_id})
            return geschafft
        except Exception:
            return False

    def warten(self, request_id: str, status_url: str, *, modell: str, art: str,
               abbruch: threading.Event | None = None,
               melden=None) -> Ergebnis:
        """Wartet bis zum Ergebnis und meldet unterwegs den Fortschritt.

        `melden(anteil, restsekunden, zustand)` wird bei jeder Abfrage aufgerufen. Der
        Anteil ist eine ehrliche Schätzung aus der bisherigen Laufzeit im Verhältnis zur
        Erfahrung — er wird bei 95 % gedeckelt, damit die Anzeige nicht stehenbleibt und
        auch nicht lügt.
        """
        begonnen = time.monotonic()
        erwartet = _laufzeiten.schaetzung(modell, art)
        letzter_zustand = ""
        fehlversuche = 0

        while True:
            if abbruch is not None and abbruch.is_set():
                self.abbrechen(request_id)
                raise errors.AbbruchFehler("Auftrag vom Benutzer abgebrochen.", ursprung=QUELLE)

            vergangen = time.monotonic() - begonnen
            if vergangen > config.JOB_TIMEOUT:
                self.abbrechen(request_id)
                raise errors.ZeitFehler(
                    f"Higgsfield ist nach {int(vergangen / 60)} Minuten nicht fertig geworden.",
                    "Der Auftrag wurde storniert. Bei kürzerer Szene oder einfacherem "
                    "Modell klappt es meist.",
                    ursprung=QUELLE, details={"request_id": request_id})

            try:
                stand = self.status(status_url)
                fehlversuche = 0
            except errors.StudioFehler as fehler:
                # Einzelne gescheiterte Abfragen sind normal; erst eine Serie ist ein Problem.
                fehlversuche += 1
                if not fehler.wiederholbar or fehlversuche > config.MAX_RETRIES + 2:
                    raise
                logbook.debug(QUELLE, f"Statusabfrage gestört ({fehler.art}) — weiter.")
                time.sleep(config.POLL_INTERVAL)
                continue

            zustand = str(stand.get("status") or "").lower()
            if zustand and zustand != letzter_zustand:
                logbook.debug(QUELLE, f"Stand: {zustand}", details={"request_id": request_id})
                letzter_zustand = zustand

            if zustand in _FERTIG:
                dauer = time.monotonic() - begonnen
                url = self._medien_url(stand)
                if not url:
                    raise errors.AnbieterFehler(
                        "Higgsfield meldet 'fertig', liefert aber keine Datei.",
                        "Bitte erneut versuchen; bleibt es dabei, ein anderes Modell wählen.",
                        ursprung=QUELLE, details={"request_id": request_id})
                _laufzeiten.merken(modell, dauer)
                if melden:
                    melden(1.0, 0.0, "fertig")
                return Ergebnis(request_id, modell, url, dauer, stand)

            if zustand in _ABGELEHNT:
                raise errors.InhaltFehler(
                    "Higgsfield hat den Inhalt abgelehnt (Moderation).",
                    "Das Guthaben wurde erstattet. Formulieren Sie die Szene harmloser — "
                    "Marken, Prominente und Gewaltdarstellung lösen die Prüfung oft aus.",
                    ursprung=QUELLE, details={"request_id": request_id})

            if zustand in _GESCHEITERT:
                grund = str(stand.get("error") or stand.get("message") or "")[:300]
                raise errors.AnbieterFehler(
                    "Higgsfield konnte den Auftrag nicht ausführen.",
                    (f"Begründung: {grund}" if grund else
                     "Keine Begründung geliefert. Das Guthaben wird bei Fehlschlag erstattet."),
                    ursprung=QUELLE, details={"request_id": request_id})

            if zustand in _ABGEBROCHEN:
                raise errors.AbbruchFehler("Der Auftrag wurde storniert.", ursprung=QUELLE)

            if melden:
                anteil = min(0.95, vergangen / erwartet) if erwartet > 0 else 0.5
                # Vor dem Start läuft die Uhr nicht — 'queued' heißt Warteschlange.
                if zustand == "queued":
                    anteil = min(anteil, 0.15)
                rest = max(0.0, erwartet - vergangen)
                melden(anteil, rest, zustand or "läuft")

            time.sleep(config.POLL_INTERVAL)

    @staticmethod
    def _medien_url(stand: dict) -> str:
        """Findet die Ergebnis-URL. Die API hat je nach Modell unterschiedliche
        Antwortformen, darum erst die bekannten Felder, dann als Netz darunter eine
        Mustersuche über die gesamte Antwort."""
        for schluessel in ("result_url", "video_url", "image_url", "url", "min_result_url"):
            wert = stand.get(schluessel)
            if isinstance(wert, str) and wert.startswith("http"):
                return wert
        for behaelter in ("video", "image", "output", "result"):
            wert = stand.get(behaelter)
            if isinstance(wert, dict):
                for schluessel in ("url", "result_url", "min_url"):
                    if isinstance(wert.get(schluessel), str):
                        return wert[schluessel]
            elif isinstance(wert, str) and wert.startswith("http"):
                return wert
        for behaelter in ("results", "outputs", "media"):
            liste = stand.get(behaelter)
            if isinstance(liste, list) and liste:
                erstes = liste[0]
                if isinstance(erstes, dict):
                    for schluessel in ("url", "result_url", "min_url"):
                        if isinstance(erstes.get(schluessel), str):
                            return erstes[schluessel]
                elif isinstance(erstes, str) and erstes.startswith("http"):
                    return erstes
        treffer = _MEDIEN_MUSTER.search(json.dumps(stand, ensure_ascii=False))
        return treffer.group(0) if treffer else ""

    # ── Herunterladen ────────────────────────────────────────────────────────

    def herunterladen(self, url: str, ziel: Path,
                      abbruch: threading.Event | None = None,
                      melden=None) -> Path:
        """Lädt das Ergebnis stückweise herunter — große Videos sollen nicht komplett im
        Arbeitsspeicher landen. Erst in eine Nebendatei, dann umbenennen: so gibt es nie
        eine halb heruntergeladene Datei in der Bibliothek."""
        ziel = Path(ziel)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        vorlaeufig = ziel.with_suffix(ziel.suffix + ".teil")

        def einmal() -> Path:
            geladen = 0
            try:
                with httpx.Client(timeout=180, follow_redirects=True) as klient:
                    with klient.stream("GET", url, headers={"User-Agent": _UA}) as antwort:
                        if antwort.status_code >= 400:
                            raise errors.aus_httpfehler(antwort.status_code,
                                                        "Download abgelehnt", ursprung=QUELLE)
                        gesamt = int(antwort.headers.get("content-length") or 0)
                        with open(vorlaeufig, "wb") as datei:
                            for brocken in antwort.iter_bytes(65536):
                                if abbruch is not None and abbruch.is_set():
                                    raise errors.AbbruchFehler("Abgebrochen.", ursprung=QUELLE)
                                datei.write(brocken)
                                geladen += len(brocken)
                                if melden and gesamt:
                                    melden(min(1.0, geladen / gesamt), 0.0, "lädt")
            except httpx.TimeoutException as fehler:
                raise errors.ZeitFehler("Der Download hat zu lange gedauert.",
                                        "Das Programm versucht es erneut.",
                                        ursprung=QUELLE) from fehler
            except httpx.HTTPError as fehler:
                raise errors.NetzFehler("Der Download ist abgebrochen.",
                                        "Internetverbindung prüfen.",
                                        ursprung=QUELLE) from fehler

            if geladen < 1024:
                raise errors.AnbieterFehler(
                    "Die heruntergeladene Datei ist unbrauchbar klein.",
                    "Vermutlich ein Fehler beim Dienst — bitte erneut versuchen.",
                    ursprung=QUELLE, details={"bytes": geladen})
            vorlaeufig.replace(ziel)
            return ziel

        try:
            pfad = self._mit_wiederholung(einmal, beschreibung="Download", abbruch=abbruch)
        finally:
            try:
                if vorlaeufig.exists():
                    vorlaeufig.unlink()
            except Exception:
                pass
        logbook.info(QUELLE, f"Datei gespeichert: {pfad.name} "
                             f"({pfad.stat().st_size / 1_048_576:.1f} MB)")
        return pfad

    # ── Fachliche Aufrufe ────────────────────────────────────────────────────

    def bild(self, prompt: str, *, seitenverhaeltnis: str = "16:9", aufloesung: str = "1080p",
             modell: str = "", verbessern: bool = True, saat: int | None = None,
             abbruch: threading.Event | None = None, melden=None) -> Ergebnis:
        """Erzeugt ein Standbild — das Startbild für die spätere Animation."""
        modell = modell or config.IMAGE_MODEL
        rumpf: dict = {"prompt": prompt[:config.MAX_PROMPT_CHARS],
                       "aspect_ratio": seitenverhaeltnis,
                       "resolution": aufloesung,
                       "enhance_prompt": bool(verbessern)}
        if saat and saat >= 1:
            rumpf["seed"] = int(saat)
        kennung, status_url = self.auftrag_erstellen(modell, rumpf, abbruch)
        return self.warten(kennung, status_url, modell=modell, art="bild",
                           abbruch=abbruch, melden=melden)

    def video_aus_bild(self, prompt: str, bild_url: str, *, dauer: int = 5,
                       modell: str = "", saat: int | None = None,
                       bewegungen: list[str] | None = None,
                       abbruch: threading.Event | None = None, melden=None) -> Ergebnis:
        """Animiert ein vorhandenes Bild. `dauer` wird auf einen vom Modell erlaubten Wert
        gebracht, statt den Dienst mit einem ungültigen Wert abzuweisen."""
        modell = modell or config.VIDEO_MODEL
        rumpf: dict = {"prompt": prompt[:config.MAX_PROMPT_CHARS],
                       "image_url": bild_url,
                       "duration": erlaubte_dauer(modell, dauer)}
        if saat and saat >= 1:
            rumpf["seed"] = int(saat)
        if bewegungen:
            # Die dop-Modelle erwarten Objekte, keine bloßen Zeichenketten.
            rumpf["motions"] = [{"id": kennung} for kennung in bewegungen if kennung]
        kennung, status_url = self.auftrag_erstellen(modell, rumpf, abbruch)
        return self.warten(kennung, status_url, modell=modell, art="video",
                           abbruch=abbruch, melden=melden)

    def video_aus_text(self, prompt: str, *, dauer: int = 6, modell: str = "",
                       abbruch: threading.Event | None = None, melden=None) -> Ergebnis:
        """Erzeugt ein Video ohne Zwischenbild."""
        modell = modell or config.T2V_MODEL
        rumpf = {"prompt": prompt[:config.MAX_PROMPT_CHARS],
                 "duration": erlaubte_dauer(modell, dauer)}
        kennung, status_url = self.auftrag_erstellen(modell, rumpf, abbruch)
        return self.warten(kennung, status_url, modell=modell, art="video",
                           abbruch=abbruch, melden=melden)

    # ── Selbstauskunft ───────────────────────────────────────────────────────

    def bewegungen(self) -> list[dict]:
        """Katalog der Kamerabewegungen (`GET /v1/motions`) — für die Auswahl im Formular."""
        try:
            code, daten, text = self._anfrage("GET", "v1/motions", zeitlimit=20)
            if code >= 400:
                return []
            liste = daten.get("inhalt") if "inhalt" in daten else daten
            if not isinstance(liste, list):
                return []
            return [{"id": e.get("id", ""), "name": e.get("name", ""),
                     "beschreibung": (e.get("description") or "")[:200]}
                    for e in liste if isinstance(e, dict) and e.get("id")]
        except Exception:
            return []

    def selbsttest(self) -> dict:
        """Prüft den Zugang, ohne Guthaben zu verbrauchen.

        Ein Auftrag mit *leerem* Rumpf wird von der Schemaprüfung mit 422 abgewiesen,
        bevor der Dienst überhaupt bis zur Guthabenprüfung kommt. Das beweist zuverlässig,
        dass die Anmeldung stimmt — über den Kontostand sagt es dagegen **nichts**.
        Für den Kontostand wird der gemerkte Ausgang des letzten echten Auftrags
        herangezogen; ohne einen solchen bleibt er ehrlich „unbekannt“.
        """
        if not self.verfuegbar:
            return {"zustand": "kein_schluessel", "ok": False, "guthaben": "unbekannt",
                    "meldung": "Kein Higgsfield-Schlüssel hinterlegt.",
                    "hinweis": "HIGGSFIELD_API_KEY in der .env eintragen (ID:SECRET)."}
        try:
            code, _, text = self._anfrage("POST", config.IMAGE_MODEL, {}, zeitlimit=20)
        except errors.StudioFehler as fehler:
            return {"zustand": "unerreichbar", "ok": False, "guthaben": "unbekannt",
                    "meldung": fehler.meldung, "hinweis": fehler.hinweis}

        klein = (text or "").lower()

        if code == 403 and "not_enough_credits" in klein:
            _guthaben.merken(False, "Selbsttest erhielt 403")
            return {"zustand": "kein_guthaben", "ok": False, "guthaben": "leer",
                    "meldung": "Zugang gültig, aber kein API-Guthaben.",
                    "hinweis": "Ein Web-Abo (Soul/Plus) füllt den API-Topf nicht — das sind "
                               "getrennte Guthaben. Unter cloud.higgsfield.ai API-Credits "
                               "aufladen."}
        if code in (401, 403):
            return {"zustand": "abgelehnt", "ok": False, "guthaben": "unbekannt",
                    "meldung": f"Higgsfield lehnt den Schlüssel ab (Code {code}).",
                    "hinweis": "HIGGSFIELD_API_KEY prüfen (Format ID:SECRET)."}
        if code == 404:
            return {"zustand": "modell_fehlt", "ok": False, "guthaben": "unbekannt",
                    "meldung": f"Das eingestellte Bildmodell gibt es nicht: {config.IMAGE_MODEL}",
                    "hinweis": "MPW_IMAGE_MODEL in der .env korrigieren."}
        if code != 422:
            return {"zustand": "unklar", "ok": False, "guthaben": "unbekannt",
                    "meldung": f"Unerwartete Antwort (Code {code}).",
                    "hinweis": config.entschaerfe(text[:200])}

        # 422 → Anmeldung in Ordnung. Jetzt der gemerkte Kontostand.
        stand = _guthaben.lesen()
        if not stand:
            return {"zustand": "zugang_ok", "ok": True, "guthaben": "unbekannt",
                    "meldung": "Zugang gültig. Der Guthabenstand zeigt sich beim ersten Auftrag.",
                    "hinweis": ""}
        alter_minuten = int((time.time() - float(stand.get("zeitpunkt", 0))) / 60)
        wann = (f"vor {alter_minuten} Min." if alter_minuten < 90
                else f"vor {alter_minuten // 60} Std.")
        if stand.get("guthaben"):
            return {"zustand": "bereit", "ok": True, "guthaben": "vorhanden",
                    "meldung": f"Zugang gültig, Guthaben zuletzt bestätigt ({wann}).",
                    "hinweis": ""}
        return {"zustand": "kein_guthaben", "ok": False, "guthaben": "leer",
                "meldung": f"Zugang gültig, aber beim letzten Auftrag ({wann}) fehlte das "
                           f"Guthaben.",
                "hinweis": "Unter cloud.higgsfield.ai API-Credits aufladen. Der Probelauf-"
                           "Modus funktioniert unabhängig davon."}

    def guthaben_wirklich_pruefen(self) -> dict:
        """Ausdrückliche Prüfung mit einem echten, sofort stornierten Bildauftrag.
        Kostet im schlimmsten Fall ein Bild — wird deshalb nie automatisch aufgerufen,
        sondern nur auf Knopfdruck."""
        if not self.verfuegbar:
            return {"ok": False, "guthaben": "unbekannt",
                    "meldung": "Kein Schlüssel hinterlegt."}
        try:
            code, daten, text = self._anfrage(
                "POST", config.IMAGE_MODEL,
                {"prompt": "a plain grey square", "aspect_ratio": "1:1",
                 "resolution": "720p", "enhance_prompt": False})
        except errors.StudioFehler as fehler:
            return {"ok": False, "guthaben": "unbekannt", "meldung": fehler.meldung}

        if code == 403 and "not_enough_credits" in (text or "").lower():
            _guthaben.merken(False, "ausdrückliche Prüfung")
            return {"ok": False, "guthaben": "leer",
                    "meldung": "Bestätigt: kein API-Guthaben vorhanden.",
                    "hinweis": "Unter cloud.higgsfield.ai API-Credits aufladen."}
        if code >= 400:
            fehler = errors.aus_httpfehler(code, text, ursprung=QUELLE)
            return {"ok": False, "guthaben": "unbekannt", "meldung": fehler.meldung,
                    "hinweis": fehler.hinweis}

        _guthaben.merken(True, "ausdrückliche Prüfung")
        kennung = str(daten.get("request_id") or daten.get("id") or "")
        if kennung:
            self.abbrechen(kennung)      # sofort stornieren, bevor gerechnet wird
        return {"ok": True, "guthaben": "vorhanden",
                "meldung": "Bestätigt: Guthaben vorhanden. Der Probeauftrag wurde storniert."}

    def guthaben_bekannt(self) -> dict:
        """Zuletzt beobachteter Kontostand — ohne jeden Netzaufruf."""
        return _guthaben.lesen()


# ── Modellwissen ─────────────────────────────────────────────────────────────
# Belegt durch echte Fehlermeldungen der API, siehe docs/API_BEFUND.md.
# Kein Ratewerk: jeder Eintrag stammt aus einer Antwort der Form
# "duration: 999 is not one of [...]".

ERLAUBTE_DAUER: dict[str, tuple[int, ...]] = {
    "kling-video/v2.6/pro/image-to-video": (5, 10),
    "kling-video/v2.1/pro/image-to-video": (5, 10),
    "kling-video/v2.1/master/image-to-video": (5, 10),
    "kling-video/v2.1/standard/image-to-video": (5, 10),
    "minimax/hailuo-02/pro/image-to-video": (6,),
    "minimax/hailuo-02/pro/text-to-video": (6,),
    "minimax/hailuo-02/standard/text-to-video": (6, 10),
}

#: Modelle, die ohne Startbild auskommen.
TEXT_ZU_VIDEO = ("minimax/hailuo-02/pro/text-to-video",
                 "minimax/hailuo-02/standard/text-to-video")


def erlaubte_dauer(modell: str, wunsch: int) -> int:
    """Nächstgelegene erlaubte Clipdauer. Unbekannte Modelle bekommen den Wunsch
    unverändert — dann entscheidet der Dienst, und sein Fehler ist aussagekräftig."""
    moeglich = ERLAUBTE_DAUER.get(modell)
    if not moeglich:
        return max(1, int(wunsch))
    return min(moeglich, key=lambda w: (abs(w - wunsch), w))


def braucht_startbild(modell: str) -> bool:
    return modell not in TEXT_ZU_VIDEO


#: Für die Auswahl in der Oberfläche — nur nachweislich vorhandene Modelle.
VIDEOMODELLE = [
    {"id": "kling-video/v2.6/pro/image-to-video", "name": "Kling 2.6 Pro",
     "beschreibung": "Neueste Version, sehr saubere Bewegung. Startbild nötig.",
     "dauer": [5, 10], "startbild": True, "empfohlen": True},
    {"id": "kling-video/v2.1/master/image-to-video", "name": "Kling 2.1 Master",
     "beschreibung": "Höchste Detailtreue, etwas langsamer. Startbild nötig.",
     "dauer": [5, 10], "startbild": True, "empfohlen": False},
    {"id": "kling-video/v2.1/standard/image-to-video", "name": "Kling 2.1 Standard",
     "beschreibung": "Günstiger und schnell. Startbild nötig.",
     "dauer": [5, 10], "startbild": True, "empfohlen": False},
    {"id": "higgsfield-ai/dop/turbo", "name": "Higgsfield DoP Turbo",
     "beschreibung": "Kinolook mit wählbarer Kamerafahrt. Startbild nötig.",
     "dauer": [5], "startbild": True, "empfohlen": False, "bewegungen": True},
    {"id": "higgsfield-ai/dop/standard", "name": "Higgsfield DoP Standard",
     "beschreibung": "Ausgewogen, mit Kamerafahrten. Startbild nötig.",
     "dauer": [5], "startbild": True, "empfohlen": False, "bewegungen": True},
    {"id": "minimax/hailuo-02/standard/text-to-video", "name": "Hailuo 02 (ohne Startbild)",
     "beschreibung": "Erzeugt direkt aus Text — schneller, weniger Kontrolle über den Look.",
     "dauer": [6, 10], "startbild": False, "empfohlen": False},
]

BILDMODELLE = [
    {"id": "higgsfield-ai/soul/standard", "name": "Soul Standard",
     "beschreibung": "Fotorealistisch, verlässlich.", "empfohlen": True},
    {"id": "higgsfield-ai/soul/turbo/standard", "name": "Soul Turbo",
     "beschreibung": "Schneller, minimal weniger Detail.", "empfohlen": False},
]


def modell_info(modell_id: str) -> dict:
    for eintrag in VIDEOMODELLE:
        if eintrag["id"] == modell_id:
            return eintrag
    return {"id": modell_id, "name": modell_id, "dauer": [5],
            "startbild": braucht_startbild(modell_id), "beschreibung": ""}


#: Gemeinsame Instanz — der Client ist zustandslos, mehrere braucht niemand.
client = Higgsfield()
