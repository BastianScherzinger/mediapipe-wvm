# MEDIAPIPE WVM — technische Dokumentation

Stand 03.08.2026 · Version 1.0.0

Diese Datei richtet sich an denjenigen, der das Werkzeug später ändert oder erweitert.
Für die Bedienung genügt die [README](../README.md).

---

## 1. Aufbau

```
run.py                Start: Diagnose → Server → Desktop-Fenster
start.bat             Doppelklick-Start für den Kunden

app/
├── config.py         Konfiguration, .env, Startdiagnose, Secret-Maskierung
├── errors.py         Fehlerklassen mit Meldung UND Handlungshinweis
├── logbook.py        Logbuch + Ereignisverteilung (ein Kanal für beides)
├── higgsfield.py     Platform-API: Bild, Video, Polling, Restzeit, Abbruch
├── promptsmith.py    Briefing → Drehbuch (der eigentliche Mehrwert)
├── llm/              Sprachmodell-Kette: CLI → API → Ollama
│   ├── claude_cli.py
│   ├── claude_api.py
│   └── lokal.py
├── pipeline.py       Zustandsmaschine über die fünf Blöcke
├── jobstore.py       Aufträge in SQLite, überleben Neustarts
├── media.py          ffmpeg: Montage, Formate, GIF, Vorschaubild
├── library.py        Bibliothek, Pfadsicherheit, Formate nachziehen
├── topics.py         Themen- und Merkmalkatalog (reine Daten)
└── server.py         Flask-Routen, Ereignisstrom, Dateiauslieferung

static/js/            kern · formular · ablauf · logbuch · bibliothek · start
static/css/app.css    Design-Tokens und alle Bausteine
templates/index.html  Struktur + eingebetteter Iconsatz

data/                 auftraege.db, laufzeiten.json, guthabenstand.json
output/               ein Ordner je Video
tests/                156 Tests
```

**Abhängigkeitsrichtung:** `server → pipeline → {promptsmith, higgsfield, media, library,
jobstore}`. Darunter liegen `config`, `errors`, `logbook`, die jeder benutzen darf.
Nach oben zeigt nichts — `media` weiß nichts von `pipeline`, `library` nichts von `server`.

---

## 2. Die beiden Anbieterketten

Kein Zugang ist fest verdrahtet. Fällt eine Stufe aus, rückt die nächste nach, und die
Oberfläche sagt, welcher Weg gerade trägt.

**Sprachmodell** (`MPW_LLM_CHAIN`, Vorgabe `cli,api,local`)

| Stufe | Wann sie greift | Stand 03.08.2026 |
|---|---|---|
| `cli` | Claude-CLI mit Abo-Anmeldung, kein Guthaben nötig | funktioniert |
| `api` | `ANTHROPIC_KEY` mit Guthaben | Schlüssel gültig, **kein Guthaben** |
| `local` | Ollama auf dem Rechner | läuft, `qwen2.5:7b` |

Eine Stufe, die an Zugang oder Guthaben scheitert, wird fünf Minuten gesperrt
(`llm._SPERRDAUER`), damit nicht jede Anfrage in dieselbe Wand läuft. Ein Netzhänger
sperrt nicht — der kann beim nächsten Mal weg sein.

**Video** (`MPW_VIDEO_CHAIN`)

| Stufe | Stand |
|---|---|
| `platform` | Schlüssel gültig, **kein API-Guthaben** (403 `not_enough_credits`) |
| `demo` | `media.platzhalter_clip()` — ganze Kette ohne Guthaben prüfbar |

---

## 3. Higgsfield — was zu wissen ist

Vollständiger Befund: [`API_BEFUND.md`](API_BEFUND.md). Die drei Punkte, die immer
wieder Zeit kosten:

**Zwei getrennte Guthaben.** Das Web-Abo (Soul/Plus auf higgsfield.ai) und die
Platform-API-Credits (platform.higgsfield.ai) sind verschiedene Töpfe. Ein Jahresabo
füllt den API-Topf nicht. Das ist die häufigste Fehlerursache überhaupt.

