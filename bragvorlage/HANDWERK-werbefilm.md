> **Herkunft dieser Datei.** Sie ist beim Bau des Werbevideos für Rümpelwerk
> Mitteldeutschland entstanden (18.09.2026, 26 s, 1080×1920) und beschreibt das
> Handwerk, das dort erarbeitet wurde. Sie gilt als **Maßstab für jeden
> Dienstleistungs-Markenfilm** dieses Programms. Die Beispiele nennen Rümpelwerk —
> gemeint ist die Machart, nicht der Inhalt: Farben, Texte und Belege kommen immer
> vom jeweiligen Kunden.

# Werbevideo-Produktion — was ich gelernt habe

**Stand: 18.09.2026** · Erarbeitet an der ersten und zweiten Fassung des
Rümpelwerk-Videos (1080×1920, 26 s). Diese Datei ist die Wissensgrundlage für
den geplanten Video-Skill. Sie trennt drei Dinge sauber:

1. **Das Handwerk** — wie Leute arbeiten, die Werbefilm als Beruf machen, mit Quellen.
2. **Die Pipeline** — der Ablauf, der hier funktioniert hat, Schritt für Schritt.
3. **Die Fallen** — was schiefgegangen ist und woran man es erkennt.

> **Grundsatz, der alles andere überschreibt:** Ein Werbevideo ist kein Design,
> es ist eine **Behauptung über ein echtes Unternehmen**. Jede Zahl, jede
> Zusage und jedes Gesicht darin muss belegt sein. Das ist kein Feinschliff,
> das ist die Eintrittskarte.

---

## Teil 1 — Das Handwerk

### 1.1 Das ABCD-Gerüst (Google/YouTube) — der Bauplan, nicht die Deko

Google hat mit Ipsos, Nielsen und Kantar gemessen, welche Merkmale Videowerbung
wirksam machen, und daraus vier Bereiche destilliert. Anzeigen, die sie
einhalten, zeigen im Schnitt **+30 % kurzfristige Kaufwahrscheinlichkeit** und
**+17 % langfristigen Markenbeitrag**.

| | Was es heißt | Was das konkret bedeutet |
|---|---|---|
| **A — Attention** | Aufmerksamkeit holen **und halten** | Sofort in die Geschichte springen, nicht aufbauen. Helle, kontrastreiche Bilder. Ton und Text verstärken dieselbe Aussage, statt zu konkurrieren. |
| **B — Branding** | „Show up early **and throughout**" | Die Marke ab der ersten Sekunde und **durchgehend** — Logo, Produktbild, Grafikelemente, Farbe, Ton. |
| **C — Connection** | Emotional oder intellektuell andocken | **Menschen zeigen.** Sprache einfach und fokussiert halten. Humor, Überraschung, Neugier. |
| **D — Direction** | Klar sagen, was zu tun ist | Ein CTA, bewusst platziert — **nach** dem Kontext, nicht davor. |

**Der Fehler der ersten Fassung war B.** Das Logo kam erst bei Sekunde 17. Wer
vorher abbrach — also die große Mehrheit — hat nie erfahren, wer da wirbt.
Das ist der Unterschied zwischen einem hübschen Film und Werbung.

**Konsequenz für jeden künftigen Film:** ein **Marken-Bug** — Logo-Lockup in
einer weißen Pille, oben links in der sicheren Zone, ab Sekunde 0,25 bis zur
End-Card. Er kostet 90 × 620 px Bildfläche und löst das Problem vollständig.

### 1.2 Safe Zones — die Regel, die am meisten Arbeit spart

Bei 9:16 legt **die App ihre Bedienelemente über das Bild**. Was dort liegt,
ist verdeckt — auf allen Geräten, immer. Gemessene Werte (2026):

| Rand | TikTok | Instagram Reels | **Praxiswert** |
|---|---|---|---|
| oben | ~140 px | ~220 px | **250 px** |
| unten | ~400 px | ~420 px | **440 px** |
| links | ~60 px | ~35 px | **90 px** |
| **rechts** | **~180 px** | ~60 px | **200 px** |

