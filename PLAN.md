# MEDIAPIPE WVM — KI-Video-Studio
### Implementierungsplan · Stand 03.08.2026

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
