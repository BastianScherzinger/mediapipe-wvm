# API-Befund — live geprüft am 03.08.2026

Alles hier Dokumentierte wurde mit echten Aufrufen ermittelt, nicht aus Dokumentation
abgeschrieben. Grundlage für `app/higgsfield.py` und `app/llm/`.

> **Achtung — das kostete zwei Kundenläufe:** Alles in diesem Dokument gilt
> **ausschließlich für die Platform-API** (`platform.higgsfield.ai`). Der MCP-Dienst des
> Web-Abos (`mcp.higgsfield.ai`) spricht an mehreren Stellen anders. Zweimal ist genau
> diese Übertragung schiefgegangen:
>
> | Feld | Platform-API (hier dokumentiert) | MCP-Dienst (Abo-Weg) |
> |---|---|---|
> | Modell | Pfade wie `higgsfield-ai/soul/standard` | kurze Kennungen ohne Schrägstrich; ein Pfad ergibt `unknown model` |
> | Startbild | `image_url` mit einer HTTPS-Adresse | **nur** Kennungen in `params.medias` (Medium oder fertiger Auftrag) |
>
> Beide Male war das Startbild zu diesem Zeitpunkt schon erzeugt und **bezahlt**.
> `higgsfield_mcp` übersetzt deshalb beides, bevor etwas hinausgeht
> (`modell_aufloesen()`, `medienkennung()`). Einzelheiten:
> [`BEFUND_2026-08-26.md`](BEFUND_2026-08-26.md) und
> [`BEFUND_2026-09-05.md`](BEFUND_2026-09-05.md).
>
> **Die MCP-Seite ließ sich hier nicht nachmessen:** `mcp.higgsfield.ai` beantwortet
> ohne Anmeldung jede Anfrage mit `401`, auch `tools/list`. Sie ist das einzige in
> diesem Projekt, das nicht live geprüft ist — abgesichert wird das durch
> Laufzeitabfragen (`models_explore`, `tools/list`) und dadurch, dass beide plausiblen
> Formen probiert werden, nicht durch eine Annahme.
>
> **Regel daraus:** Kein Feld aus diesem Dokument ungeprüft in `higgsfield_mcp.py`
> übernehmen. Was für die Platform-API belegt ist, ist für den Abo-Weg nur eine
> Vermutung.

---

## 1. Zugänge — Ist-Zustand

| Zugang | Ergebnis | Bewertung |
|---|---|---|
| Higgsfield Platform-API-Key (`ID:SECRET`, aus jarvis2) | Auth **gültig** (`GET /v1/motions` → 200), Auftrag → **403 `not_enough_credits`** | Key funktioniert, Credit-Topf leer |
| Higgsfield MCP/Abo (`mcp.higgsfield.ai`) | OAuth-Discovery **erreichbar**, alle Endpunkte vorhanden | Nutzbar nach einmaligem Browser-Login |
| Anthropic-Schlüssel aus jarvis2 | **400** – „credit balance is too low" | gültig, aber ohne Guthaben |
| Anthropic-Schlüssel aus `DjangoTeamApp\.env` | **funktioniert** | jetzt in der `.env` hinterlegt |
| Claude-Abo-Token aus `livingen\.env` (`sk-ant-oat01-…`) | **funktioniert** über die CLI | jetzt als `CLAUDE_CODE_OAUTH_TOKEN` hinterlegt |
| Claude-CLI mit der Anmeldung dieses Rechners | **funktioniert** | greift, wenn kein Token gesetzt ist |
| Ollama lokal | **läuft** — `qwen2.5:7b`, `qwen2.5:3b`, `qwen2.5-coder:7b/1.5b` | Offline-Rückfallebene sofort bereit |
| ffmpeg | System `N-55702` **und** `imageio-ffmpeg` 7.1 | siehe Warnung unten |
| pywebview | 6.2.1 installiert | Desktop-Fenster möglich |

**Vollständige Suche nach Zugängen (03.08.2026).** Der gesamte Benutzerordner wurde nach
Schlüsselmustern durchsucht und jeder Fund einzeln gegen den echten Dienst geprüft:

