# MEDIAPIPE WVM — KI-Video-Studio
### Implementierungsplan · aufgestellt 03.08.2026 · fortgeschrieben 26.08.2026

Die Abschnitte 1 bis 5 sind der ursprüngliche Plan und bleiben unverändert stehen — sie
zeigen, was vorher entschieden wurde. Was danach dazukam, steht in Abschnitt 6 unter
„Danach hinzugekommen“; der jüngste Befund in
[`docs/BEFUND_2026-08-26.md`](docs/BEFUND_2026-08-26.md).

---

## 1. Was gebaut wird

Ein lokal laufendes Desktop-Werkzeug, mit dem ein Nicht-Techniker jeden Tag professionelle
KI-Videos erzeugt: **Briefing eingeben → Claude formt daraus einen Profi-Videoprompt →
Higgsfield erzeugt Startbild und Video → fertige Datei in allen benötigten Formaten.**

Kein Spielzeug, kein Demo-Dashboard. Ein Werkzeug, das an einen Kunden übergeben wird und
funktioniert, solange die Zugänge Kontingent haben.

**Nicht enthalten** (bewusst ausgeklammert): Cloud-Hosting, Mehrbenutzer-Betrieb,
Vertonung/Voiceover, Videoschnitt von Hand, andere KI-Anbieter als Higgsfield.

---

## 2. Verifizierte Ausgangslage

Alles Folgende wurde vor dem Planen **live geprüft**, nicht angenommen:

| Baustein | Befund |
|---|---|
| Higgsfield-Key | `HIGGSFIELD_API_KEY` aus `jarvis2\.env`, Format `ID:SECRET` (36:64 Zeichen) — **gültig**, `GET /v1/motions` antwortet 200 |
| Auth-Verfahren | `Authorization: Key <id>:<secret>` **oder** Header `hf-api-key` + `hf-secret` — beide akzeptiert. `Bearer` wird abgelehnt (401) |
| API-Muster | `POST https://platform.higgsfield.ai/{modell-pfad}` → `{request_id, status:"queued"}`, danach `GET /requests/{id}/status` bis `completed` |
| Statuswerte | `queued` · `in_progress` · `completed` · `failed` · `nsfw` (bei `failed`/`nsfw` werden Credits erstattet) |
| Modellpfade | Bild: `higgsfield-ai/soul/standard`, `reve/text-to-image` · Video: `higgsfield-ai/dop/preview`, `kling-video/v2.1/pro/image-to-video`, `bytedance/seedance/v1/pro/image-to-video` |
| Alter jarvis2-Pfad | `/v1/generations` mit `dop-lite` ist **veraltet** (daher die 404 von damals) — wird nicht übernommen |
| Claude | `ANTHROPIC_KEY` aus `jarvis2\.env` (108 Zeichen), `anthropic` 0.105.2 installiert |
| Lokale KI | Ollama-Fallback nach Wunsch; Modell wird beim ersten Bedarf automatisch geladen |
| Laufzeit | Python 3.14.4 · Flask 3.0.3 · httpx 0.28.1 · Pillow 11.3 · ffmpeg im PATH **und** `imageio-ffmpeg` als Rückfallebene |

> **Offener Punkt, der zuerst geklärt wird (P0):** Welche Videomodelle mit *diesem* Key
> tatsächlich laufen und welche `duration`/`aspect_ratio`-Werte sie akzeptieren, steht in
> keiner Doku vollständig. Das wird durch echte Aufträge ermittelt und in
> `docs/API_BEFUND.md` festgeschrieben — die Modellauswahl im Tool zeigt danach nur noch
> nachweislich funktionierende Modelle.

---

## 3. Getroffene Entscheidungen

