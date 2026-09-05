# MEDIAPIPE WVM — technische Dokumentation

Stand 26.08.2026 · Version 1.0.0

Diese Datei richtet sich an denjenigen, der das Werkzeug später ändert oder erweitert.
Für die Bedienung genügt die [README](../README.md).

> **Zuerst lesen, wenn etwas klemmt:** [`BEFUND_2026-08-26.md`](BEFUND_2026-08-26.md).
> Dort steht, was beim ersten Lauf auf dem Kundenrechner schiefging, woran es lag, was
> daraufhin geändert wurde und was noch offen ist. Es ist die jüngste Prüfung und geht
> im Zweifel diesem Dokument vor.

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
├── higgsfield_mcp.py Abo-Weg über MCP: OAuth-Anmeldung, Bild, Video,
│                     Übersetzung der Modellnamen (Platform ≠ MCP)
├── videoquelle.py    Wählt zwischen Platform, Abo und Probelauf
├── promptsmith.py    Briefing → Drehbuch (der eigentliche Mehrwert)
├── llm/              Sprachmodell-Kette: CLI → API → Ollama
│   ├── claude_cli.py
│   ├── claude_api.py
│   └── lokal.py
├── pipeline.py       Zustandsmaschine über die fünf Blöcke
├── jobstore.py       Aufträge in SQLite, überleben Neustarts
├── media.py          ffmpeg: Montage, Formate, GIF, Vorschaubild
├── library.py        Bibliothek, Pfadsicherheit, Formate nachziehen
├── updater.py        Aktualisierung aus dem Repository + Neustart
├── topics.py         Themen- und Merkmalkatalog (reine Daten)
└── server.py         Flask-Routen, Ereignisstrom, Dateiauslieferung

static/js/            kern · formular · ablauf · logbuch · bibliothek ·
                      aktualisierung · abo · start
static/css/app.css    Design-Tokens und alle Bausteine
templates/index.html  Struktur + eingebetteter Iconsatz

data/                 auftraege.db, laufzeiten.json, guthabenstand.json,
                      higgsfield_abo.json
