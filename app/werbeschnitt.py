"""
werbeschnitt.py — aus den Aufnahmen einer Webseite wird ein TikTok-Werbevideo.

Kein KI-Videomodell, sondern Motion-Design: Jedes Bild wird mit Pillow gezeichnet und
direkt an ffmpeg gereicht. Das hat drei Gründe:

  * **Schrift bleibt Schrift.** KI-Videomodelle verzerren Text und Bildschirminhalte.
    Eine Webseite, deren Überschrift im Video zerfließt, wirbt gegen sich selbst.
  * **Es kostet nichts und gelingt immer.** Kein Guthaben, kein Warten auf einen Dienst.
    Wer Higgsfield-Credits hat, kann zusätzlich eine KI-Szene einfügen lassen.
  * **Volle Kontrolle über die Bewegung.** Weiche Kurven, Wort-für-Wort-Einblendungen,
    ein Handy, durch dessen Bildschirm die Seite scrollt — Filterketten in ffmpeg
    können das nicht verlässlich, schon gar nicht auf jedem Build.

Der Aufbau folgt dem, was auf TikTok funktioniert:

    Aufhänger (0–2,5 s)  →  Enthüllung  →  [KI-Szene]  →  Scrollen mit Vorteilen
                         →  Details  →  Handlungsaufforderung

Alles liegt im 1080×1920-Raster, Text nur in der sicheren Zone (oben und unten liegen
die Bedienelemente der App). Die Schnitte sitzen auf dem Takt der Musik, die hier
ebenfalls entsteht — synthetisch, also ohne Lizenzfragen.
"""
from __future__ import annotations

import array
import math
import random
import subprocess
import threading
import wave
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import config, errors, logbook, media

QUELLE = "Schnitt"

BREITE, HOEHE, BILDRATE = 1080, 1920, 30

#: Sichere Zone für Text: TikTok legt oben die Reiter, unten Beschreibung und Knöpfe,
#: rechts die Symbolleiste über das Video.
OBEN, UNTEN, RECHTS = 200, 1500, 150

#: Grundfarben je Stil — gilt, wenn die Webseite keine brauchbare Markenfarbe hat.
STILE = {
    "energisch": {"akzent": (255, 64, 110), "bpm": 124, "grund": (10, 10, 16)},
    "edel": {"akzent": (212, 175, 92), "bpm": 96, "grund": (12, 11, 10)},
    "freundlich": {"akzent": (34, 211, 238), "bpm": 110, "grund": (9, 13, 18)},
}


@dataclass
class Konzept:
    """Was im Video steht. Entsteht in `webwerbung` aus Seite und Sprachmodell."""
    marke: str
    hook: str
    untertitel: str = ""
    vorteile: list[str] = field(default_factory=list)
    cta: str = "Jetzt entdecken"
    host: str = ""
    stil: str = "energisch"
    farbe: tuple[int, int, int] | None = None

    @property
    def akzent(self) -> tuple[int, int, int]:
        return self.farbe or STILE.get(self.stil, STILE["energisch"])["akzent"]


# ── Schriften ────────────────────────────────────────────────────────────────

_SCHRIFTEN = {
    "schwarz": ("seguibl.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"),
    "fett": ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"),
    "halb": ("seguisb.ttf", "segoeuib.ttf", "arial.ttf", "DejaVuSans.ttf"),
    "normal": ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"),
}
_schriftspeicher: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def schrift(art: str, groesse: int) -> ImageFont.ImageFont:
    """Segoe UI auf Windows, sonst Arial oder DejaVu, zur Not Pillows eigene."""
    schluessel = (art, groesse)
    if schluessel in _schriftspeicher:
        return _schriftspeicher[schluessel]
    ordner = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu"),
              Path("/Library/Fonts")]
    for name in _SCHRIFTEN.get(art, _SCHRIFTEN["normal"]):
        for basis in ordner:
            pfad = basis / name
            if pfad.exists():
                try:
                    _schriftspeicher[schluessel] = ImageFont.truetype(str(pfad), groesse)
                    return _schriftspeicher[schluessel]
                except OSError:
                    continue
    _schriftspeicher[schluessel] = ImageFont.load_default(size=groesse)
    return _schriftspeicher[schluessel]


# ── Bewegung ─────────────────────────────────────────────────────────────────

def _klemmen(x: float) -> float:
    return max(0.0, min(1.0, x))


def aus_kubisch(x: float) -> float:
    x = _klemmen(x)
    return 1 - (1 - x) ** 3


def weich(x: float) -> float:
    x = _klemmen(x)
    return x * x * (3 - 2 * x)


def aus_zurueck(x: float) -> float:
    """Schießt leicht über das Ziel hinaus und federt zurück — für Einblendungen."""
    x = _klemmen(x)
    c1, c3 = 1.4, 2.4
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def _phase(t: float, beginn: float, dauer: float) -> float:
    return _klemmen((t - beginn) / dauer) if dauer > 0 else 1.0


# ── Bausteine ────────────────────────────────────────────────────────────────

def _cover(bild: Image.Image, breite: int, hoehe: int) -> Image.Image:
    """Füllt die Fläche ohne Verzerrung — was übersteht, wird mittig abgeschnitten."""
    faktor = max(breite / bild.width, hoehe / bild.height)
    neu = bild.resize((max(1, round(bild.width * faktor)), max(1, round(bild.height * faktor))),
                      Image.LANCZOS)
    links = (neu.width - breite) // 2
    oben = (neu.height - hoehe) // 2
    return neu.crop((links, oben, links + breite, oben + hoehe))