| Thema | Entscheidung |
|---|---|
| Higgsfield-Zugang | Platform-API-Key fest hinterlegt (Jahresabo). Kein OAuth-Login nötig |
| Claude-Zugang | API-Key aus jarvis2; bei Limit/Ausfall **automatischer Umstieg auf lokale KI**, die die App bei Bedarf selbst lädt |
| Programmform | Lokaler Flask-Server + **eigenes Desktop-Fenster** (pywebview), Start per Doppelklick, Browser als Rückfallebene |
| Videolänge | **Umschaltbar**: bis ~10 s Einzelclip, darüber Storyboard-Modus (Claude teilt in Szenen, ffmpeg montiert) |
| Text → Video | **Erst Startbild, dann animieren** — der Bildschritt ist ein **eigener sichtbarer Block** im Workflow |
| Ausgabeformate | 9:16 · 1:1 · 16:9 + Web-Variante · GIF + Poster-Bild — **per Klick** in der Bibliothek, kein Pipeline-Zwang |
| Design | Graphit-Verlauf `#0A0B0D → #121418`, Glasboxen, aktiver Block leuchtet cyan `#22D3EE`, wandernder Punkt auf den Verbindungen |
| Übergabe | Git-Repo ohne Zugangsdaten; `.env` wird fertig befüllt separat übergeben |

---

## 4. Oberfläche

```
┌──────────────────────┬──────────────────────────────────────────────────────────┐
│  BRIEFING            │  WORKFLOW                                                │
│  ┌────────────────┐  │  ┌────┐ ·→ ┌────┐ ·→ ┌────┐ ·→ ┌────┐ ·→ ┌────┐          │
│  │Formular│Prompt │  │  │Brie│    │Clau│    │Bild│    │Higg│    │Ausg│          │
│  └────────────────┘  │  │fing│    │de  │    │    │    │sfld│    │abe │          │
│                      │  └────┘    └────┘    └────┘    └────┘    └────┘          │
│  Thema      ▾        │            aktiv: weicher cyan Schein hinter der Glasbox │
│  ┌──┐┌──┐┌──┐┌──┐    │            Fortschritt · Restzeit · Startbild-Vorschau   │
│  │Ar││gu││me││nte│   ├──────────────────────────────────────────────────────────┤
│  └──┘└──┘└──┘└──┘    │  LOGBUCH                                                 │
│                      │  14:02:11  Claude    Storyboard erstellt · 6 Szenen      │
│  Ziellänge  ──●───   │  14:02:44  Higgsf.   Szene 2/6 · in Arbeit · noch ~40 s  │
│  Stil       ▾        ├──────────────────────────────────────────────────────────┤
│  Modell     ▾        │  BIBLIOTHEK                                              │
│                      │  ▸ werbung_bäckerei   30 s   [9:16][1:1][16:9][GIF]  ▶   │
│  [  Video erzeugen ] │  ▸ produkt_uhr        8 s    [9:16] 1:1 fehlt        ▶   │
└──────────────────────┴──────────────────────────────────────────────────────────┘
```

Links wird zwischen **Formular** (Startansicht) und **eigenem Prompt** umgeschaltet, ohne
dass Eingaben verloren gehen. Rechts oben der Workflow, darunter Logbuch und Bibliothek.

---

## 5. Architektur

```
MEDIAPIPEWVM/
├── run.py                 Start: Diagnose → Server → Desktop-Fenster
├── start.bat              Doppelklick-Start für den Kunden
├── .env                   Zugänge (NIE im Git)
├── app/
│   ├── config.py          Konfiguration, Validierung, Secret-Maskierung
│   ├── logbook.py         Logbuch: Ring-Puffer + Datei + Live-Strom
│   ├── errors.py          Verständliche Fehlermeldungen statt Tracebacks
│   ├── higgsfield.py      API-Client: Auftrag, Polling, Restzeit, Abbruch
│   ├── promptsmith.py     Briefing → Profi-Prompt / Storyboard
│   ├── llm/               Claude-API + lokale KI als Rückfallebene
│   ├── pipeline.py        Zustandsmaschine über die fünf Blöcke
│   ├── jobstore.py        Aufträge in SQLite, überleben Neustart
│   ├── media.py           ffmpeg: Montage, Formate, GIF, Poster
│   ├── library.py         Bibliothek: Dateien, Varianten, Metadaten
│   ├── topics.py          Themen- und Argumentkatalog
│   └── server.py          Flask-Routen + Ereignisstrom
├── static/ · templates/   Oberfläche
├── data/ · output/        Auftragsdaten · fertige Videos
├── tests/                 pytest
└── docs/                  API-Befund, technische Dokumentation
```

