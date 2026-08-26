"""
videoquelle.py — welcher Dienst erzeugt gerade die Bilder und Videos?

Es gibt drei Wege, und die Ablaufsteuerung soll keinen davon kennen müssen. Sie fragt
`aktiv()` und bekommt etwas, das `bild()`, `video_aus_bild()`, `video_aus_text()` und
`herunterladen()` beherrscht — mehr braucht sie nicht zu wissen.

    platform   Platform-API mit dem Schlüssel aus der .env.
               Eigener Credit-Topf. Am 03.08.2026: Schlüssel gültig, Topf leer.
    abo        MCP-Dienst mit den Credits des Web-Abos.
               Braucht eine einmalige Anmeldung im Browser.
    demo       Erzeugt Platzhalterclips mit ffmpeg, ohne jeden Netzzugriff.
               Damit lässt sich die ganze Kette vorführen und prüfen, ohne dass
               Guthaben fließt.

Die Reihenfolge steht in `MPW_VIDEO_CHAIN`. Genommen wird der erste Weg, der wirklich
kann — und das Ergebnis wird protokolliert, damit im Logbuch nachvollziehbar bleibt,
wer das Video gemacht hat.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from . import config, errors, higgsfield, higgsfield_mcp, logbook, media

QUELLE = "Videoquelle"


# ── Probelauf ────────────────────────────────────────────────────────────────

class Probelauf:
    """Erzeugt echte Videodateien ohne Netz und ohne Guthaben.

    Kein Ersatz für Higgsfield, aber ehrlich als Platzhalter erkennbar — und die
    einzige Möglichkeit, dem Kunden die vollständige Kette zu zeigen, wenn gerade
    kein Guthaben da ist.
    """

    name = "Probelauf (ohne Guthaben)"
    verfuegbar = True

    def _melden(self, melden, sekunden: float) -> None:
        # Ein bisschen Wartezeit vortäuschen wäre unehrlich — stattdessen sofort fertig.
        if melden:
            melden(1.0, 0.0, "fertig")

    def bild(self, prompt: str, *, seitenverhaeltnis: str = "16:9", aufloesung: str = "1080p",
             modell: str = "", verbessern: bool = True, saat: int | None = None,
             abbruch: threading.Event | None = None, melden=None) -> higgsfield.Ergebnis:
        ziel = config.DATA_DIR / "probelauf" / f"bild_{int(time.time() * 1000)}.jpg"
        ziel.parent.mkdir(parents=True, exist_ok=True)
        clip = media.platzhalter_clip(ziel.with_suffix(".mp4"), sekunden=1,
                                      breite=1280, hoehe=720, abbruch=abbruch)
        media.format_erzeugen(clip, ziel, "poster", abbruch=abbruch)
        clip.unlink(missing_ok=True)
        self._melden(melden, 1)
        return higgsfield.Ergebnis("probe-bild", "probelauf", str(ziel), 1.0, {})

    def video_aus_bild(self, prompt: str, bild_url: str, *, dauer: int = 5,
                       modell: str = "", saat: int | None = None,
                       bewegungen: list[str] | None = None,
                       seitenverhaeltnis: str = "16:9",
                       abbruch: threading.Event | None = None,
                       melden=None) -> higgsfield.Ergebnis:
        ziel = config.DATA_DIR / "probelauf" / f"clip_{int(time.time() * 1000)}.mp4"
        ziel.parent.mkdir(parents=True, exist_ok=True)
        media.platzhalter_clip(ziel, sekunden=max(1, int(dauer)), text=prompt[:60],
                               abbruch=abbruch)
        self._melden(melden, dauer)
        return higgsfield.Ergebnis("probe-video", "probelauf", str(ziel), float(dauer), {})

    def video_aus_text(self, prompt: str, *, dauer: int = 6, modell: str = "",
                       seitenverhaeltnis: str = "16:9",
                       abbruch: threading.Event | None = None,
                       melden=None) -> higgsfield.Ergebnis:
        return self.video_aus_bild(prompt, "", dauer=dauer, abbruch=abbruch, melden=melden)

    def herunterladen(self, url, ziel, abbruch=None, melden=None) -> Path:
        """Es gibt nichts zu holen — die Datei liegt schon hier."""
        import shutil
        ziel = Path(ziel)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(url, ziel)
        return ziel

    def abbrechen(self, request_id: str) -> bool:
        return True

    def selbsttest(self) -> dict:
        bereit = media.ffmpeg_vorhanden()
        return {"zustand": "bereit" if bereit else "kein_ffmpeg", "ok": bereit,
                "guthaben": "nicht nötig",
                "meldung": "Probelauf möglich — erzeugt Platzhalterclips ohne Guthaben."
                           if bereit else "Für den Probelauf fehlt ffmpeg.",
                "hinweis": ""}


probelauf = Probelauf()


# ── Auswahl ──────────────────────────────────────────────────────────────────

def _wege() -> dict:
    # `higgsfield.client` wird bewusst bei jedem Aufruf frisch gelesen: Tests tauschen
    # dieses Attribut aus, und die Auswahl soll das mitbekommen.
    return {"platform": higgsfield.client, "abo": higgsfield_mcp.client,
            "demo": probelauf}


def _reihenfolge() -> list[str]:
    erlaubt = ("platform", "abo", "demo")
    gewaehlt = [w for w in config.VIDEO_CHAIN if w in erlaubt]
    # Der Abo-Weg steht nicht in der Vorgabekette, ist aber der einzige mit Guthaben,
    # sobald er angemeldet ist — dann rückt er automatisch nach vorn.
    if "abo" not in gewaehlt and higgsfield_mcp.angemeldet():
        gewaehlt.insert(0, "abo")
    return gewaehlt or ["platform"]


_letzter: str = ""

#: Wie lange ein beobachteter Guthabenstand die Auswahl beeinflusst (Sekunden).
#: Danach wird der Weg wieder probiert — sonst bliebe ein aufgeladenes Konto
#: für immer übersprungen.
GEDAECHTNIS = 6 * 3600


def _kann_liefern(name: str, weg) -> bool:
    """Kann dieser Weg gerade wirklich ein Video machen?

    `verfuegbar` heißt nur „eingerichtet“. Ein gültiger Schlüssel auf einem leeren
    Guthabentopf ist eingerichtet und trotzdem nutzlos — ohne diese Unterscheidung
    stünde der zweite Eintrag in `MPW_VIDEO_CHAIN` bloß zur Zierde da, denn der erste
    würde jeden Auftrag an sich ziehen und dann mit 403 abbrechen.
    """
    if not getattr(weg, "verfuegbar", False):
        return False

    # Gefragt wird der Weg selbst, nicht das Modul: Tests setzen eigene Dienste ein,
    # und ein Dienst ohne Guthabengedächtnis gilt schlicht als einsatzbereit.
    merker = getattr(weg, "guthaben_bekannt", None)
    if callable(merker):
        stand = merker() or {}
        frisch = (time.time() - float(stand.get("zeitpunkt", 0))) < GEDAECHTNIS
        if stand and frisch and not stand.get("guthaben"):
            return False
    return True


def aktiv():
    """Der Dienst, der den nächsten Auftrag ausführt."""
    global _letzter
    reihenfolge = _reihenfolge()

    for pruefung in (_kann_liefern, lambda n, w: bool(getattr(w, "verfuegbar", False))):
        # Zweiter Durchgang ohne Guthabenprüfung: Kann keiner sicher liefern, ist die
        # Fehlermeldung des Dienstes selbst immer noch besser als gar kein Versuch.
        for name in reihenfolge:
            weg = _wege().get(name)
            if weg is None or not pruefung(name, weg):
                continue
            if name != _letzter:
                # Der Probelauf ist eine Warnung wert: Er liefert Platzhalter, und wer
                # das im Logbuch überliest, hält sie am Ende für das Ergebnis.
                melden = logbook.warnung if name == "demo" else logbook.info
                melden(QUELLE, f"Videoerzeugung läuft über: {getattr(weg, 'name', name)}")
                _letzter = name
            return weg

    raise errors.KonfigurationsFehler(
        "Es steht kein Weg zur Videoerzeugung bereit.",
        "Entweder HIGGSFIELD_API_KEY eintragen, das Abo im Dashboard anmelden oder "
        "MPW_VIDEO_CHAIN auf „demo“ stellen.", ursprung=QUELLE)


def name_des_aktiven() -> str:
    try:
        return getattr(aktiv(), "name", "unbekannt")
    except errors.StudioFehler:
        return "keiner"


def befund() -> dict:
    """Kurzurteil für die Ampel im Kopf — **ohne** Netzaufruf.

    Die Ampel soll nicht bei jedem Fensteröffnen den Dienst befragen, aber sie darf
    auch nicht grün leuchten, während der Guthabentopf nachweislich leer ist. Beides
    zusammen geht nur mit dem, was ohne Netz bekannt ist: die Anmeldung des Abos und
    der Ausgang des letzten echten Auftrags.
    """
    demo_moeglich = "demo" in config.VIDEO_CHAIN and media.ffmpeg_vorhanden()
    ausweichen = (" Solange erzeugt der Probelauf Platzhalterclips."
                  if demo_moeglich else "")

    if higgsfield_mcp.angemeldet():
        return {"ok": True, "zustand": "ok",
                "meldung": "Abo verbunden — Videos laufen über die Credits des Abos.",
                "hinweis": ""}

    if not higgsfield.client.verfuegbar:
        if demo_moeglich:
            return {"ok": True, "zustand": "warnung",
                    "meldung": "Kein Zugang zu Higgsfield — nur Probelauf möglich.",
                    "hinweis": "Oben auf „Abo verbinden“ klicken oder einen "
                               "HIGGSFIELD_API_KEY in die .env eintragen."}
        return {"ok": False, "zustand": "fehler",
                "meldung": "Kein Weg zur Videoerzeugung.",
                "hinweis": "Oben auf „Abo verbinden“ klicken oder einen "
                           "HIGGSFIELD_API_KEY in die .env eintragen."}

    stand = higgsfield.client.guthaben_bekannt()
    if not stand:
        return {"ok": True, "zustand": "ok",
                "meldung": "Higgsfield-Zugang hinterlegt. Das Guthaben zeigt sich beim "
                           "ersten Auftrag.",
                "hinweis": ""}
    if stand.get("guthaben"):
        return {"ok": True, "zustand": "ok",
                "meldung": "Higgsfield bereit — Guthaben zuletzt bestätigt.", "hinweis": ""}
    return {"ok": True, "zustand": "warnung",
            "meldung": "Higgsfield-Zugang gültig, aber der API-Topf ist leer.",
            "hinweis": "Oben auf „Abo verbinden“ klicken — das nutzt die Credits des "
                       "Web-Abos. Oder unter cloud.higgsfield.ai API-Credits aufladen."
                       + ausweichen}


def startbericht() -> dict:
    """`config.diagnose_kurz()`, aber mit dem ehrlichen Urteil über den Videoweg.

    `config.diagnose()` kennt nur die .env und sieht deshalb einen hinterlegten
    Schlüssel als „in Ordnung“ an. Für die Ampel und den Startbericht ist das zu wenig:
    ein gültiger Schlüssel auf einem leeren Guthabentopf erzeugt kein einziges Video.
    Terminal und Fenster sollen dasselbe sagen — deshalb steht das hier an einer Stelle.
    """
    kurz = config.diagnose_kurz()
    urteil = befund()
    for eintrag in kurz["befunde"]:
        if eintrag["name"] == "Higgsfield":
            eintrag.update(urteil)
    fehler = [e for e in kurz["befunde"] if e["zustand"] == "fehler"]
    kurz["startbereit"] = not fehler
    kurz["anzahl_fehler"] = len(fehler)
    return kurz


def uebersicht() -> list[dict]:
    """Für den Selbsttest: welcher Weg kann, welcher nicht und warum."""
    ergebnis = []
    aktiver = None
    try:
        aktiver = aktiv()
    except errors.StudioFehler:
        pass

    for name in ("platform", "abo", "demo"):
        weg = _wege()[name]
        pruefung = weg.selbsttest()
        ergebnis.append({
            "weg": name,
            "name": getattr(weg, "name", name),
            "bereit": bool(getattr(weg, "verfuegbar", False)),
            "aktiv": weg is aktiver,
            **pruefung,
        })
    return ergebnis