* **Sechs verschiedene Anthropic-Zugänge** gefunden — zwei API-Schlüssel (einer mit,
  einer ohne Guthaben), zwei Zugriffstoken (beide funktionsfähig), ein Erneuerungstoken
  und ein Testwert aus der eigenen Testsuite.
* **Genau ein Higgsfield-Schlüssel**, in drei Dateien identisch (`jarvis2\.env`,
  `~\.claude\.env`, hier). Gegen **alle sechs** bekannten Modellpfade geprüft — jedes Mal
  `403 not_enough_credits`. Einen zweiten Higgsfield-Zugang gibt es auf diesem Rechner
  nicht, und es liegt auch kein MCP-Anmeldezwischenspeicher vor.

Die Videoerzeugung hängt damit allein an der Guthabenfrage, nicht an einem fehlenden
oder falschen Schlüssel.

> **Achtung, ffmpeg:** Im Suchpfad lag ein Programm namens `ffmpeg.EXE`, das die Option
> `-hide_banner` nicht kennt und jeden Aufruf mit „Option not found“ abbricht. Das
> Programm prüft deshalb jeden Kandidaten mit einem Probeaufruf, bevor es ihn benutzt,
> und landet hier beim mitgelieferten `imageio-ffmpeg` 7.1.

> **Wichtig für die Übergabe:** Higgsfield trennt zwei getrennte Guthaben —
> das Web-Abo (Soul/Plus auf higgsfield.ai, per Jahresabo bezahlt) und die
> Platform-API-Credits (platform.higgsfield.ai). Ein Jahresabo füllt den API-Topf **nicht**.
> Entweder API-Credits aufladen oder den MCP/Abo-Weg nutzen.

---

## 2. Higgsfield Platform-API — verifiziertes Verhalten

**Basis:** `https://platform.higgsfield.ai`

**Authentifizierung** (beide Varianten akzeptiert, `Bearer` wird mit 401 abgelehnt):
```
Authorization: Key <KEY_ID>:<KEY_SECRET>
```
```
hf-api-key: <KEY_ID>
hf-secret:  <KEY_SECRET>
```

**Ablauf:**
```
POST /{modell-pfad}          → 200 {"request_id": "...", "status": "queued", ...}
GET  /requests/{id}/status   → {"status": "...", ...Medien-URLs bei completed}
POST /requests/{id}/cancel   → 202, nur solange "queued"
GET  /health                 → 204   (für Erreichbarkeitsprüfung)
GET  /v1/motions             → 200   Liste der Kamerabewegungen mit UUID + Beschreibung
```

**Statuswerte:** `queued` · `in_progress` · `completed` · `failed` · `nsfw`
(bei `failed` und `nsfw` werden Credits erstattet)

**Fehlercodes, beobachtet:**

| Code | Bedeutung |
|---|---|
| 400 | Schema-Verstoß beim JSON-Schema-Validator (z. B. `duration: 999 is not one of [5, 10]`) |
| 403 | `not_enough_credits` — Auth in Ordnung, Guthaben leer |
| 404 | `model_not_found` — Modellpfad existiert nicht |
| 405 | Unbekannter GET-Pfad (jeder Pfad ist ein POST-Auftragsendpunkt, daher nie 404 bei GET) |
| 422 | Pydantic-Validierung mit vollständiger Feldliste — sehr nützlich zur Schema-Erkundung |
| 423 | `model_blocked` — Modell für diesen Zugang gesperrt (z. B. `reve/text-to-image`) |

**Kein Endpunkt für den Credit-Stand.** Der Stand lässt sich nur indirekt ermitteln
(403 bei Auftrag). Das Tool bildet das als Zustand „Guthaben erschöpft" ab.

---

## 3. Modellkatalog — geprüft, welche Pfade existieren

**Gilt für die Platform-API.** Für den Abo-Weg siehe den Kasten ganz oben.

