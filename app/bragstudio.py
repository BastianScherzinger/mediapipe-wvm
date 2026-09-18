"""
bragstudio.py — „Premium-Film": Claude baut den Film selbst.

Der Unterschied zu den beiden anderen Bereichen: Hier entsteht kein KI-Video aus
Higgsfield und keine Bildschirmaufnahme mit Textbannern, sondern eine **gebaute
Komposition** — Typografie, Bewegung, Musik, Beat, beide Formate. Claude arbeitet dabei
wie ein Mensch am Rechner: liest das Material, schreibt ein Storyboard, baut HTML,
prüft, sieht sich Einzelbilder an, rendert.

Fünf Blöcke:

    Material  →  Prompt   →  Bauen    →  Rendern  →  Ausgabe
    Ordner,      Claude      Claude      MP4 in      film.mp4,
    Aufnahme,    schreibt    baut die    beiden      film_hoch.mp4,
    Uploads      den Auf-    Komposi-    Formaten    Poster, Posting,
                 trag        tionen                  Abrechnung

Drei Quellen sind möglich, und sie decken die drei Fälle des Alltags ab:

  * **webseite** — nur ein Link. Die Seite gehört jemand anderem, es gibt keinen
    Quelltext. Das Programm fotografiert sie und liest ihre Texte.
  * **ordner** — ein Projektordner auf diesem Rechner. Dann liest Claude die echten
    Inhalte: Preise, Schriften, Farben, Bilder. Das gibt die besten Filme.
  * **thema** — gar keine Seite, nur eine Beschreibung und hochgeladenes Material.

**Was hier bewusst NICHT passiert:** Das Programm schreibt kein Storyboard und kein
HTML. Es stellt Material und Auftrag zusammen, ruft den Agenten und räumt hinterher auf.
Alles Gestalterische liegt bei Claude und den Skills — sonst hätte man zwei Stellen, an
denen dieselbe Entscheidung getroffen wird, und die eine wäre immer die schlechtere.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from . import (bragagent, config, errors, jobstore, library, llm, logbook, media,
               webaufnahme)

QUELLE = "Premium-Film"

BLOECKE = ("material", "prompt", "bauen", "render", "ausgabe")
BLOCKNAMEN = {"material": "Material", "prompt": "Auftrag", "bauen": "Bauen",
              "render": "Rendern", "ausgabe": "Ausgabe"}

QUELLEN = [
    {"kennung": "webseite", "name": "Webseite (Link)",
     "beschreibung": "Die Seite gehört jemand anderem oder liegt nur online — sie wird "
                     "fotografiert und ausgelesen."},
    {"kennung": "ordner", "name": "Projektordner",
     "beschreibung": "Ein Ordner auf diesem Rechner. Claude liest die echten Texte, "
                     "Preise, Farben und Bilder — das ergibt die besten Filme."},
    {"kennung": "thema", "name": "Thema oder Produkt",
     "beschreibung": "Keine Webseite: Sie beschreiben es, laden Bilder dazu, fertig."},
]

TONFAELLE = [
    {"kennung": "polished", "name": "Edel und ruhig",
     "beschreibung": "Wenige Szenen, lange Standzeiten, weiche Übergänge. Für Handwerk, "
                     "Beratung, Praxen, alles Hochpreisige."},
    {"kennung": "app-store", "name": "Klar und modern",
     "beschreibung": "Saubere Karten, freundliches Tempo. Für Software, Shops, Dienste."},
    {"kennung": "cinematic", "name": "Kinoreif",
     "beschreibung": "Große Typo, dramatische Enthüllungen. Für Marken und Launches."},
    {"kennung": "default", "name": "Locker und hell",
     "beschreibung": "Freundlich, gut teilbar. Für Alltagsgeschäft und Social Media."},
]

DAUERN = (18, 22, 25)
SPRACHEN = [{"kennung": "de", "name": "Deutsch"}, {"kennung": "en", "name": "Englisch"}]

#: Worum der Film geht. Das ist die Frage, an der der erste Luviq-Film gescheitert ist:
#: Für einen Modeladen einen Film über *die Webseite* zu machen, ist so falsch wie für
#: eine Agentur einen Film über *ihre Bilder*. Niemand kauft eine Webseite — gekauft
#: wird das, was darauf steht.
FOKUS = [
    {"kennung": "auto", "name": "Automatisch",
     "beschreibung": "Das Programm sieht sich das Material an und entscheidet — "
                     "Ware, Arbeit oder Angebot."},
    {"kennung": "produkt", "name": "Produkt & Marke",
     "beschreibung": "Die Ware trägt den Film: Kleidung, Speisen, Möbel, Handwerk zum "
                     "Anfassen. Bilder groß, Text kurz. Vorbild: Luviq."},
    {"kennung": "dienstleistung", "name": "Dienstleistung",
     "beschreibung": "Die Arbeit und ihr Ergebnis tragen den Film: Vorher/Nachher, "
                     "Leistungen, Zusagen, Gesicht, End-Card mit einer Handlung. "
                     "Vorbild: Rümpelwerk, Flügel."},
    {"kennung": "webseite", "name": "Webseite & Angebot",
     "beschreibung": "Der Film zeigt die Seite selbst: Preise, Ablauf, Oberfläche. "
                     "Für Software und alles, was erklärt werden muss."},
]

#: Wörter, die eine **Dienstleistung** anzeigen — es wird Arbeit verkauft, kein Ding.
_DIENSTWORTE = re.compile(
    r"(reinigung|entrümpel|entsorg|sanierung|renovier|montage|installat|wartung|"
    r"hausmeister|winterdienst|gartenpflege|galabau|heckenschnitt|pflege|räumung|"
    r"umzug|dachdeck|maler|elektr|sanitär|heizung|schlüsseldienst|pflasterarbeit|"
    r"angebot einholen|termin|besichtigung|kostenlos anfragen|festpreis)", re.IGNORECASE)

#: Wörter, die ein **Produkt** anzeigen — es wird ein Ding verkauft.
_PRODUKTWORTE = re.compile(
    r"(shop|warenkorb|kollektion|unikat|produkt|bestell|kaufen|sortiment|größe|"
    r"lieferzeit|versand|ausverkauft|sold|artikel|speisekarte|menü)", re.IGNORECASE)

#: Wörter, die für einen Marken-/Produktfilm sprechen (Verkauf von Dingen und Arbeit).
_MARKENWORTE = re.compile(
    r"(shop|warenkorb|kollektion|unikat|produkt|bestell|kaufen|sortiment|galerie|"
    r"speisekarte|menü|reinigung|montage|sanierung|garten|pflege|handwerk|atelier|"
    r"werkstatt|lieferung|versand)", re.IGNORECASE)

#: Wörter, die für einen Film über die Seite und ihr Angebot sprechen.
_ANGEBOTSWORTE = re.compile(
    r"(webseite|website|agentur|software|saas|beratung|kanzlei|coaching|kurs|abo|"
    r"tarif|plan|demo|anmelden|registrieren|pauschal|festpreis|pro monat)",
    re.IGNORECASE)


def fokus_bestimmen(bilder: list, texte: dict, gewaehlt: str = "auto") -> dict:
    """Entscheidet, **welche Sorte Film** gebaut wird — und sagt, warum.

    Drei Sorten, weil es drei Arten von Geschäft gibt, und jede braucht einen anderen
    Film:

    * **produkt** — verkauft wird ein Ding. Die Ware trägt den Film (Luviq).
    * **dienstleistung** — verkauft wird Arbeit. Ihr Ergebnis trägt den Film:
      Vorher/Nachher, Zusagen, das Gesicht, eine Handlungsaufforderung (Rümpelwerk,
      Flügel).
    * **webseite** — es gibt nichts zu fotografieren, nur ein Angebot zu erklären.

    Die Entscheidung hängt an Material und Wortfeld, nicht an Geschmack. Ein Film über
    Kleidungsstücke ohne Kleidungsstücke ist so falsch wie ein Film über eine
    Gebäudereinigung, in dem keine gereinigte Fläche vorkommt.
    """
    if gewaehlt in ("produkt", "dienstleistung", "webseite"):
        return {"fokus": gewaehlt, "gewaehlt": True, "begruendung": "So ausgewählt."}
    if gewaehlt == "marke":          # Fassung vor dem 18.09.2026
        gewaehlt = "auto"

    anzahl = len(bilder or [])
    worte = " ".join(str(w) for w in [
        texte.get("titel", ""), texte.get("beschreibung", ""),
        " ".join(texte.get("ueberschriften", []) or []),
        " ".join(texte.get("knoepfe", []) or []),
        " ".join(str(b.get("hinweis", "")) for b in (bilder or [])),
    ])
    dienst = len(set(m.group(0).lower() for m in _DIENSTWORTE.finditer(worte)))
    produkt = len(set(m.group(0).lower() for m in _PRODUKTWORTE.finditer(worte)))
    angebot = len(set(m.group(0).lower() for m in _ANGEBOTSWORTE.finditer(worte)))

    if anzahl < 4:
        return {"fokus": "webseite", "gewaehlt": False,
                "begruendung": f"Nur {anzahl} verwendbare Bild(er) — der Film erzählt die "
                               "Seite und ihr Angebot, statt Bilder vorzutäuschen."}
    if dienst > produkt:
        return {"fokus": "dienstleistung", "gewaehlt": False,
                "begruendung": f"{anzahl} Arbeitsfotos und {dienst} Hinweise auf "
                               "Dienstleistung — der Film zeigt Arbeit und Ergebnis."}
    if produkt > 0 and produkt >= dienst:
        return {"fokus": "produkt", "gewaehlt": False,
                "begruendung": f"{anzahl} Motivbilder und {produkt} Hinweise auf Ware — "
                               "der Film zeigt das Produkt."}
    if angebot > dienst + produkt:
        return {"fokus": "webseite", "gewaehlt": False,
                "begruendung": f"{angebot} Hinweise auf ein erklärungsbedürftiges "
                               "Angebot — der Film zeigt die Seite und ihr Angebot."}
    return {"fokus": "dienstleistung", "gewaehlt": False,
            "begruendung": f"{anzahl} echte Fotos ohne klares Warensignal — behandelt "
                           "wie eine Dienstleistung: Arbeit, Ergebnis, Ansprechpartner."}

#: Dateiendungen, die als Material taugen. Alles andere wird nicht mitgenommen —
#: ein Projektordner enthält sonst schnell ein Gigabyte Abhängigkeiten.
_TEXT_ENDUNGEN = {".html", ".htm", ".css", ".js", ".py", ".md", ".txt", ".json", ".json5",
                  ".yml", ".yaml", ".toml", ".jsx", ".tsx", ".ts", ".vue", ".svelte"}
_BILD_ENDUNGEN = {".webp", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".avif", ".ico"}
_SCHRIFT_ENDUNGEN = {".woff2", ".woff", ".ttf", ".otf"}

#: Ordner, die in keinem Projekt etwas zum Film beitragen.
_UEBERSPRINGEN = {"node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build",
                  ".next", "staticfiles", ".idea", ".vscode", "site-packages", ".pytest_cache",
                  "migrations", ".cache", "coverage", "htmlcov", "brag-output"}

#: Wie viel Material in einem Rutsch hochgeladen werden darf.
MAX_UPLOAD_BYTES = 250 * 1024 * 1024
#: Was hochgeladen werden darf. Alles andere wird abgewiesen — ein Film entsteht aus
#: Bildern, Texten und Videos, nicht aus Programmen.
_UPLOAD_ENDUNGEN = (_BILD_ENDUNGEN | _TEXT_ENDUNGEN | _SCHRIFT_ENDUNGEN |
                    {".mp4", ".mov", ".webm", ".m4v", ".pdf", ".mp3", ".wav", ".csv"})

#: Grenzen für den Materialauszug aus einem Projektordner.
_MAX_TEXTDATEI = 400_000        # größere Dateien sind Daten, kein Inhalt
_MAX_DATEIEN = 400
_MAX_GESAMT = 300 * 1024 * 1024


def katalog() -> dict:
    """Alles, was die Oberfläche für diesen Bereich braucht."""
    return {
        "quellen": QUELLEN,
        "fokus": FOKUS,
        "tonfaelle": TONFAELLE,
        "dauern": list(DAUERN),
        "sprachen": SPRACHEN,
        "modelle": [{"id": kennung, "name": name} for kennung, name in config.BRAG_MODELLE],
        "modell_vorgabe": config.BRAG_MODEL,
        "bloecke": [{"kennung": b, "name": BLOCKNAMEN[b]} for b in BLOECKE],
        "befund": bragagent.befund(),
    }


# ── Einstellungen ────────────────────────────────────────────────────────────

def einstellungen_pruefen(roh: dict, Einstellungen):
    """Macht aus den Antworten des Formulars einen gültigen Auftrag.

    Nimmt auch die gespeicherten Einstellungen eines früheren Auftrags entgegen (dort
    steht alles unter `premium`) — so funktioniert „Erneut versuchen“.
    """
    roh = {**(roh.get("premium") or {}),
           **{k: v for k, v in roh.items() if v not in (None, "")}}

    quelle = str(roh.get("quelle") or "webseite")
    if quelle not in {q["kennung"] for q in QUELLEN}:
        quelle = "webseite"

    url = webaufnahme.adresse_normieren(str(roh.get("url") or "")) if quelle == "webseite" else ""
    ordner = str(roh.get("projektordner") or "").strip() if quelle == "ordner" else ""
    thema = " ".join(str(roh.get("thema") or "").split())[:600]

    if quelle == "webseite" and not url:
        raise errors.EingabeFehler(
            "Es fehlt der Link zur Webseite.",
            "Zum Beispiel: meinbetrieb.de", ursprung=QUELLE)
    if quelle == "ordner":
        if not ordner:
            raise errors.EingabeFehler(
                "Es fehlt der Projektordner.",
                "Auf „Ordner wählen“ klicken und den Ordner der Webseite auswählen.",
                ursprung=QUELLE)
        if not Path(ordner).is_dir():
            raise errors.EingabeFehler(
                "Diesen Ordner gibt es nicht.",
                f"Geprüft wurde: {ordner[:160]}", ursprung=QUELLE)
    if quelle == "thema" and len(thema) < 10:
        raise errors.EingabeFehler(
            "Die Beschreibung ist zu kurz.",
            "Zwei bis drei Sätze darüber, was das Video zeigen soll, genügen.",
            ursprung=QUELLE)

    tonfall = str(roh.get("tonfall") or "polished")
    if tonfall not in {t["kennung"] for t in TONFAELLE}:
        tonfall = "polished"
    try:
        dauer = int(roh.get("dauer") or 22)
    except (TypeError, ValueError):
        dauer = 22
    dauer = min(DAUERN, key=lambda d: abs(d - dauer))
    sprache = "en" if str(roh.get("sprache") or "de") == "en" else "de"
    modell = str(roh.get("modell") or config.BRAG_MODEL)
    if modell not in {m for m, _ in config.BRAG_MODELLE}:
        modell = config.BRAG_MODEL

    fokus = str(roh.get("fokus") or "auto")
    if fokus not in {f["kennung"] for f in FOKUS}:
        fokus = "auto"

    premium = {
        "quelle": quelle,
        "fokus": fokus,
        "url": url,
        "projektordner": ordner,
        "thema": thema,
        "kunde": " ".join(str(roh.get("kunde") or "").split())[:80],
        "zielgruppe": " ".join(str(roh.get("zielgruppe") or "").split())[:200],
        "botschaft": " ".join(str(roh.get("botschaft") or "").split())[:300],
        "cta": " ".join(str(roh.get("cta") or "").split())[:60],
        "kontakt": " ".join(str(roh.get("kontakt") or "").split())[:120],
        "tonfall": tonfall,
        "dauer": dauer,
        "sprache": sprache,
        "modell": modell,
        "wunsch": " ".join(str(roh.get("wunsch") or "").split())[:600],
        "korb": re.sub(r"[^a-zA-Z0-9]", "", str(roh.get("korb") or ""))[:32],
    }

    return Einstellungen(
        briefing=(url or ordner or thema)[:config.MAX_BRIEFING_CHARS],
        art="premium", szenen=1, sekunden=dauer, seitenverhaeltnis="16:9",
        formate=(), videomodell="", bildmodell="",
        zielgruppe=premium["zielgruppe"], tonfall=tonfall,
        stil=premium["kunde"] or _titel_aus(premium),
        wiederholung_von=str(roh.get("wiederholung_von") or "").strip()[:32],
        premium=premium)


def _titel_aus(premium: dict) -> str:
    """Ein sprechender Name für Auftrag und Ordner, wenn der Kunde keinen genannt hat."""
    if premium.get("url"):
        return premium["url"].split("//")[-1].strip("/").split("/")[0]
    if premium.get("projektordner"):
        return Path(premium["projektordner"]).name
    return " ".join(premium.get("thema", "").split()[:6]) or "Premium-Film"


def _dateiname(text: str) -> str:
    sauber = re.sub(r"[^a-z0-9]+", "_", str(text or "film").lower()).strip("_")
    return (sauber or "film")[:40]


# ── Ereignisse ───────────────────────────────────────────────────────────────

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


# ── Material ─────────────────────────────────────────────────────────────────

def korb_ordner(kennung: str) -> Path:
    """Wohin hochgeladene Dateien kommen, bevor der Auftrag läuft."""
    sauber = re.sub(r"[^a-zA-Z0-9]", "", kennung or "")[:32] or "leer"
    ziel = config.DATA_DIR / "material" / sauber
    ziel.mkdir(parents=True, exist_ok=True)
    return ziel


def material_annehmen(korb: str, dateien) -> dict:
    """Legt hochgeladene Dateien in den Korb.

    Die Ordnerstruktur bleibt erhalten (der Browser schickt sie bei einem Ordner-Upload
    im Dateinamen mit), aber jeder Pfadteil wird entschärft: Ein Upload darf niemals
    außerhalb des Korbs landen, auch nicht mit `..` im Namen.
    """
    if not korb:
        raise errors.EingabeFehler("Es fehlt die Kennung des Materialkorbs.",
                                   ursprung=QUELLE)
    ziel = korb_ordner(korb)
    angenommen, abgewiesen, bytes_gesamt = [], [], 0

    for datei in dateien or []:
        roh = datei.filename or ""
        teile = [re.sub(r"[^\w.\- ]", "_", teil)[:60]
                 for teil in roh.replace("\\", "/").split("/")
                 if teil not in ("", ".", "..")]
        if not teile:
            continue
        name = teile[-1]
        if Path(name).suffix.lower() not in _UPLOAD_ENDUNGEN:
            abgewiesen.append(name)
            continue
        pfad = ziel.joinpath(*teile[-3:])       # höchstens zwei Ebenen Struktur
        pfad.parent.mkdir(parents=True, exist_ok=True)
        datei.save(pfad)
        try:
            bytes_gesamt += pfad.stat().st_size
        except OSError:
            pass
        angenommen.append(pfad.relative_to(ziel).as_posix())

    logbook.info(QUELLE, f"Material angenommen: {len(angenommen)} Datei(en), "
                         f"{bytes_gesamt / 1_048_576:.1f} MB.")
    return {"korb": korb, "angenommen": angenommen[:200], "anzahl": len(angenommen),
            "abgewiesen": abgewiesen[:20], "mb": round(bytes_gesamt / 1_048_576, 2)}


def korb_leeren(korb: str) -> int:
    """Wirft einen Materialkorb weg — etwa wenn der Kunde die Auswahl verwirft."""
    sauber = re.sub(r"[^a-zA-Z0-9]", "", korb or "")[:32]
    if not sauber:
        return 0
    ordner = config.DATA_DIR / "material" / sauber
    anzahl = sum(1 for p in ordner.rglob("*") if p.is_file()) if ordner.is_dir() else 0
    shutil.rmtree(ordner, ignore_errors=True)
    return anzahl


def ordner_waehlen() -> dict:
    """Öffnet den Ordner-Dialog des Systems und gibt den gewählten Pfad zurück.

    Der Dialog erscheint bewusst im Vordergrund (`TopMost`): Sonst öffnet er sich hinter
    dem Programmfenster, und für den Kunden sieht es aus, als sei der Knopf kaputt.
    """
    import subprocess
    import sys

    if sys.platform != "win32":
        raise errors.EingabeFehler(
            "Der Ordner-Dialog gibt es nur unter Windows.",
            "Bitte den Pfad des Ordners von Hand in das Feld schreiben.", ursprung=QUELLE)

    skript = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$eltern = New-Object System.Windows.Forms.Form -Property @{TopMost=$true};"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$d.Description = 'Projektordner der Webseite wählen';"
        "$d.ShowNewFolderButton = $false;"
        "if ($d.ShowDialog($eltern) -eq [System.Windows.Forms.DialogResult]::OK)"
        " { Write-Output $d.SelectedPath }"
    )
    try:
        lauf = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", skript],
                              capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as fehler:
        raise errors.VerarbeitungsFehler(
            "Der Ordner-Dialog ließ sich nicht öffnen.",
            f"Bitte den Pfad von Hand eintragen. Systemmeldung: {fehler}",
            ursprung=QUELLE) from fehler

    pfad = (lauf.stdout or "").strip().splitlines()
    gewaehlt = pfad[-1].strip() if pfad else ""
    if not gewaehlt:
        return {"pfad": "", "abgebrochen": True}
    return ordner_pruefen(gewaehlt)


def ordner_pruefen(pfad: str) -> dict:
    """Sieht nach, ob der Ordner taugt — und sagt, was er enthält."""
    pfad = str(pfad or "").strip().strip('"')
    if not pfad:
        raise errors.EingabeFehler("Es wurde kein Ordner angegeben.", ursprung=QUELLE)
    ordner = Path(pfad)
    if not ordner.is_dir():
        raise errors.EingabeFehler(
            "Diesen Ordner gibt es nicht.", f"Geprüft wurde: {pfad[:160]}", ursprung=QUELLE)

    texte = bilder = 0
    for datei in ordner.rglob("*"):
        if not datei.is_file():
            continue
        if any(teil in _UEBERSPRINGEN for teil in datei.parts):
            continue
        endung = datei.suffix.lower()
        if endung in _TEXT_ENDUNGEN:
            texte += 1
        elif endung in _BILD_ENDUNGEN:
            bilder += 1
        if texte + bilder > 5000:
            break

    return {"pfad": str(ordner), "abgebrochen": False, "name": ordner.name,
            "texte": texte, "bilder": bilder,
            "taugt": bool(texte or bilder),
            "hinweis": "" if (texte or bilder) else
                       "In diesem Ordner liegen weder Texte noch Bilder — daraus lässt "
                       "sich kein Film bauen."}


def projekt_auszug(quelle: Path, ziel: Path) -> dict:
    """Kopiert aus einem Projektordner nur das, was für einen Film zählt.

    Warum nicht der ganze Ordner: Ein Django-Projekt hat schnell 500 MB in
    `node_modules`, `.venv` und `staticfiles` — nichts davon sagt etwas über die Marke.
    Genommen werden Texte (Vorlagen, Stylesheets, Daten, Doku), Bilder und Schriften.
    Der Agent arbeitet damit auf einer Kopie; am Original wird nichts verändert.
    """
    quelle, ziel = Path(quelle), Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    genommen = {"texte": 0, "bilder": 0, "schriften": 0, "bytes": 0, "ausgelassen": 0}

    for pfad in sorted(quelle.rglob("*")):
        if genommen["texte"] + genommen["bilder"] + genommen["schriften"] >= _MAX_DATEIEN:
            break
        if genommen["bytes"] >= _MAX_GESAMT:
            break
        if not pfad.is_file() or pfad.is_symlink():
            continue
        if any(teil in _UEBERSPRINGEN or teil.startswith(".") for teil in pfad.relative_to(quelle).parts[:-1]):
            continue
        endung = pfad.suffix.lower()
        try:
            groesse = pfad.stat().st_size
        except OSError:
            continue

        if endung in _TEXT_ENDUNGEN and groesse <= _MAX_TEXTDATEI:
            art = "texte"
        elif endung in _BILD_ENDUNGEN:
            art = "bilder"
        elif endung in _SCHRIFT_ENDUNGEN:
            art = "schriften"
        else:
            genommen["ausgelassen"] += 1
            continue

        zieldatei = ziel / pfad.relative_to(quelle)
        try:
            zieldatei.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pfad, zieldatei)
        except OSError:
            continue
        genommen[art] += 1
        genommen["bytes"] += groesse

    return genommen


def _material_uebernehmen(korb: str, ziel: Path) -> int:
    """Holt hochgeladene Dateien in den Auftragsordner und räumt den Korb weg."""
    if not korb:
        return 0
    quelle = korb_ordner(korb)
    anzahl = 0
    for pfad in sorted(quelle.rglob("*")):
        if not pfad.is_file():
            continue
        zieldatei = ziel / pfad.relative_to(quelle)
        zieldatei.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(pfad, zieldatei)
            anzahl += 1
        except OSError:
            continue
    shutil.rmtree(quelle, ignore_errors=True)
    return anzahl


def _verzeichnis(ordner: Path, grenze: int = 120) -> str:
    """Ein Inhaltsverzeichnis für den Prompt — damit Claude weiß, was da liegt."""
    zeilen = []
    for pfad in sorted(ordner.rglob("*")):
        if not pfad.is_file():
            continue
        try:
            groesse = pfad.stat().st_size
        except OSError:
            continue
        zeilen.append(f"  {pfad.relative_to(ordner).as_posix()}  ({groesse // 1024} KB)")
        if len(zeilen) >= grenze:
            zeilen.append(f"  … und weitere Dateien")
            break
    return "\n".join(zeilen) or "  (keine)"


# ── Der Auftragstext für den Agenten ─────────────────────────────────────────

#: Was ein **Dienstleistungs-Film** leisten muss. Das Gerüst stammt aus der
#: Rümpelwerk-Produktion (siehe `rezept/HANDWERK-werbefilm.md`) und ist an Googles
#: ABCD-Rahmen gebaut: Aufmerksamkeit, Marke von Anfang an, Mensch, eine Handlung.
_FOKUS_DIENSTLEISTUNG = """\
## Worum dieser Film geht: die Arbeit und ihr Ergebnis