output/               ein Ordner je Video
tests/                251 Tests
```

**Abhängigkeitsrichtung:** `server → pipeline → {promptsmith, higgsfield, media, library,
jobstore}`. Darunter liegen `config`, `errors`, `logbook`, die jeder benutzen darf.
Nach oben zeigt nichts — `media` weiß nichts von `pipeline`, `library` nichts von `server`.

---

## 2. Die beiden Anbieterketten

Kein Zugang ist fest verdrahtet. Fällt eine Stufe aus, rückt die nächste nach, und die
Oberfläche sagt, welcher Weg gerade trägt.

**Sprachmodell** (`MPW_LLM_CHAIN`, Vorgabe `cli,api,local`)

| Stufe | Wann sie greift | Entwicklungsrechner 03.08.2026 | Kundenrechner 26.08.2026 |
|---|---|---|---|
| `cli` | Claude-CLI über die Abo-Anmeldung, kein Guthaben nötig | **funktioniert** | Fehler — Grund wurde damals nicht protokolliert |
| `api` | `ANTHROPIC_KEY` mit Guthaben | **funktioniert** | **kein Guthaben mehr** |
| `local` | Ollama auf dem Rechner | läuft, `qwen2.5:7b` | nicht installiert |

Trägt keine Stufe, baut `promptsmith._notbehelf()` das Drehbuch selbst. Das Programm
läuft dann weiter — mit sichtbar schwächerer Qualität, weil die Bildprompts auf Deutsch
bleiben. Es ist ein Notausgang, kein Betriebszustand.

> **Ein ungültiges Abo-Token macht den CLI-Weg nicht mehr kaputt.** `CLAUDE_CODE_OAUTH_TOKEN`
> aus der `.env` wird in die Umgebung der CLI gesetzt und **überschreibt damit die
> Anmeldung des Rechners**. Gilt es nicht mehr, war der Weg früher tot, obwohl
> `claude login` getragen hätte. `claude_cli.erzeuge()` versucht es bei einem
> Zugangsfehler deshalb ein zweites Mal ohne Token.

> **Zum Abo-Token.** In der `.env` steht `CLAUDE_CODE_OAUTH_TOKEN`. Damit läuft der
> CLI-Weg auch auf einem Rechner, auf dem nie `claude login` ausgeführt wurde — genau
> das braucht ein Kunde ohne eigenes Claude-Konto. Ohne das Token nimmt die CLI die
> Anmeldung des jeweiligen Rechners; ist keine da, rückt die nächste Stufe nach.
> Ein neues Token erzeugt man mit `claude setup-token`.
>
> Wichtig ist außerdem die Reihenfolge im Umgang mit den Umgebungsvariablen: liegt ein
> `ANTHROPIC_KEY` in der Umgebung, nimmt die CLI den API-Weg statt der Abo-Anmeldung.
> `claude_cli._umgebung()` entfernt ihn deshalb vor jedem Aufruf.

Eine Stufe, die an Zugang oder Guthaben scheitert, wird fünf Minuten gesperrt
(`llm._SPERRDAUER`), damit nicht jede Anfrage in dieselbe Wand läuft. Ein Netzhänger
sperrt nicht — der kann beim nächsten Mal weg sein.

**Video** (`MPW_VIDEO_CHAIN`, Auswahl in `videoquelle.aktiv()`)

| Stufe | Was sie ist | Stand |
|---|---|---|
| `platform` | Platform-API mit dem Schlüssel aus der `.env` | Schlüssel gültig, **kein Guthaben** (403 bei allen Modellen, 03.08.2026) |
| `abo` | MCP-Dienst mit den Credits des Web-Abos | beim Kunden verbunden und mit Credits (26.08.2026) |
| `demo` | Platzhalterclips aus ffmpeg, ohne Netz | jederzeit einsatzbereit |

> **Der Abo-Weg steht bewusst nicht in der Vorgabekette.** Sobald er angemeldet ist,
> schiebt `videoquelle._reihenfolge()` ihn selbsttätig nach vorn — er ist dann der
> einzige mit Guthaben. Niemand muss dafür die `.env` anfassen. Wer ihn trotzdem
> festschreiben will, darf `abo` seit dem 26.08.2026 in `MPW_VIDEO_CHAIN` eintragen;
> vorher hat `config._chain()` ihn stillschweigend herausgefiltert.

**„Verfügbar“ genügt nicht.** Ein hinterlegter Schlüssel auf einem leeren Guthabentopf
ist eingerichtet und trotzdem nutzlos. Würde die Auswahl nur `verfuegbar` prüfen, zöge
`platform` jeden Auftrag an sich und bräche mit 403 ab — der zweite Eintrag der Kette
stünde bloß zur Zierde da. `videoquelle._kann_liefern()` fragt deshalb zusätzlich das
Guthabengedächtnis des Weges (`guthaben_bekannt()`, nur der Platform-Client hat eins).

Zwei Dinge halten das ehrlich:

* Der Befund verfällt nach `videoquelle.GEDAECHTNIS` (6 Stunden). Wer nachlädt, wird
  sonst für immer übersprungen.
* Findet der erste Durchgang niemanden, läuft ein zweiter **ohne** Guthabenprüfung. Die
  Fehlermeldung des Dienstes selbst ist immer noch besser als gar kein Versuch.

Fällt die Wahl auf den Probelauf, ist die Logzeile eine **Warnung**, keine Notiz — wer
sie überliest, hält die Platzhalter am Ende für das Ergebnis.

**So läuft die Anmeldung** (`higgsfield_mcp.py`): Das Programm meldet sich selbst als
Anwendung an (dynamische Registrierung nach RFC 7591 — geprüft, HTTP 201), erzeugt eine
Anmelde-URL mit PKCE/S256 und nimmt die Antwort auf einem lokalen Port zwischen 8765 und
8779 entgegen. Danach liegt ein Erneuerungstoken in `data/higgsfield_abo.json`, und alle
weiteren Starts brauchen keinen Browser mehr. Der Dienst spricht MCP über HTTP und
antwortet wahlweise als JSON oder als Ereignisstrom; `_zerlegen()` versteht beides.

**Die Modellnamen unterscheiden sich von der Platform-API** — dort Pfade wie
`higgsfield-ai/soul/standard`, hier kurze Kennungen ohne Schrägstrich. Wird ein
Platform-Name durchgereicht, antwortet der Dienst mit `unknown model` und der Auftrag
ist gescheitert, bevor er begonnen hat. Genau daran ist der erste Lauf beim Kunden am
26.08.2026 abgebrochen (→ [`BEFUND_2026-08-26.md`](BEFUND_2026-08-26.md), Abschnitt 2).

Seither übersetzt `higgsfield_mcp.modell_aufloesen(wunsch, art)`, und zwar mit zwei
Sicherungen übereinander:

1. **Kein Platform-Name verlässt je den Abo-Weg.** Alles mit Schrägstrich geht durch die
   Tabelle `_UEBERSETZUNG` — eine Kandidatenliste je Modell, nicht eine feste Zuordnung.
2. **Der Dienst hat das letzte Wort.** `modellliste()` fragt `models_explore` und merkt
   sich die Antwort eine Stunde lang. Was der Dienst führt, schlägt jede Tabelle.

Weist er ein Modell trotzdem ab, wird die Liste frisch geholt und der Auftrag **einmal**
mit einem nachweislich vorhandenen Namen wiederholt. Das steht dann so im Logbuch:

```
Modell „…“ ist dem Abo-Dienst unbekannt — es wird „…“ genommen.
```

Wer diese Zeile sieht, trägt den genannten Namen in `_UEBERSETZUNG` nach; dann entfällt
der Umweg über den zweiten Versuch.

> Die Kennungen in `_UEBERSETZUNG` sind **nicht nachgemessen** — `mcp.higgsfield.ai`
> beantwortet ohne Anmeldung jede Anfrage mit `401`, auch `tools/list`. Die
> Laufzeitabfrage ist deshalb die eigentliche Absicherung, die Tabelle nur der
> Rückfall.

**Für die Übergabe:** `data/higgsfield_abo.json` ist von `.gitignore` erfasst. Wer die
Anmeldung auf den Kundenrechner mitgeben will, kopiert die Datei mit der `.env` zusammen;
sonst klickt der Kunde einmal selbst.

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
| `warteschlange` | eingereiht · entfernt · geleert |
| `szene_ausgefallen` | eine Szene hat es nicht geschafft, der Film entsteht ohne sie |
| `bibliothek` | Bestand hat sich geändert |

**Ein Auftrag zur Zeit — aber eine Reihe dahinter.** `pipeline._aktuell` ist die Sperre.
Zwei gleichzeitige Läufe würden sich um dieselben Dateien streiten und wären zusammen
keine Sekunde schneller; bei Higgsfield steht ohnehin eine Warteschlange.

Es gibt deshalb zwei Eingänge:

| Funktion | Verhalten, wenn schon etwas läuft |
|---|---|
| `pipeline.starten()` | wirft `EingabeFehler` — für alles, was jetzt laufen muss oder gar nicht |
| `pipeline.einreihen()` | stellt an (höchstens `MAX_SCHLANGE` = 10) und gibt `(auftrag, gestartet)` zurück |

Die Route `POST /api/auftrag` nimmt `einreihen`. Nach jedem Lauf holt `_bearbeiten` im
`finally` den nächsten Wartenden herein (`_naechsten_starten`) — außerhalb der Sperre,
denn die ist nicht wiedereintrittsfähig. Wer inzwischen aus der Reihe genommen wurde,
wird übersprungen; ein Fehler beim Nachrücken kann den Arbeitsfaden nicht mitreißen.

**Der Ausfall einer Szene beendet den Lauf nicht.** Bezahlte Clips wegzuwerfen, weil
eine von fünf Szenen die Moderation nicht passiert hat, war der teuerste Ausgang, den
das Programm kannte. Unterschieden wird jetzt:

* `GuthabenFehler`, `ZugangFehler`, `KonfigurationsFehler` und `AbbruchFehler` beenden
  den Lauf sofort — die nächste Szene liefe in dieselbe Wand (`pipeline._TOEDLICH`);
* alles andere überspringt nur diese Szene. Ist am Ende keine einzige entstanden,
  scheitert der Auftrag mit dem Grund der letzten.

Was fehlt, steht in `ergebnis["ausgefallen"]`, im Logbuch und auf dem Block „Higgsfield“.

**Abbruch** läuft über ein `threading.Event`, das jeder wartende Aufruf prüft — auch
mitten im ffmpeg-Lauf und mitten im Polling. Wartende Higgsfield-Aufträge werden
zusätzlich beim Dienst storniert.

---

## 4b. Aktualisierung und Neustart

`updater.py` hält das Werkzeug beim Kunden aktuell, ohne dass er ein Terminal öffnet.

```
GET  /api/aktualisierung           Stand prüfen (?schnell=1 ohne Netz)
POST /api/aktualisierung           holen und neu starten
POST /api/neustart                 nur neu starten (etwa nach einer .env-Änderung)
```

Drei Festlegungen, die bewusst so getroffen sind:

**Nur vorspulen.** `git pull --ff-only`. Es entsteht nie ein Merge, und lokale Änderungen
brechen den Vorgang mit einer verständlichen Meldung ab, statt überschrieben zu werden.
Ein Test hält das fest (`test_nur_vorspulen_niemals_zusammenfuehren`).

**Nie während eines Auftrags.** Sowohl die Oberfläche als auch `updater.aktualisieren()`
prüfen `pipeline.laeuft_gerade()`. Ein Neustart mitten in der Videoerzeugung würde
bereits bezahltes Guthaben verbrennen.

**Der Neustart über einen Helfer.** Ein Prozess kann sich nicht selbst wiederbeleben.
`neu_starten()` startet deshalb einen losgelösten Python-Prozess, der kurz wartet und
dann `run.py` erneut aufruft; das Original beendet sich mit `os._exit(0)`. Ein sauberes
Herunterfahren wäre hier falsch — es bliebe am wartenden Ereignisstrom und am Fenster
hängen. Die Oberfläche wartet unterdessen darauf, dass `/api/lebt` erst *verschwindet*
und dann *wiederkommt*, und lädt sich erst dann neu; ohne diese zwei Stufen würde sie
beim sterbenden Server zu früh neu laden.

**Voraussetzung beim Kunden:** eine Git-Arbeitskopie. Wer das ZIP herunterlädt, hat
keine, und der Knopf meldet das ehrlich, statt es zu versuchen.

---

## 4c. Die Kopfzeile

Sie ist das Einzige, was der Kunde liest, bevor er den ersten Auftrag startet — und die
einzige Stelle, an der er Fachjargon zu sehen bekäme. Deshalb steht dort ausschließlich,
was eine Funktion *tut*:

| Anzeige | Innerer Name | Woher der Zustand kommt |
|---|---|---|
| **Higgsfield** | `Higgsfield` | `videoquelle.befund()` — grün nur, wenn echte Videos entstehen können |
| **Drehbuch** | `Sprachmodell` | `llm.verfuegbare_wege()` |
| **Videoschnitt** | `ffmpeg` | `media.selbsttest()` |
| **Prüfen** | — | `POST /api/selbsttest` |
| **Update** | — | `GET /api/aktualisierung` |
| **Abo verbinden** | — | `GET /api/abo` |

Die inneren Namen bleiben unverändert; nur die Beschriftung in `index.html` und die Texte
im Frontend sind Kundensprache. `tests/test_kopfzeile.py` hält beides fest — sowohl die
neuen Wörter als auch die Abwesenheit der alten.

Drei Festlegungen dahinter:

**Die Ampel darf nicht umspringen.** Vorher war die Higgsfield-Lampe beim Start grün
(`config.diagnose()` sieht nur die `.env` und findet dort einen gültigen Schlüssel) und
wurde nach dem ersten Prüfen gelb. `server.diagnose_mit_videoweg()` ersetzt den Befund
deshalb durch den der Videoquelle — die weiß vom Abo und vom Guthabengedächtnis und
kommt ohne Netzaufruf aus.

**Gelb ist kein Startverbot.** Nur ein `fehler` kippt `startbereit`. Ein leerer
Guthabentopf ist eine Warnung: das Programm läuft, es erzeugt eben Platzhalter.

**Der Knopf heißt immer „Update“.** Ein wechselnder Text („Aktuell“ / „Version“ /
„Aktualisierung (3)“) lässt ihn wie verschiedene Knöpfe wirken. Zustand sagen Farbe und
Zahl.

---

## 5. Was beim Bauen Zeit gekostet hat

Acht Fallen, die alle im Code kommentiert sind — damit sie niemand ein zweites Mal tritt:

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

**Die Batchdatei mit LF-Zeilenenden.** `start.bat` war mit reinen LF-Enden und
Kastenstrichen in den Kommentaren geschrieben. cmd.exe liest eine Batchdatei in der
eingestellten Codepage und braucht CRLF — beides zusammen führte zu wirren Zeichen
statt eines Starts. Die Datei ist jetzt reines ASCII mit CRLF, und `.gitattributes`
nagelt das fest, damit ein `git clone` auf dem Kundenrechner die Zeilenenden nicht
wieder umstellt.

**Zusammengedrückte Videokacheln.** Die rechte Spalte war ein Raster mit flexibler
letzter Zeile. Bei kleinem Fenster blieben für die Bibliothek 67 Pixel übrig, die
Kacheln wurden auf einen Streifen gestaucht — die Kopfzeile meldete „1 Video“, zu
sehen war nichts. Jetzt rollt die Spalte als Ganzes, und die Kacheln behalten über
`align-items: start` ihre eigene Höhe.

**Ein Test, der die Annahme mitmacht, die er prüfen sollte.** Der Abo-Weg war getestet —
aber nur gegen eine Attrappe, und die hat jeden Modellnamen angenommen. Der echte Dienst
kennt die Platform-Pfade nicht; der erste Lauf beim Kunden brach genau daran ab. Das ist
die teuerste der Fallen hier, weil sie sich hinter grünen Tests versteckt hat.
(`higgsfield_mcp.modell_aufloesen`, → [`BEFUND_2026-08-26.md`](BEFUND_2026-08-26.md))

**Der `═`-Balken gegen cp1252.** Geht `stdout` nicht an ein Terminal, nimmt Windows die
ANSI-Codepage — und schon die erste Zeile des Startberichts löst einen
`UnicodeEncodeError` aus. Das Programm startet dann **gar nicht**. `start.bat` setzt
`PYTHONIOENCODING` und verdeckte das; `run.py` stellt jetzt selbst um und verlässt sich
nicht mehr auf die Umgebung. (`run.py:voraussetzungen_melden`)

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
python -m pytest tests/ -q                    # 251 Tests, rund 2,5 Minuten
python -m pytest tests/ -q -m "not langsam"   # 234, ohne echte ffmpeg-Läufe, ~5 Sekunden
```

