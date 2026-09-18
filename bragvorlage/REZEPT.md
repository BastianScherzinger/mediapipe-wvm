# Rezept für einen Premium-Film

Dieses Rezept ist die Erfahrung aus einem fertig gebauten, verkaufsfähigen Film
(Webagentur Scherzinger, 17.09.2026) — beide Formate, Musik, Beat-Sync, bestandener
`hyperframes check`. Es steht hier, damit der nächste Film nicht wieder bei null anfängt.

**Es ersetzt die Skills nicht.** `/brag` bestimmt die Story, `hyperframes-*` die Technik.
Dieses Rezept sagt nur, was in der Praxis getragen hat und woran es zweimal gescheitert
wäre.

---

## 1. Was ein Video für 1.000 € von einem für 50 € unterscheidet

| | billig | verkaufsfähig |
|---|---|---|
| Inhalt | „Innovative Lösungen für Ihren Erfolg" | echte Sätze, Zahlen und Bilder des Kunden |
| Belege | Stockbilder, erfundene Sterne | Screenshots der echten Seiten, echte Preise |
| Typografie | eine Systemschrift, alles gleich groß | die Schrift der Marke, Display-Serif gegen Sans |
| Bewegung | alles fliegt von unten ein | jede Szene mit eigener Choreografie, Beat-gebunden |
| Ton | Musik drüber | Musikbett + 5–7 gesetzte Geräusche auf echten Bewegungen |
| Ende | „Danke für Ihre Aufmerksamkeit" | Logo, Claim, Kontakt — postfertig |

**Die härteste Regel: nichts erfinden.** Keine Preise, keine Auszeichnungen, keine
Kundenstimmen, die nicht im Material stehen. Ein erfundener Beleg ist kein Stilfehler,
sondern ein Rückrufgrund — und bei Werbung abmahnfähig.

## 1b. Die erste Frage: Produkt, Dienstleistung oder Webseite?

Bevor eine Sekunde geplant wird, muss klar sein, **worüber** der Film geht. Das ist
nicht dasselbe wie der Tonfall — es entscheidet, was auf der Leinwand passiert.

| | **Produkt-Film** | **Dienstleistungs-Film** | **Webseiten-Film** |
|---|---|---|---|
| Für | Shop, Mode, Speisen, Möbel | Reinigung, Garten, Entrümpelung, Handwerk | Software, Beratung, Erklärungsbedürftiges |
| Held | die Ware | das Ergebnis der Arbeit + der Mensch dahinter | das Angebot: Preis, Ablauf, Zusage |
| Bild | Produktfotos, groß, ruhig bewegt | Vorher/Nachher, Leistungsbilder, Gesicht | Seitenausschnitte, Karten, große Zahlen |
| Aufbau | Haken → Ware → Handschrift → Abbinder | ABCD: Problem → Beweis → Leistungen → Zusagen → Gesicht → End-Card | Frage → Antwort → Beweis → Abbinder |
| Pflicht | jedes gute Produktfoto kommt vor | Marken-Bug ab Sekunde 0, **ein** CTA, 4,5 s End-Card | die tragende Zahl groß |

**Ein Modeladen bekommt keinen Film über seine Webseite.** Niemand kauft eine
Webseite; gekauft wird, was darauf steht. Der erste Luviq-Film hat genau diesen Fehler
gemacht: 22 Sekunden Schrift auf schwarzem Grund für einen Laden, der handbemalte
Einzelstücke verkauft — kein einziges Kleidungsstück war zu sehen. Er war handwerklich
sauber und trotzdem der falsche Film.

**Wenn Fotos vorliegen, tragen sie den Film.** Zwei Drittel der Laufzeit Bild,
formatfüllend, mit langsamer Bewegung; Text liegt darüber, nicht an seiner Stelle.
Fotos schneidet man mit `object-fit: cover` formatgerecht — ein verzerrtes Produktfoto
ist schlimmer als keines. Unter Text auf Bild gehört ein dunkler Verlauf, sonst ist er
nicht lesbar (und `check` meldet es zu Recht).

**Wenn keine Fotos vorliegen**, ist ein typografischer Film richtig — aber dann gehört
in den Auftrag der Satz, warum es keine gibt. Erfundene Produktansichten, Stockfotos
oder KI-Bilder von fremder Ware sind in beiden Fällen verboten.