**Rechts ist die Falle.** Dort sitzt die Aktionsleiste (Gefällt mir,
Kommentar, Teilen, Ton, seit Januar 2026 zusätzlich „Zur Playlist"). Die erste
Fassung hatte das NACHHER-Label rechts bei `right: 90px` — es wäre auf TikTok
teilweise unter den Knöpfen verschwunden.

**Daraus wird ein Token-Satz, kein Bauchgefühl:**

```css
:root {
  --sa-l: 90px;    --sa-r: 200px;
  --sa-t: 250px;   /* unten 440 px bleiben frei */
  --sa-w: 790px;   /* 1080 − 90 − 200 */
}
```

Jedes Textelement bekommt `left: var(--sa-l); width: var(--sa-w)` und liegt
zwischen y 250 und y 1480. **Bilder dürfen darüber hinaus** — nur Information
nicht.

Das ist eng: 790 von 1080 px sind 73 % der Breite. Genau deshalb ist es eine
Entwurfsentscheidung und keine Korrektur am Ende — nachträglich passt der Text
nicht mehr, und man beginnt zu schrumpfen statt zu kürzen.

### 1.3 Vorher/Nachher — warum es in dieser Branche alles schlägt

Für Entrümpelung, Reinigung, Sanierung und Renovierung ist Vorher/Nachher das
stärkste Format: Es zeigt dem Kunden genau das, was er will — **den Beweis,
dass sein Problem lösbar ist.** Das Vorher-Bild ist der Haken und entscheidet,
ob jemand stehenbleibt; es wirkt, wenn es **die Alltagsrealität des Zuschauers
spiegelt**, mit konkreten, emotional genauen Details. Die verkaufte Emotion ist
nicht Sauberkeit, sondern **Erleichterung, dass es weg ist**.

**Die Regel für den Reveal:** früh genug, um die zu belohnen, die stehenbleiben —
spät genug, dass Spannung entsteht.

**Das habe ich in Fassung 1 falsch gemacht.** Die Wischkante startete 0,6 s nach
dem Schnitt. Das Chaos war weg, bevor es wirken konnte, und die Auflösung kam,
bevor jemand eine Frage hatte. In Fassung 2 steht das Vorher **1,4 s**, dann
läuft die Kante 1,1 s. Gleiche Szenenlänge, völlig andere Wirkung.

**Merksatz:** *Der Reveal ist nur so viel wert wie die Zeit, die das Problem
vorher bekommen hat.*

### 1.4 Farbgrading als Dramaturgie, nicht als Filter

Werbefilmer trennen Vorher und Nachher nicht nur im Schnitt, sondern **in der
Farbe**:

| | Temperatur | Sättigung | Helligkeit | Wirkung |
|---|---|---|---|---|
| **Vorher** | kühl (Blau ↑, Rot ↓) | −16 bis −20 % | leicht runter | bedrückend, klamm, fremd |
| **Nachher** | warm (Rot ↑, Blau ↓) | +8 % | +12 bis +16 % | offen, freundlich, bewohnbar |

Der Zuschauer bemerkt es nicht und spürt es trotzdem. Umgesetzt wird es beim
Bildexport, nicht per CSS-Filter — dann ist es im Rendervorgang schon
eingebrannt und kostet keine Rechenzeit:

```python
a[:,:,0] *= (1 + temp*0.10)   # Rot
a[:,:,2] *= (1 - temp*0.09)   # Blau
```

### 1.5 Schnitt auf das Taktraster

Der Musikschnitt ist kein Extra, er ist der Grund, warum ein Film „sitzt".
Bei **120 BPM** liegt ein Beat alle **0,5 s**. Jeder Szenenwechsel und jeder
größere Einsatz gehört auf dieses Raster.

Konkret in diesem Film (Track 120,19 BPM, Raster ab 3,02 s):

| Zeit | Ereignis | Beat |
|---|---|---|
| 3,02 | Schnitt auf die Verwandlung | ✓ |
| 8,52 | Schnitt auf die Leistungen | ✓ |
| 13,01 | Schnitt auf die Zusagen | ✓ |
| 17,52 | Schnitt auf den Ansprechpartner | **starker Beat** |
| 21,01 | Logo-Anschlag der End-Card | **starker Beat** |
| 22,01 | CTA schlägt auf | **starker Beat** |

**Die Ausnahme, die man kennen muss:** sequentiell einlaufender **Text** darf
*nicht* auf jeden Beat. Bei 120 BPM wären das 0,5 s pro Zeile — zu schnell zum
Lesen. Text läuft auf **jeden zweiten Beat** (1,0 s). Akzente ohne Leseinhalt
(Glühen, Punkte, Ticks) dürfen auf jeden Beat.

### 1.6 Lesezeit — die Grenze, unter die man nie geht

- **Kurzes Label (1–3 Wörter):** ~0,8 s vollständig sichtbar, nach dem Einlaufen.
- **Satz/Headline:** ~0,3 s pro Wort, mindestens 1,2 s. Die Hook-Zeile bekommt am meisten.

Tempo entsteht durch **schnelle Bewegung und harte Schnitte**, nie dadurch,
dass Text früher verschwindet. Das Muster heißt **schnell rein, dann halten** —
Einlauf 0,35–0,5 s, danach stehenlassen. Ein Vier-Sekunden-Bild trägt zwei bis
drei kurze Leseeinheiten, nicht sechs.

### 1.7 Die End-Card — hier wird aus Film Werbung

Was die Praxis über Endtags sagt:

- **Der CTA ist Pflicht**, nicht optional. Höchstens drei, besser einer plus Kontaktweg.
- **Konkretheit und Dringlichkeit wirken messbar**: Formulierungen mit „jetzt"
  oder „heute" erzielen deutlich höhere Reaktionsraten als neutrale.
- Der CTA muss **wie ein Knopf aussehen** — auch wenn er im Video nicht klickbar
  ist. Das Auge kennt die Form und weiß sofort, was gemeint ist.
- **Volle Markenumgebung**: eigener Hintergrund in Markenfarbe, Logo, gleiche
  Typografie wie der Rest.
- Ein Endtag **steht nie ganz still**. 2 % Push-in über die Szene reicht.

Aufbau, der hier steht (21,0 → 26,0 s, tiefgrüner Grund):

```
Logo in weißer Karte      (Markenanker, schlägt auf Beat 21,01 auf)
„Jetzt kostenlos anfragen" (weißer Knopf, grüne Schrift, Beat 22,01, ein Puls)
+49 163 5027819           (der eigentliche Handlungsweg)
ruempelwerk-…de           (der zweite Weg)
Städtezeile               (Relevanzfilter: „ist das überhaupt meine Gegend?")
```

**Fünf Sekunden sind richtig.** Die End-Card braucht Standzeit — sie ist die
einzige Stelle, an der jemand zum Telefon greift.

### 1.8 Connection: das Gesicht

Bei lokalen Dienstleistern ist das Gesicht des Inhabers der stärkste einzelne
Vertrauensbeleg. Der Grund ist die Konkurrenz: Plattformen und Vermittler
treten anonym auf. Ein Name, ein Foto und ein Ort sind das Gegenteil davon.

Umgesetzt als eigene Szene (3,5 s): rundes Porträt mit Markenring, Badge
„IHR ANSPRECHPARTNER", Name, Rolle mit Ort, ein Satz.

**Vor der Verwendung prüfen, wen das Bild zeigt.** Hier war der Dateiname
`ichfirma.jpeg` nur ein Indiz; belegt wurde es durch `templates/ueber-uns.html`
(Alt-Text, Bildunterschrift, „Gründer & Inhaber"). Ein Gesicht falsch zu
beschriften ist eine Aussage über einen realen Menschen.

### 1.9 Ton: sparsam, gebunden, unauffällig

- **Ein Bett** durchgehend, Einblende 0,6 s, Ausblende über die letzten 1,6 s.
- **Geräusche nur, wo sich sichtbar etwas bewegt**: ein Wisch auf der Kante,
  ein Tick pro Listenzeile, ein Anschlag pro Zahl, ein Impact zum Logo.
- Bei „polished" gilt: **warme, tieffrequente Geräusche** (low HF risk), keine
  hellen Klicks in Serie — die ermüden.
- **Kein Whoosh zwischen allen Szenen.** Das ist das Kennzeichen von
  Vorlagenware.
- Zielpegel: Mittel um **−23 dB**, Spitze um **−3 dB**. Messbar mit
  `ffmpeg -af volumedetect`.

### 1.10 Was den Film „nach dieser Firma" aussehen lässt

„Im Stil der Marke" heißt nicht „mit dem Logo drauf". Es sind vier Ebenen,
und alle vier müssen aus der bestehenden Website kommen:

1. **Farbtokens 1:1** aus dem CSS des Kunden — inklusive der Eigenheiten
   (hier heißt die Primärfarbe aus historischen Gründen `--rw-orange` und ist
   Grün; die Dekorfarbe darf nie Textfarbe sein).
2. **Die echten Schriften**, als Datei aus `static/fonts/`, nicht „so ähnlich".
3. **Ein wiederkehrendes Formelement.** Hier: der grüne Akzentstrich, der im
   Hook auftaucht und danach über jeder Überschrift steht. Er klammert Szenen,
   die sonst nichts verbindet.
4. **Echtes Material.** Objektfotos des Betriebs, das Gesicht des Inhabers,
   das Original-Logo. Kein Stock.

Dazu der **Markenfuß**: ein kaum sichtbarer Grünverlauf über die unteren
520 px der hellen Szenen. Er schließt die Komposition nach unten ab, hält die
Markenfarbe präsent — und legt dabei keine Information in die verdeckte Zone.

### 1.11 Echtes Vorher/Nachher heißt: **derselbe Raum**

Das ist der Unterschied zwischen einem Beleg und einer Behauptung. Zwei schöne
Fotos aus zwei Wohnungen nebeneinanderzustellen sieht aus wie Vorher/Nachher,
ist aber keins — und der Zuschauer merkt es, auch wenn er es nicht benennen
kann. Wiedererkennbar müssen sein: **Decke, Fenster, Bodenbelag, Wandstruktur.**

**Wo die echten Paare liegen, ist fast nie der Ordner, den man zuerst findet.**
Hier lagen 13 Einzelbilder in einem Ads-Ordner — aber das CMS der Website hatte
Felder namens `bild_vor` und `bild_nach` und **5.605 Auftragsfotos**. Die lokale
Datenbank war leer; die Paare standen auf der **Live-Seite** unter `/galerie/`
und `/aktuelles/`.

**Vorgehen, das sich bewährt hat:**
1. Im Projekt nach Modellfeldern suchen, die nach Paaren klingen
   (`bild_vor`/`bild_nach`, `before`/`after`).
2. Ist die lokale Datenbank leer, die **öffentliche Galerie-Seite abrufen** —
   dort steht die Zuordnung, die im Dateinamen fehlt.
3. Alle Kandidaten als **Kontaktbogen** herunterladen und nebeneinander
   ansehen. Ein Blick auf zehn Miniaturen spart drei Fehlversuche.
4. Paare nach **Wiedererkennbarkeit** wählen, nicht nach Schönheit des
   Einzelbildes.

**Nebenbefund, der eine Annahme widerlegt hat:** Beim Vergleich stellte sich
heraus, dass das Hook-Bild aus dem Ads-Ordner **bitgleich** ein Bild aus dem
CMS war. Die Ordner mit generischen Namen enthielten also längst echtes
Firmenmaterial. **Erst vergleichen, dann über Herkunft urteilen.**

### 1.12 Kleine Quelle, große Leinwand — was man retten kann

Das bessere Paar hatte ein Problem: Das Nachher-Bild war nur **837 × 1131 px**,
der 9:16-Zuschnitt daraus 636 × 1131 — also **1,95-fache Hochrechnung** auf die
Leinwand. Trotzdem war es die richtige Wahl, weil der Beleg schwerer wiegt als
die Schärfe.

**Was hilft, in dieser Reihenfolge:**

1. **Lanczos** zum Hochrechnen (nicht bikubisch).
2. **Unsharp Mask** danach, `radius ≈ 2.0`, `percent 120–130`, `threshold 3`.
   Vor dem Hochrechnen zu schärfen verstärkt nur das Rauschen.
3. **Gamma auf die Tiefen** statt globaler Helligkeit:
   `a = (a/255) ** 0.82 * 255`. Das öffnet den Raum, statt ihn zu überstrahlen.
   Erst danach Helligkeit und Kontrast fein nachziehen.
4. **Den Kamerazoom zurücknehmen.** Ein 8-%-Ken-Burns macht die Weichheit
   sichtbar; bei stark hochgerechneten Bildern **3 % oder weniger**.
5. **Den Verlauf darüber prüfen.** Ein Abdunkler, der für ein scharfes Bild
   passte, erdrückt ein weiches vollends.

**Faustregel:** Bis etwa 1,6-fach ist Hochrechnen unsichtbar, bis 2,0-fach mit
den Schritten oben vertretbar, darüber sucht man ein anderes Bild.

### 1.13 Dekoration kollidiert mit Text — die Rechnung, die man machen muss

Ein grüner Akzentstrich lag mitten im Wort „alldem?". Im Code sah nichts falsch
aus: Headline bei `top: 1080px`, Strich bei `top: 1272px` — 192 px Abstand.

**Der Fehler war, die Texthöhe nicht auszurechnen.** Zwei Zeilen à 106 px bei
`line-height: 1.04` sind **220 px**. Der Textblock endete also bei 1300 — der
Strich lag 28 px **innerhalb** des Textes.

```
Texthöhe = Zeilen × font-size × line-height
         = 2 × 106 px × 1.04 = 220 px
```

**Regel:** Bei jedem absolut positionierten Element unter einem mehrzeiligen
Text diese Zeile ausrechnen und einen Abstand von mindestens 30 px addieren.
Kein Linter meldet das — weder Überlappung noch Kontrast schlagen an, weil der
Strich technisch „neben" dem Text liegt und nur optisch hineinragt. **Gefunden
wird es nur am Standbild.**

Das ist zugleich der stärkste Beleg für die Arbeitsweise: Der Fehler stand in
zwei gerenderten Fassungen und in mehreren Kontrollbögen — gesehen hat ihn
zuerst der Mensch, der das Video angeschaut hat. **Schlüsselbilder ansehen ist
kein Zusatzschritt, es ist der Prüfschritt.**

---

## Teil 2 — Die Pipeline, die funktioniert hat

### Schritt 0 · Quellen erschließen (vor jedem Gestalten)

Aus dem Projekt des Kunden holen — **nicht erfinden**:

| Was | Wo es typischerweise steht |
|---|---|
| Farben, Radien, Schatten | `static/css/*.css`, `:root` |
| Schriften als Datei | `static/fonts/` |
| Logo | `static/images/` |
| Claims, Überschriften | Startseiten-Template |
| Zahlen und Zusagen | Datenmodule (`data/zusagen.py`, `reviews.py`, `pricing.py`) |
| Stammdaten | `data/firma.py` |
| Fotos | Ads-/Galerie-Ordner, Medienablage |
| Regeln des Hauses | `CLAUDE.md` |

**Eine Belegtabelle anlegen, bevor die erste Zeile Text im Film steht.** Jede
Aussage bekommt eine Quelle oder fliegt raus.

### Schritt 1 · Bildmaterial aufbereiten (Python/PIL)

Nicht per CSS zuschneiden, sondern **exportieren**:

- Zuschnitt auf 9:16 mit **bewusstem Fokuspunkt** (`fx`, `fy`), nicht mittig.
- Export **größer als die Leinwand** — 1242 × 2208 statt 1080 × 1920. Der
  Überschuss ist die Reserve für den Ken-Burns-Zoom; sonst wird das Bild bei
  8 % Zoom weich.
- Grading beim Export (siehe 1.4).
- Logo: Weißpunkt normalisieren, auf Inhalt trimmen, **Bestandteile über das
  Zeilenprofil trennen** statt über geschätzte Prozentwerte.

### Schritt 2 · Komposition nach Gerüst bauen

Reihenfolge, die Nacharbeit spart:

1. Safe-Area-Tokens setzen
2. Marken-Bug anlegen (liegt über allen Szenen, eigener Clip)
3. Szenen als Clips, Zeiten auf das Taktraster
4. Pro Szene: Bild → Verlauf → Text, Text immer in der sicheren Zone
5. Zeitleiste: Einläufe schnell, Standzeiten großzügig
6. Ton zuletzt, an die fertige Bewegung gebunden

### Schritt 3 · Prüfen, mit Bildern

`check` läuft nach **jeder** Änderung (Lint, Runtime, Layout, Motion,
Kontrast). Danach **immer** Schlüsselbilder ziehen und **ansehen** — der
Lint findet keine Dramaturgie.

Die Kontrollpunkte, die sich gelohnt haben:

- kurz **vor** und **nach** jedem Schnitt
- **mitten** in jeder Bewegung (sitzt die Kante? läuft sie richtig herum?)
- der Moment, in dem eine Szene **vollständig** ist (alle Zeilen da)

### Schritt 4 · Rendern und abnehmen

- `--fps 30 --quality delivery`
- **Posterframe bewusst wählen** und als Bild 0 einbacken — sonst greift jede
  Plattform ein beliebiges erstes Bild ab. Guter Poster: hell, Text vollständig
  eingelaufen, für sich allein postbar.
- **Abnahme am fertigen MP4**, nicht am Browser-Preview: Frames mit ffmpeg
  ziehen, Tonpegel messen, Streams prüfen.

---

## Teil 3 — Die Fallen

### 3.1 Umgebung

| Falle | Symptom | Lösung |
|---|---|---|
| **Uraltes ffmpeg** | Render bricht bei „Processing audio tracks" ab: `audio_processing_failed`, in der stderr `No such filter: 'adelay'` | Der Build auf diesem Rechner (`Python313/Scripts/`) ist von 2013; `adelay` kam 2014. Aktuelles ffmpeg nach `composition/.bin/` legen und **vor** dem Render in den PATH |
| **npm-Pakete als Ballast** | 416 MB `node_modules` für zwei Binärdateien | Binaries herauskopieren, Pakete entfernen, im LIESMICH dokumentieren |
| **ffmpeg schreibt nicht nach `/tmp`** | „No such file or directory" trotz erfolgreichem Aufruf | Git-Bash-Pfade sind für die Windows-Binary unsichtbar. Windows-Pfade verwenden |

### 3.2 HyperFrames / GSAP

| Falle | Meldung | Warum es zählt |
|---|---|---|
| Layout-Eigenschaften animieren | `gsap_non_transform_motion` | `letterSpacing`, `width` u. Ä. rasten beim Layout auf ganze Pixel — unter der Frame-für-Frame-Aufnahme stottert das sichtbar. Nur Transforms tweenen |
| Zwei `fromTo` auf dasselbe Element | `gsap_repeated_fromto_without_baseline` | GSAP wendet die `from`-Werte **beim Schreiben** an, nicht zur Tween-Zeit. Der zuletzt geschriebene gewinnt und wird zum Ruhezustand. Lösung: `tl.set(...)` bei 0 **oder** `immediateRender: false` — und für reine Fortsetzungen `to()` statt `fromTo()` |
| Element ist erst sichtbar, dann animiert | Kein Lint-Fehler, aber falsch im Bild | Ein Element, das erst später erscheinen soll, braucht einen **gesetzten Ruhezustand bei t=0**. Sonst steht das NACHHER-Label schon über dem Vorher-Bild |
| Überlappende Tweens | `overlapping_gsap_tweens` | Zwei Tweens auf derselben Eigenschaft im selben Zeitfenster. Eigenschaften trennen oder zeitlich entzerren |
| `.clip` setzt `inset: 0` | Bug füllt plötzlich das ganze Bild | Wer `class="clip"` an ein positioniertes Element hängt, muss `inset: auto; width: auto; height: auto` zurücknehmen |
| Audio ohne `id` | Render ist **stumm**, kein Fehler | Jedes `<audio>` braucht ein `id`, sonst greift der Mixer es nicht |
| `data-volume` + Volume-Tween | `audio_volume_tween_overrides_gain` | Tween-Werte **ersetzen** den Grundpegel, sie skalieren ihn nicht. Entweder `data-volume="1"` und der Tween trägt den Pegel, oder beide Werte gleich |
| SFX-Slot länger als die Datei | `clip_media_fit` | Slotlänge auf die echte Medienlänge setzen (`ffprobe`) |
| Benannte Schrift ohne `@font-face` | `font_family_without_font_face` | Schriften lokal mitliefern, `font-display: block`, Timeline erst nach `document.fonts.ready` bauen |

### 3.3 Gestaltung

| Falle | Woran man sie merkt | Gegenmittel |
|---|---|---|
| **Logo kommt zu spät** | Fällt niemandem auf — das ist das Problem | Marken-Bug ab Sekunde 0 |
| **Text in der verdeckten Zone** | Im Schnittprogramm perfekt, auf dem Handy halb weg | Safe-Area-Tokens von Anfang an |
| **Reveal zu früh** | Das Vorher-Bild „kam gar nicht vor" | Dem Problem 1,2–1,5 s geben, bevor die Auflösung startet |
| **Beschriftung auf der falschen Hälfte** | „VORHER" steht über dem bereits leeren Raum | Label wechselt an **einer** Stelle, getaktet auf die Kante |
| **Verlauf frisst das Bild** | Der helle Payoff wirkt dunkel, das Foto verschwindet im Weiß | Verlauf später einsetzen lassen, Deckkraft senken; am Schlüsselbild prüfen, nicht im Code |
| **Nichtssagendes Foto** | Ein leerer, gekachelter Raum sagt nichts über die Leistung | Zum Listenpunkt „Wir räumen" gehört ein **volles** Zimmer, kein leeres |
| **Zu viel Text pro Szene** | Man muss pausieren, um mitzukommen | Lesezeit ausrechnen, dann kürzen — nie beschleunigen |
| **Fremdmarken im Bild** | Ein Werbebeutel als heimlicher Gast | Ausschnitt verschieben oder abdunkeln; ganz vermeiden lässt es sich bei echtem Material selten |
| **Deko im Text** | Ein Strich oder Punkt sitzt mitten im Wort | Texthöhe ausrechnen (Zeilen × font-size × line-height), 30 px Abstand addieren. Kein Linter findet das |
| **Vorher/Nachher aus zwei Räumen** | Sieht gut aus, überzeugt aber nicht | Im CMS nach `bild_vor`/`bild_nach` suchen, notfalls die Live-Galerie abrufen |
| **Zu stark hochgerechnetes Bild** | Wand wirkt wachsartig, Kanten flau | Lanczos, dann Unsharp, Gamma auf die Tiefen, Zoom auf ≤3 % reduzieren |
| **Umlaute abgeschnitten** | Aus „RÜMPELWERK" wird „RUMPELWERK" | Beim Freistellen von Schriftbestandteilen die Punkte über den Buchstaben mitnehmen — **Zeilenprofil auswerten**, nicht schätzen |

### 3.4 Recht und Wahrheit

- **Musiklizenz vor jeder bezahlten Auslieferung klären.** Beispiel-Assets aus
  einem Skill sind für Entwürfe da; ihre Lizenz ist oft ausdrücklich ungeprüft.
- **Keine Spitzenstellungsbehauptung** ohne Beleg (§ 5 UWG) — „Nr. 1", „der
  beste", „der günstigste".
- **Keine Zusage, die der Betrieb nicht gibt.** Beispiel aus diesem Projekt:
  „sofortige Besichtigung" gegen einen tatsächlichen Vorlauf von 24–48 Stunden.
- **Keine Preiszahl aus dem Rechner als Werbepreis.** Mindestpauschalen sind
  keine beworbenen Ab-Preise.
- **Kein Werkzeug prüft ein Video.** Auf der Website fängt `check_seo` falsche
  Zahlen ab. Im Video und im Werbekonto gibt es das nicht — nur die Belegtabelle
  und der Mensch, der sie führt.

---

## Teil 4 — Was davon in den Skill gehört

**Als feste Regeln (nicht verhandelbar):**
- Safe-Area-Tokens für jedes Zielformat
- Marken-Bug ab Sekunde 0
- Belegtabelle vor dem ersten Text
- Schnitte auf das Taktraster, Text auf jeden zweiten Beat
- Lesezeit-Untergrenzen
- End-Card mit genau einem CTA, mindestens 4,5 s
- `check` nach jeder Änderung, Schlüsselbilder ansehen, Abnahme am MP4

**Als Bausteine (wiederverwendbar):**
- Bildaufbereitung mit Fokuspunkt, Übergröße und Grading (Python/PIL)
- Logo-Zerlegung über das Zeilenprofil → Lockup, Symbol, Vollmarke
- Wischkante als Vorher/Nachher-Baustein
- Zähler (seek-sicher über ein getweentes Objekt)
- Marken-Bug, Akzentstrich, Markenfuß
- End-Card-Bauplan

**Als Fragen an den Nutzer (Intake):**
- Zielplattform → Format und Safe Zones
- Gibt es Vorher/Nachher-Material? → Formatwahl
- Gibt es ein Gesicht und ist es belegt? → Connection-Szene ja/nein
- Was ist die eine Handlung? → CTA
- Musik: eigene Lizenz vorhanden?

**Als Prüfliste vor der Auslieferung:**
1. `check` grün, Kontrast bestanden
2. Alle Texte innerhalb der sicheren Zone
3. Marke ab Sekunde 0 sichtbar
4. Jede Zahl in der Belegtabelle
5. Tonspur vorhanden, Pegel gemessen
6. Posterframe gewählt und eingebacken
7. Abnahme-Frames aus dem MP4 gesichtet
8. Kein Dekoelement ragt in einen Textblock (am Standbild geprüft)
9. Vorher/Nachher zeigt denselben Raum
10. Musiklizenz geklärt

---

## Quellen

- [Google Ads-Hilfe: Über die ABCDs wirksamer Videoanzeigen](https://support.google.com/google-ads/answer/14783551?hl=en)
- [PPC Land: Mastering YouTube advertising with the ABCD framework](https://ppc.land/mastering-youtube-advertising-with-the-abcd-framework/)
- [PPC Land: Google Cloud unveils ABCDs detector](https://ppc.land/google-cloud-unveils-abcds-detector-to-automate-youtube-ad-assessment/)
- [Kreatli: Safe Zone Hub 2026 — Reels, TikTok, Shorts](https://kreatli.com/guides/safe-zone-guide)
- [CreaMate: TikTok Safe Zone 2026](https://creamate.ai/en/blog/tiktok-safe-zone-guide)
- [Ignite Social Media: Safe Zones für TikTok und Reels](https://www.ignitesocialmedia.com/content-creation/what-are-the-safe-zones-for-tiktoks-and-instagram-reels/)
- [GetHookd: Before and After Facebook Ads — Examples & Tips](https://www.gethookd.ai/learn/before-and-after-facebook-ads-examples-tips/)
- [Graphed: Facebook Ads for Junk Removal — 2026 Strategy Guide](https://www.graphed.com/blog/facebook-ads-for-junk-removal)
- [Craftsman+: Why End Cards are a Winning Strategy](https://craftsmanplus.com/blog/why-end-cards-are-a-winning-strategy-for-your-digital-ads)
- [Sovran: Direct Response Video Ad Endings That Convert (2026)](https://sovran.ai/blog/direct-response-video-ad-endings)
- [AppSamurai: Tips To Make Amazing End Cards For Mobile Video Ads](https://appsamurai.com/blog/tips-to-make-amazing-end-cards-for-mobile-video-ads/)
- Projektintern: `CLAUDE.md` (Regeln 1, 2, 15, 23, 24), `apps/core/data/*.py`,
  `static/css/ruempelwerk.css`, `templates/ueber-uns.html`
- Werkzeuge: HyperFrames-Skills (`hyperframes-core`, `brag`), Kenney-SFX (CC0)