| Datei | Inhalt |
|---|---|
| `test_fundament.py` | Konfiguration, Fehlerübersetzung, Logbuch, Maskierung |
| `test_higgsfield.py` | API-Client mit Attrappen: Polling, Abbruch, alle Fehlerarten |
| `test_promptsmith.py` | JSON-Bergung, fremde Feldnamen, Notbehelf, Dateinamen |
| `test_media.py` | Formatvorgaben, Dateiangaben, **Montageraster**, echte ffmpeg-Läufe |
| `test_pipeline.py` | Auftragsspeicher, Eingabeprüfung, Pfadsicherheit, Bibliothek, **Warteschlange** |
| `test_updater.py` | Nur-Vorspulen, Sperre während eines Auftrags, Neustart |
| `test_videoquelle.py` | Wahl des Videowegs, Guthabengedächtnis, Abo-Anmeldung, **Übersetzung der Modellnamen**, **Übergabe des Startbildes (`medias`)** |
| `test_kopfzeile.py` | Beschriftungen und Ampelfarben über die echten Routen |
| `test_ende_zu_ende.py` | **die ganze Kette** mit Higgsfield-Attrappe |

Der Ende-zu-Ende-Test ist der wichtigste: er ersetzt nur Higgsfield und das
Sprachmodell, alles andere läuft echt — Zustandsmaschine, Montage, Formate,
Auftragsspeicher, Bibliothek und Ereignisstrom. Er prüft auch, dass jeder Block genau
einmal „fertig“ meldet und die Übergänge in der richtigen Reihenfolge kommen.