## 2. Aufbau, der trägt (15–25 s)

```
Haken (0–3 s)      eine Frage oder Aussage, die die Zielgruppe kennt
Antwort (3–9 s)    das Versprechen + das stärkste echte Bild (Preis, Produkt, Hero)
Beweis (9–17 s)    Ablauf, Leistungen oder echte Referenzen — nacheinander, nicht alle auf einmal
Abbinder (17–23 s) Gesicht oder Nutzen, dann Logo + Claim + Kontakt
```

Erprobte Zeiten für 23 s bei 110 BPM: Szenenwechsel auf 3,27 · 8,74 · 13,11 · 17,47 s,
Logo auf 20,19 s.

## 3. Lesbarkeit — die Regel, an der die meisten Videos scheitern

- Kurzes Label: **mindestens 0,8 s** vollständig sichtbar stehen lassen.
- Ganzer Satz: **0,3 s je Wort**, mindestens 1,2 s.
- Schnell hinein (0,3–0,6 s), dann **halten**. Niemals schnell hinein und gleich wieder weg.
- Vier Aufzählungspunkte in 4 s sind zu viel: Entweder jeden zweiten Beat nehmen oder die
  Szene verlängern. Tempo entsteht durch Bewegung und Schnitt, nicht durch kurzes Text-Blinken.

## 4. Gestaltung

- **Farben aus dem Material**, nicht erfunden: Hintergrund, Text, genau ein Akzent.
  Der Akzent gehört auf die wichtigste Zahl, sonst nirgends.
- **Schriften der Marke** lokal einbetten (`@font-face` auf eine mitgelieferte Datei).
  Display-Serif für Überschriften, Sans für alles andere — oder umgekehrt, aber nie zwei Sans.
- **Video ist kein Webseiten-Layout.** Überschriften 100–150 px, Fließtext 26–44 px,
  Ränder 90–140 px, Rahmen 2–3 px. Alles, was unter 24 px liegt, ist auf dem Handy weg.
- **Tiefe:** ein ruhiger Farbschein, ein feines Raster, eine Linie — mit langsamer
  Eigenbewegung. Statische Deko wirkt tot.
- **Verboten**, weil es sofort nach KI aussieht: Verlaufstext, Neon auf Dunkelblau,
  gleich große Kartenraster, überall zentrierte Blöcke, Emoji als Bedienzeichen.

## 4b. Übergänge — woran man einen Profi erkennt

Ein Schnitt ist nicht das Ende einer Szene, sondern die Verbindung zweier Szenen. Wer
jede Szene ausblendet und die nächste einblendet, hat eine Diashow gebaut, keinen Film.
**Das ist der einzige Unterschied, den ein Kunde sofort sieht, ohne ihn benennen zu
können.**

### Die vier Übergänge, die tragen

| Übergang | Wie er geht | Wann |
|---|---|---|
| **Bewegungsschnitt** | Das Bild bewegt sich VOR und NACH dem Schnitt in dieselbe Richtung weiter (z. B. beide langsam nach links). Geschnitten wird mitten in der Bewegung, nie im Stillstand. | Der Normalfall zwischen zwei Bildern |
| **Formanschluss (Match Cut)** | Zwei Bilder teilen eine Form, eine Linie oder eine Farbfläche an derselben Stelle — der Schnitt liegt genau dort. Ein Ärmel wird zur Hecke, ein heller Fleck bleibt heller Fleck. | Einmal pro Film, als bester Moment |
| **Maskenwischer** | Eine Kante (`clip-path`) fährt über das Bild und gibt das nächste frei — in der Richtung der vorherigen Bewegung, nie quer dazu. | Beim Wechsel des Themas |
| **Weiche Blende mit Weiterbewegung** | 0,4–0,6 s Überblendung, **beide** Bilder bewegen sich dabei. Zwei stehende Bilder ineinander zu blenden sieht immer billig aus. | Ruhige Passagen, Abbinder |

### Fünf Regeln, die jeden Übergang besser machen

1. **Kein Bild steht still.** Jedes Foto hat eine langsame Eigenbewegung (Zoom 1,00 → 1,06
   über die ganze Szene, oder eine Fahrt von 2–4 % der Bildbreite). Die Bewegung läuft
   **über den Schnitt hinweg** weiter — sie stoppt nicht, nur weil die Szene wechselt.
