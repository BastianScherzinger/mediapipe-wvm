# MEDIAPIPE WVM — KI-Video-Studio

Ein Werkzeug, das aus einem Satz ein fertiges Video macht.

Sie beschreiben, was zu sehen sein soll. Claude schreibt daraus ein professionelles
Drehbuch mit Bild- und Bewegungsprompts, Higgsfield erzeugt Startbild und Video, und am
Ende liegt der fertige Film in allen Formaten, die Sie brauchen — Hochformat für TikTok,
quadratisch für den Feed, Breitbild für YouTube.

---

## Installation in drei Schritten

**1. Herunterladen**

```
git clone https://github.com/BastianScherzinger/mediapipe-wvm.git
cd mediapipe-wvm
```

> Bitte wirklich `git clone` verwenden und nicht das ZIP herunterladen — nur so
> funktioniert später der Aktualisierungsknopf im Programm.

**2. Zugangsdaten einlegen**

Die Datei `.env` wird Ihnen getrennt zugeschickt. Legen Sie sie unverändert in den
Ordner `mediapipe-wvm`. Sie enthält die Schlüssel für Higgsfield und Claude und gehört
aus gutem Grund nicht ins Repository.

**3. Starten**

Doppelklick auf **`start.bat`**.

Beim allerersten Start werden die benötigten Pakete installiert — das dauert ein paar
Minuten und passiert nur einmal. Danach öffnet sich das Programmfenster in wenigen
Sekunden.

> Voraussetzung: Python 3.10 oder neuer, mit angekreuztem „Add Python to PATH“.
> Alles Weitere bringt das Programm selbst mit, auch ffmpeg.

---

## Aktualisieren

Oben rechts sitzt ein Knopf, der den Stand des Programms zeigt:

| Farbe | Bedeutung |
|---|---|
| **grün** „Aktuell“ | Es liegt nichts Neues vor. Ein Klick sieht trotzdem nach. |
| **gelb** „Aktualisierung (3)“ | Drei Änderungen liegen bereit. Ein Klick holt sie. |
| grau „Version ?“ | Der Stand ließ sich nicht abfragen — meist fehlt die Internetverbindung. |

Ein Klick auf den gelben Knopf holt den neuen Stand, zieht geänderte Pakete nach und
startet das Programm neu. Der Vorgang dauert etwa eine halbe Minute; die Ansicht
frischt sich danach von selbst auf.

**Was dabei sicher ist:** Ihre `.env`, alle fertigen Videos und alle Einstellungen
bleiben unangetastet — sie liegen außerhalb dessen, was aktualisiert wird. Es wird
ausschließlich vorgespult, nie etwas überschrieben. Solange ein Video erzeugt wird, ist
der Knopf gesperrt: ein Neustart mittendrin würde Guthaben verbrennen.

---

## Bedienung

### Links: Was für ein Video soll es werden?

**Formular** — der übliche Weg. Thema anklicken (Werbevideo, Social-Clip,
Produktvorstellung …), in einem Halbsatz sagen, worum es geht, ein paar Merkmale
anhaken. Darunter steht immer der Text, der gleich an Claude geht — keine Überraschungen.

**Eigener Prompt** — für den Fall, dass Sie genau wissen, was Sie wollen. Standardmäßig
arbeitet Claude Ihren Text noch zu einem Profi-Prompt aus. Mit dem Häkchen
„Wörtlich verwenden“ geht er unverändert an Higgsfield.

**Länge**

| Einstellung | Ergebnis |
|---|---|
| Einzelclip | Ein Clip von 5–10 Sekunden. Schnell und günstig. |
| Storyboard | Mehrere Szenen, hinterher zu einem Film montiert. |

Der Storyboard-Modus ist der einzige Weg zu Videos über zehn Sekunden: kein
Higgsfield-Modell liefert längere Clips am Stück. Fünf Szenen à fünf Sekunden ergeben
rund 25 Sekunden Film — und fünf Aufträge bei Higgsfield.

### Rechts oben: Der Ablauf

Fünf Blöcke zeigen, wo der Auftrag gerade steht. Der arbeitende Block leuchtet, ein
Punkt wandert zum nächsten, sobald der Schritt fertig ist. Im Block stehen Fortschritt
und geschätzte Restzeit — geschätzt aus den tatsächlichen Laufzeiten Ihrer bisherigen
Aufträge, nicht geraten.

```
Briefing  →  Claude  →  Startbild  →  Higgsfield  →  Ausgabe
```

Das Startbild erscheint als Vorschau, sobald es da ist. So sehen Sie den Look, bevor das
Video fertig ist.

### Rechts unten: Logbuch und Videos