Was er **nicht** kann: die Bildqualität von Higgsfield beurteilen. Sobald Guthaben da
ist, gehört ein echter Durchlauf gefahren (Aufgabe P13).

Was er ebenfalls nicht kann — und das hat am 26.08.2026 Geld und Zeit gekostet: **den
echten MCP-Dienst befragen.** Die Attrappe hat jeden Modellnamen angenommen, den echten
Dienst hätte er zum `unknown model` gebracht. Ein Test, der die Annahme mitmacht, die er
prüfen sollte, prüft nichts. `test_bild_schickt_nie_einen_platformnamen` schließt
wenigstens die eine Lücke, die aufgefallen ist: Was die Ablaufsteuerung hineingibt, darf
so nicht hinausgehen.

Am 05.09.2026 hat dieselbe Lücke ein zweites Mal zugeschlagen, eine Schnittstelle
weiter: Die Attrappe nahm auch `image_url` an, der echte Dienst verlangt `medias`.
`test_startbild_geht_als_medias_hinaus_nie_als_adresse` hält das jetzt fest — und zwar
in beide Richtungen, also auch, dass **keine** rohe Adresse mehr hinausgeht. Das Muster
dahinter lohnt die Verallgemeinerung: **Jede Annahme über eine fremde Schnittstelle
gehört als Zusicherung in einen Test, nicht nur in einen Kommentar.**