2. **Nie durch Schwarz.** Zwischen zwei Szenen darf kein leerer Rahmen liegen. Schwarz
   gehört an den Anfang und ans Ende, sonst nirgends.
3. **Der Schnitt liegt auf dem Ton.** Jeder Wechsel fällt auf einen Beat oder einen
   gesetzten Klang — nie 0,3 s daneben. Das ist der Unterschied zwischen „geschnitten"
   und „zusammengeklebt".
4. **Text und Bild wechseln nicht gleichzeitig.** Der Text geht 0,2–0,3 s vor dem Bild
   oder bleibt 0,3 s länger stehen. Alles auf einmal ist ein Wimpernschlag ins Leere.
5. **Eine Bewegungssprache je Film.** Entweder alles fährt seitlich, oder alles zoomt,
   oder alles wischt. Drei verschiedene Übergangsarten in 22 Sekunden wirken unentschlossen —
   zwei sind das Maximum, plus einen einzigen besonderen Moment.

### Was einen Film billig aussehen lässt

- Jede Szene blendet zu Schwarz und wieder auf.
- Text fliegt aus vier verschiedenen Richtungen herein.
- Jedes Bild zoomt gleich schnell hinein („Ken-Burns über alles").
- Harte Schnitte ohne Ton darunter.
- Elemente, die einfach erscheinen (`opacity 0 → 1` ohne Bewegung, ohne Maske).
- Ein Bild, das im Format nicht aufgeht und mit Balken oder Verzerrung sitzt.

## 4b2. Schnittrhythmus — gemessen, nicht gefühlt

Der zweite Luviq-Film sah gut aus und wirkte trotzdem zäh. Die Messung sagt, warum:
**In 25 Sekunden lag genau ein erkennbarer Schnitt.** Alles andere waren weiche
Blenden. Ein Film ohne Schnitte hat keinen Puls — er sieht aus wie eine Präsentation
mit Überblendung, und genau so fühlt er sich an.

**Zielwerte für 22–26 Sekunden:**

| | Wert |
|---|---|
| Bildwechsel insgesamt | **12–18** (alle 1,4–2,1 s) |
| davon harte Schnitte | **mindestens drei Viertel** |
| weiche Blenden | höchstens zwei im ganzen Film |
| längste Einstellung | 3,0 s (Ausnahme: End-Card) |
| kürzeste Einstellung | 0,5 s — als Akzent, nicht als Regel |

**Wie man Tempo erzeugt, ohne hektisch zu werden:**

1. **Zwei Einstellungen je Motiv.** Erst das Detail (Ausschnitt der Malerei, die Hand,
   die Kante), dann die Totale — oder umgekehrt. Zwei Schnitte, 0,6–0,9 s auseinander,
   auf demselben Objekt. Das ist der billigste Weg zu doppeltem Tempo ohne neues Material.
2. **Der Schnitt liegt auf dem Beat**, nie daneben. Bei 110 BPM alle 0,545 s ein
   möglicher Schnittpunkt — genommen wird jeder dritte oder vierte.
3. **Text wechselt zwischen den Bildschnitten**, nicht mit ihnen: Bild schneidet auf
   Beat 4, Text auf Beat 8. So entstehen doppelt so viele Ereignisse wie Schnitte.
4. **Die Bewegung läuft über den Schnitt weiter** — dann wirkt ein harter Schnitt nicht
   abgehackt, sondern treibend.

**Die Prüfung dazu ist eine Zeile und gehört zur Abnahme:**

```bash
ffmpeg -i brag.mp4 -filter:v "select='gt(scene,0.25)',showinfo" -f null - 2>&1 | grep -c pts_time
```

Zählt das weniger als zehn bei einem 25-Sekunden-Film, ist der Film zu träge —
unabhängig davon, wie schön die einzelnen Bilder sind.

## 4b3. Menschen im Bild — die Regel, die ein Video sofort billig macht

Der Luviq-Film zeigte die Inhaberin **freigestellt auf Schwarz**. Um Haare und Schultern
lag eine ausgefranste, bunt gesprenkelte Kante, unten brach der Körper hart ab. Das ist
der sichtbarste Amateurfehler überhaupt — und er entsteht ausgerechnet beim Versuch,
etwas besonders gut zu machen.

**Regel: Menschen werden nicht freigestellt.** Haare lassen sich mit Schwellenwerten,
Farbdistanz oder einem Weichzeichner nicht sauber ausschneiden; was übrig bleibt, ist
ein Heiligenschein. Stattdessen:

- **Das Originalfoto in einen Rahmen setzen** — ein Panel, eine halbe Bildseite, ein
  Kreis mit Markenring. Der Ausschnitt wird mit `object-fit: cover` gesetzt, das Bild
  bleibt unangetastet.
- **Mit einem Verlauf einbetten**, wenn es in die Fläche auslaufen soll: eine Maske vom
  Bildrand in den Grund (`mask-image: linear-gradient(...)`), 15–25 % der Bildbreite.
  Das ist weich, hat keine Kante und funktioniert bei jedem Motiv.
- **Gesicht groß genug**: mindestens ein Drittel der Bildhöhe. Ein Mensch, der zu klein
  im Bild steht, schafft kein Vertrauen — er wirkt wie ein Symbolbild.
- **Blickrichtung in die freie Fläche**, Text auf die andere Seite. Wer nach rechts
  schaut, bekommt den Text rechts.
- **Nie unter der Brust abschneiden** und nie an einem Gelenk. Kopf bis Hüfte oder
  Kopf bis Brust, mit Luft über dem Kopf.

Dasselbe gilt für alles Organische: Pflanzen, Fell, Rauch, transparente Stoffe.
**Freigestellte Produkte sind etwas anderes** — wenn der Shop sie bereits vor weißem
Grund fotografiert hat, ist die Kante sauber, und man darf sie benutzen.

## 4c. Der Feinschliff, der aus „gut" „verkaufsfähig" macht

Diese sechs Dinge kosten zusammen zwanzig Minuten und heben den Film sichtbar:

1. **Eine Farbwelt über alle Fotos.** Bilder aus verschiedenen Quellen haben
   verschiedene Weißabgleiche. Ein gemeinsamer Filter (`filter: saturate(.92)
   contrast(1.06) brightness(.98)` plus eine leichte Tönung in der Markenfarbe) macht aus
   sieben Fotos einen Film. Ohne ihn bleibt es eine Sammlung.
2. **Vignette.** Ein weicher dunkler Rand (radialer Verlauf, 25–40 % an den Ecken) führt
   das Auge und kaschiert unterschiedliche Bildränder.
3. **Korn.** Eine ruhige, sehr feine Körnung über dem ganzen Bild (2–4 % Deckkraft)
   nimmt Fotos das Digitale. Statisch, nicht flackernd — flackerndes Korn frisst Bitrate.
4. **Weiche Kanten statt harter Rahmen.** Ein Foto, das in den Grund ausläuft (Maske mit
   weichem Verlauf), wirkt teurer als eines mit sichtbarer Kante.
5. **Typografie mit Maske einblenden**: Text erscheint hinter einer Kante hervor
   (`clip-path` von unten), statt einzufliegen. Das ist der Unterschied zwischen
   Kinotitel und PowerPoint.
6. **Der letzte Frame steht.** Die letzten 1,5 Sekunden bewegt sich nichts mehr außer
   dem Ausklingen — der Blick soll auf Marke und Kontakt liegen bleiben.

### Bildqualität

Kleine Fotos (unter 1200 px) vertragen **höchstens 1,35-fache** Vergrößerung, sonst
werden sie weich. Plane Fahrten deshalb von groß nach klein (Zoom-out), nicht umgekehrt:
Der weichste Moment liegt dann am Anfang der Szene, wo noch niemand hinsieht.
Freistellen nur, wenn die Kante sauber wird — ein sichtbarer Schnitt an Haaren oder
Stoff ruiniert mehr, als der freigestellte Look bringt.

## 4d. Der Bauplan einer Szene — warum Flügel unruhig wirkte und Rümpelwerk nicht

Beide Filme hatten dasselbe Material-Niveau: echte Objektfotos, ein Gesicht, belegte
Zusagen. Der eine sah aus wie von einer Agentur, der andere wie zusammengesetzt. Der
Unterschied lag **nicht** an den Bildern, sondern an vier Regeln, die Rümpelwerk einhält
und Flügel verletzt hat.

### Regel 1 — Fotos füllen das Bild. Immer.

In Flügel lagen die Vorher/Nachher-Fotos als **Panel in der Mitte**, oben und unten
dunkler Grund. Ein Querformat-Foto im 9:16-Rahmen, unbeschnitten. Das sieht aus wie eine
Präsentationsfolie mit eingefügtem Bild — und genau daran erkennt man Amateurarbeit.

```css
/* richtig: das Foto ist die Szene */
.szene img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
```

Ein Querformat-Foto im Hochformat wird **beschnitten**, nicht eingepasst. Wenn der
interessante Teil dabei verloren geht, verschiebt man den Bildausschnitt
(`object-position`), statt das Bild zu verkleinern. Balken und schwebende Kästen gibt es
nicht — außer als bewusstes Gestaltungsmittel über den ganzen Film hinweg, nie einmalig.

### Regel 2 — Text hat einen festen Anker, über den ganzen Film

In Flügel saß der Text mal unten links, mal unter dem Bild, mal oben, mal in der Mitte —
in vier Szenen an vier Stellen. Das Auge muss ihn jedes Mal neu suchen, und der Film
wirkt zusammengewürfelt.

**Ein Anker je Formatseite, festgeschrieben als Token:**

```css
:root {
  --text-x: 90px;          /* linke Kante aller Texte */
  --text-y: 68%;           /* Grundlinie der Headline, 9:16 */
  --headline: 74px;        /* eine Größe für alle Headlines */
  --subline: 30px;         /* eine Größe für alle Sublines */
}
```

Jede Headline steht links an `--text-x`, jede Subline 14 px darunter, jede Headline hat
dieselbe Größe. Was wichtiger ist, bekommt **mehr Standzeit**, nicht mehr Punkte.

### Regel 3 — Ein Gedanke je Szene

Flügel zeigte im Nachher-Bild gleichzeitig: das Foto, das Label „NACHHER", eine
Google-Rezension und deren Quelle. Vier Dinge, die um dieselbe Sekunde kämpfen.

Eine Szene trägt **eine** Aussage. Das Zitat bekommt eine eigene Szene, der
Leistungsname eine eigene, der Beweis eine eigene. Wer drei Dinge in vier Sekunden
sagen will, braucht drei Szenen à 1,4 s — nicht eine mit drei Textblöcken.

### Regel 4 — Der Wechsel hell/dunkel gibt den Takt

Rümpelwerk wechselt: dunkle **Bildszene** (Foto formatfüllend, Text unten) → helle
**Infoszene** (weißer Grund, Überschrift oben, Liste oder Zahlen mit Akzentfarbe) →
dunkle Bildszene → helle Infoszene → Gesicht auf Weiß → End-Card in Markenfarbe.

Dieser Wechsel ist der Grund, warum der Film Struktur hat, obwohl er nur fünf harte
Schnitte enthält: Die **Fläche** wechselt, nicht nur das Motiv.

Flügel war durchgehend dunkelblau. Alles floss ineinander, nichts hatte ein Gewicht.

**Mindestens zwei Infoszenen je Film** — typischerweise „Was wir machen" (Leistungen als
Liste mit Haken) und „Was wir zusagen" (zwei, drei Zahlen groß, darunter, worauf sie sich
beziehen).

