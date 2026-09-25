"""
webwerbung.py — Link hinein, TikTok-Werbevideo heraus.

Der Ablauf einer Webseiten-Werbung, in denselben fünf Blöcken dargestellt wie ein
normaler Auftrag — nur mit anderen Namen:

    Webseite  →  Aufnahmen  →  Konzept  →  Schnitt  →  Ausgabe
    prüfen       Handy,        Hook,       Motion-      Film, Poster,
                 Desktop,      Vorteile,   Design,      Posting-Zettel
                 Bilder        Aufforderung Beat, KI

Ein Werbevideo aus einer Webseite braucht **kein** Guthaben: Aufnahmen, Konzept und
Schnitt laufen auf diesem Rechner. Wer möchte, lässt eine KI-Szene über Higgsfield
dazunehmen — sie wird nach der Enthüllung eingefügt. Scheitert sie, entsteht das Video
ohne sie; ein fehlendes Beiwerk darf die Werbung nicht verhindern.

Konzept: Das Sprachmodell liest Überschriften, Knöpfe und Text der Seite und schreibt
Aufhänger, drei Vorteile und die Handlungsaufforderung. Es darf dabei **nichts erfinden**
— keine Preise, keine Auszeichnungen, die nicht auf der Seite stehen. Antwortet kein
Sprachmodell, baut das Programm das Konzept selbst aus den Überschriften.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from . import (config, errors, jobstore, library, llm, logbook, media, promptsmith,
               videoquelle, webaufnahme, werbeschnitt)

QUELLE = "Webwerbung"

BLOECKE = ("pruefen", "aufnahme", "konzept", "schnitt", "ausgabe")
BLOCKNAMEN = {"pruefen": "Webseite", "aufnahme": "Aufnahmen", "konzept": "Konzept",
              "schnitt": "Schnitt", "ausgabe": "Ausgabe"}

DAUERN = (15, 20, 30)
STILE = [
    {"kennung": "energisch", "name": "Energiegeladen",
     "beschreibung": "Schnell, laut, knallige Farben — klassisch TikTok."},
    {"kennung": "freundlich", "name": "Freundlich",
     "beschreibung": "Hell und sympathisch, mittleres Tempo."},
    {"kennung": "edel", "name": "Edel",
     "beschreibung": "Ruhiger Takt, goldene Akzente — für Premium-Angebote."},
]


def katalog() -> dict:
    return {"dauern": list(DAUERN), "stile": STILE,
            "bloecke": [{"kennung": b, "name": BLOCKNAMEN[b]} for b in BLOECKE]}


# ── Einstellungen ────────────────────────────────────────────────────────────

def einstellungen_pruefen(roh: dict, Einstellungen):
    """Macht aus dem Formular der Webseiten-Seite einen gültigen Auftrag.

    Nimmt auch die gespeicherten Einstellungen eines früheren Auftrags entgegen — dort
    stehen die Angaben verschachtelt unter `webseite`. So funktioniert „Erneut versuchen“.
    """
    roh = {**(roh.get("webseite") or {}), **{k: v for k, v in roh.items() if v not in
                                              (None, "")}}
    url = webaufnahme.adresse_normieren(str(roh.get("url") or roh.get("briefing") or ""))
    try:
        dauer = int(roh.get("dauer") or 20)
    except (TypeError, ValueError):
        dauer = 20
    dauer = min(DAUERN, key=lambda d: abs(d - dauer))
    stil = str(roh.get("stil") or "energisch")
    if stil not in werbeschnitt.STILE:
        stil = "energisch"
    cta = " ".join(str(roh.get("cta") or "").split())[:40]
    hinweis = " ".join(str(roh.get("hinweis") or "").split())[:300]
    formate = tuple(f for f in (roh.get("formate") or []) if f in media.FORMATE
                    and f != "hoch")
    from . import higgsfield
    videomodell = str(roh.get("videomodell") or config.VIDEO_MODEL)
    if videomodell not in {m["id"] for m in higgsfield.VIDEOMODELLE}:
        videomodell = config.VIDEO_MODEL
    return Einstellungen(
        briefing=url, art="webseite", szenen=1, sekunden=dauer,
        seitenverhaeltnis="9:16", formate=formate,
        wiederholung_von=str(roh.get("wiederholung_von") or "").strip()[:32],
        videomodell=videomodell,
        bildmodell=config.IMAGE_MODEL,
        webseite={"url": url, "dauer": dauer, "stil": stil, "cta": cta,
                  "hinweis": hinweis, "musik": roh.get("musik", True) is not False,
                  "ki_szene": bool(roh.get("ki_szene"))})


# ── Ereignisse (dieselben wie beim normalen Auftrag) ─────────────────────────

def _block(auftrag_id, block, zustand, text="", zusatz=None):
    logbook.ereignis("block", {"block": block, "zustand": zustand, "text": text,
                               **(zusatz or {})}, job=auftrag_id)


def _fortschritt(auftrag_id, block, anteil, rest=0.0, text=""):
    logbook.ereignis("fortschritt", {"block": block,
                                     "anteil": round(max(0.0, min(1.0, anteil)), 3),
                                     "rest": round(max(0.0, rest)), "text": text},
                     job=auftrag_id)


def _uebergang(auftrag_id, von, nach):
    logbook.ereignis("uebergang", {"von": von, "nach": nach}, job=auftrag_id)


def _pruefe_abbruch(abbruch: threading.Event) -> None:
    if abbruch.is_set():
        raise errors.AbbruchFehler("Abgebrochen.", ursprung=QUELLE)


# ── Konzept ──────────────────────────────────────────────────────────────────

_SYSTEM = """\
Du bist Creative Director für kurze Werbevideos auf TikTok und Instagram Reels.
Aus den Inhalten einer Webseite machst du ein knackiges Konzept für ein 15- bis
30-Sekunden-Video, das Bildschirmaufnahmen der Seite zeigt.

