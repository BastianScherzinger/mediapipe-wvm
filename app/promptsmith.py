"""
promptsmith.py — aus einem Briefing wird ein Drehbuch.

Das ist der Punkt, an dem der Wert dieses Werkzeugs entsteht. Higgsfield liefert nur so
gute Videos, wie der Prompt gut ist — und ein guter Videoprompt sieht ganz anders aus als
das, was ein Kunde ins Formular tippt. Dieses Modul überbrückt genau diesen Abstand:

    „Werbevideo für meine Bäckerei, gemütlich, 30 Sekunden“
        ↓
    6 Szenen mit je einem fotografischen Bildprompt und einem Bewegungsprompt,
    auf Englisch, in der Sprache, die die Modelle verstehen.

Zwei Grundsätze:

  * **Prompts auf Englisch, Oberfläche auf Deutsch.** Die Bildmodelle sind auf englische
    Prompts trainiert; deutsche Prompts kosten spürbar Qualität. Der Kunde sieht deshalb
    eine deutsche Beschreibung je Szene, an das Modell geht die englische Fassung.
  * **Nie ohne Ergebnis dastehen.** Antwortet kein Sprachmodell brauchbar, baut das Modul
    aus dem Briefing selbst ein einfaches, funktionierendes Drehbuch. Lieber ein
    schlichtes Video als eine Fehlermeldung.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

from . import config, errors, higgsfield, llm, logbook

QUELLE = "Claude"


# ── Datenmodell ──────────────────────────────────────────────────────────────

@dataclass
class Szene:
    nr: int
    beschreibung: str            # deutsch — was der Zuschauer sieht
    bild_prompt: str             # englisch — für das Startbild
    video_prompt: str            # englisch — Bewegung und Kamera
    dauer: int

    def als_dict(self) -> dict:
        return {"nr": self.nr, "beschreibung": self.beschreibung,
                "bild_prompt": self.bild_prompt, "video_prompt": self.video_prompt,
                "dauer": self.dauer}


@dataclass
class Drehbuch:
    titel: str
    dateiname: str
    zusammenfassung: str
    stil: str
    szenen: list[Szene] = field(default_factory=list)
    quelle: str = ""             # welcher Weg hat es geschrieben
    notbehelf: bool = False      # selbst gebaut, weil kein Modell brauchbar war
    # Für die Veröffentlichung. Ein fertiges Video nützt wenig, wenn danach noch
    # eine halbe Stunde Textarbeit ansteht — beides entsteht in einem Zug.
    posting: str = ""            # Bildunterschrift für TikTok, Reels, Shorts
    hashtags: list[str] = field(default_factory=list)

    @property
    def gesamtdauer(self) -> int:
        return sum(s.dauer for s in self.szenen)

    def als_dict(self) -> dict:
        return {"titel": self.titel, "dateiname": self.dateiname,
                "zusammenfassung": self.zusammenfassung, "stil": self.stil,
                "szenen": [s.als_dict() for s in self.szenen],
                "gesamtdauer": self.gesamtdauer, "quelle": self.quelle,
                "notbehelf": self.notbehelf,
                "posting": self.posting, "hashtags": list(self.hashtags)}


# ── Anweisung an das Sprachmodell ────────────────────────────────────────────

_SYSTEM = """\
Du bist ein erfahrener Werbefilmer und Prompt-Spezialist für KI-Videomodelle
(Higgsfield Soul für Standbilder, Kling und Hailuo für Bewegung).

Deine Aufgabe: aus einem knappen Kundenbriefing ein sendefähiges Drehbuch machen.

REGELN FÜR BILDPROMPTS (Feld "bild_prompt", IMMER auf Englisch):
- Schreibe wie ein Fotograf, nicht wie ein Dichter. Nenne: Motiv, Umgebung, Lichtsituation,
  Kameraposition, Brennweite, Tiefenschärfe, Farbstimmung, Materialien.