Verkauft wird keine Ware, sondern **Arbeit**. Der Zuschauer will einen Beweis, dass sein
Problem lösbar ist — und dass der, der es löst, greifbar ist.

Der Bauplan (ABCD), in dieser Reihenfolge:

1. **Das Problem (0–3 s).** Ein Bild, das die Alltagsrealität des Zuschauers spiegelt —
   das ungemähte Grundstück, die verschmutzte Fläche, der volle Keller. Eine Frage oder
   ein Satz dazu. Kein Aufbau, kein Vorspann.
2. **Der Beweis (3–9 s).** **Vorher/Nachher, wenn es echte Paare gibt** — dann muss es
   derselbe Ort sein, erkennbar an Boden, Wand, Fenster. Das Vorher steht mindestens
   1,4 Sekunden, bevor die Kante läuft: Der Reveal ist nur so viel wert wie die Zeit,
   die das Problem vorher bekommen hat. Gibt es keine Paare: das stärkste
   Ergebnisbild, groß, mit einer Zeile.
3. **Was angeboten wird (9–13 s).** Drei bis vier Leistungen, **einzeln** über echten
   Fotos, jede auf ihrem Beat. Keine Liste auf einer Fläche.
4. **Was zugesagt wird (13–17 s).** Die belegbaren Zusagen des Betriebs: Antwortzeit,
   Festpreis, Versicherung, Bewertung, Jahre am Markt. **Nur, was im Material steht.**
