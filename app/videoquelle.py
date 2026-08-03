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
                       abbruch: threading.Event | None = None,
                       melden=None) -> higgsfield.Ergebnis:
        ziel = config.DATA_DIR / "probelauf" / f"clip_{int(time.time() * 1000)}.mp4"
        ziel.parent.mkdir(parents=True, exist_ok=True)
        media.platzhalter_clip(ziel, sekunden=max(1, int(dauer)), text=prompt[:60],
                               abbruch=abbruch)
        self._melden(melden, dauer)
        return higgsfield.Ergebnis("probe-video", "probelauf", str(ziel), float(dauer), {})

    def video_aus_text(self, prompt: str, *, dauer: int = 6, modell: str = "",
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


def aktiv():
    """Der Dienst, der den nächsten Auftrag ausführt."""
    global _letzter
    for name in _reihenfolge():
        weg = _wege().get(name)
        if weg is None or not getattr(weg, "verfuegbar", False):
            continue
        if name != _letzter:
            logbook.info(QUELLE, f"Videoerzeugung läuft über: {getattr(weg, 'name', name)}")
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