### Die zwei Szenentypen als Bauplan

| | **Bildszene** | **Infoszene** |
|---|---|---|
| Grund | das Foto, formatfüllend | Markenweiß oder heller Markenton |
| Verlauf | dunkler Verlauf über die unteren 45 % | keiner |
| Headline | unten links am Anker, weiß | oben links, in Markenschwarz |
| Zweite Ebene | eine Subline, klein, 80 % Deckkraft | Liste mit Haken oder große Zahlen |
| Chip | oben links unter dem Marken-Bug (`VORHER`, Leistungsname) | keiner |
| Dauer | 1,4–2,5 s | 2,5–4,0 s (mehr zu lesen) |

### Vorher/Nachher gehört in **eine** Szene

Nicht zwei Panels nebeneinander oder nacheinander, sondern **ein** formatfüllendes Bild,
über das eine Kante läuft und das zweite freigibt. Das Vorher steht 1,4 s, dann fährt die
Kante in 1,0–1,2 s durch. Der Chip wechselt dabei von `VORHER` auf `NACHHER`. Nur so
sieht man, dass es derselbe Ort ist — und genau das ist der Beweis, um den es geht.

## 5. Ton

- Musikbett aus `~/.claude/skills/brag/assets/music/`, Lautstärke 0,3, 1 s einblenden,
  am Ende ausblenden (`data-automation`-Lane auf `volume`).