5. **Der Mensch (17–21 s).** Das Gesicht des Inhabers mit Name, Rolle und Ort. Bei
   lokalen Betrieben ist das der stärkste Vertrauensbeleg, weil Plattformen und
   Vermittler anonym bleiben. Nur verwenden, wenn belegt ist, wen das Bild zeigt.
6. **Die End-Card (21–26 s).** Eigene Fläche in der Markenfarbe, Logo, **genau eine**
   Handlungsaufforderung als Knopfform („Jetzt kostenlos anfragen"), darunter Telefon
   und Adresse, dazu die Orte des Einzugsgebiets. Mindestens 4,5 Sekunden Standzeit.
   Sie bewegt sich leicht (2 % Push-in), steht aber nie still.

**Der Marken-Bug ist Pflicht:** Logo in einer kleinen Fläche, oben in der sicheren
Zone, ab Sekunde 0,25 durchgehend bis zur End-Card. Wer nach vier Sekunden wegwischt,
muss trotzdem wissen, wer geworben hat.

**Zahlen brauchen Belege.** Schreibe zu jeder Zahl im Auftrag dazu, woher sie stammt.
Was sich nicht belegen lässt, kommt nicht ins Bild."""

#: Was ein Film über das **Produkt** leisten muss: Hier sieht man die Ware.
_FOKUS_PRODUKT = """\
## Worum dieser Film geht: die Marke und ihre Ware

Der Film zeigt das, was verkauft wird — die Produkte, die Arbeit, die Menschen. **Nicht
die Webseite.** Niemand kauft eine Webseite; gekauft wird, was darauf steht.

Dafür gelten drei harte Regeln:

1. **Die Fotos tragen den Film.** Mindestens zwei Drittel der Laufzeit ist echtes
   Bildmaterial zu sehen, formatfüllend oder als großer Ausschnitt — nicht als Briefmarke
   neben Text. Jedes gelieferte Foto, das etwas taugt, kommt vor.
2. **Text ist Beiwerk.** Kurze Zeilen, die das Bild benennen oder zuspitzen. Keine
   Textwand, keine Aufzählung von Leistungen über dem Bild.
3. **Nur eine reine Schriftszene** ist erlaubt — der Haken am Anfang oder der Abbinder
   am Ende, nicht beides ohne Bild.

Ordne jedem Szenenschritt im Storyboard die **Bilddatei** zu, die dort zu sehen ist,
und sage, wie sie sich bewegt (langsame Fahrt, Zoom, Wechsel). Was das Bild zeigt, sagt
sein Dateiname — nenne es beim Namen."""

#: Was ein Film über die **Webseite** leisten muss: Angebot, Preis, Ablauf, Oberfläche.
_FOKUS_WEBSEITE = """\
## Worum dieser Film geht: die Webseite und ihr Angebot

Der Film zeigt, was die Seite leistet: das Angebot, den Preis, den Ablauf, die
Oberfläche. Er richtet sich an jemanden, der überlegt, ob er hier anfragt.

- Die stärkste Zahl oder Zusage gehört groß ins Bild (Preis, Dauer, Zusicherung).
- Wenn Bildschirmaufnahmen der Seite vorliegen, wird die Seite selbst gezeigt — in
  einem Browserrahmen oder als nachgebauter Ausschnitt.
- Liegen Fotos vor, stützen sie die Aussage (Gesicht, Arbeit, Ergebnis), tragen den
  Film aber nicht allein."""

_PROMPT_SYSTEM = """\
Du bist Creative Director einer Agentur und schreibst den **Auftrag** für einen
Motion-Designer, der daraus ein 15–25 Sekunden langes Marken-Video baut. Das Video wird
für vierstellige Beträge verkauft — dein Auftrag muss so konkret sein, dass daraus ohne
Rückfragen ein fertiger Film entsteht.

{fokus}

Regeln:
- Schreibe auf Deutsch, in klaren Sätzen, ohne Werbefloskeln.
- ERFINDE NICHTS. Verwende nur Namen, Zahlen, Preise, Leistungen und Aussagen, die im
  gelieferten Material stehen. Fehlt etwas, lass es weg statt es zu erfinden.
- Zitiere die stärksten Sätze des Materials **wörtlich** — sie gehören ins Video.
- Nenne die Farben (als Hex-Werte) und Schriften, die im Material vorkommen.
- Benenne den Haken der ersten 2 Sekunden, die Kernaussage, 2–3 Beweise und den Abbinder.
- Gib pro Szene an: Sekunden, was zu sehen ist, welcher Text erscheint (wörtlich),
  welche Datei aus dem Material gezeigt wird.
- Die Szenenzeiten müssen sich auf die gewünschte Gesamtdauer summieren.

Antworte ausschließlich mit dem Auftrag als Markdown, ohne Vorwort, ohne Code-Zaun.
Gliederung:
# Auftrag: <Titel>
## Wer und was
## Angle und Haken
## Wörtliche Texte (jede Zeile ein Zitat aus dem Material)
## Zu zeigendes Material (jede Bilddatei mit dem, was sie zeigt)
## Farben und Schriften
## Storyboard (Szene, Sekunden, welche Bilddatei, Text, Ton)
## Abbinder und Kontakt
## Was verboten ist
"""

#: Die Betriebsanweisung — sie steht vor dem Auftrag und regelt Werkzeuge, Pfade und
#: Abnahme. Der kreative Teil kommt aus dem Master-Prompt, hier steht das Handwerk.
#: Die Regel, die den zweiten Luviq-Film vom ersten unterscheidet. Der erste zeigte
#: 22 Sekunden lang Schrift auf schwarzem Grund — für einen Laden, der bemalte
#: Kleidungsstücke verkauft. Die Bilder lagen nur nicht vor. Jetzt liegen sie vor, und
#: diese Regel sorgt dafür, dass sie auch benutzt werden.
_BILDREGEL_PRODUKT = """\
### Pflicht: Die Fotos tragen diesen Film

{bilderliste}

- **Sieh dir jedes Foto zuerst an** (Read-Werkzeug auf die Bilddatei). Der Auftrag
  kennt die Bilder nur dem Dateinamen nach — „photoroom_20260504_222908" sagt nichts.
  Erst nach dem Ansehen entscheidest du, welches Bild in welche Szene gehört, und
  tauschst die Zuordnung des Auftrags, wo sie nicht passt. Schreibe in den Plan, was
  jedes verwendete Bild zeigt.
- **Unbrauchbares aussortieren:** unscharf, dunkel, Textplakat, zufälliger Ausschnitt.
  Lieber vier gute Bilder zweimal zeigen als acht, von denen die Hälfte trübe ist.
- **Mindestens zwei Drittel der Laufzeit ist ein Foto zu sehen** — formatfüllend oder
  als großer Ausschnitt, mit ruhiger Bewegung (langsamer Zoom, sanfte Fahrt).
- **Jedes brauchbare Foto kommt vor.** Zeige Ware, Arbeit und Menschen, nicht Symbole.
- Text liegt ÜBER dem Bild oder in einem schmalen Band daneben, nie statt des Bildes.
  Höchstens EINE reine Schriftszene (Haken oder Abbinder).
- Bilder werden mit `<img>` eingebunden und liegen im `assets/`-Ordner der Komposition;
  kopiere sie dorthin. Für Bewegung: Hülle mit `overflow: hidden`, das Bild darin per
  GSAP `scale`/`x`/`y` — niemals `width`/`height` animieren.
- Achte auf Lesbarkeit über dem Bild: dunkler Verlauf oder Fläche unter dem Text, sonst
  meldet `check` zu Recht einen Kontrastfehler.
- Schneide Fotos formatgerecht (`object-fit: cover`): im Hochformat hochkant, im
  Querformat quer — ein verzerrtes Produktfoto ist schlimmer als keines."""

_BILDREGEL_DIENSTLEISTUNG = """\
### Pflicht: Arbeit und Ergebnis sind zu sehen

{bilderliste}

- **Sieh dir jedes Foto zuerst an** (Read-Werkzeug). Der Dateiname sagt oft nur
  „galerie_04". Ordne dann zu: Was ist ein **Vorher**, was ein **Nachher**, was ein
  Leistungsbild, was ein Gesicht?
- **Suche nach echten Paaren**: zwei Aufnahmen desselben Ortes, erkennbar an Boden,
  Wand, Fenster, Dachkante. Findest du eines, ist es die stärkste Szene des Films —
  Vorher mindestens 1,4 s stehen lassen, dann eine Wischkante über 1,0–1,2 s.
  Findest du keines, **behaupte keines**: zwei schöne Bilder aus zwei Orten
  nebeneinander sind kein Beweis, und der Zuschauer merkt es.
- **Mindestens zwei Drittel der Laufzeit ist ein Foto zu sehen**, formatfüllend, mit
  ruhiger Bewegung. Jede Leistung bekommt ihr eigenes Bild.
- Text liegt über dem Bild mit dunklem Verlauf darunter — nie ohne.
- Gesichter nur mit Beleg, wen sie zeigen (Bildunterschrift, Alt-Text, „Inhaber").
- Formatgerecht schneiden (`object-fit: cover`), niemals verzerren."""

_BILDREGEL_WEBSEITE = """\
### Bildmaterial

{bilderliste}

- Sieh dir vorhandene Fotos mit dem Read-Werkzeug an, bevor du eines einplanst — der
  Dateiname sagt oft nichts.
- Vorhandene Fotos und Bildschirmaufnahmen stützen die Aussage: Gesicht, Arbeit,
  Ergebnis, die Seite selbst in einem Browserrahmen.
- Der Film trägt sich über Aussage, Zahl und Ablauf — er braucht keine Bilderflut, darf
  aber auch nicht 20 Sekunden reine Schrift sein, wenn Bilder vorliegen."""

_AGENT_VORSPANN = """\
Du baust einen verkaufsfähigen Marken-Film in ZWEI Formaten. Arbeite eigenständig bis
zum fertigen Ergebnis und stelle keine Rückfragen.

## Werkzeuge und Vorgehen
1. Lies zuerst `rezept/REZEPT.md` in diesem Ordner — dort stehen die Regeln für
   Lesbarkeit, Aufbau, Ton und die Fallen, die schon einmal zugeschnappt sind.
2. Benutze den Skill `/brag` (Skill-Werkzeug, Name „brag") als Arbeitsweise:
   Material sichten → Plan schreiben → Komposition bauen → prüfen → rendern.
   Lies dazu die Hyperframes-Skills (`hyperframes-core`, `-animation`, `-creative`,
   `-cli`). Starte NICHT den Hyperframes-Einstiegs-Workflow mit Rückfragen.
3. **Lies `rezept/HANDWERK-werbefilm.md`** — das Handwerkswissen aus einer fertigen,
   abgenommenen Produktion: ABCD-Gerüst, sichere Zonen der Apps, Vorher/Nachher,
   Farbgrading als Dramaturgie, Schnitt aufs Taktraster, End-Card, Bildaufbereitung
   kleiner Vorlagen. Bei einem Dienstleistungs-Film ist es die Hauptquelle.
4. Drei fertige, geprüfte Kompositionen liegen bei. Übernimm daraus die MACHART
   (Zeitachse, Audio-Verdrahtung, Bewegungsschnitte, Masken, Beat-Kommentare),
   NIEMALS Inhalte, Farben, Schriften oder Texte — die gehören anderen Kunden:
   - `rezept/referenz-dienstleistung-hochformat.html` — **der Maßstab für einen
     Dienstleistungs-Film**: Marken-Bug, Vorher/Nachher mit Wischkante, Leistungen
     einzeln, Zusagen mit Zählern, Ansprechpartner, End-Card mit einem CTA.
   - `rezept/referenz-querformat.html` und `rezept/referenz-hochformat.html` — ein
     Webseiten-/Angebotsfilm in beiden Formaten.

## Material
Alles Material liegt in diesem Arbeitsordner:
{materialuebersicht}

{bildregel}

## Zu erzeugen
- `brag-output/composition/index.html` — Querformat 1920×1080
- `brag-output/composition-hoch/index.html` — Hochformat 1080×1920
- Musik aus `~/.claude/skills/brag/assets/music/`, Geräusche aus `.../assets/sfx/`.
  Kopiere die verwendeten Dateien in den jeweiligen `assets/`-Ordner der Komposition.
- Gerendert: `brag-output/brag.mp4` (quer) und `brag-output/brag-hochformat.mp4` (hoch),
  beide mit `npx hyperframes render --quality high`.

## Falls schon etwas dasteht
Liegt im Arbeitsordner bereits eine angefangene Komposition (`brag-output/`), ist das ein
**wiederholter Lauf**: Sieh sie dir an und **baue darauf auf**, statt neu anzufangen.
Aufbereitete Bilder in `assets/`, ein vorhandener Plan und geprüfte Kompositionen sind
bezahlte Arbeit — was fehlt, ist meist nur der Render.

## Zeit — die Reihenfolge, die zählt
Für den ganzen Lauf stehen **{minuten} Minuten** zur Verfügung. Danach wird abgebrochen,
egal wie weit du bist.

- Nach spätestens **der Hälfte der Zeit** müssen beide Kompositionen stehen und die
  Renders laufen. Rendern dauert auf diesem Rechner 4–8 Minuten je Fassung.
- **Bildaufbereitung ist kein Selbstzweck.** Freistellen, Retusche und Feinschliff sind
  Kür: Gelingt eine Aufbereitung nicht in zwei, drei Anläufen, nimm das Originalfoto und
  bette es mit Verlauf oder Vignette ein. Ein gerenderter Film mit einer kleinen
  Unsauberkeit ist unendlich viel mehr wert als ein perfekter, der nie fertig wird.
- Ist noch Zeit übrig, wenn beide Filme liegen: dann bessere nach und rendere erneut.

## Abnahme (nicht abkürzen)
- `npx hyperframes check` muss in BEIDEN Kompositionsordnern ohne Fehler durchlaufen.
- Vor dem Rendern `npx hyperframes snapshot --at <Zeiten>` laufen lassen und die
  Kontaktbogen-Datei mit dem Read-Werkzeug **ansehen**. Was schief steht, wird korrigiert.
- **Lies dabei jedes Wort im Bild.** Kein Wort darf doppelt stehen (das passiert bei
  Lauftext-Bändern mit dupliziertem Inhalt), keines abgeschnitten oder mitten im Wort
  umgebrochen sein, keines ohne Verlauf auf hellem Bild liegen. Ein solcher Fehler
  macht den Film unverkäuflich — er fällt jedem Kunden sofort auf.
- Beide MP4 müssen existieren, 15–25 s lang sein und eine Tonspur haben.
- Schreibe zum Schluss `brag-output/share-copy.txt` (ein bis drei Sätze zum Posten).

## Grenzen
- Bleibe in diesem Arbeitsordner. Ändere nichts außerhalb.
- Erfinde keine Inhalte: keine Preise, Auszeichnungen, Bewertungen oder Kundenstimmen,
  die nicht im Material stehen.
- Antworte am Ende mit einer kurzen Zusammenfassung: Dateien, Dauer, was du gebaut hast.

## Der Auftrag
{auftrag}
"""


def master_prompt_schreiben(premium: dict, material: dict, ordner: Path,
                            arbeit: "Path | None" = None) -> str:
    """Lässt Claude aus Antworten und Material den Auftrag schreiben."""
    tonfall = next((t for t in TONFAELLE if t["kennung"] == premium["tonfall"]), TONFAELLE[0])
    teile = [
        f"Gewünschte Gesamtdauer: {premium['dauer']} Sekunden.",
        f"Tonalität: {tonfall['name']} — {tonfall['beschreibung']}",
        f"Sprache der Texte im Video: {'Englisch' if premium['sprache'] == 'en' else 'Deutsch'}.",
    ]
    if premium.get("kunde"):
        teile.append(f"Kunde/Marke: {premium['kunde']}")
    if premium.get("zielgruppe"):
        teile.append(f"Zielgruppe: {premium['zielgruppe']}")
    if premium.get("botschaft"):
        teile.append(f"Wichtigste Botschaft: {premium['botschaft']}")
    if premium.get("cta"):
        teile.append(f"Handlungsaufforderung am Ende: {premium['cta']}")
    if premium.get("kontakt"):
        teile.append(f"Kontaktzeile für den Abbinder: {premium['kontakt']}")
    if premium.get("wunsch"):
        teile.append(f"Besonderer Wunsch: {premium['wunsch']}")
    if premium.get("thema"):
        teile.append(f"Beschreibung: {premium['thema']}")
    if premium.get("url"):
        teile.append(f"Webseite: {premium['url']}")

    if material.get("texte"):
        gelesen = json.dumps(material["texte"], ensure_ascii=False)[:6000]
        teile.append(f"Ausgelesene Inhalte der Webseite (JSON): {gelesen}")

    teile.append(bilderliste(material.get("bilder") or [], arbeit or ordner))
    teile.append("Verzeichnis des Materials im Arbeitsordner:\n" + material["verzeichnis"])
    if material.get("leseproben"):
        teile.append("Ausschnitte aus den wichtigsten Dateien:\n" + material["leseproben"])

    fokus = (material.get("fokus") or {}).get("fokus", "webseite")
    system = _PROMPT_SYSTEM.format(fokus={
        "produkt": _FOKUS_PRODUKT,
        "dienstleistung": _FOKUS_DIENSTLEISTUNG,
    }.get(fokus, _FOKUS_WEBSEITE))
    auftrag = "\n\n".join(teile)
    antwort = llm.erzeuge(system, auftrag, zeitlimit=300)
    text = antwort.text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text).strip()
    (ordner / "master-prompt.md").write_text(text, encoding="utf-8")
    logbook.info(QUELLE, f"Auftrag geschrieben ({len(text)} Zeichen, "
                         f"{antwort.anzeigename}).")
    return text


def bilderliste(bilder: list, arbeit: Path) -> str:
    """Sagt dem Auftragschreiber, welche Bilder es gibt und was sie zeigen.

    Der Dateiname ist die einzige Beschreibung, die ein Foto von einer fremden Seite
    mitbringt — `heckenschnitt.jpg`, `galerie_04.jpg`, `Photoroom_20260504_222908.jpg`.
    Er wird deshalb mitgegeben, samt Maßen: Ein hochkantes Produktfoto trägt eine
    9:16-Szene, ein breites Landschaftsbild nicht.
    """
    if not bilder:
        return ("Bildmaterial: KEINES. Es liegt kein einziges verwendbares Foto vor — "
                "erfinde keines und behaupte keine Produktansicht, die es nicht gibt.")
    zeilen = [f"Bildmaterial: {len(bilder)} Foto(s) im Arbeitsordner. "
              "Sie sind das Material des Films:"]
    for bild in bilder:
        try:
            pfad = Path(bild["datei"]).relative_to(arbeit).as_posix()
        except (ValueError, KeyError):
            pfad = Path(str(bild.get("datei", ""))).name
        hochkant = "hochkant" if bild["hoehe"] > bild["breite"] * 1.1 else (
            "quer" if bild["breite"] > bild["hoehe"] * 1.1 else "quadratisch")
        zeilen.append(f"  {pfad} — „{bild['hinweis']}“, "
                      f"{bild['breite']}×{bild['hoehe']} ({hochkant})")
    return "\n".join(zeilen)


def _leseproben(ordner: Path, grenze: int = 6) -> str:
    """Die aussagekräftigsten Textdateien anlesen — Startseite, Stylesheet, Preisdaten."""
    kandidaten: list[tuple[int, Path]] = []
    for pfad in ordner.rglob("*"):
        if not pfad.is_file() or pfad.suffix.lower() not in _TEXT_ENDUNGEN:
            continue
        name = pfad.name.lower()
        rang = 0
        if name in ("index.html", "home.html", "base.html"):
            rang = 5
        elif "pricing" in name or "preis" in name or "firma" in name:
            rang = 4
        elif pfad.suffix.lower() == ".css":
            rang = 3
        elif name.endswith(".html"):
            rang = 2
        elif name in ("readme.md", "content.json"):
            rang = 2
        if rang:
            kandidaten.append((rang, pfad))

    kandidaten.sort(key=lambda x: (-x[0], len(str(x[1]))))
    stuecke = []
    for _, pfad in kandidaten[:grenze]:
        try:
            inhalt = pfad.read_text(encoding="utf-8", errors="replace")[:3000]
        except OSError:
            continue
        stuecke.append(f"--- {pfad.relative_to(ordner).as_posix()} ---\n{inhalt}")
    return "\n\n".join(stuecke)[:24000]


# ── Ablauf ───────────────────────────────────────────────────────────────────

def ablauf(auftrag_id: str, e, abbruch: threading.Event) -> dict:
    """Führt einen Premium-Film-Auftrag aus."""
    p = dict(getattr(e, "premium", None) or {})
    titel = p.get("kunde") or _titel_aus(p)

    alt = jobstore.holen(e.wiederholung_von) if e.wiederholung_von else None
    if alt is not None and alt.ordner and Path(alt.ordner).is_dir():
        ordner = Path(alt.ordner)
    else:
        ordner = jobstore.ordner_fuer(jobstore.holen(auftrag_id),
                                      "premium_" + _dateiname(titel))
    arbeit = ordner / "arbeit"
    arbeit.mkdir(parents=True, exist_ok=True)
    jobstore.aktualisieren(auftrag_id, titel=f"Premium-Film · {titel}", ordner=str(ordner))

    # ── Block 1: Material ────────────────────────────────────────────────────
    jobstore.aktualisieren(auftrag_id, block="material")
    _block(auftrag_id, "material", "aktiv", "Material wird zusammengestellt")
    material = _material_sammeln(auftrag_id, p, arbeit, abbruch)
    _block(auftrag_id, "material", "fertig", material["kurz"])
    _uebergang(auftrag_id, "material", "prompt")
    _pruefe_abbruch(abbruch)

    # ── Block 2: Auftrag schreiben ───────────────────────────────────────────
    jobstore.aktualisieren(auftrag_id, block="prompt")
    _block(auftrag_id, "prompt", "aktiv", "Claude schreibt den Auftrag")
    _fortschritt(auftrag_id, "prompt", 0.2, 60, "Material wird gelesen")
    master = master_prompt_schreiben(p, material, ordner, arbeit)
    jobstore.aktualisieren(auftrag_id, drehbuch={"master_prompt": master, "titel": titel})
    _fortschritt(auftrag_id, "prompt", 1.0, 0, "fertig")
    _block(auftrag_id, "prompt", "fertig", f"{len(master)} Zeichen",
           {"master_prompt": master})
    logbook.ereignis("premium", {"master_prompt": master}, job=auftrag_id)
    _uebergang(auftrag_id, "prompt", "bauen")
    _pruefe_abbruch(abbruch)

    # ── Block 3+4: Bauen und Rendern ─────────────────────────────────────────
    jobstore.aktualisieren(auftrag_id, block="bauen")
    _block(auftrag_id, "bauen", "aktiv", "Claude baut die Komposition")
    bragagent.werkzeuge_sichern(
        melden=lambda text: logbook.info(QUELLE, text, job=auftrag_id))
    shutil.copytree(config.BASE_DIR / "bragvorlage", arbeit / "rezept", dirs_exist_ok=True)

    fokus = (material.get("fokus") or {}).get("fokus", "webseite")
    vorlage = {"produkt": _BILDREGEL_PRODUKT,
               "dienstleistung": _BILDREGEL_DIENSTLEISTUNG}.get(fokus, _BILDREGEL_WEBSEITE)
    vorspann = _AGENT_VORSPANN.format(
        minuten=config.BRAG_ZEITLIMIT // 60,
        materialuebersicht=material["verzeichnis"],
        bildregel=vorlage.format(
            bilderliste=bilderliste(material.get("bilder") or [], arbeit)),
        auftrag=master)
    stand = {"block": "bauen", "schritte": 0, "begonnen": time.monotonic()}

    def agentenmeldung(text: str, art: str) -> None:
        stand["schritte"] += 1
        if art == "werkzeug":
            logbook.debug(QUELLE, text, job=auftrag_id)
            # Sobald gerendert wird, springt die Anzeige weiter: Das ist der letzte
            # und längste Abschnitt, und der Kunde soll sehen, dass es vorangeht.
            if "render" in text.lower() and stand["block"] != "render":
                _block(auftrag_id, "bauen", "fertig", f"{stand['schritte']} Schritte")
                _uebergang(auftrag_id, "bauen", "render")
                jobstore.aktualisieren(auftrag_id, block="render")
                _block(auftrag_id, "render", "aktiv", "Video wird gerendert")
                stand["block"] = "render"
        else:
            logbook.info(QUELLE, text, job=auftrag_id)
        vergangen = time.monotonic() - stand["begonnen"]
        anteil = min(0.95, vergangen / max(600.0, config.BRAG_ZEITLIMIT * 0.4))
        _fortschritt(auftrag_id, stand["block"], anteil, 0,
                     f"{stand['schritte']} Arbeitsschritte")

    lauf = bragagent.lauf(arbeit, vorspann, modell=p.get("modell") or config.BRAG_MODEL,
                          abbruch=abbruch, melden=agentenmeldung)
    if stand["block"] == "bauen":
        _block(auftrag_id, "bauen", "fertig", f"{stand['schritte']} Schritte")
        _uebergang(auftrag_id, "bauen", "render")
        jobstore.aktualisieren(auftrag_id, block="render")
    _block(auftrag_id, "render", "fertig", f"{lauf.turns} Schritte · "
                                           f"{lauf.tokens_gesamt:,} Tokens".replace(",", "."))
    _uebergang(auftrag_id, "render", "ausgabe")
    _pruefe_abbruch(abbruch)

    # ── Block 5: Ausgabe ─────────────────────────────────────────────────────
    jobstore.aktualisieren(auftrag_id, block="ausgabe")
    _block(auftrag_id, "ausgabe", "aktiv", "Fassungen werden abgelegt")
    ergebnis = _ausgabe(auftrag_id, e, p, titel, ordner, arbeit, lauf, abbruch)
    _block(auftrag_id, "ausgabe", "fertig",
           f"{ergebnis['dauer']:.0f} s · {ergebnis['bytes'] / 1_048_576:.1f} MB")
    return ergebnis


def _aufnehmen_mit_grenze(auftrag_id: str, url: str, ordner: Path,
                          abbruch: threading.Event):
    """Fotografiert die Seite — aber nicht endlos.

    Warum überhaupt eine Grenze: Auf diesem Notebook brauchte ein großer Shop mehr als
    eine Viertelstunde, ohne eine einzige Datei zu schreiben, und der Auftrag stand still.
    Ein Film entsteht auch aus den Texten der Seite und dem hochgeladenen Material; die
    Aufnahmen sind das Sahnehäubchen, nicht die Bedingung. Läuft die Zeit ab, wird der
    Browser abgeräumt und weitergearbeitet — mit einem Vermerk im Logbuch.
    """
    ende = threading.Event()          # setzt sowohl der Abbruch als auch die Zeitgrenze
    ergebnis: dict = {}

    def arbeiten() -> None:
        try:
            ergebnis["aufnahme"] = webaufnahme.aufnehmen(
                url, ordner, abbruch=ende,
                melden=lambda anteil, text: _fortschritt(auftrag_id, "material",
                                                         0.15 + 0.7 * anteil, 0, text))
        except Exception as fehler:                 # auch Abbruch landet hier
            ergebnis["fehler"] = fehler

    faden = threading.Thread(target=arbeiten, name="aufnahme", daemon=True)
    faden.start()

    frist = time.monotonic() + config.BRAG_AUFNAHME_GRENZE
    while faden.is_alive():
        if abbruch.is_set() or time.monotonic() > frist:
            ende.set()
            faden.join(timeout=20)
            break
        faden.join(timeout=2)

    _pruefe_abbruch(abbruch)
    if "aufnahme" in ergebnis:
        return ergebnis["aufnahme"]

    grund = ergebnis.get("fehler")
    logbook.warnung(QUELLE, "Die Seite ließ sich nicht (rechtzeitig) fotografieren — der "
                            "Film entsteht aus den Texten der Seite und dem hochgeladenen "
                            f"Material. Grund: {type(grund).__name__ if grund else 'Zeitgrenze'}",
                    job=auftrag_id)
    return None


def _bilder_von_der_seite(auftrag_id: str, url: str, ziel: Path,
                          abbruch: threading.Event) -> list[dict]:
    """Holt die Fotos der Seite — ohne Browser, in Sekunden.

    Das ist die Lehre aus dem ersten Luviq-Film: Er wurde rein typografisch, weil kein
    einziges Produktfoto vorlag — die Browser-Aufnahme war in ihre Zeitgrenze gelaufen.
    Dabei stehen die Bilder im HTML und sind in wenigen Sekunden geladen. Für einen
    Modeladen sind sie *der* Film.

    Neben der Startseite werden bis zu drei Unterseiten angesehen, hinter denen
    erfahrungsgemäß die Ware liegt: Shop, Produkte, Galerie, Leistungen.
    """
    try:
        seite = webaufnahme.seite_lesen(url)
    except Exception as fehler:
        logbook.warnung(QUELLE, f"Die Seite ließ sich nicht auslesen: "
                                f"{type(fehler).__name__}", job=auftrag_id)
        return []

    adressen = list(seite.get("bilder") or [])
    for link in (seite.get("links") or [])[:3]:
        _pruefe_abbruch(abbruch)
        try:
            weitere = webaufnahme.seite_lesen(link).get("bilder") or []
        except Exception:
            continue
        adressen += [b for b in weitere if b not in adressen]
        logbook.debug(QUELLE, f"Unterseite gelesen: {link[:90]}", job=auftrag_id)

    bilder = webaufnahme.motivbilder_laden(
        adressen, ziel, hoechstens=12, abbruch=abbruch,
        melden=lambda da, von: _fortschritt(auftrag_id, "material",
                                            0.2 + 0.3 * da / max(1, von), 0,
                                            f"{da} Bild(er) geladen"))
    if bilder:
        logbook.erfolg(QUELLE, f"{len(bilder)} Motivbilder von der Seite geladen: "
                               + ", ".join(b["hinweis"][:24] for b in bilder[:6]),
                       job=auftrag_id)
    else:
        logbook.warnung(QUELLE, "Auf der Seite waren keine brauchbaren Fotos zu finden.",
                        job=auftrag_id)
    return bilder


def _bilder_im_ordner(ordner: Path, hoechstens: int = 14) -> list[dict]:
    """Die größten Bilder eines Ordners — dieselbe Rolle wie die Fotos einer Seite."""
    from PIL import Image

    gefunden = []
    for pfad in sorted(Path(ordner).rglob("*")):
        if pfad.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
            continue
        try:
            with Image.open(pfad) as bild:
                breite, hoehe = bild.width, bild.height
        except Exception:
            continue
        if breite < 400 or hoehe < 400 or not (0.3 < breite / hoehe < 3.2):
            continue
        if webaufnahme._KEIN_MOTIV.search(pfad.name):
            continue
        gefunden.append({"datei": pfad, "quelle": str(pfad), "breite": breite,
                         "hoehe": hoehe, "hinweis": pfad.stem[:60]})
    gefunden.sort(key=lambda b: b["breite"] * b["hoehe"], reverse=True)
    return gefunden[:hoechstens]


def _material_sammeln(auftrag_id: str, p: dict, arbeit: Path,
                      abbruch: threading.Event) -> dict:
    """Legt alles Material in den Arbeitsordner und beschreibt es fürs Prompting."""
    material = {"texte": {}, "kurz": "", "verzeichnis": "", "leseproben": "",
                "bilder": [], "fokus": {}}
    quelle = p.get("quelle")

    hochgeladen = _material_uebernehmen(p.get("korb", ""), arbeit / "material")
    teile = [f"{hochgeladen} hochgeladene Datei(en)"] if hochgeladen else []
    bilder: list[dict] = _bilder_im_ordner(arbeit / "material", 8) if hochgeladen else []

    if quelle == "webseite":
        # Reihenfolge nach Wert je Sekunde: Texte (sofort) → Fotos (Sekunden) →
        # Bildschirmaufnahmen (Minuten, mit Frist). Ein Film überlebt fehlende
        # Aufnahmen; ohne Fotos wird er beliebig.
        _fortschritt(auftrag_id, "material", 0.1, 60, "Die Seite wird gelesen")
        material["texte"] = {k: v for k, v in webaufnahme.adresse_pruefen(p["url"]).items()
                             if k in ("titel", "beschreibung", "marke", "farbe",
                                      "ueberschriften", "knoepfe")}
        _fortschritt(auftrag_id, "material", 0.2, 45, "Fotos der Seite werden geladen")
        bilder += _bilder_von_der_seite(auftrag_id, p["url"], arbeit / "bilder", abbruch)
        if bilder:
            teile.append(f"{len(bilder)} Foto(s) von der Seite")
            logbook.ereignis("vorschau", {"block": "material",
                                          "datei": library.web_pfad(bilder[0]["datei"])},
                             job=auftrag_id)

        # Die Bildschirmaufnahme kostet Minuten. Sie lohnt sich, wenn der Film die
        # *Seite* zeigen soll — für einen Marken-Film mit eigenen Fotos ist sie
        # entbehrlich, und sieben Minuten Wartezeit für ein Bild, das nicht vorkommt,
        # sind schlicht verschenkt.
        vorab = fokus_bestimmen(bilder, material["texte"], p.get("fokus", "auto"))
        if vorab["fokus"] == "marke" and len(bilder) >= 4:
            logbook.info(QUELLE, "Genug eigene Fotos — auf die Bildschirmaufnahme wird "
                                 "verzichtet (sie käme im Marken-Film nicht vor).",
                         job=auftrag_id)
            aufnahme = None
            teile.append("Bildschirmaufnahme nicht nötig")
        else:
            _fortschritt(auftrag_id, "material", 0.55, 0, "Die Seite wird fotografiert")
            aufnahme = _aufnehmen_mit_grenze(auftrag_id, p["url"], arbeit / "aufnahme",
                                             abbruch)
        if aufnahme is not None:
            material["texte"] = aufnahme.texte or material["texte"]
            teile.append(f"Bildschirmaufnahmen von {aufnahme.host}")
            logbook.info(QUELLE, f"Webseite aufgenommen: {aufnahme.url} ({aufnahme.weg})",
                         job=auftrag_id)
        elif "Bildschirmaufnahme nicht nötig" not in teile:
            teile.append("keine Bildschirmaufnahmen")

    elif quelle == "ordner":
        _fortschritt(auftrag_id, "material", 0.3, 30, "Projektordner wird gelesen")
        gezaehlt = projekt_auszug(Path(p["projektordner"]), arbeit / "quelle")
        teile.append(f"{gezaehlt['texte']} Textdatei(en), {gezaehlt['bilder']} Bild(er), "
                     f"{gezaehlt['schriften']} Schrift(en)")
        material["leseproben"] = _leseproben(arbeit / "quelle")
        bilder += _bilder_im_ordner(arbeit / "quelle")
        logbook.info(QUELLE, f"Projektordner übernommen: {teile[-1]}", job=auftrag_id)

    else:
        teile.append("Beschreibung und hochgeladenes Material")

    material["bilder"] = bilder
    material["fokus"] = fokus_bestimmen(bilder, material["texte"], p.get("fokus", "auto"))
    logbook.info(QUELLE, f"Sorte: {material['fokus']['fokus']} — "
                         f"{material['fokus']['begruendung']}", job=auftrag_id)
    logbook.ereignis("premium", {"fokus": material["fokus"]}, job=auftrag_id)

    _fortschritt(auftrag_id, "material", 0.95, 0, "Verzeichnis wird erstellt")
    material["verzeichnis"] = _verzeichnis(arbeit)
    material["kurz"] = " · ".join(teile) or "nur Beschreibung"
    return material


# ── Ausgabe ──────────────────────────────────────────────────────────────────

def _gerenderte_videos(arbeit: Path) -> list[tuple[Path, object]]:
    """Alle brauchbaren MP4 des Agenten, mit ihren Abmessungen."""
    gefunden = []
    for pfad in sorted(arbeit.rglob("*.mp4")):
        if any(teil in ("assets", "node_modules", "snapshots") for teil in pfad.parts):
            continue
        try:
            # Nur leere Hüllen aussortieren. Über die Größe zu urteilen, führt in die
            # Irre: Ein sauber gerenderter Film mit ruhigem Bild kann winzig sein, und
            # ein abgebrochener mit Rauschen groß. Was zählt, prüft `media.angaben()`
            # gleich darunter — Maße und Länge.
            if pfad.stat().st_size < 2_000:
                continue
            angaben = media.angaben(pfad)
        except Exception:
            continue
        if angaben.breite and angaben.hoehe and angaben.dauer >= 2:
            gefunden.append((pfad, angaben))
    return gefunden


def _ausgabe(auftrag_id: str, e, p: dict, titel: str, ordner: Path, arbeit: Path,
             lauf, abbruch: threading.Event) -> dict:
    """Sortiert die gerenderten Videos in die Bibliothek ein."""
    videos = _gerenderte_videos(arbeit)
    if not videos:
        raise errors.VerarbeitungsFehler(
            "Es ist kein fertiges Video entstanden.",
            "Der Arbeitsordner des Auftrags enthält den Zwischenstand — dort steht in "
            "`brag-output/`, wie weit Claude gekommen ist. „Erneut versuchen“ baut darauf auf.",
            ursprung=QUELLE)

    quer = max((v for v in videos if v[1].breite >= v[1].hoehe),
               key=lambda v: v[1].breite * v[1].hoehe, default=None)
    hoch = max((v for v in videos if v[1].hoehe > v[1].breite),
               key=lambda v: v[1].breite * v[1].hoehe, default=None)

    ausgefallen: list[str] = []
    if quer is None:
        # Nur Hochformat entstanden: Das Querformat wird daraus geschnitten, damit der
        # Kunde nicht mit einer halben Lieferung dasteht — mit Vermerk.
        quer = hoch
        ausgefallen.append("Querformat wurde aus dem Hochformat abgeleitet")

    film = ordner / "film.mp4"
    shutil.copy2(quer[0], film)
    angaben = media.angaben(film)

    fassungen: dict[str, str] = {}
    ziel_hoch = ordner / "film_hoch.mp4"
    if hoch is not None:
        shutil.copy2(hoch[0], ziel_hoch)
        fassungen["hoch"] = library.web_pfad(ziel_hoch)
    else:
        try:
            media.format_erzeugen(film, ziel_hoch, "hoch", abbruch=abbruch)
            fassungen["hoch"] = library.web_pfad(ziel_hoch)
            ausgefallen.append("Hochformat wurde aus dem Querformat geschnitten")
        except errors.StudioFehler as fehler:
            logbook.warnung(QUELLE, f"Hochformat fehlt: {fehler.meldung}", job=auftrag_id)

    # Poster: das des Agenten, sonst selbst ziehen.
    poster = ordner / "film_poster.jpg"
    agentenposter = next((pf for pf in sorted(arbeit.rglob("*.jpg"))
                          if pf.stem in ("brag", "poster", "brag-hochformat")), None)
    try:
        if agentenposter is not None:
            shutil.copy2(agentenposter, poster)
        else:
            media.format_erzeugen(film, poster, "poster", wie_die_quelle=True,
                                  abbruch=abbruch)
    except Exception as fehler:
        logbook.warnung(QUELLE, f"Vorschaubild nicht erzeugt: {fehler}", job=auftrag_id)

    # Begleitmaterial des Agenten aufheben — Plan, Brief, Posting-Text.
    for name, ziel in (("brag-plan.md", "plan.md"),
                       ("composition-brief.md", "komposition-brief.md"),
                       ("share-copy.txt", "posting-vorschlag.txt")):
        gefunden = next(iter(sorted(arbeit.rglob(name))), None)
        if gefunden is not None:
            try:
                shutil.copy2(gefunden, ordner / ziel)
            except OSError:
                pass

    posting_text = ""
    vorschlag = ordner / "posting-vorschlag.txt"
    if vorschlag.exists():
        posting_text = vorschlag.read_text(encoding="utf-8", errors="replace")[:600].strip()

    aufwand = {
        "tokens": lauf.tokens, "tokens_gesamt": lauf.tokens_gesamt,
        "kosten_usd": round(lauf.kosten_usd, 4), "modell": lauf.modell,
        "schritte": lauf.turns, "dauer": round(lauf.dauer),
        "werkzeuge": lauf.werkzeuge,
    }
    ergebnis = {
        "film": str(film), "film_web": library.web_pfad(film),
        "poster": library.web_pfad(poster) if poster.exists() else "",
        "ordner": str(ordner), "dauer": angaben.dauer, "breite": angaben.breite,
        "hoehe": angaben.hoehe, "bytes": angaben.bytes, "szenen": 1,
        "formate": fassungen, "titel": titel, "ausgefallen": ausgefallen,
        "art": "premium", "aufwand": aufwand,
        "arbeitsordner": library.web_pfad(arbeit),
    }

    drehbuch = SimpleNamespace(titel=f"Premium-Film · {titel}", posting=posting_text,
                               hashtags=[], zusammenfassung=posting_text)
    ergebnis["posting"] = library.posting_schreiben(ordner, drehbuch, "16:9")
    library.begleitzettel_schreiben(ordner, {
        "titel": f"Premium-Film · {titel}", "art": "premium",
        "erstellt": time.strftime("%d.%m.%Y %H:%M"),
        "briefing": e.briefing,
        "einstellungen": e.als_dict(),
        "aufwand": aufwand,
        "drehbuch": {"titel": titel, "posting": posting_text, "hashtags": [],
                     "zusammenfassung": posting_text},
        "ergebnis": {k: v for k, v in ergebnis.items() if k != "formate"},
    })
    logbook.erfolg(QUELLE, f"Premium-Film fertig: {angaben.breite}×{angaben.hoehe}, "
                           f"{angaben.dauer:.0f} s, "
                           f"{'mit' if fassungen.get('hoch') else 'ohne'} Hochformat. "
                           f"Aufwand: {lauf.tokens_gesamt:,} Tokens, "
                           f"{lauf.kosten_usd:.2f} $.".replace(",", "."), job=auftrag_id)
    return ergebnis