**Grundsätze:** Jede Ebene kennt nur die darunter. Kein Netzaufruf ohne Zeitlimit, kein
Zeitlimit ohne Wiederholung, keine Wiederholung ohne Obergrenze. Jeder Fehler wird zu einem
Satz, der sagt *was* passiert ist und *was zu tun* ist. Der Server hört ausschließlich auf
127.0.0.1. Zugangsdaten erscheinen nirgends im Log, auch nicht in Fehlermeldungen.

---

## 6. Reihenfolge der Arbeitspakete

| # | Paket | Fertig, wenn |
|---|---|---|
| P0 | Live-Spike Higgsfield | Ein echtes Bild und ein echter Clip liegen auf der Platte, Modellkatalog steht in `docs/API_BEFUND.md` |
| P1 | Fundament (Config, Log, Fehler) | Fehlkonfiguration erzeugt eine verständliche Meldung statt eines Absturzes |
| P2 | Higgsfield-Client | Auftrag, Fortschritt, Abbruch und alle fünf Fehlerarten sind nachgewiesen |
| P3 | Prompt-Schmiede | Claude liefert gültiges Storyboard-JSON; bei abgeschaltetem Key übernimmt die lokale KI nahtlos |
| P4 | Pipeline + Persistenz | Auftrag überlebt einen Neustart des Programms |
| P5 | ffmpeg-Modul | Sechs Szenen werden zu einem sauberen Film montiert, alle vier Formate stimmen exakt |
| P6 | Server + Ereignisstrom | Oberfläche zeigt Fortschritt ohne Neuladen, Dateizugriff ist gegen Ausbruch gesichert |
| P7 | Formular links | Thema, Argumente, Länge, Stil funktionieren; Umschalten verliert nichts |
| P8 | Workflow-Blöcke | Blöcke leuchten in der richtigen Reihenfolge, Punkte wandern beim Übergang |
| P9 | Logbuch + Bibliothek | Fehlendes Format entsteht per Klick, Video läuft im Fenster |
| P10 | Desktop-Start | Doppelklick auf einem frischen Rechner führt zur laufenden App |
| P11 | Härtung + Tests | Tests grün, ein vollständiger echter Durchlauf dokumentiert, Störfälle bewusst provoziert |
| P12 | Übergabepaket | Kunde kann klonen, `.env` einlegen, starten — ohne Rückfragen |

Jedes Paket wird einzeln fertiggestellt, geprüft und dokumentiert, bevor das nächste beginnt.
Der Fortschritt steht in der Aufgabenliste dieser Sitzung.

**Danach hinzugekommen** — aus dem, was sich beim Benutzen zeigte:

| # | Paket | Fertig, wenn | Stand |
|---|---|---|---|
| P13 | Echter Medien-Durchlauf | Ein Film aus echtem Higgsfield-Material liegt vor, Laufzeitschätzungen sind daran geeicht | **offen** — zweimal an einer Schnittstellenannahme gescheitert (P21, P23) |
| P14 | Videobereich | Kacheln sichtbar und anklickbar, der ganze Bereich rollt | fertig |
| P15 | Glas und Ablauf | LED-Rand an den Glasboxen, Blöcke ohne Querlauf | fertig |
| P16 | Update-Knopf | Neuer Stand und Neustart per Klick, gesperrt während eines Auftrags | fertig |
| P17 | Veröffentlichung | Repository steht öffentlich, ohne eine einzige Zugangszeile | fertig |
| P18 | Abschlussdokumentation | README, technische Doku und API-Befund auf dem Stand des Codes | fertig |
| P19 | Abo-Weg über MCP | Higgsfield-Abo per Knopfdruck verbunden, Videos laufen über dessen Credits | fertig |
| P20 | Kopfzeile | Jede Beschriftung ohne Erklärung verständlich, Ampel springt nicht um | fertig |
| P21 | Abo-Weg beim Kunden | Modellnamen werden übersetzt statt durchgereicht, Fehler des MCP-Dienstes kommen im Klartext an, das Update braucht keine Änderung an der `.env` | fertig, 26.08.2026 |
| P22 | Zugänge des Kunden | `ANTHROPIC_KEY` und `HIGGSFIELD_API_KEY` gehören dem Kunden, ein Sprachmodell ist auf seinem Rechner erreichbar | **offen** — siehe unten |
| P23 | Startbild im Abo-Weg | `generate_video` bekommt das Startbild als `medias`-Kennung statt als Adresse, ein Ausfall kostet nicht den ganzen Film | fertig, 05.09.2026 |
| P24 | Hochformat, das eines ist | Ein 9:16-Auftrag ergibt einen 9:16-Film, ein 9:16-Vorschaubild und eine 9:16-Kachel — vom Probelauf bis zur Bibliothek | fertig, 05.09.2026 |
| P25 | Serientauglich für TikTok | Zielplattform setzt Format, Länge und Ausgabefassungen auf einen Klick; Aufträge lassen sich einreihen; Titel, Text und Hashtags entstehen mit | fertig, 05.09.2026 |

