"""
webaufnahme.py — eine Webseite prüfen, fotografieren und auslesen.

Der erste Teil der Funktion „Webseite → TikTok-Werbevideo“. Aus einem Link entstehen:

  * ein **Prüfbericht** — erreichbar? echte Webseite? Titel, Beschreibung, Vorschaubild;
  * **Aufnahmen** — die Startansicht auf dem Handy, ein langer Streifen der Seite zum
    Durchscrollen im Video, die Desktop-Ansicht und die großen Bilder der Seite;
  * die **Texte**, aus denen das Konzept entsteht: Marke, Überschriften, Knöpfe,
    Telefonnummer, Markenfarbe.

**Zwei Wege zum Foto, damit es beim Kunden sicher klappt.**
Erste Wahl ist Playwright mit dem Edge, der auf jedem Windows-11-Rechner liegt — es muss
kein Browser heruntergeladen werden. Playwright kann Cookie-Banner wegklicken, nachladende
Bilder abwarten und die Seite als Handy darstellen. Fehlt das Paket oder startet es nicht,
fotografiert Edge (oder Chrome) direkt über seine Kommandozeile. Das kann weniger, braucht
aber nichts außer dem Browser selbst.

**Zur Sicherheit.** Es werden nur `http`- und `https`-Adressen im öffentlichen Netz
angenommen. Adressen, die auf diesen Rechner oder ins Heimnetz zeigen, lehnt die Prüfung
ab — ein Werkzeug, das beliebige lokale Dienste aufruft und fotografiert, gehört nicht
auf einen Arbeitsrechner.
"""
from __future__ import annotations

import html
import ipaddress
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import httpx

from . import config, errors, logbook

QUELLE = "Webseite"

_UA_DESKTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0")
_UA_MOBIL = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36")

#: Handy-Ansicht: 412 × 732 CSS-Pixel mit Faktor 2,625 ergibt 1081 × 1921 — also genau
#: das TikTok-Raster. So wird nichts hochgerechnet.
MOBIL_BREITE, MOBIL_HOEHE, MOBIL_FAKTOR = 412, 732, 2.625
#: So viele Bildschirmhöhen umfasst der Streifen zum Durchscrollen höchstens.
STREIFEN_SCHIRME = 6


# ── Adresse prüfen ───────────────────────────────────────────────────────────

def adresse_normieren(roh: str) -> str:
    """„meinbetrieb.de“ → „https://meinbetrieb.de/“. Wirft bei Unsinn."""
    text = (roh or "").strip().strip("<>\"'")
    if not text:
        raise errors.EingabeFehler("Bitte einen Link eingeben.",
                                   "Zum Beispiel: meinbetrieb.de", ursprung=QUELLE)
    if len(text) > 2000:
        raise errors.EingabeFehler("Der Link ist zu lang.", ursprung=QUELLE)
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        text = "https://" + text
    teile = urllib.parse.urlsplit(text)
    if teile.scheme.lower() not in ("http", "https"):
        raise errors.EingabeFehler("Nur Links auf Webseiten (http/https) sind möglich.",
                                   ursprung=QUELLE)
    host = (teile.hostname or "").lower()
    if not host or ("." not in host and not _ist_ip(host)):
        raise errors.EingabeFehler("Das sieht nicht nach einer Webadresse aus.",
                                   "Zum Beispiel: meinbetrieb.de", ursprung=QUELLE)
    pfad = teile.path or "/"
    return urllib.parse.urlunsplit((teile.scheme.lower(), teile.netloc, pfad,
                                    teile.query, ""))


def _ist_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


#: NAT64 — ein IPv6-Netz, in dem eine IPv4-Adresse steckt (RFC 6052). In Mobilfunk-
#: und manchen Anschlussnetzen liefert der Namensdienst nur noch solche Adressen.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _entpackt(ip):
    """Holt die IPv4-Adresse heraus, wenn sie in einer IPv6-Adresse steckt.

    Ohne das galt eine ganz gewöhnliche Webseite auf diesem Anschluss als „nicht
    öffentlich": Der Namensdienst liefert hier `64:ff9b::452e:2e73`, und Python führt
    dieses Netz als *reserviert*. Geprüft werden muss aber die Adresse, die wirklich
    angesprochen wird — die IPv4 darin (hier 69.46.46.115, öffentlich).
    """
    if getattr(ip, "ipv4_mapped", None):
        return ip.ipv4_mapped
    if getattr(ip, "sixtofour", None):
        return ip.sixtofour
    if ip.version == 6 and ip in _NAT64:
        return ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
    return ip