- Konkrete Substantive schlagen Adjektive. "weathered oak counter" ist besser als "nice table".
- Ein Satz bis drei Sätze. Keine Aufzählungszeichen.
- Verbiete implizit Text im Bild: schreibe am Ende "no text, no logos, no watermark".
- Keine Markennamen, keine realen Personen, keine Prominenten — das löst die Inhaltsprüfung
  aus und der Auftrag wird abgelehnt.

REGELN FÜR BEWEGUNGSPROMPTS (Feld "video_prompt", IMMER auf Englisch):
- Beschreibe ausschließlich BEWEGUNG, die zum Startbild passt: was bewegt sich im Bild,
  und wie bewegt sich die Kamera.
- Kurz und eindeutig, ein bis zwei Sätze. Beispiel: "Slow dolly-in toward the counter while
  steam rises from the bread; soft handheld drift, subtle."
- Niemals einen Szenenwechsel, Schnitt oder eine zweite Einstellung beschreiben. Ein Clip
  ist EINE durchgehende Einstellung.
- Keine Sprache, keine Untertitel, keine eingeblendeten Texte.

REGELN FÜR DIE SZENENFOLGE:
- Die Szenen müssen zusammen eine Geschichte ergeben: Aufhänger → Aufbau → Höhepunkt → Abbinder.
- Die ERSTE Szene ist der Aufhänger und entscheidet alles. Sie muss in der ersten Sekunde
  etwas Sehenswertes zeigen — eine Bewegung, ein Gesicht, einen Kontrast. Kein langsames
  Heranfahren an ein leeres Bild, kein Logo, kein Establishing Shot ohne Ereignis.
- Halte den Look über alle Szenen gleich (gleiche Tageszeit, gleiche Farbwelt, gleicher
  Filmstil), sonst wirkt das montierte Video zusammengestückelt. Wiederhole die
  Look-Angaben deshalb in JEDEM Bildprompt.
- Das Feld "beschreibung" ist für den Kunden: ein kurzer deutscher Satz, was man sieht.

ANTWORTFORMAT — ausschließlich dieses JSON, kein Vorwort, keine Code-Auszeichnung:
{
  "titel": "Kurzer Titel auf Deutsch",
  "dateiname": "kurz_und_klein_mit_unterstrichen",
  "zusammenfassung": "Ein deutscher Satz, worum es im Video geht.",
  "stil": "Ein deutscher Halbsatz zum Look, z.B. warmes Morgenlicht, dokumentarisch",
  "posting": "Deutsche Bildunterschrift zum Veröffentlichen, 1-2 Sätze, ohne Hashtags",
  "hashtags": ["ohneRaute", "kleingeschrieben", "hoechstens acht"],
  "szenen": [
    {
      "beschreibung": "Deutscher Satz für den Kunden",
      "bild_prompt": "English photographic prompt ... no text, no logos, no watermark",
      "video_prompt": "English motion prompt, one continuous shot"
    }
  ]
}"""


#: Was ein Bildformat für die Bildgestaltung bedeutet. Ohne diesen Hinweis schreibt
#: jedes Sprachmodell Breitbild-Prompts („wide establishing shot“, „panoramic vista“) —
#: und die sehen im Hochformat aus wie ein Ausschnitt aus einem anderen Film.
_FORMATHINWEIS = {
    "9:16": ("Das Video ist HOCHKANT (9:16) für TikTok, Reels und Shorts. Die Bildprompts "
             "müssen dazu passen: senkrechte Bildkomposition, Motiv mittig und formatfüllend, "
             "nah dran statt weit weg. Keine Panoramen, keine breiten Establishing Shots. "
             "Oben und unten etwas Luft lassen — dort liegen die Bedienelemente der App. "
             "Schreibe das ausdrücklich in jeden Bildprompt: \"vertical 9:16 composition\"."),
    "3:4": ("Das Video ist hochkant (3:4). Senkrechte Bildkomposition, Motiv mittig und nah. "
            "Schreibe in jeden Bildprompt: \"vertical 3:4 composition\"."),
    "1:1": ("Das Video ist quadratisch (1:1) für den Instagram- und Facebook-Feed. Motiv "
            "mittig, keine breiten Panoramen. Schreibe in jeden Bildprompt: "
            "\"square 1:1 composition\"."),
    "16:9": ("Das Video ist im Breitbild (16:9) für YouTube und Webseiten. Schreibe in jeden "
             "Bildprompt: \"cinematic 16:9 composition\"."),
}


def _auftragstext(briefing: str, *, szenen: int, sekunden_je_szene: int,
                  stil: str, zielgruppe: str, tonfall: str,
                  seitenverhaeltnis: str = "") -> str:
    if szenen == 1:
        umfang = (f"Erzeuge GENAU EINE Szene von {sekunden_je_szene} Sekunden. "
                  "Sie muss für sich allein stehen und sofort wirken.")
    else:
        umfang = (f"Erzeuge GENAU {szenen} Szenen à {sekunden_je_szene} Sekunden "
                  f"(zusammen {szenen * sekunden_je_szene} Sekunden). "
                  "Die Szenen werden hintereinander montiert.")

    zusatz = []
    hinweis = _FORMATHINWEIS.get(seitenverhaeltnis or "")
    if hinweis:
        zusatz.append(hinweis)
    if stil:
        zusatz.append(f"Gewünschter Look: {stil}.")
    if zielgruppe:
        zusatz.append(f"Zielgruppe: {zielgruppe}.")
    if tonfall:
        zusatz.append(f"Tonfall: {tonfall}.")

    # Das Format steht bewusst NOCHMALS hier im Auftrag und nicht nur in der
    # Systemanweisung: läuft die Anfrage über die Claude-CLI, bringt diese einen eigenen,
    # sehr umfangreichen Systemtext mit, hinter dem unsere Anweisung verblasst. Am
    # Auftragstext hält sich jedes Modell zuverlässiger.
    return (f"BRIEFING DES KUNDEN:\n{briefing.strip()}\n\n"
            f"{umfang}\n"
            + (" ".join(zusatz) + "\n" if zusatz else "")
            + """
