"""
topics.py — der Themen- und Argumentkatalog für das Formular.

Die linke Seite des Dashboards soll ohne Nachdenken bedienbar sein: Thema auswählen,
ein paar Merkmale anklicken, fertig. Was hier steht, bestimmt, was zur Auswahl steht.

Aufbau eines Themas:
  * `vorlage`  — der Satz, aus dem das Briefing entsteht; {betreff} wird ersetzt
  * `felder`   — was zusätzlich abgefragt wird (nur, was wirklich hilft)
  * `argumente`— anklickbare Merkmale, die dem Briefing angehängt werden
  * `vorschlag`— sinnvolle Voreinstellung für Szenenzahl und Länge

Die Kataloge sind bewusst Daten, kein Code: neue Themen kommen ohne Programmänderung dazu.
"""
from __future__ import annotations

#: Anklickbare Merkmale, nach Gruppen. Jede Gruppe erscheint als eigene Reihe.
ARGUMENTGRUPPEN = [
    {
        "kennung": "stimmung",
        "name": "Stimmung",
        "mehrfach": True,
        "argumente": [
            {"kennung": "hochwertig", "name": "Hochwertig", "text": "premium, hochwertig, edel"},
            {"kennung": "warm", "name": "Warm & einladend", "text": "warm, einladend, gemütlich"},
            {"kennung": "energisch", "name": "Energiegeladen", "text": "dynamisch, energiegeladen, schnell"},
            {"kennung": "ruhig", "name": "Ruhig", "text": "ruhig, entspannt, gelassen"},
            {"kennung": "technisch", "name": "Technisch & präzise", "text": "technisch, präzise, sachlich"},
            {"kennung": "verspielt", "name": "Verspielt", "text": "verspielt, humorvoll, leicht"},
            {"kennung": "dramatisch", "name": "Dramatisch", "text": "dramatisch, kontrastreich, kinoreif"},
            {"kennung": "natuerlich", "name": "Natürlich", "text": "natürlich, echt, ungestellt"},
        ],
    },
    {
        "kennung": "licht",
        "name": "Licht & Zeit",
        "mehrfach": False,
        "argumente": [
            {"kennung": "morgen", "name": "Morgenlicht", "text": "warmes Morgenlicht, goldene Stunde"},
            {"kennung": "tag", "name": "Tageslicht", "text": "helles natürliches Tageslicht"},
            {"kennung": "abend", "name": "Abendlicht", "text": "warmes Abendlicht, tiefstehende Sonne"},
            {"kennung": "nacht", "name": "Nacht", "text": "nachts, künstliches Licht, Neonreflexe"},
            {"kennung": "studio", "name": "Studio", "text": "sauberes Studiolicht, weicher Hintergrund"},
            {"kennung": "bewoelkt", "name": "Weich bewölkt", "text": "weiches diffuses Licht, bedeckter Himmel"},
        ],
    },
    {
        "kennung": "kamera",
        "name": "Kameraführung",
        "mehrfach": False,
        "argumente": [
            {"kennung": "ruhig_kamera", "name": "Ruhig & stabil", "text": "ruhige Kamera, langsame Fahrten"},
            {"kennung": "handkamera", "name": "Handkamera", "text": "leichte Handkamera, dokumentarisch"},
            {"kennung": "drohne", "name": "Aus der Luft", "text": "Luftaufnahme, weite Perspektive"},
            {"kennung": "nah", "name": "Nah dran", "text": "Nahaufnahmen, Details, flache Schärfentiefe"},
            {"kennung": "kran", "name": "Große Bewegung", "text": "große Kranfahrten, eröffnende Bewegung"},
        ],
    },
    {
        "kennung": "bildstil",
        "name": "Bildstil",
        "mehrfach": False,
        "argumente": [
            {"kennung": "fotoreal", "name": "Fotorealistisch", "text": "fotorealistisch, wie mit Vollformatkamera"},
            {"kennung": "kino", "name": "Kinofilm", "text": "kinoreif, anamorph, Filmkorn"},
            {"kennung": "clean", "name": "Clean & modern", "text": "clean, modern, minimalistisch"},
            {"kennung": "vintage", "name": "Vintage", "text": "Vintage-Look, warme Farben, analog"},
            {"kennung": "animation", "name": "Animation", "text": "stilisierte 3D-Animation, weiche Formen"},
            {"kennung": "illustration", "name": "Illustriert", "text": "illustrierter Stil, gezeichnet"},
        ],
    },
]