- 5–7 Geräusche, jedes auf einer **sichtbaren** Bewegung: Tastenticks beim Tippen, ein
  weicher Impact auf der Kernzahl, ein leiser Drop je Karte, eine Glocke aufs Logo.
- Beat-Raster aus `assets/music/cues/<track>.music-cues.md` lesen: 1–3 große Momente auf
  starke Cues legen, Reihen auf aufeinanderfolgende Beats — aber nur, solange es die
  Lesezeit nicht kaputtmacht.
- Eine dezente audio-reaktive Ebene (RMS auf Leuchten/Skalierung, 3–6 %) macht den
  Unterschied zwischen „Folien mit Musik" und Film. Keine Wellenformen, keine Equalizer.

## 6. Beide Formate — neu bauen, nicht beschneiden

Querformat 1920×1080 und Hochformat 1080×1920 sind **zwei Kompositionen** mit gleichem
Text, gleicher Musik und gleichen Zeiten. Im Hochformat:

- Überschriften brechen auf zwei bis drei Zeilen (feste Zeilen, keine zufälligen Umbrüche).
- Was im Querformat nebeneinander steht, steht hier untereinander.
- Reihen laufen senkrecht (Verbindungslinie wächst nach unten, `scaleY`).
- Bildstapel kaskadieren nach unten statt nach rechts.
- Ränder 90 px, nichts näher als 60 px an den Rand — sonst liegt es unter der TikTok-Bedienleiste.

