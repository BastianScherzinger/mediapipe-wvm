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