#: Themen — jedes bringt eine Briefing-Vorlage und eine sinnvolle Voreinstellung mit.
THEMEN = [
    {
        "kennung": "werbung",
        "name": "Werbevideo",
        "symbol": "◆",
        "beschreibung": "Ein Produkt oder ein Geschäft ansprechend zeigen",
        "vorlage": "Werbevideo für {betreff}. Es soll Interesse wecken und zum Besuch "
                   "oder Kauf anregen.",
        "platzhalter": "z. B. eine Handwerksbäckerei in Mannheim",
        "vorschlag": {"szenen": 5, "sekunden": 5, "seitenverhaeltnis": "16:9"},
        "felder": ["zielgruppe", "botschaft"],
    },
    {
        "kennung": "social",
        "name": "Social-Media-Clip",
        "symbol": "▲",
        "beschreibung": "Kurz, hochkant, sofort wirksam — für Reels, TikTok, Shorts",
        "vorlage": "Kurzer Social-Media-Clip über {betreff}. Der Anfang muss in der "
                   "ersten Sekunde fesseln.",
        "platzhalter": "z. B. eine neue Kaffeesorte",
        "vorschlag": {"szenen": 3, "sekunden": 5, "seitenverhaeltnis": "9:16"},
        "felder": ["zielgruppe"],
    },
    {
        "kennung": "produkt",
        "name": "Produktvorstellung",
        "symbol": "■",
        "beschreibung": "Ein einzelnes Produkt ins beste Licht rücken",
        "vorlage": "Produktvideo für {betreff}. Das Produkt steht im Mittelpunkt und wird "
                   "von mehreren Seiten gezeigt.",
        "platzhalter": "z. B. eine Armbanduhr aus gebürstetem Stahl",
        "vorschlag": {"szenen": 4, "sekunden": 5, "seitenverhaeltnis": "16:9"},
        "felder": ["botschaft"],
    },
    {
        "kennung": "immobilie",
        "name": "Immobilie / Räume",
        "symbol": "▬",
        "beschreibung": "Räume, Gebäude und Grundstücke zeigen",
        "vorlage": "Immobilienvideo für {betreff}. Die Räume sollen großzügig und "
                   "einladend wirken.",
        "platzhalter": "z. B. eine sanierte Altbauwohnung mit Stuck",
        "vorschlag": {"szenen": 5, "sekunden": 5, "seitenverhaeltnis": "16:9"},
        "felder": [],
    },
    {
        "kennung": "youtube",
        "name": "YouTube-Inhalt",
        "symbol": "●",
        "beschreibung": "Vorspann, Übergänge oder Bildmaterial für ein Video",
        "vorlage": "Bildmaterial für ein YouTube-Video über {betreff}. Es dient als "
                   "Hintergrund und Illustration.",
        "platzhalter": "z. B. die Geschichte der Raumfahrt",
        "vorschlag": {"szenen": 6, "sekunden": 5, "seitenverhaeltnis": "16:9"},
        "felder": ["botschaft"],
    },
    {
        "kennung": "animation",
        "name": "Animationsvideo",
        "symbol": "◈",
        "beschreibung": "Abstrakte oder gestaltete Bewegtbilder statt Realaufnahmen",
        "vorlage": "Animationsvideo zum Thema {betreff}. Keine Realaufnahme, sondern "
                   "eine gestaltete Bildwelt.",
        "platzhalter": "z. B. Datenströme in einem Rechenzentrum",
        "vorschlag": {"szenen": 4, "sekunden": 5, "seitenverhaeltnis": "16:9"},
        "felder": [],
    },
    {
        "kennung": "gastro",
        "name": "Gastronomie",
        "symbol": "❋",
        "beschreibung": "Speisen, Getränke, Lokale — mit Appetit im Blick",
        "vorlage": "Video für {betreff}. Speisen und Atmosphäre sollen Appetit machen.",
        "platzhalter": "z. B. eine italienische Trattoria",
        "vorschlag": {"szenen": 4, "sekunden": 5, "seitenverhaeltnis": "9:16"},
        "felder": ["zielgruppe"],
    },
    {
        "kennung": "handwerk",
        "name": "Handwerk & Dienstleistung",
        "symbol": "✦",
        "beschreibung": "Arbeit, Können und Ergebnis eines Betriebs zeigen",
        "vorlage": "Video für {betreff}. Es zeigt die Arbeit, das Können und das "
                   "fertige Ergebnis.",
        "platzhalter": "z. B. einen Elektrobetrieb für Photovoltaik",
        "vorschlag": {"szenen": 5, "sekunden": 5, "seitenverhaeltnis": "16:9"},
        "felder": ["zielgruppe", "botschaft"],
    },
    {
        "kennung": "marke",
        "name": "Markenfilm",
        "symbol": "◇",
        "beschreibung": "Haltung und Gefühl statt Produktmerkmale",
        "vorlage": "Markenfilm für {betreff}. Es geht um Haltung und Gefühl, nicht um "
                   "einzelne Produktmerkmale.",
        "platzhalter": "z. B. ein Familienunternehmen in dritter Generation",
        "vorschlag": {"szenen": 6, "sekunden": 5, "seitenverhaeltnis": "16:9"},
        "felder": ["botschaft"],
    },
]