Das **Logbuch** zeigt jeden Schritt mit Uhrzeit. Bei einem Problem steht dort im
Klartext, was passiert ist und was zu tun wäre.

Bei den **Videos** liegt jedes fertige Ergebnis als Kachel. Ein Klick auf das Bild
spielt es ab. Darunter sehen Sie die vorhandenen Fassungen (grün) und die fehlenden
(mit Plus). Ein Klick auf eine fehlende Fassung erzeugt sie in wenigen Sekunden — ganz
ohne neues Guthaben, denn das rechnet Ihr Rechner selbst aus.

| Fassung | Wofür |
|---|---|
| 9:16 | TikTok, Reels, Shorts — 1080×1920 |
| 1:1 | Instagram- und Facebook-Feed — 1080×1080 |
| 16:9 | YouTube, Webseite, Präsentation — 1920×1080 |
| Web | Kleine Datei zum Einbetten — 1280×720 |
| GIF | Endlosschleife ohne Ton, erste 8 Sekunden |

---

## Wo die Videos liegen

Im Ordner `output`, ein Unterordner je Video:

```
output/2026-08-03_werbung_baeckerei_a1b2c3/
├── film.mp4            ← der fertige Film
├── film_poster.jpg     ← Vorschaubild
├── film_hoch.mp4       ← die erzeugten Fassungen
├── szene_01.mp4        ← die Einzelszenen
├── szene_01_start.jpg  ← die Startbilder
└── auftrag.json        ← Briefing und Drehbuch zum Nachlesen
```

Über das Ordnersymbol auf jeder Kachel springen Sie direkt dorthin.

---

## Wenn etwas nicht klappt

Oben rechts sitzt der **Selbsttest**. Er prüft alle Zugänge und sagt in einem Satz, was
fehlt. Die drei Lämpchen daneben zeigen den Zustand auf einen Blick.

| Meldung | Bedeutung und Abhilfe |
|---|---|
| „Higgsfield hat kein Guthaben mehr.“ | Der API-Topf ist leer. **Wichtig:** Ein Web-Abo (Soul/Plus) füllt ihn *nicht* — das sind getrennte Guthaben. Unter cloud.higgsfield.ai API-Credits aufladen. |
| „Das Claude-Abo hat sein Kontingent erreicht.“ | Bis zur Rückstellung übernimmt automatisch die lokale KI. Sie ist etwas schwächer, kostet aber nichts. |
| „Kein Sprachmodell verfügbar.“ | Entweder einmal `claude login` im Terminal ausführen, oder Ollama starten (`ollama serve`). |
| „Kein brauchbares ffmpeg gefunden.“ | `python -m pip install imageio-ffmpeg`, dann neu starten. |
| „Higgsfield hat den Inhalt abgelehnt.“ | Die Inhaltsprüfung hat angeschlagen. Marken, echte Personen und Gewalt vermeiden. Das Guthaben wird erstattet. |
| „Es läuft bereits ein Auftrag.“ | Es wird bewusst nur einer gleichzeitig bearbeitet. Abwarten oder abbrechen. |

Das Programm startet auch dann, wenn etwas fehlt, und zeigt die offenen Punkte im
Fenster an. Nichts bricht wortlos ab.

---

## Gut zu wissen

- **Es kostet Guthaben.** Jede Szene ist ein Auftrag bei Higgsfield. Vor dem Start steht
  im Formular, wie viele Aufträge entstehen.
- **Abbrechen wirkt sofort.** Wartende Aufträge werden bei Higgsfield storniert, damit
  kein Guthaben für ein Ergebnis draufgeht, das niemand mehr braucht.
- **Formate kosten nichts.** Sie entstehen aus dem fertigen Film auf Ihrem Rechner.
- **Nichts verlässt Ihren Rechner** außer den Prompts an Claude und Higgsfield. Das
  Programm ist nur lokal erreichbar, nicht im Netzwerk.
- **Ihre Eingaben bleiben erhalten**, auch wenn Sie das Fenster schließen.

---

## Für Techniker

Aufbau, Module, API-Befunde und Wartungshinweise stehen in
[`docs/DOKUMENTATION.md`](docs/DOKUMENTATION.md), der geprüfte Stand der Higgsfield-API in
[`docs/API_BEFUND.md`](docs/API_BEFUND.md).

Tests:

```
python -m pytest tests/ -q                    # alle (rund 100 Sekunden)
python -m pytest tests/ -q -m "not langsam"   # nur die schnellen
```

Start ohne Doppelklick:

```
python run.py                 eigenes Fenster
python run.py --browser       im Standardbrowser
python run.py --kein-fenster  nur der Server
python run.py --pruefen       nur die Voraussetzungen prüfen
```