def _oeffentlich(host: str) -> bool:
    """Zeigt der Name ausschließlich auf öffentliche Adressen?"""
    if host in ("localhost",) or host.endswith((".local", ".localhost", ".internal")):
        return False
    try:
        adressen = {eintrag[4][0] for eintrag in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return True             # nicht auflösbar — das meldet gleich der Abruf selbst
    for adresse in adressen:
        try:
            ip = ipaddress.ip_address(adresse.split("%")[0])
        except ValueError:
            continue
        ip = _entpackt(ip)
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def sicher_abrufen(url: str, *, kopf: dict | None = None, zeitlimit: float = 20,
                   hoechstens: int = 6) -> httpx.Response:
    """Ein GET, der jede Weiterleitung einzeln prüft.

    Mit `follow_redirects=True` würde httpx einer Weiterleitung auf eine Adresse im
    eigenen Netz folgen und sie abfragen, **bevor** eine Prüfung greift. Deshalb werden
    Weiterleitungen hier von Hand verfolgt, und jeder Schritt muss öffentlich sein.
    """
    aktuell = url
    with httpx.Client(timeout=zeitlimit, follow_redirects=False, headers=kopf or {}) as k:
        for _ in range(hoechstens):
            teile = urllib.parse.urlsplit(aktuell)
            if teile.scheme.lower() not in ("http", "https") or \
                    not _oeffentlich((teile.hostname or "").lower()):
                raise errors.EingabeFehler(
                    "Die Seite leitet auf eine nicht öffentliche Adresse um.",
                    "Es lassen sich nur öffentlich erreichbare Webseiten verwenden.",
                    ursprung=QUELLE)
            antwort = k.get(aktuell)
            ziel = antwort.headers.get("location")
            if antwort.is_redirect and ziel:
                aktuell = urllib.parse.urljoin(str(antwort.url), ziel)
                continue
            return antwort
    raise errors.NetzFehler("Die Webseite leitet zu oft weiter.",
                            "Bitte die Adresse prüfen, die im Browser am Ende erscheint.",
                            ursprung=QUELLE)


class _Leser(HTMLParser):
    """Liest aus rohem HTML, was ohne Browser zu haben ist."""

    def __init__(self, basis: str):
        super().__init__(convert_charrefs=True)
        self.basis = basis
        self.titel = ""
        self.meta: dict[str, str] = {}
        self.ueberschriften: list[str] = []
        self.knoepfe: list[str] = []
        self.bilder: list[str] = []
        self.icons: list[str] = []
        self._in: list[str] = []
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            schluessel = (a.get("property") or a.get("name") or "").lower()
            if schluessel and a.get("content"):
                self.meta.setdefault(schluessel, a["content"].strip())
        elif tag == "link" and "icon" in a.get("rel", "").lower() and a.get("href"):
            self.icons.append(urllib.parse.urljoin(self.basis, a["href"]))
        elif tag == "img" and (a.get("src") or a.get("data-src")):
            self.bilder.append(urllib.parse.urljoin(self.basis,
                                                    a.get("src") or a.get("data-src")))
        if tag in ("title", "h1", "h2", "h3", "button", "a"):
            self._in.append(tag)
            self._text.append("")

    def handle_endtag(self, tag):
        if self._in and self._in[-1] == tag:
            self._in.pop()
            text = " ".join(self._text.pop().split())
            if tag == "title":
                self.titel = self.titel or text
            elif tag in ("h1", "h2", "h3") and 2 < len(text) < 140:
                self.ueberschriften.append(text)
            elif tag in ("button", "a") and 1 < len(text) < 40:
                self.knoepfe.append(text)

    def handle_data(self, data):
        if self._text:
            self._text[-1] += " " + data


def adresse_pruefen(roh: str) -> dict:
    """Prüft einen Link und liefert, was die Oberfläche als Vorschau zeigt.

    Wirft `EingabeFehler` bei ungültigen oder unzulässigen Adressen und `NetzFehler`,
    wenn die Seite nicht erreichbar ist — beides mit einem Satz, den der Kunde versteht.
    """
    url = adresse_normieren(roh)
    host = urllib.parse.urlsplit(url).hostname or ""
    if not _oeffentlich(host):
        raise errors.EingabeFehler(
            "Diese Adresse zeigt nicht ins öffentliche Internet.",
            "Es lassen sich nur öffentlich erreichbare Webseiten verwenden.",
            ursprung=QUELLE)

    begonnen = time.monotonic()
    antwort = None
    letzter: Exception | None = None
    kandidaten = [url]
    if url.startswith("https://"):
        kandidaten.append("http://" + url[len("https://"):])
    for versuch in kandidaten:
        try:
            antwort = sicher_abrufen(versuch, kopf={
                "User-Agent": _UA_DESKTOP, "Accept-Language": "de-DE,de;q=0.9,en;q=0.6"})
            break
        except httpx.HTTPError as fehler:
            letzter = fehler
            antwort = None
    if antwort is None:
        grund = type(letzter).__name__ if letzter else "unbekannt"
        raise errors.NetzFehler(
            "Die Webseite ist nicht erreichbar.",
            f"Stimmt der Link? Ist die Seite online? (Technischer Grund: {grund})",
            ursprung=QUELLE)

    endadresse = str(antwort.url)
    endhost = antwort.url.host or host
    if endhost != host and not _oeffentlich(endhost):
        raise errors.EingabeFehler("Die Seite leitet auf eine nicht öffentliche Adresse um.",
                                   ursprung=QUELLE)
    if antwort.status_code >= 400:
        raise errors.EingabeFehler(
            f"Die Webseite antwortet mit einem Fehler (Code {antwort.status_code}).",
            "Stimmt der Link? Manche Seiten sperren automatische Abrufe — dann lieber "
            "die Startseite versuchen.", ursprung=QUELLE)
    art = antwort.headers.get("content-type", "").lower()
    if "html" not in art and "xml" not in art:
        raise errors.EingabeFehler("Unter diesem Link liegt keine Webseite.",
                                   f"Gefunden wurde: {art or 'unbekannter Inhalt'}.",
                                   ursprung=QUELLE)

    leser = _Leser(endadresse)
    try:
        leser.feed(antwort.text[:1_500_000])
    except Exception:
        pass
    meta = leser.meta
    titel = html.unescape(meta.get("og:title") or leser.titel or endhost)[:160]
    beschreibung = html.unescape(meta.get("og:description") or
                                 meta.get("description") or "")[:300]
    bild = meta.get("og:image") or meta.get("twitter:image") or ""
    return {
        "url": endadresse,
        "host": endhost.removeprefix("www."),
        "titel": titel,
        "beschreibung": beschreibung,
        "bild": urllib.parse.urljoin(endadresse, bild) if bild else "",
        "favicon": leser.icons[0] if leser.icons else
                   f"{antwort.url.scheme}://{endhost}/favicon.ico",
        "marke": html.unescape(meta.get("og:site_name") or "")[:80],
        "farbe": meta.get("theme-color", "")[:20],
        "ueberschriften": leser.ueberschriften[:12],
        "knoepfe": leser.knoepfe[:40],
        "bilder": leser.bilder[:30],
        "dauer_ms": int((time.monotonic() - begonnen) * 1000),
        "status": antwort.status_code,
    }


# ── Aufnahmen ────────────────────────────────────────────────────────────────

@dataclass
class Aufnahme:
    """Was von einer Webseite fürs Video gebraucht wird."""
    url: str
    host: str
    start_mobil: Path | None = None       # Startansicht auf dem Handy (≈1080×1920)
    streifen_mobil: Path | None = None    # die Seite von oben nach unten, zum Scrollen
    desktop: Path | None = None           # Startansicht am Rechner (1440×900)
    bilder: list[Path] = field(default_factory=list)
    texte: dict = field(default_factory=dict)
    weg: str = ""

    def als_dict(self) -> dict:
        from . import library
        return {"url": self.url, "host": self.host, "weg": self.weg,
                "start_mobil": library.web_pfad(self.start_mobil),
                "streifen_mobil": library.web_pfad(self.streifen_mobil),
                "desktop": library.web_pfad(self.desktop),
                "bilder": [library.web_pfad(b) for b in self.bilder],
                "texte": self.texte}


#: Liest im Browser alles, was das Konzept braucht. Läuft in der Seite selbst.
_JS_TEXTE = r"""
() => {
  const sauber = (t) => (t || "").replace(/\s+/g, " ").trim();
  const sichtbar = (el) => {
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && s.visibility !== "hidden" && s.display !== "none";
  };
  const meta = (n) => {
    const el = document.querySelector(`meta[property="${n}"], meta[name="${n}"]`);
    return el ? sauber(el.content) : "";
  };
  const ueberschriften = [...document.querySelectorAll("h1, h2, h3")]
    .filter(sichtbar).map((e) => sauber(e.innerText)).filter((t) => t.length > 2 && t.length < 140);
  const knoepfe = [...document.querySelectorAll("a, button")]
    .filter(sichtbar).map((e) => sauber(e.innerText)).filter((t) => t.length > 1 && t.length < 40);
  const bilder = [...document.images]
    .filter((i) => i.naturalWidth >= 500 && i.naturalHeight >= 300 && sichtbar(i))
    .sort((a, b) => b.naturalWidth * b.naturalHeight - a.naturalWidth * a.naturalHeight)
    .map((i) => i.currentSrc || i.src).filter((s) => s && !s.startsWith("data:"));
  const text = sauber(document.body ? document.body.innerText : "").slice(0, 6000);
  const telefon = (text.match(/(\+?\d[\d\s\/\-()]{7,}\d)/) || [""])[0];
  // Markenfarbe: der Hintergrund des auffälligsten Knopfes, sonst theme-color.
  let farbe = meta("theme-color");
  for (const el of [...document.querySelectorAll("a, button")].filter(sichtbar).slice(0, 80)) {
    const bg = getComputedStyle(el).backgroundColor;
    const m = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/);
    if (!m || (m[4] !== undefined && Number(m[4]) < 0.6)) continue;
    const [r, g, b] = [Number(m[1]), Number(m[2]), Number(m[3])];
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    if (max - min > 60 && max > 80) { farbe = `rgb(${r},${g},${b})`; break; }
  }
  const logo = [...document.querySelectorAll("img")].find((i) =>
    /logo/i.test((i.alt || "") + (i.className || "") + (i.src || "")) && sichtbar(i));
  return {
    titel: sauber(document.title), beschreibung: meta("og:description") || meta("description"),
    marke: meta("og:site_name"), ueberschriften: ueberschriften.slice(0, 16),
    knoepfe: [...new Set(knoepfe)].slice(0, 40), bilder: [...new Set(bilder)].slice(0, 8),
    telefon, farbe, logo: logo ? (logo.currentSrc || logo.src) : "", text,
  };
}
"""

#: Klickt übliche Zustimmungsknöpfe weg und blendet übrig gebliebene Banner aus.
_JS_BANNER = r"""
() => {
  const woerter = /^(alle[s]?\s+)?(akzeptieren|zustimmen|annehmen|einverstanden|verstanden|ok|okay|accept( all)?( cookies)?|allow all|agree|i agree|got it|alle cookies akzeptieren|cookies zulassen|zulassen)\b/i;
  let geklickt = 0;
  for (const el of document.querySelectorAll("button, a, [role=button], input[type=button], input[type=submit]")) {
    const t = (el.innerText || el.value || "").trim();
    if (t && t.length < 40 && woerter.test(t)) {
      try { el.click(); geklickt++; } catch (e) {}
      if (geklickt >= 2) break;
    }
  }
  // Bekannte Banner-Wurzeln — viele liegen im Shadow-DOM und sind nur über ihren
  // Wirt zu fassen (Usercentrics bei dm.de: #usercentrics-root).
  for (const el of document.querySelectorAll(
      "#usercentrics-root, #usercentrics-cmp-ui, #CybotCookiebotDialog, #onetrust-consent-sdk, " +
      "#didomi-host, .cc-window, #cmpbox, #cmpbox2, #BorlabsCookieBox, .borlabs-cookie, " +
      "#cookie-law-info-bar, #moove_gdpr_cookie_info_bar, .cmplz-cookiebanner, " +
      "[id^='sp_message_container'], .sp_veil, #cookiebanner, #cookie-banner, .cookie-banner")) {
    el.style.setProperty("display", "none", "important");
  }
  const muster = /(cookie|consent|datenschutz|privacy|gdpr|dsgvo|usercentrics|cookiebot|onetrust|borlabs)/i;
  for (const el of document.querySelectorAll("body *")) {
    const s = getComputedStyle(el);
    if (s.position !== "fixed" && s.position !== "sticky") continue;
    const kennung = (el.id || "") + " " + (el.className && el.className.toString ? el.className.toString() : "");
    const r = el.getBoundingClientRect();
    const gross = r.width * r.height > window.innerWidth * window.innerHeight * 0.18;
    if (muster.test(kennung) || (gross && muster.test((el.innerText || "").slice(0, 400)))) {
      el.style.setProperty("display", "none", "important");
    }
  }
  document.documentElement.style.setProperty("overflow", "auto", "important");
  if (document.body) document.body.style.setProperty("overflow", "auto", "important");
  return geklickt;
}
"""


def aufnehmen(url: str, ordner: Path, *, abbruch: threading.Event | None = None,
              melden=None) -> Aufnahme:
    """Fotografiert die Seite und liest ihre Texte. Wirft nur, wenn gar nichts gelingt."""
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    pruefung = adresse_pruefen(url)
    aufnahme = Aufnahme(url=pruefung["url"], host=pruefung["host"])
    aufnahme.texte = {k: pruefung.get(k) for k in ("titel", "beschreibung", "marke",
                                                    "farbe", "ueberschriften", "knoepfe")}

    gruende: list[str] = []
    try:
        _mit_playwright(aufnahme, ordner, abbruch, melden)
        aufnahme.weg = "Playwright"
    except errors.AbbruchFehler:
        raise
    except Exception as fehler:
        gruende.append(f"Playwright: {type(fehler).__name__}: {str(fehler)[:160]}")
        logbook.info(QUELLE, "Aufnahme über Playwright nicht möglich — es wird der "
                             "Browser direkt verwendet.")
        try:
            _mit_browser_direkt(aufnahme, ordner, abbruch, melden)
            aufnahme.weg = "Browser direkt"
        except errors.AbbruchFehler:
            raise
        except Exception as zweiter:
            gruende.append(f"Browser: {type(zweiter).__name__}: {str(zweiter)[:160]}")

    if not aufnahme.start_mobil or not aufnahme.start_mobil.exists():
        logbook.warnung(QUELLE, "Aufnahme gescheitert: " + " | ".join(gruende))
        raise errors.VerarbeitungsFehler(
            "Die Webseite ließ sich nicht fotografieren.",
            "Dafür wird Microsoft Edge oder Google Chrome gebraucht. Bitte oben auf "
            "„Update“ klicken; bleibt es dabei, das Logbuch weitergeben.",
            ursprung=QUELLE, details={"gruende": gruende})

    # Fehlende Texte aus der HTML-Prüfung ergänzen, Bilder der Seite holen.
    for schluessel, wert in pruefung.items():
        if schluessel in ("ueberschriften", "knoepfe", "bilder") and not \
                aufnahme.texte.get(schluessel):
            aufnahme.texte[schluessel] = wert
        elif isinstance(wert, str) and not aufnahme.texte.get(schluessel):
            aufnahme.texte[schluessel] = wert
    aufnahme.bilder = _bilder_holen(aufnahme.texte.get("bilder") or
                                    ([pruefung["bild"]] if pruefung.get("bild") else []),
                                    ordner, abbruch)
    logbook.erfolg(QUELLE, f"{aufnahme.host} aufgenommen ({aufnahme.weg}): "
                           f"{len(aufnahme.bilder)} Bild(er) der Seite.")
    return aufnahme


def _pruefe_abbruch(abbruch) -> None:
    if abbruch is not None and abbruch.is_set():
        raise errors.AbbruchFehler("Abgebrochen.", ursprung=QUELLE)


def _mit_playwright(aufnahme: Aufnahme, ordner: Path, abbruch, melden) -> None:
    from playwright.sync_api import sync_playwright   # noqa: WPS433 — bewusst spät

    with sync_playwright() as pw:
        browser, gruende = None, []
        # Erst die installierten Browser — dann muss nichts heruntergeladen werden.
        for kanal in ("msedge", "chrome", ""):
            try:
                browser = (pw.chromium.launch(channel=kanal, headless=True) if kanal
                           else pw.chromium.launch(headless=True))
                break
            except Exception as fehler:
                gruende.append(f"{kanal or 'chromium'}: {str(fehler)[:80]}")
        if browser is None:
            raise RuntimeError("Kein Browser startbar — " + "; ".join(gruende))
        try:
            _pruefe_abbruch(abbruch)
            handy = browser.new_context(
                viewport={"width": MOBIL_BREITE, "height": MOBIL_HOEHE},
                device_scale_factor=MOBIL_FAKTOR, is_mobile=True, has_touch=True,
                user_agent=_UA_MOBIL, locale="de-DE")
            handy.route("**/*", _nur_oeffentlich)
            seite = handy.new_page()
            _laden(seite, aufnahme.url)
            if melden:
                melden(0.35, "Handyansicht")
            _pruefe_abbruch(abbruch)

            aufnahme.start_mobil = ordner / "aufnahme_handy_start.png"
            seite.screenshot(path=str(aufnahme.start_mobil))
            hoehe = int(seite.evaluate("() => document.documentElement.scrollHeight") or 0)
            streifen = max(MOBIL_HOEHE, min(hoehe, MOBIL_HOEHE * STREIFEN_SCHIRME))
            aufnahme.streifen_mobil = ordner / "aufnahme_handy_seite.png"
            seite.screenshot(path=str(aufnahme.streifen_mobil), full_page=True,
                             clip={"x": 0, "y": 0, "width": MOBIL_BREITE, "height": streifen})
            try:
                texte = seite.evaluate(_JS_TEXTE) or {}
                aufnahme.texte.update({k: v for k, v in texte.items() if v})
            except Exception:
                pass
            handy.close()
            if melden:
                melden(0.7, "Desktopansicht")
            _pruefe_abbruch(abbruch)

            rechner = browser.new_context(viewport={"width": 1440, "height": 900},
                                          device_scale_factor=1, user_agent=_UA_DESKTOP,
                                          locale="de-DE")
            rechner.route("**/*", _nur_oeffentlich)
            seite = rechner.new_page()
            _laden(seite, aufnahme.url)
            aufnahme.desktop = ordner / "aufnahme_desktop.png"
            seite.screenshot(path=str(aufnahme.desktop))
            rechner.close()
        finally:
            browser.close()


def _nur_oeffentlich(route) -> None:
    """Sperrt jede Anfrage der fotografierten Seite an diesen Rechner oder das Heimnetz.

    Eine Webseite könnte per Skript `http://127.0.0.1:7788/…` laden — dann landete
    etwa das Logbuch dieses Programms im Werbevideo. Geprüft wird ohne Namensauflösung
    (sie kostete bei jeder der hundert Anfragen einer Seite Zeit): Namen wie
    `localhost` und nackte private Adressen werden abgewiesen.
    """
    try:
        host = (urllib.parse.urlsplit(route.request.url).hostname or "").lower()
        privat = host in ("localhost",) or host.endswith((".local", ".localhost",
                                                          ".internal"))
        if not privat and host:
            try:
                ip = ipaddress.ip_address(host.strip("[]"))
                privat = (ip.is_private or ip.is_loopback or ip.is_link_local or
                          ip.is_reserved or ip.is_unspecified)
            except ValueError:
                pass
        if privat:
            route.abort()
        else:
            route.continue_()
    except Exception:
        try:
            route.continue_()
        except Exception:
            pass


def _laden(seite, url: str) -> None:
    """Seite laden, Banner wegräumen, nachladende Bilder abwarten, nach oben zurück."""
    seite.goto(url, wait_until="domcontentloaded", timeout=45000)
    # Der Browser folgt Weiterleitungen selbst. Die Adresse kommt schon geprüft und mit
    # aufgelösten Weiterleitungen aus `adresse_pruefen`; landet er trotzdem anderswo
    # (etwa per Skript), wird nichts von dort fotografiert.
    endhost = (urllib.parse.urlsplit(seite.url).hostname or "").lower()
    if endhost and not _oeffentlich(endhost):
        raise errors.EingabeFehler("Die Seite leitet auf eine nicht öffentliche Adresse um.",
                                   ursprung=QUELLE)
    try:
        seite.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    _banner_wegklicken(seite)
    for rahmen in [seite.main_frame, *seite.frames[1:6]]:
        try:
            rahmen.evaluate(_JS_BANNER)
        except Exception:
            pass
    try:
        seite.evaluate("""async () => {
            const schritt = window.innerHeight * 0.8;
            for (let y = 0; y < Math.min(document.body.scrollHeight, schritt * 10); y += schritt) {
              window.scrollTo(0, y); await new Promise(r => setTimeout(r, 140));
            }
            window.scrollTo(0, 0);
        }""")
        seite.wait_for_timeout(700)
        seite.evaluate(_JS_BANNER)
        # Animationen der Seite anhalten, damit nichts halb eingeblendet fotografiert wird.
        seite.add_style_tag(content="*,*::before,*::after{animation-duration:0s!important;"
                                    "transition-duration:0s!important}")
        seite.wait_for_timeout(250)
    except Exception:
        pass


#: Zuerst ablehnen: Für ein Foto der Seite braucht es keine Einwilligung in Werbe- und
#: Statistik-Cookies. Nur wo es keinen Ablehnen-Knopf gibt, wird zugestimmt.
_ABLEHNEN = re.compile(
    r"^\s*(alle\s+)?(ablehnen|einwilligung ablehnen|nicht zustimmen|"
    r"nur\s+(notwendige|essenzielle|essentielle|erforderliche|technisch notwendige)"
    r"(\s+cookies)?(\s+(akzeptieren|zulassen|erlauben))?|"
    r"reject(\s+all)?|decline(\s+all)?|deny|only necessary|necessary only)\b", re.IGNORECASE)
_ANNEHMEN = re.compile(
    r"^\s*(alle[s]?\s+)?(akzeptieren|zustimmen|annehmen|einverstanden|verstanden|ok|okay|"
    r"accept(\s+all)?(\s+cookies)?|allow all|agree|i agree|got it|"
    r"alle cookies akzeptieren|cookies (zulassen|akzeptieren)|zulassen)\b", re.IGNORECASE)


def _banner_wegklicken(seite) -> bool:
    """Klickt einen Cookie-Banner weg — auch im Shadow-DOM und in Rahmen.

    Die Rollen-Suche von Playwright durchdringt offenes Shadow-DOM; ein
    `querySelectorAll` im Seitenskript tut das nicht. Genau daran blieb der Banner von
    dm.de (Usercentrics) beim ersten Härtetest am 11.09.2026 im Bild.
    """
    rahmen = [seite.main_frame, *[f for f in seite.frames if f != seite.main_frame][:6]]
    for muster in (_ABLEHNEN, _ANNEHMEN):
        for teil in rahmen:
            for rolle in ("button", "link"):
                try:
                    knopf = teil.get_by_role(rolle, name=muster)
                    if knopf.count() == 0:
                        continue
                    erster = knopf.first
                    if not erster.is_visible():
                        continue
                    erster.click(timeout=2500)
                    seite.wait_for_timeout(700)
                    return True
                except Exception:
                    continue
    return False


def browser_pfad() -> str:
    """Pfad zu einem installierten Edge oder Chrome — leer, wenn keiner da ist."""
    kandidaten = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for name in ("msedge", "chrome", "google-chrome", "chromium"):
        gefunden = shutil.which(name)
        if gefunden:
            kandidaten.insert(0, gefunden)
    return next((k for k in kandidaten if Path(k).exists()), "")


def _mit_browser_direkt(aufnahme: Aufnahme, ordner: Path, abbruch, melden) -> None:
    """Edge oder Chrome ohne Playwright: ein Foto je Aufruf, über die Kommandozeile."""
    programm = browser_pfad()
    if not programm:
        raise RuntimeError("Weder Edge noch Chrome gefunden.")
    profil = ordner / ".browserprofil"

    def foto(ziel: Path, breite: int, hoehe: int, faktor: float, ua: str) -> Path:
        _pruefe_abbruch(abbruch)
        befehl = [programm, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                  "--no-first-run", "--no-default-browser-check", "--mute-audio",
                  f"--user-data-dir={profil}", f"--window-size={breite},{hoehe}",
                  f"--force-device-scale-factor={faktor}", f"--user-agent={ua}",
                  "--virtual-time-budget=9000", f"--screenshot={ziel}", aufnahme.url]
        subprocess.run(befehl, capture_output=True, timeout=90)
        if not ziel.exists() or ziel.stat().st_size < 2000:
            raise RuntimeError("Der Browser hat kein Bild geliefert.")
        return ziel

    try:
        aufnahme.start_mobil = foto(ordner / "aufnahme_handy_start.png", MOBIL_BREITE,
                                    MOBIL_HOEHE, MOBIL_FAKTOR, _UA_MOBIL)
        if melden:
            melden(0.4, "Handyansicht")
        try:
            aufnahme.streifen_mobil = foto(ordner / "aufnahme_handy_seite.png",
                                           MOBIL_BREITE, MOBIL_HOEHE * 4, MOBIL_FAKTOR,
                                           _UA_MOBIL)
        except Exception:
            aufnahme.streifen_mobil = aufnahme.start_mobil
        if melden:
            melden(0.7, "Desktopansicht")
        try:
            aufnahme.desktop = foto(ordner / "aufnahme_desktop.png", 1440, 900, 1,
                                    _UA_DESKTOP)
        except Exception:
            aufnahme.desktop = None
    finally:
        shutil.rmtree(profil, ignore_errors=True)


def _bilder_holen(adressen: list[str], ordner: Path, abbruch) -> list[Path]:
    """Lädt bis zu vier große Bilder der Seite — Produkte, Räume, Menschen."""
    from PIL import Image

    gespeichert: list[Path] = []
    for adresse in adressen[:10]:
        if len(gespeichert) >= 4:
            break
        _pruefe_abbruch(abbruch)
        if not str(adresse).startswith(("http://", "https://")):
            continue
        try:
            antwort = sicher_abrufen(adresse, kopf={"User-Agent": _UA_DESKTOP})
            if antwort.status_code >= 400 or len(antwort.content) < 15000:
                continue
            if not antwort.headers.get("content-type", "").lower().startswith("image/"):
                continue
            ziel = ordner / f"aufnahme_bild_{len(gespeichert) + 1}.jpg"
            from io import BytesIO
            with Image.open(BytesIO(antwort.content)) as bild:
                bild = bild.convert("RGB")
                if bild.width < 480 or bild.height < 300:
                    continue
                bild.thumbnail((2000, 2000))
                bild.save(ziel, "JPEG", quality=90)
            gespeichert.append(ziel)
        except Exception:
            continue
    return gespeichert


def werkzeuge_befund() -> dict:
    """Für „Prüfen“: Womit kann fotografiert werden?"""
    try:
        import playwright  # noqa: F401
        playwright_da = True
    except Exception:
        playwright_da = False
    browser = browser_pfad()
    if playwright_da and browser:
        return {"ok": True, "meldung": "Webseiten-Aufnahme bereit (Playwright + Browser)."}
    if browser:
        return {"ok": True, "meldung": "Webseiten-Aufnahme bereit (Browser direkt)."}
    if playwright_da:
        return {"ok": True, "meldung": "Webseiten-Aufnahme über Playwright möglich — "
                                       "beim ersten Mal wird ein Browser geladen."}
    return {"ok": False, "meldung": "Für die Webseiten-Aufnahme fehlt ein Browser.",
            "hinweis": "Microsoft Edge oder Google Chrome installieren."}