#: Zusatzfelder, die ein Thema anfordern kann.
ZUSATZFELDER = {
    "zielgruppe": {"name": "Zielgruppe",
                   "platzhalter": "z. B. Familien aus der Umgebung, 30–60 Jahre",
                   "hinweis": "Wen soll das Video ansprechen?"},
    "botschaft": {"name": "Kernbotschaft",
                  "platzhalter": "z. B. seit 40 Jahren jeden Morgen frisch gebacken",
                  "hinweis": "Was soll hängenbleiben?"},
}


def thema(kennung: str) -> dict | None:
    for eintrag in THEMEN:
        if eintrag["kennung"] == kennung:
            return eintrag
    return None


def argument_text(kennungen: list[str]) -> str:
    """Setzt die angeklickten Merkmale zu einem Satzteil zusammen."""
    texte: list[str] = []
    for gruppe in ARGUMENTGRUPPEN:
        for argument in gruppe["argumente"]:
            if argument["kennung"] in (kennungen or []):
                texte.append(argument["text"])
    return ", ".join(texte)


def briefing_bauen(thema_kennung: str, betreff: str, argumente: list[str],
                   zusatz: dict | None = None) -> str:
    """Baut aus den Formulareingaben den Briefingtext, der an die Prompt-Schmiede geht.

    Das geschieht bewusst hier und nicht erst im Sprachmodell: so sieht der Kunde in der
    Oberfläche genau den Text, der weitergereicht wird — keine Blackbox.
    """
    daten = thema(thema_kennung)
    betreff = (betreff or "").strip()
    if daten and betreff:
        text = daten["vorlage"].format(betreff=betreff)
    elif daten:
        text = daten["vorlage"].format(betreff="dem angegebenen Thema")
    else:
        text = betreff or ""

    zusatz = zusatz or {}
    if zusatz.get("zielgruppe"):
        text += f" Zielgruppe: {str(zusatz['zielgruppe']).strip()}."
    if zusatz.get("botschaft"):
        text += f" Kernbotschaft: {str(zusatz['botschaft']).strip()}."

    merkmale = argument_text(argumente)
    if merkmale:
        text += f" Gewünschte Anmutung: {merkmale}."
    return text.strip()


# ── Zielplattformen ──────────────────────────────────────────────────────────
#
# Was ein Video für TikTok von einem für YouTube unterscheidet, sind vier Zahlen:
# Bildformat, Länge, Szenenzahl und die Ausgabefassungen. Wer das jedes Mal einzeln
# in „Weitere Einstellungen“ zusammensuchen muss, wählt am Ende doch 16:9 — und lädt
# ein Breitbildvideo bei TikTok hoch.
#
# Die Plattform steht deshalb **vor** dem Thema und setzt alle vier auf einmal.
# Überstimmen lässt sich hinterher jede einzelne.

PLATTFORMEN = [
    {
        "kennung": "tiktok",
        "name": "TikTok / Reels",
        "beschreibung": "Hochkant, kurz, Aufhänger in der ersten Sekunde",
        "seitenverhaeltnis": "9:16",
        "szenen": 4,
        "sekunden": 5,
        "formate": ["hoch"],
        "hinweis": "9:16 · rund 20 Sekunden — die Länge, die auf TikTok und Reels "
                   "am zuverlässigsten zu Ende gesehen wird.",
    },
    {
        "kennung": "shorts",
        "name": "YouTube Shorts",
        "beschreibung": "Hochkant, etwas mehr Erzählraum",
        "seitenverhaeltnis": "9:16",
        "szenen": 6,
        "sekunden": 5,
        "formate": ["hoch"],
        "hinweis": "9:16 · rund 30 Sekunden. Shorts verträgt mehr Aufbau als TikTok.",
    },
    {
        "kennung": "feed",
        "name": "Instagram-Feed",
        "beschreibung": "Quadratisch, für die Zeitleiste",
        "seitenverhaeltnis": "1:1",
        "szenen": 3,
        "sekunden": 5,
        "formate": ["quadrat"],
        "hinweis": "1:1 · rund 15 Sekunden — im Feed wird ohne Ton und im Vorbeiscrollen "
                   "geschaut.",
    },
    {
        "kennung": "youtube",
        "name": "YouTube / Webseite",
        "beschreibung": "Breitbild, für den großen Bildschirm",
        "seitenverhaeltnis": "16:9",
        "szenen": 5,
        "sekunden": 5,
        "formate": ["breit", "web"],
        "hinweis": "16:9 · rund 25 Sekunden. Dazu entsteht eine kleine Webfassung "
                   "zum Einbetten.",
    },
]


def plattform(kennung: str) -> dict | None:
    for eintrag in PLATTFORMEN:
        if eintrag["kennung"] == kennung:
            return eintrag
    return None


def katalog() -> dict:
    """Alles, was die Oberfläche zum Aufbau des Formulars braucht."""
    return {"themen": THEMEN, "argumentgruppen": ARGUMENTGRUPPEN,
            "zusatzfelder": ZUSATZFELDER, "plattformen": PLATTFORMEN}