def _abgerundet(groesse: tuple[int, int], radius: int) -> Image.Image:
    maske = Image.new("L", groesse, 0)
    ImageDraw.Draw(maske).rounded_rectangle((0, 0, groesse[0] - 1, groesse[1] - 1),
                                            radius=radius, fill=255)
    return maske


def _schatten(groesse: tuple[int, int], radius: int, weich_px: int = 40,
              deckung: int = 150) -> Image.Image:
    rand = weich_px * 2
    flaeche = Image.new("L", (groesse[0] + rand * 2, groesse[1] + rand * 2), 0)
    ImageDraw.Draw(flaeche).rounded_rectangle(
        (rand, rand, rand + groesse[0], rand + groesse[1]), radius=radius, fill=deckung)
    return flaeche.filter(ImageFilter.GaussianBlur(weich_px))


def _hintergrund(quelle: Image.Image, grund: tuple[int, int, int],
                 akzent: tuple[int, int, int]) -> Image.Image:
    """Unscharfe, abgedunkelte Webseite mit farbigem Schein — 12 % größer fürs Zoomen."""
    b, h = int(BREITE * 1.12), int(HOEHE * 1.12)
    bild = _cover(quelle.convert("RGB"), b // 4, h // 4)
    bild = bild.filter(ImageFilter.GaussianBlur(10)).resize((b, h), Image.BILINEAR)
    dunkel = Image.new("RGB", (b, h), grund)
    bild = Image.blend(bild, dunkel, 0.72)
    schein = Image.new("L", (b, h), 0)
    ImageDraw.Draw(schein).ellipse((-b * 0.3, -h * 0.15, b * 0.9, h * 0.45), fill=120)
    schein = schein.filter(ImageFilter.GaussianBlur(180))
    farbe = Image.new("RGB", (b, h), akzent)
    bild = Image.composite(farbe, bild, schein.point(lambda v: int(v * 0.45)))
    vignette = Image.new("L", (b, h), 0)
    ImageDraw.Draw(vignette).rectangle((0, int(h * 0.72), b, h), fill=190)
    vignette = vignette.filter(ImageFilter.GaussianBlur(160))
    return Image.composite(Image.new("RGB", (b, h), (0, 0, 0)), bild, vignette)


def _zoomausschnitt(bild: Image.Image, stufe: float) -> Image.Image:
    """Ein ruhig wandernder Ausschnitt aus dem 12 % größeren Hintergrund.

    Früher wurde je Bild herangezoomt, also das ganze Bild neu skaliert — rund ein
    Drittel der Rechenzeit, für einen Hintergrund, der ohnehin unscharf ist. Ein
    langsames Wandern wirkt genauso lebendig und ist nur ein Ausschnitt.
    """
    luft_x, luft_y = bild.width - BREITE, bild.height - HOEHE
    s = _klemmen(stufe)
    links = int(luft_x * (0.2 + 0.6 * s))
    oben = int(luft_y * (0.75 - 0.5 * s))
    return bild.crop((links, oben, links + BREITE, oben + HOEHE))


def lesbar_auf(farbe: tuple[int, int, int]) -> tuple[int, int, int]:
    """Weiß oder fast Schwarz — was auf dieser Farbe lesbar ist.

    Die Akzentfarbe kommt von der Webseite und kann alles sein. Auf dem Gelb von
    python.org stand im ersten Entwurf weiße Schrift — kaum zu entziffern.
    """
    def kanal(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    helligkeit = 0.2126 * kanal(farbe[0]) + 0.7152 * kanal(farbe[1]) + 0.0722 * kanal(farbe[2])
    # Kontrast gegen Weiß und gegen fast Schwarz vergleichen — das bessere gewinnt.
    gegen_weiss = 1.05 / (helligkeit + 0.05)
    gegen_schwarz = (helligkeit + 0.05) / 0.056
    return (255, 255, 255) if gegen_weiss >= gegen_schwarz else (16, 16, 20)


@dataclass
class _Wort:
    bild: Image.Image
    x: int
    y: int
    hervor: bool = False


def _worte_setzen(text: str, art: str, groesse: int, max_breite: int, *,
                  farbe=(255, 255, 255), akzent=(255, 64, 110), hervorheben: int = -1,
                  zeilenabstand: float = 1.08, mitte_y: int = 900,
                  hoechstens_zeilen: int = 4) -> list[_Wort]:
    """Setzt Text Wort für Wort in Zeilen. Jedes Wort wird einmal gerendert und
    später nur noch verschoben und skaliert — das hält das Rendern schnell.

    Passt der Text nicht in `hoechstens_zeilen`, wird die Schrift verkleinert.
    """
    worte = text.split()
    if not worte:
        return []
    while True:
        f = schrift(art, groesse)
        luft = int(groesse * 0.28)
        zeilen: list[list[str]] = [[]]
        breite_zeile = 0
        for wort in worte:
            w = f.getbbox(wort)[2]
            if zeilen[-1] and breite_zeile + luft + w > max_breite:
                zeilen.append([])
                breite_zeile = 0
            zeilen[-1].append(wort)
            breite_zeile += (luft if breite_zeile else 0) + w
        zu_breit = any(f.getbbox(w)[2] > max_breite for w in worte)
        if (len(zeilen) <= hoechstens_zeilen and not zu_breit) or groesse <= 40:
            break
        groesse = int(groesse * 0.88)

    hoehe_zeile = int(groesse * zeilenabstand)
    # Oberlänge + Unterlänge: Ohne die Unterlänge schnitt das Wortbild „g“, „y“ und „p“
    # unten ab — aus „Python.org“ wurde auf dem Bildschirm „Pvthon.ora“.
    oberlaenge, unterlaenge = f.getmetrics()
    zeichen_hoehe = oberlaenge + unterlaenge
    gesamt = hoehe_zeile * len(zeilen)
    y = mitte_y - gesamt // 2
    ergebnis: list[_Wort] = []
    index = 0
    for zeile in zeilen:
        breiten = [f.getbbox(w)[2] for w in zeile]
        x = (BREITE - (sum(breiten) + luft * (len(zeile) - 1))) // 2
        for wort, w in zip(zeile, breiten):
            hervor = index == hervorheben
            polster = int(groesse * 0.18) if hervor else 4
            # +8: Platz für den Schlagschatten, der 4 px nach unten versetzt liegt.
            bild = Image.new("RGBA", (w + polster * 2 + 8, zeichen_hoehe + polster * 2 + 8),
                             (0, 0, 0, 0))
            zeichner = ImageDraw.Draw(bild)
            if hervor:
                oben_box = f.getbbox(wort)[1]
                zeichner.rounded_rectangle(
                    (0, polster + oben_box - int(groesse * 0.14), bild.width - 1,
                     polster + oberlaenge + int(unterlaenge * 0.55)),
                    radius=int(groesse * 0.2), fill=akzent + (255,))
            # Weicher Schlagschatten für Lesbarkeit auf jedem Grund — nicht auf der
            # farbigen Hervorhebung, dort machte er dunkle Schrift nur unscharf.
            schriftfarbe = lesbar_auf(akzent) if hervor else farbe
            if not hervor or schriftfarbe == (255, 255, 255):
                zeichner.text((polster + 3, polster + 4), wort, font=f, fill=(0, 0, 0, 110))
            zeichner.text((polster, polster), wort, font=f, fill=schriftfarbe + (255,))
            ergebnis.append(_Wort(bild, x - polster, y - polster, hervor))
            x += w + luft
            index += 1
        y += hoehe_zeile
    return ergebnis


def _worte_zeichnen(leinwand: Image.Image, worte: list[_Wort], t: float, beginn: float,
                    abstand: float = 0.09, dauer: float = 0.32) -> None:
    """Wort für Wort: aus 125 % Größe herein, mit Deckkraft — der typische TikTok-Pop."""
    for i, wort in enumerate(worte):
        p = _phase(t, beginn + i * abstand, dauer)
        if p <= 0:
            continue
        skala = 1.25 - 0.25 * aus_kubisch(p)
        bild = wort.bild
        if abs(skala - 1) > 0.01:
            bild = bild.resize((max(1, int(bild.width * skala)), max(1, int(bild.height * skala))),
                               Image.BILINEAR)
        if p < 1:
            alpha = bild.getchannel("A").point(lambda v, q=weich(p * 1.6): int(v * min(1, q)))
            bild = bild.copy()
            bild.putalpha(alpha)
        x = wort.x - (bild.width - wort.bild.width) // 2
        y = wort.y - (bild.height - wort.bild.height) // 2
        leinwand.alpha_composite(bild, (x, y))


def _pille(text: str, art: str, groesse: int, *, grund, schriftfarbe,
           polster=(34, 16), radius: int | None = None) -> Image.Image:
    f = schrift(art, groesse)
    box = f.getbbox(text)
    b = box[2] - box[0] + polster[0] * 2
    h = int(groesse * 1.25) + polster[1] * 2
    bild = Image.new("RGBA", (b, h), (0, 0, 0, 0))
    z = ImageDraw.Draw(bild)
    z.rounded_rectangle((0, 0, b - 1, h - 1), radius=radius if radius is not None else h // 2,
                        fill=tuple(grund) + ((255,) if len(grund) == 3 else ()))
    z.text((polster[0] - box[0], polster[1] + int(groesse * 0.05)), text, font=f,
           fill=tuple(schriftfarbe) + ((255,) if len(schriftfarbe) == 3 else ()))
    return bild


def _mittig(leinwand: Image.Image, bild: Image.Image, y: int, deckung: float = 1.0,
            skala: float = 1.0, x: int | None = None) -> None:
    if deckung <= 0.01:
        return
    if abs(skala - 1) > 0.01:
        bild = bild.resize((max(1, int(bild.width * skala)), max(1, int(bild.height * skala))),
                           Image.BILINEAR)
    if deckung < 0.99:
        bild = bild.copy()
        bild.putalpha(bild.getchannel("A").point(lambda v: int(v * deckung)))
    links = (BREITE - bild.width) // 2 if x is None else x
    leinwand.alpha_composite(bild, (links, y - bild.height // 2))


class _Handy:
    """Ein Telefon, auf dessen Bildschirm die Webseite läuft."""

    def __init__(self, streifen: Image.Image, bildschirm_breite: int = 700):
        self.b = bildschirm_breite
        self.h = int(bildschirm_breite * 16 / 9)
        self.rand = int(bildschirm_breite * 0.035)
        faktor = self.b / streifen.width
        self.inhalt = streifen.convert("RGB").resize(
            (self.b, max(self.h, int(streifen.height * faktor))), Image.LANCZOS)
        radius = int(self.b * 0.12)
        gb, gh = self.b + self.rand * 2, self.h + self.rand * 2
        self.maske = _abgerundet((self.b, self.h), radius - self.rand)
        rahmen = Image.new("RGBA", (gb, gh), (0, 0, 0, 0))
        z = ImageDraw.Draw(rahmen)
        z.rounded_rectangle((0, 0, gb - 1, gh - 1), radius=radius, fill=(18, 18, 22, 255))
        z.rounded_rectangle((2, 2, gb - 3, gh - 3), radius=radius - 2,
                            outline=(90, 90, 100, 255), width=3)
        self.rahmen = rahmen
        # Der Schatten wird einmal als fertige RGBA-Fläche gebaut — je Bild nur eingesetzt.
        maske = _schatten((gb, gh), radius, 46, 170)
        self.schatten = Image.new("RGBA", maske.size, (0, 0, 0, 255))
        self.schatten.putalpha(maske)
        kerbe_b = int(self.b * 0.28)
        self.kerbe = (kerbe_b, int(self.b * 0.055))

    @property
    def groesse(self) -> tuple[int, int]:
        return self.rahmen.size

    def rendern(self, versatz: float) -> Image.Image:
        """Das Telefon mit Seiteninhalt; `versatz` 0…1 scrollt von oben nach unten."""
        weg = self.inhalt.height - self.h
        y = int(weg * _klemmen(versatz))
        bildschirm = self.inhalt.crop((0, y, self.b, y + self.h))
        bild = self.rahmen.copy()
        bild.paste(bildschirm, (self.rand, self.rand), self.maske)
        z = ImageDraw.Draw(bild)
        kb, kh = self.kerbe
        x0 = (bild.width - kb) // 2
        z.rounded_rectangle((x0, self.rand + 16, x0 + kb, self.rand + 16 + kh),
                            radius=kh // 2, fill=(8, 8, 10, 255))
        return bild

    def setzen(self, leinwand: Image.Image, mitte_x: int, mitte_y: int,
               versatz: float) -> None:
        """Setzt das Telefon mittig auf (mitte_x, mitte_y). Teile außerhalb der Leinwand
        werden abgeschnitten — Pillow nimmt dafür keine negativen Koordinaten."""
        bild = self.rendern(versatz)
        _einsetzen(leinwand, self.schatten, mitte_x - self.schatten.width // 2,
                   mitte_y - self.schatten.height // 2 + 30)
        _einsetzen(leinwand, bild, mitte_x - bild.width // 2, mitte_y - bild.height // 2)


def _einsetzen(leinwand: Image.Image, bild: Image.Image, x: int, y: int) -> None:
    """`alpha_composite`, das auch mit Teilen außerhalb der Leinwand zurechtkommt."""
    links, oben = max(0, -x), max(0, -y)
    rechts = min(bild.width, leinwand.width - x)
    unten = min(bild.height, leinwand.height - y)
    if rechts <= links or unten <= oben:
        return
    teil = bild if (links, oben, rechts, unten) == (0, 0, bild.width, bild.height) \
        else bild.crop((links, oben, rechts, unten))
    leinwand.alpha_composite(teil, (max(0, x), max(0, y)))


# ── Szenen ───────────────────────────────────────────────────────────────────

class _Film:
    """Hält alles Vorbereitete und zeichnet daraus Bild für Bild."""

    def __init__(self, aufnahme, konzept: Konzept, dauer: float):
        self.k = konzept
        stil = STILE.get(konzept.stil, STILE["energisch"])
        self.grundfarbe = stil["grund"]
        self.akzent = konzept.akzent
        self.takt = 60.0 / stil["bpm"]

        start = Image.open(aufnahme.start_mobil).convert("RGB")
        streifen_pfad = aufnahme.streifen_mobil or aufnahme.start_mobil
        streifen = Image.open(streifen_pfad).convert("RGB")
        self.grund = _hintergrund(start, self.grundfarbe, self.akzent)
        # Zwei fertig skalierte Telefone statt je Bild neu zu skalieren.
        self.handy = _Handy(streifen, 644)          # Enthüllung
        self.handy_klein = _Handy(streifen, 602)    # Scrollen

        details: list[Image.Image] = []
        for pfad in getattr(aufnahme, "bilder", [])[:3]:
            try:
                details.append(_cover(Image.open(pfad).convert("RGB"),
                                      int(BREITE * 1.1), int(HOEHE * 1.1)))
            except Exception:
                continue
        if len(details) < 3 and getattr(aufnahme, "desktop", None):
            try:
                desktop = Image.open(aufnahme.desktop).convert("RGB")
                details += [self._browserkarte(desktop, i) for i in range(3 - len(details))]
            except Exception:
                pass
        while len(details) < 3:
            details.append(_cover(start, int(BREITE * 1.1), int(HOEHE * 1.1)))
        self.details = details[:3]

        # Zeitplan: Gewichte für 20 s, auf die bestellte Länge gestreckt und auf den
        # Takt gerundet — die Schnitte sollen auf die Schläge fallen.
        gewichte = [("hook", 2.5), ("enthuellung", 2.5), ("scrollen", 6.0),
                    ("details", 4.0), ("cta", 5.0)]
        faktor = dauer / sum(g for _, g in gewichte)
        self.plan: list[tuple[str, float, float]] = []
        t = 0.0
        for name, gewicht in gewichte:
            laenge = max(self.takt * 2, round(gewicht * faktor / self.takt) * self.takt)
            self.plan.append((name, t, laenge))
            t += laenge
        self.dauer = t

        vorteile = [v for v in konzept.vorteile if v][:3] or [konzept.untertitel or konzept.marke]
        while len(vorteile) < 3:
            vorteile.append(vorteile[-1])
        self.vorteile = vorteile

        self.hook_worte = _worte_setzen(konzept.hook, "schwarz", 118, BREITE - 160 - RECHTS // 2,
                                        akzent=self.akzent,
                                        hervorheben=len(konzept.hook.split()) - 1,
                                        mitte_y=880, hoechstens_zeilen=4)
        self.marke_worte = _worte_setzen(konzept.marke, "schwarz", 104, BREITE - 180,
                                         mitte_y=360, hoechstens_zeilen=2)
        self.vorteil_worte = [
            _worte_setzen(v, "schwarz", 84, BREITE - 200, akzent=self.akzent,
                          hervorheben=0, mitte_y=330, hoechstens_zeilen=2)
            for v in self.vorteile]
        self.detail_worte = [
            _worte_setzen(v, "schwarz", 92, BREITE - 220, akzent=self.akzent,
                          hervorheben=0, mitte_y=UNTEN - 180, hoechstens_zeilen=2)
            for v in self.vorteile]
        verlauf = Image.linear_gradient("L").resize((1, HOEHE))
        self.detail_dunkel = Image.new("RGBA", (BREITE, HOEHE), (0, 0, 0, 255))
        self.detail_dunkel.putalpha(verlauf.point(
            lambda v: 0 if v < 90 else min(215, int((v - 90) * 1.3))).resize((BREITE, HOEHE)))
        self.zaehler = [_pille(f"0{i + 1} / 03", "fett", 30, grund=(255, 255, 255, 36),
                               schriftfarbe=(255, 255, 255)) for i in range(3)]
        self.pfeil = _pille("↓  Link in der Bio", "halb", 34, grund=(0, 0, 0, 0),
                            schriftfarbe=(255, 255, 255))
        # Die Farbflächen der Schlussszene: einmal weichgezeichnet, doppelt so groß wie
        # das Bild. Je Bild wird nur ein wandernder Ausschnitt genommen — vorher wurde
        # jedes Bild neu weichgezeichnet, bis zu 0,8 Sekunden lang.
        schein = Image.new("L", (BREITE // 3, HOEHE // 3), 0)
        z = ImageDraw.Draw(schein)
        z.ellipse((-schein.width * 0.2, -schein.height * 0.05, schein.width * 0.75,
                   schein.height * 0.55), fill=175)
        z.ellipse((schein.width * 0.35, schein.height * 0.5, schein.width * 1.25,
                   schein.height * 1.05), fill=125)
        schein = schein.filter(ImageFilter.GaussianBlur(55)).resize(
            (int(BREITE * 1.25), int(HOEHE * 1.25)), Image.BILINEAR)
        self.cta_schein = Image.new("RGBA", schein.size, self.akzent + (255,))
        self.cta_schein.putalpha(schein)
        self.cta_marke = _worte_setzen(konzept.marke, "schwarz", 128, BREITE - 180,
                                       mitte_y=760, hoechstens_zeilen=3)
        self.cta_text = _worte_setzen(konzept.cta, "fett", 70, BREITE - 220,
                                      mitte_y=1030, hoechstens_zeilen=2)
        self.kicker_host = _pille(konzept.host or konzept.marke, "halb", 38,
                                  grund=(255, 255, 255, 40), schriftfarbe=(255, 255, 255))
        self.kicker_das_ist = _pille("DAS IST", "fett", 34, grund=self.akzent,
                                     schriftfarbe=lesbar_auf(self.akzent))
        # Der Link-Knopf: weiß mit Akzentschrift — außer die Akzentfarbe ist zu hell für
        # Weiß, dann umgekehrt: Akzentfläche mit lesbarer Schrift.
        if lesbar_auf(self.akzent) == (255, 255, 255):
            knopf_grund, knopf_schrift = (255, 255, 255), self.akzent
        else:
            knopf_grund, knopf_schrift = self.akzent, lesbar_auf(self.akzent)
        self.pille_link = _pille(konzept.host or "Jetzt ansehen", "fett", 50,
                                 grund=knopf_grund, schriftfarbe=knopf_schrift,
                                 polster=(56, 26))

    def _browserkarte(self, desktop: Image.Image, stelle: int) -> Image.Image:
        """Ein Ausschnitt der Desktopansicht in einem Browserfenster auf dunklem Grund."""
        flaeche = Image.new("RGB", (int(BREITE * 1.1), int(HOEHE * 1.1)), self.grundfarbe)
        karte_b = int(flaeche.width * 0.86)
        inhalt = desktop.resize((karte_b, int(desktop.height * karte_b / desktop.width)),
                                Image.LANCZOS)
        leiste = 64
        karte = Image.new("RGB", (karte_b, inhalt.height + leiste), (28, 28, 34))
        z = ImageDraw.Draw(karte)
        for i, farbe in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
            z.ellipse((26 + i * 34, 22, 46 + i * 34, 42), fill=farbe)
        f = schrift("halb", 26)
        z.rounded_rectangle((150, 14, karte_b - 40, 50), radius=18, fill=(46, 46, 54))
        z.text((178, 17), self.k.host or self.k.marke, font=f, fill=(210, 210, 220))
        karte.paste(inhalt, (0, leiste))
        maske = _abgerundet(karte.size, 26)
        # Jede Karte etwas näher dran, abwechselnd auf die linke und rechte Seite der
        # Seite gerichtet — aber nie so weit, dass die Adresszeile aus dem Bild rutscht.
        skala = (1.0, 1.18, 1.18)[stelle % 3]
        karte = karte.resize((int(karte.width * skala), int(karte.height * skala)),
                             Image.LANCZOS)
        maske = maske.resize(karte.size, Image.LANCZOS)
        mitte = (flaeche.width - karte.width) // 2
        x = mitte + (0, 1, -1)[stelle % 3] * abs(mitte)
        y = (flaeche.height - karte.height) // 2 - int(HOEHE * 0.08)
        schatten = _schatten(karte.size, 26, 40, 160)
        flaeche.paste((0, 0, 0), (x - 80, y - 50), schatten)
        flaeche.paste(karte, (x, y), maske)
        return flaeche

    # ── Ein Bild ─────────────────────────────────────────────────────────────

    def bild(self, t: float) -> Image.Image:
        for name, beginn, laenge in self.plan:
            if t < beginn + laenge or name == "cta":
                lokal = t - beginn
                aktuell = getattr(self, "_" + name)(lokal, laenge)
                # Weicher Übergang in den letzten 0,22 s jeder Szene.
                ende = laenge - lokal
                if ende < 0.22 and name != "cta":
                    stelle = [p[0] for p in self.plan].index(name) + 1
                    naechste = self.plan[stelle]
                    folgend = getattr(self, "_" + naechste[0])(0.0, naechste[2])
                    mischung = weich(1 - ende / 0.22)
                    aktuell = Image.blend(aktuell, folgend, mischung)
                return aktuell
        return self._cta(self.plan[-1][2], self.plan[-1][2])

    def _leinwand(self, zoom: float) -> Image.Image:
        return _zoomausschnitt(self.grund, zoom).convert("RGBA")

    def _hook(self, t: float, laenge: float) -> Image.Image:
        l = self._leinwand(_phase(t, 0, laenge))
        _mittig(l, self.kicker_host, OBEN + 60, deckung=aus_kubisch(_phase(t, 0.05, 0.3)))
        _worte_zeichnen(l, self.hook_worte, t, 0.12, abstand=min(0.12, laenge * 0.5 /
                                                               max(1, len(self.hook_worte))))
        # Unterstrich in der Akzentfarbe, der unter dem Text aufgezogen wird.
        if self.hook_worte:
            unten = max(w.y + w.bild.height for w in self.hook_worte) + 36
            p = aus_kubisch(_phase(t, 0.5, 0.5))
            if p > 0:
                breite = int(420 * p)
                ImageDraw.Draw(l).rounded_rectangle(
                    ((BREITE - breite) // 2, unten, (BREITE + breite) // 2, unten + 14),
                    radius=7, fill=self.akzent + (255,))
        return l.convert("RGB")

    def _enthuellung(self, t: float, laenge: float) -> Image.Image:
        l = self._leinwand(1 - 0.3 * _phase(t, 0, laenge))
        p = aus_zurueck(_phase(t, 0.0, 0.7))
        mitte_y = int(HOEHE + 900 - (HOEHE + 900 - 1180) * p)
        self.handy.setzen(l, BREITE // 2, mitte_y, 0.0)
        _mittig(l, self.kicker_das_ist, OBEN + 40, deckung=aus_kubisch(_phase(t, 0.1, 0.3)))
        _worte_zeichnen(l, self.marke_worte, t, 0.25, abstand=0.08)
        return l.convert("RGB")

    def _scrollen(self, t: float, laenge: float) -> Image.Image:
        l = self._leinwand(0.7 + 0.3 * _phase(t, 0, laenge))
        versatz = weich(_phase(t, 0.3, laenge - 0.5))
        self.handy_klein.setzen(l, BREITE // 2, 1230, versatz)
        abschnitt = laenge / 3
        stelle = min(2, int(t / abschnitt))
        lokal = t - stelle * abschnitt
        _mittig(l, self.zaehler[stelle], OBEN + 10)
        _worte_zeichnen(l, self.vorteil_worte[stelle], lokal, 0.0, abstand=0.07, dauer=0.28)
        return l.convert("RGB")

    def _details(self, t: float, laenge: float) -> Image.Image:
        abschnitt = laenge / 3
        stelle = min(2, int(t / abschnitt))
        lokal = t - stelle * abschnitt
        quelle = self.details[stelle]
        zoom = 1.0 + 0.09 * _phase(lokal, 0, abschnitt)
        b, h = int(BREITE * 1.1 / zoom), int(HOEHE * 1.1 / zoom)
        x = (quelle.width - b) // 2 + int((stelle - 1) * 30 * _phase(lokal, 0, abschnitt))
        y = (quelle.height - h) // 2
        bild = quelle.crop((x, y, x + b, y + h)).resize((BREITE, HOEHE), Image.BILINEAR)
        l = bild.convert("RGBA")
        l.alpha_composite(self.detail_dunkel)
        # Blitz beim Schnitt: kurz aufhellen, das Auge folgt dem Takt.
        if lokal < 0.1:
            blitz = Image.new("RGBA", (BREITE, HOEHE), (255, 255, 255, int(120 * (1 - lokal / 0.1))))
            l.alpha_composite(blitz)
        _worte_zeichnen(l, self.detail_worte[stelle], lokal, 0.05, abstand=0.06, dauer=0.25)
        return l.convert("RGB")

    def _cta(self, t: float, laenge: float) -> Image.Image:
        l = Image.new("RGBA", (BREITE, HOEHE), self.grundfarbe + (255,))
        # Die Farbflächen wandern sanft — ein Ausschnitt aus der vorbereiteten Fläche.
        luft_x = self.cta_schein.width - BREITE
        luft_y = self.cta_schein.height - HOEHE
        x = int(luft_x * (0.5 + 0.45 * math.sin(t * 0.8)))
        y = int(luft_y * (0.5 + 0.45 * math.cos(t * 0.6)))
        l.alpha_composite(self.cta_schein.crop((x, y, x + BREITE, y + HOEHE)))

        _worte_zeichnen(l, self.cta_marke, t, 0.05, abstand=0.08)
        _worte_zeichnen(l, self.cta_text, t, 0.45, abstand=0.06)
        # Der Link als Knopf, der im Takt pulsiert.
        p = aus_zurueck(_phase(t, 0.8, 0.45))
        if p > 0:
            schlag = (t % self.takt) / self.takt
            puls = 1 + 0.035 * (1 - aus_kubisch(schlag)) if t > 1.25 else 1.0
            _mittig(l, self.pille_link, 1260, deckung=min(1, p), skala=p * puls)
            _mittig(l, self.pfeil, 1400, deckung=_phase(t, 1.3, 0.4))
        return l.convert("RGB")


# ── Musik ────────────────────────────────────────────────────────────────────

def musik_schreiben(ziel: Path, dauer: float, stil: str = "energisch",
                    schnitte: list[float] | None = None, rate: int = 44100) -> Path:
    """Ein Beat zum Video: Bassdrum, Klatscher, Hi-Hat, Basslinie, Rauschen vor Schnitten.

    Reines Python — kein Paket, keine Lizenz. Klingt nicht nach Studio, aber nach
    Absicht; und die Schläge liegen genau auf den Schnitten.
    """
    angaben = STILE.get(stil, STILE["energisch"])
    takt = 60.0 / angaben["bpm"]
    n = int(dauer * rate)
    spur = array.array("f", [0.0]) * n
    zufall = random.Random(7)

    def einmischen(klang: list[float], ab: float, lautstaerke: float) -> None:
        start = int(ab * rate)
        for i, wert in enumerate(klang):
            j = start + i
            if 0 <= j < n:
                spur[j] += wert * lautstaerke

    def kick() -> list[float]:
        laenge = int(0.28 * rate)
        klang, phase = [], 0.0
        for i in range(laenge):
            t = i / rate
            frequenz = 45 + 115 * math.exp(-t * 32)
            phase += 2 * math.pi * frequenz / rate
            klang.append(math.sin(phase) * math.exp(-t * 11))
        return klang

    def rauschen(laenge_s: float, abfall: float, hell: bool) -> list[float]:
        klang, vorher = [], 0.0
        for i in range(int(laenge_s * rate)):
            wert = zufall.uniform(-1, 1)
            if hell:
                wert, vorher = wert - vorher, wert
            klang.append(wert * math.exp(-(i / rate) * abfall))
        return klang

    def bass(frequenz: float, laenge_s: float) -> list[float]:
        return [math.sin(2 * math.pi * frequenz * i / rate) * 0.9 *
                min(1.0, i / 400) * math.exp(-(i / rate) * 3.2)
                for i in range(int(laenge_s * rate))]

    k, klatsch, hat = kick(), rauschen(0.18, 28, False), rauschen(0.05, 90, True)
    ruhig = stil == "edel"
    grundtoene = [55.0, 43.65, 65.41, 49.0]          # A – F – C – G
    schlag = 0
    t = 0.0
    while t < dauer - 0.05:
        einmischen(k, t, 0.9 if not ruhig else 0.7)
        if schlag % 4 in (1, 3):
            einmischen(klatsch, t, 0.32 if not ruhig else 0.18)
        einmischen(hat, t + takt / 2, 0.10 if not ruhig else 0.06)
        if not ruhig:
            einmischen(hat, t + takt / 4 * 3, 0.05)
        ton = grundtoene[(schlag // 4) % len(grundtoene)]
        einmischen(bass(ton, takt * 0.95), t, 0.35)
        schlag += 1
        t += takt

    for schnitt in schnitte or []:
        laenge = 0.45
        zisch = [w * (i / (laenge * rate)) ** 2 for i, w in
                 enumerate(rauschen(laenge, 0, True))]
        einmischen(zisch, max(0.0, schnitt - laenge), 0.16)

    spitze = max(1e-6, max(abs(v) for v in spur))
    ausblenden = int(0.8 * rate)
    daten = array.array("h", [0]) * n
    for i in range(n):
        wert = math.tanh(spur[i] / spitze * 1.6) * 0.72
        if i > n - ausblenden:
            wert *= (n - i) / ausblenden
        daten[i] = int(wert * 32767)
    with wave.open(str(ziel), "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(rate)
        datei.writeframes(daten.tobytes())
    return ziel


# ── Zusammensetzen ───────────────────────────────────────────────────────────

def _bilder_an_ffmpeg(film: _Film, ziel: Path, von: float, bis: float,
                      abbruch: threading.Event | None, melden, anteil_von: float,
                      anteil_bis: float) -> None:
    programm = config.ffmpeg_pfad()
    if not programm:
        raise errors.VerarbeitungsFehler("Es wurde kein ffmpeg gefunden.",
                                         "python -m pip install imageio-ffmpeg",
                                         ursprung=QUELLE)
    fehlerdatei = ziel.with_suffix(".log")
    befehl = [programm, "-hide_banner", "-loglevel", "error", "-y",
              "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{BREITE}x{HOEHE}",
              "-r", str(BILDRATE), "-i", "-",
              # Quadratische Pixel ausdrücklich setzen: Rohbilder haben kein
              # Pixelseitenverhältnis, und der concat-Filter weist Teile mit
              # abweichendem ab — dann scheiterte ausgerechnet der Film mit KI-Szene.
              "-vf", "setsar=1",
              # „faster“ statt „medium“: halbiert die Kodierzeit, und bei Flächen und
              # Schrift, wie sie hier entstehen, sieht man bei crf 19 keinen Unterschied.
              "-c:v", "libx264", "-preset", "faster", "-crf", "19",
              "-pix_fmt", "yuv420p", "-r", str(BILDRATE), "-movflags", "+faststart",
              str(ziel)]
    anzahl = max(1, int(round((bis - von) * BILDRATE)))
    with media._ffmpeg_schlange, open(fehlerdatei, "wb") as fehler:
        lauf = subprocess.Popen(befehl, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=fehler)
        try:
            for i in range(anzahl):
                if abbruch is not None and abbruch.is_set():
                    raise errors.AbbruchFehler("Schnitt abgebrochen.", ursprung=QUELLE)
                bild = film.bild(von + i / BILDRATE)
                lauf.stdin.write(bild.tobytes())
                if melden and i % 15 == 0:
                    melden(anteil_von + (anteil_bis - anteil_von) * i / anzahl)
            lauf.stdin.close()
            lauf.wait(timeout=600)
        except BaseException as fehler_lauf:
            # Jeder Fehler beim Zeichnen muss ffmpeg beenden — sonst wartet es ewig an
            # der offenen Eingabe, hält die ffmpeg-Sperre und den Arbeitsordner fest.
            lauf.kill()
            try:
                lauf.wait(timeout=10)
            except Exception:
                pass
            if isinstance(fehler_lauf, (errors.StudioFehler, KeyboardInterrupt)):
                raise
            text = fehlerdatei.read_text(encoding="utf-8", errors="replace")[:300] \
                if fehlerdatei.exists() else ""
            raise errors.VerarbeitungsFehler(
                "Der Videoschnitt ist abgebrochen.",
                text or f"{type(fehler_lauf).__name__}: {str(fehler_lauf)[:200]}",
                ursprung=QUELLE) from fehler_lauf
    text = fehlerdatei.read_text(encoding="utf-8", errors="replace") if \
        fehlerdatei.exists() else ""
    fehlerdatei.unlink(missing_ok=True)
    if lauf.returncode != 0:
        raise errors.VerarbeitungsFehler("Der Videoschnitt ist fehlgeschlagen.",
                                         " ".join(text.split())[:300], ursprung=QUELLE)


def _mit_ki_szene(film: "_Film", ki_clip: Path, arbeit: Path, ziel: Path,
                  schnitte: list[float], abbruch, melden) -> list[float]:
    """Vorderteil, KI-Szene und Hinterteil zu einem stummen Film verbinden."""
    nach_enthuellung = film.plan[2][1]
    vorne, hinten, ki = arbeit / "vorne.mp4", arbeit / "hinten.mp4", arbeit / "ki.mp4"
    _bilder_an_ffmpeg(film, vorne, 0.0, nach_enthuellung, abbruch, melden, 0.0, 0.35)
    media._normalisieren(ki_clip, ki, breite=BREITE, hoehe=HOEHE, bildrate=BILDRATE,
                         abbruch=abbruch)
    _bilder_an_ffmpeg(film, hinten, nach_enthuellung, film.dauer, abbruch, melden, 0.4, 0.85)
    teile = [vorne, ki, hinten]
    eingaben: list[str] = []
    for teil in teile:
        eingaben += ["-i", str(teil)]
    # Jeden Teil vor dem Verbinden auf dasselbe Raster bringen — auch wenn es schon
    # stimmt. Der concat-Filter bricht bei der kleinsten Abweichung ab.
    vorbereitung = ";".join(f"[{i}:v]scale={BREITE}:{HOEHE},setsar=1,fps={BILDRATE},"
                            f"format=yuv420p[t{i}]" for i in range(len(teile)))
    kette = "".join(f"[t{i}]" for i in range(len(teile)))
    media._ffmpeg([*eingaben, "-filter_complex",
                   f"{vorbereitung};{kette}concat=n={len(teile)}:v=1:a=0[v]",
                   "-map", "[v]", "-c:v", "libx264", "-preset", "faster", "-crf", "19",
                   "-pix_fmt", "yuv420p", str(ziel)],
                  beschreibung="Szenen verbinden", abbruch=abbruch)
    ki_dauer = media.angaben(ki).dauer
    neu = [s if s < nach_enthuellung else s + ki_dauer for s in schnitte]
    neu.insert(2, nach_enthuellung + ki_dauer)
    return sorted(neu)


def rendern(aufnahme, konzept: Konzept, ziel: Path, *, dauer: int = 20,
            musik: bool = True, ki_clip: Path | None = None,
            abbruch: threading.Event | None = None, melden=None) -> Path:
    """Rendert das Werbevideo. `ki_clip` wird nach der Enthüllung eingefügt."""
    ziel = Path(ziel)
    arbeit = ziel.parent / f".schnitt_{ziel.stem}"
    arbeit.mkdir(parents=True, exist_ok=True)
    try:
        logbook.info(QUELLE, "Szenen werden gezeichnet …")
        film = _Film(aufnahme, konzept, float(dauer))
        schnitte = [beginn for _, beginn, _ in film.plan[1:]]
        stumm_gesamt = arbeit / "gesamt.mp4"

        mit_ki = False
        if ki_clip and Path(ki_clip).exists():
            try:
                schnitte = _mit_ki_szene(film, Path(ki_clip), arbeit, stumm_gesamt,
                                         schnitte, abbruch, melden)
                mit_ki = True
            except errors.AbbruchFehler:
                raise
            except errors.StudioFehler as fehler:
                # Die KI-Szene ist Beiwerk und womöglich schon bezahlt — aber ein Film
                # ohne sie ist besser als gar keiner.
                logbook.warnung(QUELLE, f"Die KI-Szene ließ sich nicht einfügen "
                                        f"({fehler.meldung}) — das Video entsteht ohne sie.")
                schnitte = [beginn for _, beginn, _ in film.plan[1:]]
        if not mit_ki:
            stumm = arbeit / "bild.mp4"
            _bilder_an_ffmpeg(film, stumm, 0.0, film.dauer, abbruch, melden, 0.0, 0.85)
            stumm.replace(stumm_gesamt)
        gesamt = media.angaben(stumm_gesamt).dauer or film.dauer

        if musik:
            ton = musik_schreiben(arbeit / "musik.wav", gesamt, konzept.stil, schnitte)
            media._ffmpeg(["-i", str(stumm_gesamt), "-i", str(ton), "-map", "0:v", "-map",
                           "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                           "-shortest", "-movflags", "+faststart", str(ziel)],
                          beschreibung="Musik anlegen", abbruch=abbruch)
        else:
            stumm_gesamt.replace(ziel)
        if melden:
            melden(1.0)
        return ziel
    finally:
        import shutil
        shutil.rmtree(arbeit, ignore_errors=True)