**P21** entstand aus dem ersten echten Lauf beim Kunden. Ursache, Behebung und
Prüfprotokoll stehen vollständig in
[`docs/BEFUND_2026-08-26.md`](docs/BEFUND_2026-08-26.md).

**P23 bis P25** entstanden aus dem zweiten Lauf beim Kunden und dem anschließenden
Durchgang durch den gesamten Code. Der schwerste Fund war dabei nicht der Abbruch,
sondern **P24**: Hochformat wurde seit jeher auf Breitbild montiert, ohne dass je eine
Fehlermeldung erschien. Alles in
[`docs/BEFUND_2026-09-05.md`](docs/BEFUND_2026-09-05.md).

**P22 ist der einzige Punkt, den kein Update lösen kann** — er verlangt Handlungen an
den Konten, nicht am Code:

1. Beide Schlüssel in der `.env` durch die des Kunden ersetzen. Bis dahin geht jeder
   Aufruf auf die Rechnung des Entwicklers.
2. Einen Weg zu einem Sprachmodell herstellen. Am einfachsten `claude login` im Terminal
   des Kunden — das nutzt sein Claude-Abo und kostet nichts extra. Sonst: eigenes
   Anthropic-Guthaben, ein frisches `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`),
   oder Ollama. Ohne einen davon entsteht das Drehbuch aus dem Notbehelf, und die
   Videoqualität leidet sichtbar.

---

## 7. Absicherung (nicht verhandelbar)

- **Zugänge**: nur aus `.env`, nie im Code, nie im Log, `.gitignore` deckt sie ab; die
  Oberfläche zeigt Keys ausschließlich maskiert
- **Netz**: jeder Aufruf mit Zeitlimit; Wiederholung mit wachsender Wartezeit bei
  vorübergehenden Fehlern; niemals endlos pollen
- **Geld**: vor jedem Auftrag wird die geschätzte Credit-Menge angezeigt; Doppelklick auf
  „Erzeugen" kann keinen zweiten Auftrag auslösen; Abbruch storniert wartende Aufträge
- **Dateien**: Ausgabe nur unterhalb von `output/`, jeder Pfad wird geprüft; Löschen nur mit
  Rückfrage; keine Datei wird ohne Vorlesen überschrieben
- **Ausfälle**: fehlt ffmpeg, fehlt Ollama, ist der Key ungültig oder das Kontingent leer —
  die App startet trotzdem und sagt im Klartext, was fehlt und wie es behoben wird
- **Absturzsicherheit**: laufende Aufträge stehen in der Datenbank und werden nach einem
  Neustart korrekt als abgebrochen oder fertig erkannt

---

## 8. Was der Kunde am Ende bekommt

Ein Git-Repository ohne Zugangsdaten, eine separat übergebene `.env`, eine README, die in
drei Schritten zur laufenden App führt, und ein Werkzeug, das mit einem Doppelklick startet.

**Und einen Update-Knopf, der ohne Terminal auskommt.** Am 26.08.2026 an einem echten
Klon geprüft: `.env`, die Higgsfield-Abo-Anmeldung (`data/higgsfield_abo.json`) und alle
fertigen Videos sind danach unverändert — Byte für Byte —, die Arbeitskopie bleibt
sauber, und die neue Fassung startet. Der Kunde drückt **Update**, bestätigt, und wartet,
bis sich das Fenster selbst auffrischt. Mehr nicht.