## 6b. Zeit einteilen — der häufigste Totalausfall

Ein Film, der nie gerendert wird, ist kein Film. Der erste Luviq-Durchgang ist genau so
gestorben: vierzig Minuten Bildfreistellung, dann Zeitlimit — beide Kompositionen fertig,
kein einziges Video.

- **Zur Hälfte der verfügbaren Zeit müssen die Renders laufen.** Rendern dauert 4–8
  Minuten je Fassung; was danach kommt, ist Zugabe.
- **Bildaufbereitung ist Kür.** Freistellen, Retusche, Kantenglättung: Gelingt es nicht
  in zwei, drei Anläufen, nimm das Originalfoto und bette es mit Verlauf, Vignette oder
  Maske ein. Ein sichtbar ausgeschnittenes Haar ist ein Schönheitsfehler; ein fehlender
  Film ist ein Totalausfall.
- **Erst rendern, dann verbessern.** Liegen beide Filme, ist alles Weitere risikolos —
  und man kann erneut rendern, wenn Zeit bleibt.

## 7. Ablauf des Baus

1. Material sichten (`material/`, `aufnahme/`, Projektordner) — echte Texte, Farben, Bilder ziehen.
2. `brag-output/brag-plan.md` schreiben (Storyboard mit Sekunden, Szenenzeiten summiert 15–25 s).
3. Querformat bauen → `npx hyperframes check` → `npx hyperframes snapshot --at …` → Bilder **ansehen**.
4. Hochformat bauen → dieselben Schritte.
5. Rendern: `npx hyperframes render --quality high --output …`.
6. Posterbild aus der stärksten Sekunde ziehen und als Bild 0 einbacken.

## 8. Fallen, die schon zugeschnappt sind