---

## 8. Erweitern

**Neues Thema im Formular** — Eintrag in `topics.THEMEN`. Kein Code nötig.

**Neues Merkmal** — Eintrag in `topics.ARGUMENTGRUPPEN`. `mehrfach: False` macht die
Gruppe zu einer Entweder-oder-Wahl.

**Neues Ausgabeformat** — Eintrag in `media.FORMATE` mit `kurz`-Kürzel für die Kachel.
Oberfläche und Bibliothek nehmen es automatisch auf.

**Neues Videomodell** — drei Schritte, der dritte wird gern vergessen:

1. Mit der Sonde aus Abschnitt 3 prüfen (kostet kein Guthaben).
2. In `higgsfield.VIDEOMODELLE` und `ERLAUBTE_DAUER` eintragen.
3. **In `higgsfield_mcp._UEBERSETZUNG` eintragen.** Ohne diesen Schritt funktioniert das
   Modell über die Platform-API, aber nicht über das Abo — dort heißt es anders. Die
   Laufzeitabfrage fängt das zwar ab, aber erst nach einem Fehlversuch.

**Anderer Videoanbieter** — eine Klasse mit denselben Methoden wie `Higgsfield`
(`bild`, `video_aus_bild`, `video_aus_text`, `herunterladen`, `abbrechen`, `selbsttest`)
genügt; die Pipeline spricht nur über diese Schnittstelle. Der Ende-zu-Ende-Test zeigt
an seiner Attrappe, wie wenig dafür nötig ist.

