# MEDIAPIPE WVM — KI-Video-Studio

Ein Werkzeug, das aus einem Satz ein fertiges Video macht.

Sie beschreiben, was zu sehen sein soll. Claude schreibt daraus ein professionelles
Drehbuch mit Bild- und Bewegungsprompts, Higgsfield erzeugt Startbild und Video, und am
Ende liegt der fertige Film in allen Formaten, die Sie brauchen — Hochformat für TikTok,
quadratisch für den Feed, Breitbild für YouTube.

---

## Installation in drei Schritten

**0. Einmalige Voraussetzungen**

Zwei Programme müssen auf dem Rechner sein. Beide sind kostenlos:

| Programm | Woher | Worauf zu achten ist |
|---|---|---|
| **Python 3.10 oder neuer** | [python.org/downloads](https://www.python.org/downloads/) | Im Installationsfenster unten **„Add python.exe to PATH“ ankreuzen**. Ohne dieses Häkchen findet `start.bat` Python nicht. |
| **Git** | [git-scm.com/download/win](https://git-scm.com/download/win) | Alle Vorgaben können bleiben, einfach durchklicken. |

**1. Herunterladen**

Eingabeaufforderung öffnen (Windows-Taste, `cmd` tippen, Enter) und diese drei Zeilen
nacheinander eingeben:

```
cd %USERPROFILE%\Desktop
git clone https://github.com/BastianScherzinger/mediapipe-wvm.git
cd mediapipe-wvm
```

Danach liegt der Ordner **mediapipe-wvm** auf dem Desktop.

> Bitte wirklich `git clone` verwenden und nicht das ZIP herunterladen — nur so
> funktioniert später der Update-Knopf im Programm.

**2. Zugangsdaten einlegen**

Die Datei `.env` wird Ihnen getrennt zugeschickt. Legen Sie sie unverändert in den
Ordner `mediapipe-wvm`, direkt neben `start.bat`. Sie enthält die Schlüssel für
Higgsfield und Claude und gehört aus gutem Grund nicht ins Repository.

**3. Starten**

Doppelklick auf **`start.bat`**.

Beim allerersten Start werden die benötigten Pakete installiert — das dauert ein paar
Minuten und passiert nur einmal. Danach öffnet sich das Programmfenster in wenigen
Sekunden. Ab dann genügt jedes Mal der Doppelklick auf `start.bat`.

> Alles Weitere bringt das Programm selbst mit, auch ffmpeg. Fehlt etwas, sagt das
> Fenster im Klartext, was — es bricht nicht wortlos ab.

---

## Die zwei Guthaben von Higgsfield

Higgsfield führt zwei getrennte Konten, und das ist die häufigste Stolperfalle:

| Guthaben | Wofür | Wie das Programm es nutzt |
|---|---|---|
| **Web-Abo** (Soul/Plus auf higgsfield.ai) | das, was man beim Abschluss eines Abos bezahlt | über den Knopf **„Abo verbinden“** |
| **Platform-API-Credits** (cloud.higgsfield.ai) | eigenes Konto, extra aufzuladen | über den `HIGGSFIELD_API_KEY` in der `.env` |

**Ein Jahresabo füllt den API-Topf nicht.** Ist er leer, meldet das Programm das im
Klartext, die Lampe „Higgsfield“ steht auf Gelb, und oben erscheint der Knopf
„Abo verbinden“.

Ein Klick darauf öffnet einmalig die Higgsfield-Anmeldeseite im Browser. Es entstehen
dabei keine zusätzlichen Kosten — das bestehende Abo wird lediglich mit dem Programm
verbunden. Nach der Bestätigung laufen alle Videos über die Credits des Abos, und zwar
dauerhaft: Das Programm merkt sich die Anmeldung und erneuert sie selbstständig. Ein
zweites Mal klicken muss niemand.

Steht der Knopf auf „Abo verbunden“, ist alles in Ordnung. Ein Klick darauf würde die
Verbindung wieder trennen.

---

## Aktualisieren

Oben rechts sitzt der Knopf **Update**. Er heißt immer gleich; was zu tun ist, sagt
seine Farbe:

| Knopf | Bedeutung |
|---|---|
| **grün** „Update“ | Es liegt nichts Neues vor. Ein Klick sieht trotzdem nach. |
| **gelb** „Update (3)“ | Drei Änderungen liegen bereit. Ein Klick holt sie. |
| grau „Update ?“ | Der Stand ließ sich nicht abfragen — meist fehlt die Internetverbindung. |

Ein Klick auf den gelben Knopf holt den neuen Stand, zieht geänderte Pakete nach und
startet das Programm neu. Der Vorgang dauert etwa eine halbe Minute; die Ansicht
frischt sich danach von selbst auf.

**Was dabei sicher ist:** Ihre `.env`, alle fertigen Videos, die Verbindung zum
Higgsfield-Abo und alle Einstellungen bleiben unangetastet — sie liegen außerhalb
dessen, was aktualisiert wird. Es wird ausschließlich vorgespult, nie etwas
überschrieben. Solange ein Video erzeugt wird, ist der Knopf gesperrt: ein Neustart
mittendrin würde Guthaben verbrennen.

**Sie müssen nach einem Update nichts umstellen.** Insbesondere die Modellnamen in der
`.env` dürfen unverändert stehen bleiben.

Falls der Knopf meldet, es gebe *lokale Änderungen*: Im Projektordner einmal
`git checkout -- .` ausführen, danach klappt das Update. Ihre `.env` und Ihre Videos
sind davon nicht betroffen — git fasst sie nicht an.

---

## Bedienung

### Links: Was für ein Video soll es werden?

**Formular** — der übliche Weg. Thema anklicken (Werbevideo, Social-Clip,
Produktvorstellung …), in einem Halbsatz sagen, worum es geht, ein paar Merkmale
anhaken. Darunter steht immer der Text, der gleich an Claude geht — keine Überraschungen.

**Eigener Prompt** — für den Fall, dass Sie genau wissen, was Sie wollen. Standardmäßig
arbeitet Claude Ihren Text noch zu einem Profi-Prompt aus. Mit dem Häkchen
„Wörtlich verwenden“ geht er unverändert an Higgsfield.

**Wohin soll das Video?** — die wichtigste Einstellung, und deshalb die erste.

| Auswahl | Was sie einstellt |
|---|---|
| TikTok / Reels | 9:16 hochkant · 4 Szenen à 5 s · rund 20 Sekunden |
| YouTube Shorts | 9:16 hochkant · 6 Szenen à 5 s · rund 30 Sekunden |
| Instagram-Feed | 1:1 quadratisch · 3 Szenen à 5 s · rund 15 Sekunden |
| YouTube / Webseite | 16:9 breit · 5 Szenen à 5 s · rund 25 Sekunden |

Ein Klick setzt Bildformat, Länge, Szenenzahl **und** die Ausgabefassungen. Jede
einzelne Einstellung lässt sich hinterher unter „Weitere Einstellungen“ überstimmen.

Das Bildformat geht dabei auch an Claude: Bei 9:16 schreibt es senkrechte Bildprompts
mit dem Motiv in der Mitte statt breiter Panoramen — und achtet darauf, dass die erste
Szene sofort etwas zeigt. Bei TikTok entscheidet die erste Sekunde.

**Länge**

| Einstellung | Ergebnis |
|---|---|
| Einzelclip | Ein Clip von 5–10 Sekunden. Schnell und günstig. |
| Storyboard | Mehrere Szenen, hinterher zu einem Film montiert. |

Der Storyboard-Modus ist der einzige Weg zu Videos über zehn Sekunden: kein
Higgsfield-Modell liefert längere Clips am Stück. Fünf Szenen à fünf Sekunden ergeben
rund 25 Sekunden Film — und fünf Aufträge bei Higgsfield.

**Mehrere Videos hintereinander.** Es läuft immer nur ein Auftrag — zwei gleichzeitig
wären zusammen keine Sekunde schneller. Sie müssen aber nicht danebensitzen: Klicken
Sie einfach wieder auf „Video erzeugen“, dann stellt sich der Auftrag an und startet
von selbst, sobald der vorige fertig ist. Die Wartenden stehen unter dem Startknopf
und lassen sich mit dem × einzeln wieder herausnehmen. Höchstens zehn — jeder
kostet später Guthaben.

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

**Text zum Veröffentlichen.** Beim Abspielen steht unter dem Video ein fertiger
Vorschlag: Titel, Bildunterschrift und Hashtags. „Kopieren“ legt alles in die
Zwischenablage — beim Hochladen bei TikTok oder Instagram nur noch einfügen.
Dasselbe liegt als `posting.txt` im Videoordner.

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
├── posting.txt         ← Titel, Text und Hashtags zum Veröffentlichen
└── auftrag.json        ← Briefing und Drehbuch zum Nachlesen
```

Über das Ordnersymbol auf jeder Kachel springen Sie direkt dorthin.

---

## Wenn etwas nicht klappt

Oben rechts sitzt der Knopf **Prüfen**. Er sieht alle Zugänge durch und sagt in einem
Satz, was fehlt. Die drei Lämpchen daneben zeigen dasselbe auf einen Blick:

| Lampe | Steht für |
|---|---|
| **Higgsfield** | Können echte Videos entstehen? Grün heißt: Guthaben ist da (über das Abo oder den API-Topf). Gelb: es geht nur der Probelauf mit Platzhaltern. |
| **Drehbuch** | Ist eine KI erreichbar, die aus dem Briefing das Drehbuch schreibt? |
| **Videoschnitt** | Ist ffmpeg einsatzbereit? Es montiert die Szenen und erzeugt die Formate. |

Ein Klick auf ein Lämpchen prüft ebenfalls alles durch.

| Meldung | Bedeutung und Abhilfe |
|---|---|
| „Higgsfield hat kein Guthaben mehr.” | Der API-Topf ist leer. **Wichtig:** Ein Web-Abo (Soul/Plus) füllt ihn *nicht* — das sind getrennte Guthaben. Entweder unter cloud.higgsfield.ai API-Credits aufladen **oder** oben auf „Abo verbinden” klicken (siehe oben). |
| „Das Claude-Abo hat sein Kontingent erreicht.“ | Bis zur Rückstellung übernimmt automatisch die lokale KI. Sie ist etwas schwächer, kostet aber nichts. |
| „Kein Sprachmodell verfügbar.“ | Entweder einmal `claude login` im Terminal ausführen, oder Ollama starten (`ollama serve`). |
| „Kein brauchbares ffmpeg gefunden.“ | `python -m pip install imageio-ffmpeg`, dann neu starten. |
| „Higgsfield hat den Inhalt abgelehnt.“ | Die Inhaltsprüfung hat angeschlagen. Marken, echte Personen und Gewalt vermeiden. Das Guthaben wird erstattet. |
| „Es läuft bereits ein Auftrag.“ | Es wird bewusst nur einer gleichzeitig bearbeitet. Abwarten oder abbrechen. |
| „Higgsfield kennt das eingestellte Modell im Abo nicht.“ | Das Web-Abo führt andere Modellnamen als der API-Zugang. Das Programm übersetzt sie selbst; bleibt die Meldung, im Formular ein anderes Videomodell wählen und oben auf **Update** drücken. |
| „Das Higgsfield-Abo hat keine Credits mehr.“ | Das Abo selbst ist aufgebraucht. Unter higgsfield.ai nachsehen. Solange erzeugt der Probelauf Platzhalterclips. |
| „Kein Sprachmodell lieferte ein brauchbares Drehbuch“ | Das Programm hat sich selbst beholfen und läuft weiter — die Videos werden aber sichtbar schwächer. Abhilfe: einmal `claude login` im Terminal ausführen. Das nutzt Ihr Claude-Abo und kostet nichts extra. |

Das Programm startet auch dann, wenn etwas fehlt, und zeigt die offenen Punkte im
Fenster an. Nichts bricht wortlos ab.

---

## Gut zu wissen

- **Es kostet Guthaben.** Jede Szene ist ein Auftrag bei Higgsfield. Vor dem Start steht
  im Formular, wie viele Aufträge entstehen.
- **Abbrechen wirkt sofort.** Wartende Aufträge werden bei Higgsfield storniert, damit
  kein Guthaben für ein Ergebnis draufgeht, das niemand mehr braucht.
- **Formate kosten nichts.** Sie entstehen aus dem fertigen Film auf Ihrem Rechner.
- **Ohne Guthaben läuft der Probelauf.** Statt abzubrechen erzeugt das Programm dann
  Platzhalterclips, damit sich der ganze Ablauf trotzdem zeigen lässt. Es sagt das
  deutlich: die Lampe „Higgsfield“ steht auf Gelb und im Logbuch erscheint
  „Videoerzeugung läuft über: Probelauf (ohne Guthaben)“.
- **Nichts verlässt Ihren Rechner** außer den Prompts an Claude und Higgsfield. Das
  Programm ist nur lokal erreichbar, nicht im Netzwerk.
- **Ihre Eingaben bleiben erhalten**, auch wenn Sie das Fenster schließen.

---

## Für Techniker

Aufbau, Module, API-Befunde und Wartungshinweise stehen in
[`docs/DOKUMENTATION.md`](docs/DOKUMENTATION.md), der geprüfte Stand der Higgsfield-API in
[`docs/API_BEFUND.md`](docs/API_BEFUND.md). Was beim ersten Lauf auf dem Kundenrechner
schiefging und was daraufhin geändert wurde, steht in
[`docs/BEFUND_2026-08-26.md`](docs/BEFUND_2026-08-26.md).

Tests:

```
python -m pytest tests/ -q                    # alle 229 (rund 2 Minuten)
python -m pytest tests/ -q -m "not langsam"   # nur die 217 schnellen
```

Start ohne Doppelklick:

```
python run.py                 eigenes Fenster
python run.py --browser       im Standardbrowser
python run.py --kein-fenster  nur der Server
python run.py --pruefen       nur die Voraussetzungen prüfen
```