| Falle | Was passiert | Abhilfe |
|---|---|---|
| **Altes ffmpeg im Suchpfad** | Render läuft zwei Minuten und stirbt am Tonmix (`audio_processing_failed`) | Das Programm legt ein aktuelles ffmpeg voran — nicht selbst eines suchen |
| `line-height` unter 1,05 bei großer Serif | `check` meldet `content_overlap` als Fehler | 1,1 oder mehr |
| Deckender Hintergrund auf einem Szenen-Clip | Überblendungen werden zu harten Schnitten, Hintergrundebene verschwindet | Hintergrund nur auf `#root` bzw. einer eigenen Ebene |
| Ausgehende Szene blendet 0,5 s | Alte und neue Überschrift liegen kurz übereinander | Ausgehend 0,3 s, eingehenden Text 0,2 s später starten |
| Cursor/Caret hinter unsichtbarem Text | Steht von Sekunde 0 am Zeilenende | `opacity: 0` in CSS und `immediateRender: false` im Tween |
| Karte zu weit unten im Hochformat | `panel_out_of_canvas` | Alles bis 1.860 px halten |
| `data-duration` länger als die Tondatei | `clip_media_fit`-Warnung | Länge der Datei eintragen |
| Nur `check` bestanden | Sagt nichts über Schönheit | Immer Snapshots ansehen |
| **Lauftext/Marquee mit verdoppeltem Text** | Im Standbild steht „LUVIQLU VIQ" oder „JETZT ENTDECKENJETZT ENTDECKEN" — für ein Video, das als Standbild vorschaut, unbrauchbar | Kein dupliziertes Band. Ein Wort erscheint **einmal**; Bewegung kommt aus Maske, Zoom oder Laufweite, nicht aus zwei Kopien nebeneinander |
| **Freistell-Ränder an Personen** | Rote/weiße Fransen um Haare und Schultern | Freistellen nur, wenn es sauber wird. Sonst das Originalfoto nehmen und mit Verlauf oder Vignette in den Grund einbetten — ein ganzes Foto ist besser als ein schlecht ausgeschnittenes |

### Textprüfung an jedem Schnappschuss (nicht überspringen)

Beim Ansehen der Kontaktbögen wird **jedes Wort gelesen**, nicht nur der Eindruck geprüft:

- Steht ein Wort versehentlich zweimal? (Marquee, Klon-Ebene, doppelte Zeile)
- Ist ein Wort abgeschnitten, gestaucht oder in der Mitte umgebrochen?
- Liegt Text auf einer hellen Bildstelle ohne Verlauf darunter?
- Ragt etwas aus dem Bild, das nicht darf?

Ein einziger dieser Fehler macht den Film unverkäuflich — er fällt jedem Kunden in der
ersten Sekunde auf.

## 8b. Die drei Sorten Film — und wo ihr Vorbild liegt

| Sorte | Wofür | Vorbild | Was den Film trägt |
|---|---|---|---|
| **Produkt & Marke** | Shop, Mode, Speisen, Möbel | Luviq Universe | Die Ware, groß und ruhig bewegt. Text ist Beiwerk |
| **Dienstleistung** | Reinigung, Garten, Entrümpelung, Handwerk | Rümpelwerk, Flügel | Vorher/Nachher, Leistungen, Zusagen, Gesicht, End-Card |
| **Webseite & Angebot** | Software, Beratung, alles Erklärungsbedürftige | Webagentur Scherzinger | Die Aussage, die Zahl, der Ablauf, die Oberfläche |

**Für Dienstleistungsfilme ist `HANDWERK-werbefilm.md` die Hauptquelle** — dort steht
das ABCD-Gerüst, die sicheren Zonen der Apps, wie ein echtes Vorher/Nachher aussieht,
warum das Vorher 1,4 Sekunden braucht, und wie eine End-Card gebaut wird, die Anrufe
auslöst. Es ist an einer abgenommenen Produktion erarbeitet, nicht ausgedacht.

## 9. Referenzdateien

`referenz-querformat.html` und `referenz-hochformat.html` sind ein fertiger
Webseiten-/Angebotsfilm in beiden Formaten. `referenz-dienstleistung-hochformat.html`
ist der abgenommene Rümpelwerk-Film (9:16, 26 s) — **der Maßstab für jeden
Dienstleistungsfilm**: Marken-Bug, Wischkante, Leistungen einzeln, Zähler, End-Card.
Alle drei sind als **Technik-Vorlage** gedacht: Zeitachse, Audioverdrahtung,
Bewegungsschnitte, Masken, Beat-Kommentare, Szenenaufbau.

**Inhalte, Farben, Schriften und Texte daraus niemals übernehmen** — sie gehören einem
anderen Kunden. Was übernommen wird, ist die Machart.