Antworte mit GENAU diesem JSON-Objekt — keine zusätzlichen Felder, keine Verschachtelung,
kein Vor- oder Nachwort:

{
  "titel": "<kurzer deutscher Titel>",
  "dateiname": "<kleinbuchstaben_mit_unterstrichen>",
  "zusammenfassung": "<ein deutscher Satz>",
  "stil": "<deutscher Halbsatz zum Look>",
  "posting": "<deutsche Bildunterschrift zum Veröffentlichen, 1-2 Sätze, ohne Hashtags>",
  "hashtags": ["<ohne Raute>", "<höchstens acht>"],
  "szenen": [
    {
      "beschreibung": "<ein deutscher Satz für den Kunden>",
      "bild_prompt": "<ENGLISCH: fotografischer Prompt für das Standbild, endet mit: no text, no logos, no watermark>",
      "video_prompt": "<ENGLISCH: nur Bewegung und Kamerafahrt, eine durchgehende Einstellung>"
    }
  ]
}

Zwingend:
- Die Felder heißen genau "bild_prompt" und "video_prompt".
- Beide Prompts sind auf ENGLISCH. Nur "beschreibung", "titel", "stil" und
  "zusammenfassung" sind auf Deutsch.
- Kein Feld "projekt", kein Feld "montage", keine Audio- oder Schnittangaben.""")


# ── JSON aus einer Modellantwort holen ───────────────────────────────────────

def _json_finden(text: str) -> dict | None:
    """Holt das JSON-Objekt aus einer Antwort. Sprachmodelle verpacken es gern in
    Code-Auszeichnung oder in Höflichkeiten — beides wird hier abgeräumt."""
    if not text:
        return None
    roh = text.strip()

    # 1. Code-Auszeichnung entfernen
    zaun = re.search(r"```(?:json)?\s*(.+?)```", roh, re.DOTALL)
    if zaun:
        roh = zaun.group(1).strip()

    # 2. Direktversuch
    try:
        daten = json.loads(roh)
        if isinstance(daten, dict):
            return daten
    except ValueError:
        pass

    # 3. Größte geschweifte Klammer ausschneiden
    start, ende = roh.find("{"), roh.rfind("}")
    if start >= 0 and ende > start:
        ausschnitt = roh[start:ende + 1]
        try:
            daten = json.loads(ausschnitt)
            if isinstance(daten, dict):
                return daten
        except ValueError:
            # 4. Die zwei häufigsten Schludrigkeiten reparieren:
            #    überzähliges Komma vor einer schließenden Klammer, einfache Anführungszeichen
            geflickt = re.sub(r",(\s*[}\]])", r"\1", ausschnitt)
            try:
                daten = json.loads(geflickt)
                if isinstance(daten, dict):
                    return daten
            except ValueError:
                return None
    return None


def _saeubere_dateinamen(text: str, ersatz: str = "video") -> str:
    """Macht aus einem Titel einen unbedenklichen Dateinamen. Bewusst streng: nur
    Kleinbuchstaben, Ziffern und Unterstriche — damit nichts an Windows-Sonderregeln
    oder an einer Pfadprüfung scheitert."""
    umschrift = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                 "Ä": "ae", "Ö": "oe", "Ü": "ue"}
    for zeichen, ersetzung in umschrift.items():
        text = text.replace(zeichen, ersetzung)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    text = re.sub(r"_{2,}", "_", text)
    return (text[:48] or ersatz)


# ── Prüfen und zurechtrücken ─────────────────────────────────────────────────

#: Feldnamen, unter denen Modelle dasselbe meinen. Belegt durch echte Antworten:
#: die Claude-CLI liefert etwa "prompt"/"kamera"/"bewegung_im_bild" statt der
#: angeforderten Namen, weil ihr eigener Systemtext den unsrigen überlagert. Statt darauf
#: zu bestehen, versteht dieses Modul beide Sprachen — das kostet nichts und macht die
#: Prompt-Schmiede unabhängig davon, welches Modell gerade antwortet.
_ALIAS_BILD = ("bild_prompt", "image_prompt", "bildprompt", "visual_prompt",
               "prompt", "bild", "visual", "szene", "scene")
_ALIAS_BEWEGUNG = ("video_prompt", "motion_prompt", "videoprompt", "bewegungsprompt",
                   "motion", "bewegung")
_ALIAS_KAMERA = ("kamera", "camera", "kamerafahrt", "camera_movement", "kamerabewegung")
_ALIAS_BILDBEWEGUNG = ("bewegung_im_bild", "motion_in_frame", "subject_motion", "action")
_ALIAS_BESCHREIBUNG = ("beschreibung", "description", "titel", "title", "name")


def _erstes_feld(eintrag: dict, namen: tuple[str, ...]) -> str:
    """Erster nicht-leerer Texteintrag unter den angegebenen Namen."""
    for name in namen:
        wert = eintrag.get(name)
        if isinstance(wert, str) and wert.strip():
            return wert.strip()
        if isinstance(wert, list) and wert:            # manche Modelle liefern Listen
            teile = [str(t).strip() for t in wert if str(t).strip()]
            if teile:
                return ", ".join(teile)
    return ""


def _kopffeld(daten: dict, namen: tuple[str, ...]) -> str:
    """Wie `_erstes_feld`, sucht aber auch eine Ebene tiefer — Modelle packen Titel und
    Look gern in einen Unterabschnitt wie "projekt"."""
    direkt = _erstes_feld(daten, namen)
    if direkt:
        return direkt
    for wert in daten.values():
        if isinstance(wert, dict):
            tiefer = _erstes_feld(wert, namen)
            if tiefer:
                return tiefer
    return ""


def _szenenliste(daten: dict) -> list:
    """Findet die Szenenliste, auch wenn sie anders heißt oder verschachtelt liegt."""
    for name in ("szenen", "scenes", "shots", "einstellungen", "clips"):
        wert = daten.get(name)
        if isinstance(wert, list) and wert:
            return wert
    for wert in daten.values():
        if isinstance(wert, dict):
            tiefer = _szenenliste(wert)
            if tiefer:
                return tiefer
    return []


def _zu_drehbuch(daten: dict, *, szenen_soll: int, dauer_soll: int,
                 briefing: str, quelle: str) -> Drehbuch:
    """Macht aus der Modellantwort ein geprüftes Drehbuch. Alles, was fehlt oder unsinnig
    ist, wird ergänzt statt zurückgewiesen — ein halb brauchbares Drehbuch ist besser als
    gar keins, und der Kunde sieht die Szenen ohnehin vor dem Start."""
    roh_szenen = _szenenliste(daten)
    if not roh_szenen:
        raise errors.AnbieterFehler(
            "Das Sprachmodell hat keine Szenen geliefert.",
            "Beim nächsten Versuch übernimmt ein anderer Weg.", ursprung=QUELLE)

    szenen: list[Szene] = []
    for stelle, eintrag in enumerate(roh_szenen[:szenen_soll], start=1):
        if isinstance(eintrag, str):                   # reine Textliste
            eintrag = {"prompt": eintrag}
        if not isinstance(eintrag, dict):
            continue

        bild = _erstes_feld(eintrag, _ALIAS_BILD)
        bewegung = _erstes_feld(eintrag, _ALIAS_BEWEGUNG)
        beschreibung = _erstes_feld(eintrag, _ALIAS_BESCHREIBUNG)

        # Kein eigener Bewegungsprompt? Dann aus Kameraführung und Bildbewegung einen
        # bauen — die Angaben sind da, nur anders einsortiert.
        if not bewegung:
            teile = [_erstes_feld(eintrag, _ALIAS_KAMERA),
                     _erstes_feld(eintrag, _ALIAS_BILDBEWEGUNG)]
            bewegung = ". ".join(t for t in teile if t)

        if not bild and not bewegung:
            continue
        if not bild:
            # Ohne Bildprompt lässt sich kein Startbild bauen — aus der Bewegung ableiten.
            bild = f"Cinematic still frame: {bewegung}. no text, no logos, no watermark"
        if not bewegung:
            bewegung = "Subtle natural motion, slow cinematic camera push-in, one continuous shot."
        if "no text" not in bild.lower():
            bild = f"{bild.rstrip('. ')}. no text, no logos, no watermark"

        szenen.append(Szene(
            nr=stelle,
            beschreibung=(beschreibung or f"Szene {stelle}")[:300],
            bild_prompt=bild[:config.MAX_PROMPT_CHARS],
            video_prompt=bewegung[:config.MAX_PROMPT_CHARS],
            dauer=dauer_soll,
        ))

    if not szenen:
        raise errors.AnbieterFehler(
            "Keine der gelieferten Szenen war brauchbar.",
            "Das Werkzeug baut jetzt selbst ein einfaches Drehbuch.", ursprung=QUELLE)

    titel = (_kopffeld(daten, ("titel", "title", "projekttitel"))
             or briefing.strip()[:60] or "Video")
    dateiname = _saeubere_dateinamen(
        _kopffeld(daten, ("dateiname", "filename", "slug")) or titel)

    # Sanfte Qualitätskontrolle: sind die Prompts erkennbar deutsch geblieben, sinkt die
    # Bildqualität spürbar. Das wird protokolliert, aber nicht erzwungen — ein deutscher
    # Prompt liefert immer noch ein Video, ein Abbruch liefert keins.
    if _wirkt_deutsch(" ".join(s.bild_prompt for s in szenen)):
        logbook.warnung(QUELLE, "Die Bildprompts wirken deutsch. Die Modelle arbeiten mit "
                                "englischen Prompts deutlich besser — Ergebnis kann "
                                "schwächer ausfallen.")

    zusammenfassung = _kopffeld(daten, ("zusammenfassung", "summary", "logline"))[:500]
    return Drehbuch(
        titel=titel[:120],
        dateiname=dateiname,
        zusammenfassung=zusammenfassung,
        stil=_kopffeld(daten, ("stil", "style", "look", "stilrichtung",
                               "farbstimmung"))[:200],
        szenen=szenen,
        quelle=quelle,
        # Ohne eigenen Posting-Text ist die Zusammenfassung der beste Ersatz — besser
        # als ein leeres Feld, das der Kunde selbst füllen müsste.
        posting=(_kopffeld(daten, ("posting", "caption", "bildunterschrift",
                                   "beschreibung_social")) or zusammenfassung)[:600],
        hashtags=_hashtags(daten),
    )


#: Zeichen, die in einem Hashtag nichts verloren haben.
_HASHTAG_UNRAT = re.compile(r"[^0-9A-Za-zÄÖÜäöüß_]")


def _hashtags(daten: dict) -> list[str]:
    """Die Hashtags aus der Modellantwort — geputzt und begrenzt.

    Sprachmodelle liefern sie mal als Liste, mal als eine Zeile mit Rauten, mal mit
    Leerzeichen mittendrin. Alles davon wird zu derselben schlichten Liste ohne Raute;
    die setzt die Oberfläche selbst, damit sie überall gleich aussieht.
    """
    roh = None
    for name in ("hashtags", "tags", "schlagworte"):
        if daten.get(name):
            roh = daten[name]
            break
    if roh is None:
        return []
    if isinstance(roh, str):
        roh = roh.replace("#", " ").split()
    if not isinstance(roh, list):
        return []

    sauber: list[str] = []
    for eintrag in roh:
        wort = _HASHTAG_UNRAT.sub("", str(eintrag).lstrip("#").replace(" ", ""))
        if wort and wort.lower() not in {w.lower() for w in sauber}:
            sauber.append(wort[:40])
    return sauber[:8]


#: Wörter, die in einem englischen Prompt praktisch nie vorkommen.
_DEUTSCHE_MARKER = (" der ", " die ", " das ", " und ", " mit ", " einer ", " eines ",
                    " im ", " durch ", " über ", " nicht ", "ß", "ä", "ö", "ü")


def _wirkt_deutsch(text: str) -> bool:
    klein = f" {text.lower()} "
    treffer = sum(1 for wort in _DEUTSCHE_MARKER if wort in klein)
    return treffer >= 3


def _notbehelf(briefing: str, *, szenen_soll: int, dauer_soll: int, stil: str) -> Drehbuch:
    """Selbst gebautes Drehbuch, wenn kein Sprachmodell brauchbar geantwortet hat.

    Kein Ersatz für ein echtes Drehbuch, aber es funktioniert: das Briefing wird als
    Motiv gesetzt, und die Szenen unterscheiden sich in der Kameraführung. Damit kommt
    trotzdem ein ansehbares Video heraus.
    """
    logbook.warnung(QUELLE, "Kein Sprachmodell lieferte ein brauchbares Drehbuch — "
                            "einfaches Drehbuch wird selbst erstellt.")
    motiv = " ".join(briefing.split())[:400] or "a modern product presentation"
    grundlook = stil or "cinematic, natural light, shallow depth of field, muted warm colours"

    kameras = [
        ("Ruhige Annäherung", "slow dolly-in, steady"),
        ("Sanfter Schwenk", "slow lateral pan, steady"),
        ("Aufsteigende Kamera", "slow crane-up revealing the surroundings"),
        ("Nahaufnahme", "slow push-in on the main detail, shallow focus"),
        ("Umkreisen", "slow orbit around the subject"),
        ("Zurückfahren", "slow dolly-out revealing the whole scene"),
    ]

    szenen = []
    for stelle in range(1, szenen_soll + 1):
        name, bewegung = kameras[(stelle - 1) % len(kameras)]
        szenen.append(Szene(
            nr=stelle,
            beschreibung=f"Szene {stelle}: {name}",
            bild_prompt=(f"Cinematic photograph of {motiv}. {grundlook}, professional "
                         f"commercial photography, high detail. no text, no logos, no watermark"),
            video_prompt=f"{bewegung.capitalize()}, subtle natural motion, one continuous shot.",
            dauer=dauer_soll,
        ))

    return Drehbuch(
        titel=briefing.strip()[:60] or "Video",
        dateiname=_saeubere_dateinamen(briefing[:40]),
        zusammenfassung="Automatisch erstelltes Drehbuch ohne Sprachmodell.",
        stil=grundlook,
        szenen=szenen,
        quelle="Notbehelf",
        notbehelf=True,
        # Ohne Sprachmodell gibt es keinen klugen Posting-Text. Das Briefing ist der
        # ehrlichste Ersatz — und es steht wenigstens etwas da, das sich anpassen lässt.
        posting=briefing.strip()[:280],
    )


# ── Öffentliche Schnittstelle ────────────────────────────────────────────────

def drehbuch_erstellen(briefing: str, *, szenen: int = 1, sekunden_je_szene: int = 5,
                       stil: str = "", zielgruppe: str = "", tonfall: str = "",
                       modell: str = "", seitenverhaeltnis: str = "") -> Drehbuch:
    """Erzeugt das Drehbuch. Wirft nie wegen eines Modellausfalls — im äußersten Fall
    kommt das selbst gebaute Drehbuch zurück."""
    briefing = (briefing or "").strip()
    if len(briefing) < 3:
        raise errors.EingabeFehler(
            "Das Briefing ist zu kurz.",
            "Beschreiben Sie in einem Satz, was im Video zu sehen sein soll.",
            ursprung=QUELLE)
    briefing = briefing[:config.MAX_BRIEFING_CHARS]

    szenen = max(1, min(szenen, config.MAX_SCENES))
    sekunden_je_szene = higgsfield.erlaubte_dauer(modell or config.VIDEO_MODEL,
                                                  sekunden_je_szene)

    logbook.info(QUELLE, f"Schreibe Drehbuch: {szenen} Szene(n) à {sekunden_je_szene} s.")
    auftrag = _auftragstext(briefing, szenen=szenen, sekunden_je_szene=sekunden_je_szene,
                            stil=stil, zielgruppe=zielgruppe, tonfall=tonfall,
                            seitenverhaeltnis=seitenverhaeltnis)

    try:
        antwort = llm.erzeuge(_SYSTEM, auftrag, zeitlimit=240)
    except errors.StudioFehler as fehler:
        logbook.warnung(QUELLE, f"Kein Sprachmodell erreichbar: {fehler.meldung}")
        return _notbehelf(briefing, szenen_soll=szenen, dauer_soll=sekunden_je_szene, stil=stil)

    daten = _json_finden(antwort.text)
    if daten is None:
        # Einmal nachfassen: oft reicht die ausdrückliche Bitte um reines JSON.
        logbook.warnung(QUELLE, "Antwort war kein gültiges JSON — es wird einmal nachgefasst.")
        try:
            zweite = llm.erzeuge(
                _SYSTEM,
                auftrag + "\n\nWICHTIG: Deine vorige Antwort war kein gültiges JSON. "
                          "Antworte NUR mit dem JSON-Objekt, beginnend mit { und endend mit }.",
                zeitlimit=240, bevorzugt=antwort.weg)
            daten = _json_finden(zweite.text)
            antwort = zweite
        except errors.StudioFehler:
            daten = None

    if daten is None:
        return _notbehelf(briefing, szenen_soll=szenen, dauer_soll=sekunden_je_szene, stil=stil)

    try:
        drehbuch = _zu_drehbuch(daten, szenen_soll=szenen, dauer_soll=sekunden_je_szene,
                                briefing=briefing, quelle=antwort.anzeigename)
    except errors.StudioFehler as fehler:
        logbook.warnung(QUELLE, fehler.meldung)
        return _notbehelf(briefing, szenen_soll=szenen, dauer_soll=sekunden_je_szene, stil=stil)

    # Hat das Modell zu wenige Szenen geliefert, wird ergänzt statt abgebrochen — der
    # Kunde hat eine Länge bestellt und soll sie bekommen.
    while len(drehbuch.szenen) < szenen:
        vorlage = drehbuch.szenen[len(drehbuch.szenen) % len(drehbuch.szenen)]
        nummer = len(drehbuch.szenen) + 1
        drehbuch.szenen.append(Szene(
            nr=nummer,
            beschreibung=f"Szene {nummer}: Variante von Szene {vorlage.nr}",
            bild_prompt=vorlage.bild_prompt,
            video_prompt="Slow steady camera move, subtle natural motion, one continuous shot.",
            dauer=sekunden_je_szene))
        logbook.debug(QUELLE, f"Szene {nummer} ergänzt — das Modell lieferte zu wenige.")

    logbook.erfolg(QUELLE, f"Drehbuch „{drehbuch.titel}“ steht · {len(drehbuch.szenen)} Szene(n) "
                           f"· {drehbuch.gesamtdauer} s · geschrieben von {drehbuch.quelle}.")
    return drehbuch


def drehbuch_aus_dict(daten: dict) -> Drehbuch | None:
    """Baut ein gespeichertes Drehbuch wieder auf — für „Erneut versuchen“.

    Ein zweites Mal das Sprachmodell zu fragen, kostete Zeit und ergäbe ein anderes
    Drehbuch: Die schon bezahlten Startbilder und Clips passten dann nicht mehr dazu.
    """
    if not isinstance(daten, dict):
        return None
    szenen = []
    for stelle, eintrag in enumerate(daten.get("szenen") or [], start=1):
        if not isinstance(eintrag, dict) or not eintrag.get("bild_prompt"):
            continue
        szenen.append(Szene(nr=int(eintrag.get("nr") or stelle),
                            beschreibung=str(eintrag.get("beschreibung") or ""),
                            bild_prompt=str(eintrag["bild_prompt"]),
                            video_prompt=str(eintrag.get("video_prompt") or ""),
                            dauer=int(eintrag.get("dauer") or 5)))
    if not szenen:
        return None
    return Drehbuch(titel=str(daten.get("titel") or "Video"),
                    dateiname=str(daten.get("dateiname") or "video"),
                    zusammenfassung=str(daten.get("zusammenfassung") or ""),
                    stil=str(daten.get("stil") or ""), szenen=szenen,
                    quelle=str(daten.get("quelle") or "übernommen"),
                    notbehelf=bool(daten.get("notbehelf")),
                    posting=str(daten.get("posting") or ""),
                    hashtags=list(daten.get("hashtags") or []))


def eigenen_prompt_veredeln(prompt: str, *, sekunden: int = 5, modell: str = "",
                            seitenverhaeltnis: str = "") -> Drehbuch:
    """Für den Freitext-Bereich: der eingegebene Prompt wird zu einem sauberen
    Einzelclip-Drehbuch ausgearbeitet."""
    return drehbuch_erstellen(prompt, szenen=1, sekunden_je_szene=sekunden, modell=modell,
                              seitenverhaeltnis=seitenverhaeltnis)


def eigenen_prompt_woertlich(prompt: str, *, sekunden: int = 5,
                             modell: str = "") -> Drehbuch:
    """Für den Freitext-Bereich mit Häkchen „wörtlich verwenden“: kein Sprachmodell,
    der Text geht unverändert an Higgsfield. Wer genau weiß, was er will, soll nicht
    bevormundet werden."""
    prompt = (prompt or "").strip()
    if len(prompt) < 3:
        raise errors.EingabeFehler("Der Prompt ist zu kurz.",
                                   "Mindestens ein kurzer Satz.", ursprung=QUELLE)
    dauer = higgsfield.erlaubte_dauer(modell or config.VIDEO_MODEL, sekunden)
    logbook.info(QUELLE, "Eigener Prompt wird wörtlich übernommen — kein Sprachmodell.")
    return Drehbuch(
        titel=prompt[:60],
        dateiname=_saeubere_dateinamen(prompt[:40], "eigener_prompt"),
        zusammenfassung="Wörtlich übernommener Prompt.",
        stil="",
        szenen=[Szene(1, "Ihr Prompt, unverändert",
                      prompt[:config.MAX_PROMPT_CHARS],
                      prompt[:config.MAX_PROMPT_CHARS], dauer)],
        quelle="unverändert übernommen",
    )