Zwei Tests halten die Schnittstelle zusammen, und beide sind aus Schaden entstanden:
`test_abo_kann_alles_was_die_pipeline_braucht` (fehlt eine Methode, fliegt es sonst erst
mitten im Auftrag auf) und `test_alle_videowege_nehmen_dasselbe_seitenverhaeltnis_entgegen`
(dasselbe für die Parameter). Wer einen Weg hinzufügt, erweitert beide.

---

## 9. Wenn beim Kunden etwas klemmt

Die Reihenfolge, in der sich am schnellsten klären lässt, woran es liegt:

1. **Logbuch lesen — es nennt seit dem 26.08.2026 den Grund, nicht nur den Umstand.**
   Besonders die Zeilen der Quellen `Videoquelle`, `Sprachmodell` und `Higgsfield (Abo)`.
2. **Welcher Videoweg läuft gerade?** Die Zeile `Videoerzeugung läuft über: …` steht
   direkt nach dem Start. `Probelauf (ohne Guthaben)` heißt: die Clips sind Platzhalter.
3. **Steht `Modell „…“ ist dem Abo-Dienst unbekannt`?** Dann hat sich die Benennung bei
   Higgsfield geändert. Der genannte Ersatzname gehört in `_UEBERSETZUNG`.
4. **Schrieb ein Sprachmodell das Drehbuch?** Die Erfolgszeile nennt den Weg
   (`Claude (Abo)`, `Claude (API)`, `Lokal (…)`). Steht dort stattdessen
   `einfaches Drehbuch wird selbst erstellt`, war keiner erreichbar — die Videoqualität
   leidet dann sichtbar, und die Zeilen darüber sagen, warum.
5. **Der Knopf „Prüfen"** geht alle Zugänge durch, ohne Guthaben zu verbrauchen.
6. **`POST /api/guthaben-pruefen`** ist der einzige verlässliche Weg zum Kontostand der
   Platform-API — er schickt einen schemakorrekten Auftrag und storniert ihn sofort.
   Deshalb nur auf Knopfdruck, nie automatisch.