**Der Kontostand ist nicht abfragbar.** Es gibt keinen Endpunkt dafür, und ein
Probeauftrag mit leerem Rumpf taugt nicht: die Schemaprüfung läuft **vor** der
Guthabenprüfung, ein leerer Rumpf bekommt also immer 422 — auch bei leerem Konto.
Deshalb lernt `higgsfield._Guthabenstand` den Stand aus echten Aufträgen und merkt ihn
sich in `data/guthabenstand.json`. Der Selbsttest meldet ehrlich „unbekannt“, solange
kein Auftrag gelaufen ist.

**Neue Modelle aufnehmen** — ohne Guthaben zu verbrauchen:

```
POST /{modellpfad}  mit  {}                     → 422 nennt alle Pflichtfelder
POST /{modellpfad}  mit  {"duration": 999, …}   → nennt alle erlaubten Werte
```

Beides erzeugt keinen Auftrag. Die Ergebnisse gehören dann nach
`higgsfield.ERLAUBTE_DAUER` und `higgsfield.VIDEOMODELLE`.

---

## 4. Der Ablauf

`pipeline._bearbeiten()` läuft in einem eigenen Faden und durchläuft fünf Blöcke. Jeder
Zustandswechsel geht als Ereignis an die Oberfläche:

| Ereignis | Wirkung im Dashboard |
|---|---|
| `block` | Blockzustand: wartend · aktiv · fertig · fehler · uebersprungen |
| `fortschritt` | Balken und Restzeit im aktiven Block |
| `uebergang` | der wandernde Punkt auf der Verbindung |
| `startbild` | Vorschaubild im Bild-Block |
| `auftrag` | gestartet · fertig · fehler · abgebrochen |
| `bibliothek` | Bestand hat sich geändert |

**Ein Auftrag zur Zeit.** `pipeline._aktuell` ist die Sperre; ein zweiter Start wirft
einen `EingabeFehler`. Das schützt vor doppelten Kosten und vor zwei Aufträgen, die sich
um dieselben Dateien streiten.

**Abbruch** läuft über ein `threading.Event`, das jeder wartende Aufruf prüft — auch
mitten im ffmpeg-Lauf und mitten im Polling. Wartende Higgsfield-Aufträge werden
zusätzlich beim Dienst storniert.

---

## 5. Was beim Bauen Zeit gekostet hat

Vier Fallen, die alle im Code kommentiert sind — damit sie niemand ein zweites Mal tritt:

**`Connection: keep-alive` im Ereignisstrom.** Nach PEP 3333 ein verbotener
Verbindungs-Header. Waitress bricht die Anfrage mit `AssertionError` ab — und damit fiel
der *gesamte* Ereignisstrom aus, ohne dass die Oberfläche einen Fehler zeigte. Sie wirkte
nur tot. (`server.py`, Route `/api/strom`)

**Ein Programm namens `ffmpeg`, das keines ist.** Im Suchpfad lag eine Hülle, die
`-hide_banner` nicht kannte und jeden Aufruf mit „Option not found“ abbrach. Seitdem
wird jeder Kandidat einmal erprobt, statt dem Namen zu vertrauen.
(`config._ffmpeg_taugt`)

**Die Endung der Nebendatei.** Beim Schreiben nach `name.mp4.teil` konnte ffmpeg das
Ausgabeformat nicht ableiten. Nebendateien heißen deshalb `name.teil.mp4`.
(`media.format_erzeugen`)

**Die Claude-CLI hält sich nicht ans vorgegebene Schema.** Sie bringt einen eigenen,
sehr umfangreichen Systemtext mit, hinter dem eine angehängte Anweisung verblasst — sie
lieferte `projekt`/`szenen`/`montage` mit Feldern `prompt`/`kamera`/`bewegung_im_bild`
statt der angeforderten Struktur, und das auf Deutsch. Zwei Gegenmaßnahmen:
das Format steht **zusätzlich im Auftragstext**, und `promptsmith` versteht über
Alias-Listen beide Schemata. (`promptsmith._ALIAS_*`)