### Bild aus Text
| Pfad | Pflichtfelder | Optionen |
|---|---|---|
| `higgsfield-ai/soul/standard` | `prompt` | `aspect_ratio` = 9:16 · 16:9 · 4:3 · 3:4 · 1:1 · 2:3 · 3:2 · `resolution` = 720p · 1080p · `enhance_prompt` bool · `seed` ≥ 1 |
| `higgsfield-ai/soul/turbo/{mode}` | `prompt` | zusätzlich `mode` im Pfad = `standard` · `reference` · `character` |
| `higgsfield-ai/soul/lite/{mode}` | `prompt` | wie oben |
| `reve/text-to-image` | — | **423 gesperrt** |

### Video aus Bild
| Pfad | Pflichtfelder | Dauer |
|---|---|---|
| `higgsfield-ai/dop/lite` · `/standard` · `/turbo` | `prompt`, `image_url` | `motions` = Liste von **Objekten** (IDs aus `/v1/motions`), `seed`, `enhance_prompt` |
| `higgsfield-ai/dop/{stufe}/first-last-frame` | `prompt`, `image_url` | Start- und Endbild |
| `kling-video/v2.1/pro` · `/master` · `/standard` `/image-to-video` | `prompt`, `image_url` | **5 oder 10 s** |
| `kling-video/v2.6/pro/image-to-video` | `prompt`, `image_url` | **5 oder 10 s** — neueste Version |
| `minimax/hailuo-02/pro/image-to-video` | `prompt`, `image_url` | **6 s** |

### Video direkt aus Text
| Pfad | Dauer |
|---|---|
| `minimax/hailuo-02/pro/text-to-video` | **6 s** |
| `minimax/hailuo-02/standard/text-to-video` | **6 oder 10 s** |

### Nicht vorhanden (404)
`bytedance/seedance/*` · `google/veo3/*` · `kling-video/v2.5/*` · `kling-video/*/text-to-video` ·
`wan/*` · `higgsfield-ai/text-to-video`

> Der in jarvis2 verwendete Pfad `/v1/generations` mit `dop-lite` ist **veraltet** — daher
> die damaligen 404. Wird nicht übernommen.

**Folge für die Videolänge:** Ein Auftrag liefert maximal 10 s. Alles darüber entsteht
zwingend durch Montage mehrerer Szenen — der Storyboard-Modus ist damit keine Spielerei,
sondern technische Notwendigkeit.

---

## 4. Erkundungstechnik (für spätere Wartung)

Das Schema eines Modells lässt sich **ohne Credit-Verbrauch** ermitteln:

1. `POST /{modell}` mit leerem Body `{}` → 422 listet alle Pflichtfelder auf
2. `POST` mit absichtlich ungültigen Werten (`duration: 999`, `aspect_ratio: "99:1"`) →
   die Fehlermeldung nennt **alle erlaubten Werte**

Beide Varianten erzeugen keinen Auftrag. So bleibt der Modellkatalog wartbar, wenn
Higgsfield neue Modelle veröffentlicht.

---

## 5. Konsequenz für die Architektur

Zwei Anbieterketten mit automatischem Durchreichen — jede Stufe wird beim Start geprüft
und im Dashboard sichtbar gemacht:

**Sprachmodell (Prompt-Schmiede)**
```
1. Claude-CLI (Abo)      ✓ funktioniert heute
2. Anthropic API-Key     ⏳ greift automatisch, sobald Guthaben vorhanden
3. Ollama lokal          ✓ läuft, offline, kostenlos
```

**Videoerzeugung**
```
1. Platform-API-Key      ⏳ eingebaut, greift sobald API-Credits vorhanden
2. MCP/Abo-Login         ✓ Weg vorhanden, ein Browser-Klick nötig
3. Probelauf-Modus       ✓ vollständige Kette ohne Credits (Demo/Test)
```

Kein Weg ist fest verdrahtet: Fällt eine Stufe aus, rückt die nächste nach, und die
Oberfläche sagt in einem Satz, welcher Weg gerade aktiv ist und warum.