Regeln:
- Schreibe auf Deutsch, in der Du-Form, kurz und konkret. Keine Floskeln wie
  „Qualität, die überzeugt“ oder „Ihr Partner für …“.
- ERFINDE NICHTS. Nenne nur Leistungen, Orte, Zahlen und Vorteile, die in den Inhalten
  stehen. Keine Preise, Rabatte, Siegel oder Bewertungen, die dort nicht vorkommen.
- "hook": höchstens 7 Wörter. Eine Frage oder starke Aussage, die die Zielgruppe in der
  ersten Sekunde anspricht. Das letzte Wort wird farbig hervorgehoben — es soll das
  wichtigste sein.
- "vorteile": genau drei, je höchstens 4 Wörter.
- "cta": höchstens 4 Wörter, eine klare Aufforderung passend zur Seite
  (z. B. „Jetzt Termin sichern“, „Kostenlos anfragen“).
- "marke": der Name des Unternehmens, höchstens 3 Wörter.
- "ki_szene": EIN englischer Prompt für eine stimmungsvolle, senkrechte Filmszene, die
  zum Angebot passt (Ort, Menschen bei der Arbeit, Produkt) — ohne Text, ohne Logos.

Antworte ausschließlich mit diesem JSON, ohne Vorwort und ohne Code-Auszeichnung:
{"marke": "", "hook": "", "untertitel": "", "vorteile": ["", "", ""], "cta": "",
 "posting": "1-2 Sätze Bildunterschrift ohne Hashtags", "hashtags": ["ohne Raute"],
 "ki_szene": ""}"""

_NAVIGATION = re.compile(
    r"^(menü|menu|home|startseite|kontakt|impressum|datenschutz|login|anmelden|suche|"
    r"search|close|schließen|skip|mehr|more|cookie|agb|jobs|karriere|blog|news|faq)\b",
    re.IGNORECASE)
_AUFFORDERUNG = re.compile(
    r"(anfrag|kontakt|termin|jetzt|buch|bestell|angebot|start|kauf|shop|reserv|"
    r"probier|testen|berat|anruf|registr|sichern|vereinbar)", re.IGNORECASE)


def _kurz(text: str, worte: int, zeichen: int) -> str:
    teile = " ".join(str(text or "").replace("\n", " ").split()).split()
    return " ".join(teile[:worte])[:zeichen].strip(" ,.;:-–|")


def _marke_aus(texte: dict, host: str) -> str:
    kandidat = texte.get("marke") or ""
    if not kandidat:
        titel = str(texte.get("titel") or "")
        kandidat = re.split(r"\s[|–—\-:·]\s", titel)[0] if titel else ""
    kandidat = _kurz(kandidat, 4, 32)
    if not kandidat or len(kandidat) < 2:
        kandidat = host.split(".")[0].capitalize()
    return kandidat


def farbe_lesen(roh: str) -> tuple[int, int, int] | None:
    """„rgb(12, 34, 56)“ oder „#1a2b3c“ → Farbe, aber nur, wenn sie als Akzent taugt:
    nicht fast schwarz, nicht fast weiß, nicht grau."""
    roh = str(roh or "").strip()
    werte = None
    treffer = re.match(r"rgba?\((\d+)\D+(\d+)\D+(\d+)", roh)
    if treffer:
        werte = tuple(int(x) for x in treffer.groups())
    elif re.fullmatch(r"#?[0-9a-fA-F]{6}", roh):
        roh = roh.lstrip("#")
        werte = tuple(int(roh[i:i + 2], 16) for i in (0, 2, 4))
    if not werte:
        return None
    hoch, tief = max(werte), min(werte)
    helligkeit = (0.2126 * werte[0] + 0.7152 * werte[1] + 0.0722 * werte[2]) / 255
    saettigung = (hoch - tief) / hoch if hoch else 0
    if helligkeit < 0.12 or helligkeit > 0.86 or saettigung < 0.3:
        return None
    return werte  # type: ignore[return-value]


def konzept_selbst(texte: dict, host: str, einstellungen: dict) -> dict:
    """Das Konzept ohne Sprachmodell — aus Überschriften, Knöpfen und Beschreibung."""
    marke = _marke_aus(texte, host)
    # Überschriften, die zugleich Knöpfe oder Links sind, gehören zur Navigation
    # („Download“, „Docs“, „Get Started“) — als Aufhänger oder Vorteil taugen sie nicht.
    menue = {" ".join(str(k).lower().split()) for k in (texte.get("knoepfe") or [])}
    ueberschriften = [u for u in (texte.get("ueberschriften") or [])
                      if 3 <= len(u) <= 70 and not _NAVIGATION.match(u)
                      and " ".join(u.lower().split()) not in menue]
    hook = next((_kurz(u, 7, 60) for u in ueberschriften if len(u.split()) >= 3), "")
    if not hook:
        hook = f"Schon {marke} entdeckt?"
    vorteile = [_kurz(u, 4, 32) for u in ueberschriften
                if len(u) <= 40 and _kurz(u, 7, 60) != hook][:3]
    beschreibung = str(texte.get("beschreibung") or "")
    for teil in re.split(r"[.,;–|]", beschreibung):
        if len(vorteile) >= 3:
            break
        teil = _kurz(teil, 4, 32)
        if len(teil) > 5 and teil not in vorteile:
            vorteile.append(teil)
    while len(vorteile) < 3:
        vorteile.append(("Alles auf einen Blick", "Einfach online", "Direkt erreichbar")
                        [len(vorteile)])
    cta = next((_kurz(k, 4, 28) for k in (texte.get("knoepfe") or [])
                if _AUFFORDERUNG.search(k) and len(k) <= 30), "") or "Jetzt entdecken"
    return {"marke": marke, "hook": hook, "untertitel": _kurz(beschreibung, 10, 80),
            "vorteile": vorteile, "cta": einstellungen.get("cta") or cta,
            "posting": _kurz(beschreibung, 30, 220) or f"{marke} — schau vorbei!",
            "hashtags": [re.sub(r"\W", "", marke.lower())[:30] or "werbung", "werbung",
                         "tipp", "fyp"],
            "ki_szene": "", "quelle": "selbst erstellt"}


def konzept_erstellen(aufnahme, einstellungen: dict) -> dict:
    """Konzept vom Sprachmodell — geprüft, gekürzt und notfalls selbst ergänzt."""
    texte = aufnahme.texte or {}
    grundlage = konzept_selbst(texte, aufnahme.host, einstellungen)
    auftrag = (
        f"WEBSEITE: {aufnahme.url}\n"
        f"TITEL: {texte.get('titel', '')}\n"
        f"BESCHREIBUNG: {texte.get('beschreibung', '')}\n"
        f"ÜBERSCHRIFTEN: {' | '.join((texte.get('ueberschriften') or [])[:16])}\n"
        f"KNÖPFE: {' | '.join((texte.get('knoepfe') or [])[:30])}\n"
        f"SEITENTEXT (Auszug): {str(texte.get('text') or '')[:2500]}\n\n"
        f"GEWÜNSCHTER STIL: {einstellungen.get('stil', 'energisch')}, "
        f"Länge {einstellungen.get('dauer', 20)} Sekunden.\n"
        + (f"WUNSCH DES KUNDEN: {einstellungen['hinweis']}\n"
           if einstellungen.get("hinweis") else "")
        + (f"DIE HANDLUNGSAUFFORDERUNG STEHT FEST: {einstellungen['cta']}\n"
           if einstellungen.get("cta") else ""))
    try:
        antwort = llm.erzeuge(_SYSTEM, auftrag, zeitlimit=180)
        daten = promptsmith._json_finden(antwort.text) or {}
        quelle = antwort.anzeigename
    except errors.StudioFehler as fehler:
        logbook.warnung(QUELLE, f"Kein Sprachmodell für das Konzept ({fehler.meldung}) — "
                                "es wird aus den Überschriften der Seite gebaut.")
        return grundlage

    if not daten:
        logbook.warnung(QUELLE, "Das Konzept kam nicht als JSON — es wird aus den "
                                "Überschriften der Seite gebaut.")
        return grundlage

    vorteile = [_kurz(v, 5, 34) for v in _als_liste(daten.get("vorteile"))
                if str(v).strip()]
    konzept = {
        "marke": _kurz(daten.get("marke"), 4, 32) or grundlage["marke"],
        "hook": _kurz(daten.get("hook"), 8, 64) or grundlage["hook"],
        "untertitel": _kurz(daten.get("untertitel"), 12, 90),
        "vorteile": (vorteile + grundlage["vorteile"])[:3],
        "cta": einstellungen.get("cta") or _kurz(daten.get("cta"), 5, 30) or grundlage["cta"],
        "posting": str(daten.get("posting") or grundlage["posting"])[:500],
        "hashtags": promptsmith._hashtags(daten) or grundlage["hashtags"],
        "ki_szene": str(daten.get("ki_szene") or "")[:600],
        "quelle": quelle,
    }
    return konzept


def _als_liste(wert) -> list:
    """Eine Aufzählung aus der Modellantwort als Liste.

    Sprachmodelle liefern „vorteile“ gelegentlich als eine Zeile statt als Liste. Ohne
    diese Prüfung zerfiel „Schnell, günstig, nah“ beim Durchlaufen in Einzelbuchstaben.
    Zeichenketten werden an Komma, Semikolon, Zeilenumbruch und Aufzählungspunkt
    geteilt; alles andere, was keine Liste ist, wird verworfen.
    """
    if isinstance(wert, str):
        return [t.strip(" -–*\t") for t in re.split(r"[,;\n•·]+", wert)
                if t.strip(" -–*\t")]
    if isinstance(wert, (list, tuple)):
        return [v for v in wert if isinstance(v, (str, int, float))]
    return []


# ── KI-Szene ─────────────────────────────────────────────────────────────────

def _ki_szene(auftrag_id: str, e, konzept: dict, ordner: Path,
              abbruch: threading.Event) -> Path | None:
    """Eine Filmszene über Higgsfield. Scheitert sie, geht es ohne sie weiter."""
    from . import higgsfield, pipeline

    ziel = ordner / "ki_szene.mp4"
    if ziel.exists():
        try:
            media.pruefe_video(ziel)
            logbook.info(QUELLE, "Die KI-Szene vom letzten Versuch wird übernommen — kostet "
                                 "nichts.", job=auftrag_id)
            return ziel
        except errors.StudioFehler:
            ziel.unlink(missing_ok=True)
    try:
        dienst = videoquelle.aktiv()
    except errors.StudioFehler:
        return None
    weg = videoquelle.weg_von(dienst)
    if weg not in ("abo", "platform"):
        logbook.info(QUELLE, "KI-Szene übersprungen — es ist kein Higgsfield-Zugang aktiv "
                             "(Probelauf).", job=auftrag_id)
        return None

    prompt = konzept.get("ki_szene") or (
        f"Cinematic vertical shot that captures the atmosphere of {konzept['marke']}, "
        "warm natural light, shallow depth of field, premium commercial look")
    prompt = f"{prompt.rstrip('. ')}. vertical 9:16 composition, no text, no logos, no watermark"
    try:
        einstellung = SimpleNamespace(videomodell=e.videomodell, bildmodell=e.bildmodell,
                                      seitenverhaeltnis="9:16", sekunden=5)
        pipeline._vorpruefen(auftrag_id, einstellung, dienst, block="schnitt")

        def melden(anteil, rest, zustand):
            _fortschritt(auftrag_id, "schnitt", 0.3 * anteil, rest, f"KI-Szene · {zustand}")

        bewegung = "Slow cinematic push-in, subtle natural motion, one continuous shot."
        if higgsfield.braucht_startbild(e.videomodell):
            _block(auftrag_id, "schnitt", "aktiv", "KI-Szene: Startbild")
            bild = pipeline._aufrufen(dienst.bild, prompt, seitenverhaeltnis="9:16",
                                      modell=e.bildmodell or config.IMAGE_MODEL,
                                      abbruch=abbruch)
            dienst.herunterladen(bild.url, ordner / "ki_szene_start.jpg", abbruch)
            _block(auftrag_id, "schnitt", "aktiv", "KI-Szene: Bewegung")
            clip = pipeline._aufrufen(
                dienst.video_aus_bild, bewegung, bild.url, dauer=einstellung.sekunden,
                modell=e.videomodell, seitenverhaeltnis="9:16", abbruch=abbruch,
                melden=melden, bild_kennung=bild.request_id)
        else:
            # Ein Modell ohne Startbild bekommt keins — sonst wäre das Bild bezahlt und
            # der Videoauftrag scheiterte trotzdem.
            _block(auftrag_id, "schnitt", "aktiv", "KI-Szene")
            clip = pipeline._aufrufen(
                dienst.video_aus_text, f"{prompt}. {bewegung}", dauer=einstellung.sekunden,
                modell=e.videomodell, seitenverhaeltnis="9:16", abbruch=abbruch,
                melden=melden)
        dienst.herunterladen(clip.url, ziel, abbruch)
        media.pruefe_video(ziel)
        logbook.erfolg(QUELLE, "KI-Szene ist fertig und kommt ins Video.", job=auftrag_id)
        return ziel
    except errors.AbbruchFehler:
        raise
    except errors.StudioFehler as fehler:
        logbook.warnung(QUELLE, f"KI-Szene entfällt ({fehler.meldung}) — das Video entsteht "
                                "ohne sie.", job=auftrag_id)
        return None


# ── Der Ablauf ───────────────────────────────────────────────────────────────

def _dateiname(host: str) -> str:
    return promptsmith._saeubere_dateinamen(f"{host.split('.')[0]}_tiktok", "webseite")


def ablauf(auftrag_id: str, e, abbruch: threading.Event) -> dict:
    """Führt einen Webseiten-Auftrag aus und gibt das Ergebnis wie ein Videoauftrag zurück."""
    w = dict(e.webseite or {})
    url = w.get("url") or e.briefing

    # ── Webseite prüfen ──────────────────────────────────────────────────────
    jobstore.aktualisieren(auftrag_id, block="pruefen")
    _block(auftrag_id, "pruefen", "aktiv", "Link wird geprüft")
    pruefung = webaufnahme.adresse_pruefen(url)
    titel = f"TikTok-Werbung · {pruefung['host']}"
    alt = jobstore.holen(e.wiederholung_von) if e.wiederholung_von else None
    if alt is not None and alt.ordner and Path(alt.ordner).is_dir():
        # Beim Wiederholen derselbe Ordner: Dort liegt eine schon bezahlte KI-Szene.
        ordner = Path(alt.ordner)
    else:
        ordner = jobstore.ordner_fuer(jobstore.holen(auftrag_id),
                                      _dateiname(pruefung["host"]))
    jobstore.aktualisieren(auftrag_id, titel=titel, ordner=str(ordner))
    logbook.info(QUELLE, f"Webseite erreichbar: {pruefung['titel'][:80]} "
                         f"({pruefung['dauer_ms']} ms)", job=auftrag_id)
    _block(auftrag_id, "pruefen", "fertig", pruefung["host"])
    _uebergang(auftrag_id, "pruefen", "aufnahme")
    _pruefe_abbruch(abbruch)

    # ── Aufnahmen ────────────────────────────────────────────────────────────
    jobstore.aktualisieren(auftrag_id, block="aufnahme")
    _block(auftrag_id, "aufnahme", "aktiv", "Seite wird fotografiert")
    _fortschritt(auftrag_id, "aufnahme", 0.1, 35, "Browser startet")
    aufnahme = webaufnahme.aufnehmen(
        pruefung["url"], ordner, abbruch=abbruch,
        melden=lambda anteil, text: _fortschritt(auftrag_id, "aufnahme", anteil, 0, text))
    logbook.ereignis("vorschau", {"block": "aufnahme",
                                  "datei": library.web_pfad(aufnahme.start_mobil)},
                     job=auftrag_id)
    _block(auftrag_id, "aufnahme", "fertig",
           f"Handy, Desktop, {len(aufnahme.bilder)} Bild(er)")
    _uebergang(auftrag_id, "aufnahme", "konzept")
    _pruefe_abbruch(abbruch)

    # ── Konzept ──────────────────────────────────────────────────────────────
    jobstore.aktualisieren(auftrag_id, block="konzept")
    _block(auftrag_id, "konzept", "aktiv", "Aufhänger und Vorteile")
    _fortschritt(auftrag_id, "konzept", 0.15, 30, "Sprachmodell liest die Seite")
    konzept = konzept_erstellen(aufnahme, w)
    logbook.erfolg(QUELLE, f"Konzept steht: „{konzept['hook']}“ · "
                           f"{' · '.join(konzept['vorteile'])} · {konzept['cta']} "
                           f"({konzept['quelle']})", job=auftrag_id)
    _fortschritt(auftrag_id, "konzept", 1.0, 0, "fertig")
    _block(auftrag_id, "konzept", "fertig", konzept["hook"][:60], {"konzept": konzept})
    _uebergang(auftrag_id, "konzept", "schnitt")
    _pruefe_abbruch(abbruch)

    # ── Schnitt ──────────────────────────────────────────────────────────────
    jobstore.aktualisieren(auftrag_id, block="schnitt")
    _block(auftrag_id, "schnitt", "aktiv", "Szenen werden gezeichnet")
    ki_clip = _ki_szene(auftrag_id, e, konzept, ordner, abbruch) if w.get("ki_szene") else None
    farbe = farbe_lesen((aufnahme.texte or {}).get("farbe", ""))
    schnitt_konzept = werbeschnitt.Konzept(
        marke=konzept["marke"], hook=konzept["hook"], untertitel=konzept["untertitel"],
        vorteile=konzept["vorteile"], cta=konzept["cta"], host=aufnahme.host,
        stil=w.get("stil", "energisch"), farbe=farbe)
    film = ordner / "film.mp4"
    begonnen = time.monotonic()
    anfang = 0.3 if ki_clip else 0.0

    def schnittmeldung(anteil: float) -> None:
        vergangen = time.monotonic() - begonnen
        rest = vergangen / anteil * (1 - anteil) if anteil > 0.03 else 90
        _fortschritt(auftrag_id, "schnitt", anfang + (1 - anfang) * anteil, rest,
                     "Motion-Design")

    werbeschnitt.rendern(aufnahme, schnitt_konzept, film, dauer=int(w.get("dauer", 20)),
                         musik=w.get("musik", True), ki_clip=ki_clip, abbruch=abbruch,
                         melden=schnittmeldung)
    angaben = media.pruefe_video(film)
    _block(auftrag_id, "schnitt", "fertig", f"{angaben.dauer:.0f} s · 9:16")
    _uebergang(auftrag_id, "schnitt", "ausgabe")

    # ── Ausgabe ──────────────────────────────────────────────────────────────
    jobstore.aktualisieren(auftrag_id, block="ausgabe")
    _block(auftrag_id, "ausgabe", "aktiv", "Vorschaubild und Formate")
    poster = ordner / "film_poster.jpg"
    try:
        media.format_erzeugen(film, poster, "poster", wie_die_quelle=True, abbruch=abbruch)
    except errors.StudioFehler as fehler:
        logbook.warnung(QUELLE, f"Vorschaubild nicht erzeugt: {fehler.meldung}",
                        job=auftrag_id)
        poster = None
    erzeugte: dict[str, str] = {}
    for kennung in e.formate:
        _pruefe_abbruch(abbruch)
        try:
            vorgabe = media.FORMATE[kennung]
            ziel = ordner / f"film_{kennung}.{vorgabe.endung}"
            media.format_erzeugen(film, ziel, kennung, abbruch=abbruch)
            erzeugte[kennung] = library.web_pfad(ziel)
        except errors.AbbruchFehler:
            raise
        except errors.StudioFehler as fehler:
            logbook.warnung(QUELLE, f"Format {kennung} nicht erzeugt: {fehler.meldung}",
                            job=auftrag_id)

    angaben = media.angaben(film)
    drehbuch = SimpleNamespace(titel=titel, posting=konzept["posting"],
                               hashtags=konzept["hashtags"],
                               zusammenfassung=konzept["untertitel"])
    ergebnis = {
        "film": str(film), "film_web": library.web_pfad(film),
        "poster": library.web_pfad(poster) if poster else "",
        "ordner": str(ordner), "dauer": angaben.dauer, "breite": angaben.breite,
        "hoehe": angaben.hoehe, "bytes": angaben.bytes, "szenen": 1,
        "formate": erzeugte, "titel": titel, "ausgefallen": [], "art": "webseite",
        "url": aufnahme.url,
    }
    ergebnis["posting"] = library.posting_schreiben(ordner, drehbuch, "9:16")
    library.begleitzettel_schreiben(ordner, {
        "titel": titel, "art": "webseite",
        "erstellt": time.strftime("%d.%m.%Y %H:%M"),
        "briefing": f"Werbevideo aus {aufnahme.url}",
        "einstellungen": e.als_dict(), "konzept": konzept,
        "aufnahme": aufnahme.als_dict(),
        "drehbuch": {"titel": titel, "posting": konzept["posting"],
                     "hashtags": konzept["hashtags"],
                     "zusammenfassung": konzept["untertitel"]},
        "ergebnis": {k: v for k, v in ergebnis.items() if k != "formate"},
    })
    _fortschritt(auftrag_id, "ausgabe", 1.0, 0, "fertig")
    _block(auftrag_id, "ausgabe", "fertig",
           f"{angaben.dauer:.0f} s · {angaben.bytes / 1_048_576:.1f} MB")
    return ergebnis