---

## 6. Sicherheit

- **Zugangsdaten** nur aus der `.env`, nie im Code. `config.entschaerfe()` räumt sie aus
  jedem Text, der ins Logbuch oder in eine Fehlermeldung geht — auch aus Ausnahmetexten
  fremder Bibliotheken. In der Oberfläche erscheinen sie ausschließlich maskiert.
- **Der Server hört nur auf 127.0.0.1.** Fest verdrahtet, nicht konfigurierbar.
- **Jeder Pfad aus der Oberfläche** geht durch `library.sicherer_pfad()`. Das löst auch
  Verknüpfungen auf, die Prüfung ist also nicht durch eine Verknüpfung im Ausgabeordner
  zu umgehen.
- **Löschen** verlangt eine ausdrückliche Bestätigung im Auftrag, zusätzlich zur
  Rückfrage in der Oberfläche.
- **Netzaufrufe** haben immer ein Zeitlimit; Wiederholungen sind begrenzt und finden nur
  bei vorübergehenden Fehlern statt. Guthaben- und Inhaltsfehler werden nie wiederholt —
  das würde nur Zeit kosten.

---

## 7. Tests

```
python -m pytest tests/ -q                    # 156 Tests, rund 100 Sekunden
python -m pytest tests/ -q -m "not langsam"   # ohne echte ffmpeg-Läufe, ~5 Sekunden
```

| Datei | Inhalt |
|---|---|
| `test_fundament.py` | Konfiguration, Fehlerübersetzung, Logbuch, Maskierung |
| `test_higgsfield.py` | API-Client mit Attrappen: Polling, Abbruch, alle Fehlerarten |
| `test_promptsmith.py` | JSON-Bergung, fremde Feldnamen, Notbehelf, Dateinamen |
| `test_media.py` | Formatvorgaben, Dateiangaben, echte ffmpeg-Läufe |
| `test_pipeline.py` | Auftragsspeicher, Eingabeprüfung, Pfadsicherheit, Bibliothek |
| `test_ende_zu_ende.py` | **die ganze Kette** mit Higgsfield-Attrappe |

Der Ende-zu-Ende-Test ist der wichtigste: er ersetzt nur Higgsfield und das
Sprachmodell, alles andere läuft echt — Zustandsmaschine, Montage, Formate,
Auftragsspeicher, Bibliothek und Ereignisstrom. Er prüft auch, dass jeder Block genau
einmal „fertig“ meldet und die Übergänge in der richtigen Reihenfolge kommen.

Was er **nicht** kann: die Bildqualität von Higgsfield beurteilen. Sobald Guthaben da
ist, gehört ein echter Durchlauf gefahren (Aufgabe P13).

---

## 8. Erweitern

**Neues Thema im Formular** — Eintrag in `topics.THEMEN`. Kein Code nötig.

**Neues Merkmal** — Eintrag in `topics.ARGUMENTGRUPPEN`. `mehrfach: False` macht die
Gruppe zu einer Entweder-oder-Wahl.

**Neues Ausgabeformat** — Eintrag in `media.FORMATE` mit `kurz`-Kürzel für die Kachel.
Oberfläche und Bibliothek nehmen es automatisch auf.

**Neues Videomodell** — erst mit der Sonde aus Abschnitt 3 prüfen, dann in
`higgsfield.VIDEOMODELLE` und `ERLAUBTE_DAUER` eintragen.

**Anderer Videoanbieter** — eine Klasse mit denselben vier Methoden wie
`Higgsfield` (`bild`, `video_aus_bild`, `video_aus_text`, `herunterladen`) genügt; die
Pipeline spricht nur über diese Schnittstelle. Der Ende-zu-Ende-Test zeigt an seiner
Attrappe, wie wenig dafür nötig ist.
