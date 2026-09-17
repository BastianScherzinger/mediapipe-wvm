"""
bragagent.py — Claude als Werkzeugbenutzer, nicht nur als Texter.

Der Unterschied zu `llm/claude_cli.py`: Dort schreibt Claude **Text**, hier **baut** Claude
etwas. Für einen Premium-Film muss Claude Dateien anlegen, `hyperframes check` laufen
lassen, Einzelbilder ansehen und rendern — also mit Werkzeugen arbeiten. Das kann nur die
Claude-Code-CLI im Agentenmodus (`-p` mit Werkzeugfreigabe).

Drei Dinge regelt dieses Modul, und nichts sonst:

1. **Werkzeuge bereitstellen.** Der `/brag`-Skill und die Hyperframes-Skills müssen auf
   dem Rechner liegen, sonst weiß Claude nichts von ihnen. Beides wird einmalig geholt
   und danach nur noch geprüft — auf dem Rechner des Kunden genauso wie hier.

2. **Den Lauf führen.** Prompt hinein, Ereignisstrom heraus: Jeder Werkzeugaufruf wird
   gemeldet, damit im Logbuch steht, was gerade passiert. Ein Lauf dauert Minuten; ohne
   diese Meldungen säße man vor einem stummen Fenster.

3. **Abrechnen.** Die CLI meldet am Ende Tokens und Listenpreis. Beides wird
   weitergereicht und landet beim Video — die Frage „was hat das gekostet?“ soll nicht
   geschätzt werden müssen.

**Zur Freigabe der Werkzeuge — bewusst so, mit offenen Karten:** Der Lauf läuft mit
`--permission-mode bypassPermissions`. Ein nicht-interaktiver Lauf bliebe sonst an der
ersten Rückfrage stehen, und ohne die Shell gäbe es kein Video: `npx hyperframes check`
und `npx hyperframes render` sind der Kern der Arbeit. Das heißt aber auch: **Während
eines Laufs kann Claude auf diesem Rechner Befehle ausführen.** Wer das nicht will, darf
den Bereich nicht benutzen.

Eingegrenzt wird, was sich sinnvoll eingrenzen lässt:

* **Arbeitsverzeichnis** — der Auftragsordner unter `output/`; nur er ist über
  `--add-dir` freigegeben, und der Auftragstext sagt ausdrücklich, dass nichts
  außerhalb geändert wird.
* **Netzsuche und Netzabruf** sind abgeschaltet (`WebSearch`, `WebFetch`).
* **Fremde Zugangsdaten sieht der Lauf nicht** (`_ohne_geheimnisse`): Higgsfield-Schlüssel,
  Zahlungs- und Cloud-Zugänge werden aus der Umgebung entfernt. Übrig bleibt das
  Claude-Token, mit dem sich die CLI anmeldet.

Eine echte Sandbox (Container, Windows-Sandbox) wäre die saubere Lösung; sie setzt aber
auf dem Rechner eines Kunden mehr voraus, als hier vorausgesetzt werden darf. Solange es
sie nicht gibt, ist die Grenze das Arbeitsverzeichnis plus diese Notiz.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config, errors, logbook

QUELLE = "Filmagent"
ANZEIGENAME = "Claude (Agent)"

#: Wohin die geholten Werkzeuge gelegt werden.
_WERKZEUGE = config.DATA_DIR / "werkzeuge"

#: Der `/brag`-Skill — MIT-Lizenz, Quelle wird beim Holen mitgeschrieben.
_BRAG_REPO = "https://github.com/latent-spaces/brag.git"

#: Skills, die Claude für den Bau braucht. Ohne sie entstünde irgendein HTML,
#: aber keine renderbare Komposition.
_HYPERFRAMES_SKILLS = ("hyperframes-core", "hyperframes-animation", "hyperframes-creative",
                       "hyperframes-cli", "hyperframes-keyframes")


def _skillordner() -> Path:
    """Wo die Claude-CLI nach Skills sucht: der Ordner des angemeldeten Benutzers."""
    return Path.home() / ".claude" / "skills"


# ── Bereitschaft ─────────────────────────────────────────────────────────────

def node_vorhanden() -> tuple[bool, str]:
    """Node ist die Laufzeit von Hyperframes. Ohne sie gibt es kein Video."""
    pfad = shutil.which("node")
    if not pfad:
        return False, "Node.js nicht gefunden (nodejs.org, Fassung 22 oder neuer)"
    try:
        lauf = subprocess.run([pfad, "--version"], capture_output=True, text=True,
                              timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False, "Node.js ließ sich nicht starten"
    fassung = (lauf.stdout or "").strip().lstrip("v")
    haupt = int(fassung.split(".")[0]) if fassung[:1].isdigit() else 0
    if haupt and haupt < 22:
        return False, f"Node.js {fassung} ist zu alt — gebraucht wird 22 oder neuer"
    return True, fassung


def bereit() -> tuple[bool, str]:
    """Kann ein Premium-Film gebaut werden? Der erste Satz, der im Weg steht, gewinnt."""
    if not config.claude_cli_pfad():
        return False, "Claude-CLI nicht gefunden (npm i -g @anthropic-ai/claude-code)"
    gut, grund = node_vorhanden()
    if not gut:
        return False, grund
    if not config.ffmpeg_pfad():
        return False, "kein brauchbares ffmpeg gefunden"
    return True, ""


def befund() -> dict:
    """Für die Statuslampe in der Oberfläche."""
    gut, grund = bereit()
    node_gut, node_text = node_vorhanden()
    return {
        "bereit": gut,
        "grund": grund,
        "claude_cli": bool(config.claude_cli_pfad()),
        "node": node_text if node_gut else "",
        "ffmpeg": bool(config.ffmpeg_pfad()),
        "brag_skill": (_skillordner() / "brag" / "SKILL.md").exists(),
        "hyperframes_skills": all((_skillordner() / name / "SKILL.md").exists()
                                  for name in _HYPERFRAMES_SKILLS),
        "modell": config.BRAG_MODEL,
    }


# ── Werkzeuge bereitstellen ──────────────────────────────────────────────────

def _lauf(befehl: list[str], *, zeitlimit: int, cwd: "Path | None" = None) -> tuple[int, str]:
    try:
        ergebnis = subprocess.run(befehl, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=zeitlimit,
                                  cwd=str(cwd) if cwd else None)
    except subprocess.TimeoutExpired:
        return -1, f"Zeitüberschreitung nach {zeitlimit} s"
    except OSError as fehler:
        return -2, str(fehler)
    return ergebnis.returncode, ((ergebnis.stdout or "") + (ergebnis.stderr or ""))[-1500:]


def _brag_skill_holen(melden=None) -> None:
    """Holt den `/brag`-Skill und legt ihn in den Skillordner des Benutzers.

    Zwei Wege, in dieser Reihenfolge: Liegt der Skill schon irgendwo auf diesem Rechner
    (etwa weil hier damit gearbeitet wurde), wird kopiert. Sonst wird das Repository
    geholt — flach, es geht nur um den Inhalt, nicht um seine Geschichte.
    """
    ziel = _skillordner() / "brag"
    if (ziel / "SKILL.md").exists():
        return
    ziel.parent.mkdir(parents=True, exist_ok=True)

    repo = _WERKZEUGE / "brag-repo"
    quelle = repo / "skills" / "brag"
    if not (quelle / "SKILL.md").exists():
        if melden:
            melden("Der /brag-Skill wird geholt (einmalig, etwa 20 MB) …")
        repo.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(repo, ignore_errors=True)
        code, ausgabe = _lauf(["git", "clone", "--depth", "1", _BRAG_REPO, str(repo)],
                              zeitlimit=300)
        if code != 0 or not (quelle / "SKILL.md").exists():
            raise errors.KonfigurationsFehler(
                "Der /brag-Skill ließ sich nicht holen.",
                f"git meldet: {config.entschaerfe(ausgabe[:300])}. Er lässt sich auch von "
                f"Hand holen: git clone {_BRAG_REPO} — danach den Ordner skills/brag "
                f"nach {ziel} kopieren.", ursprung=QUELLE)

    shutil.copytree(quelle, ziel, dirs_exist_ok=True)
    for zettel in ("LICENSE", "README.md"):
        if (repo / zettel).exists():
            shutil.copy2(repo / zettel, ziel / f"HERKUNFT_{zettel}")
    logbook.erfolg(QUELLE, f"/brag-Skill eingerichtet: {ziel}")


def _hyperframes_skills_holen(melden=None) -> None:
    """Installiert die Hyperframes-Skills über deren eigenes Werkzeug."""
    fehlend = [name for name in _HYPERFRAMES_SKILLS
               if not (_skillordner() / name / "SKILL.md").exists()]
    if not fehlend:
        return
    if melden:
        melden("Die Hyperframes-Skills werden geholt (einmalig) …")
    code, ausgabe = _lauf(["npx", "-y", f"hyperframes@{config.HYPERFRAMES_VERSION}",
                           "skills"], zeitlimit=900)
    noch_fehlend = [name for name in _HYPERFRAMES_SKILLS
                    if not (_skillordner() / name / "SKILL.md").exists()]
    if noch_fehlend:
        raise errors.KonfigurationsFehler(
            "Die Hyperframes-Skills ließen sich nicht einrichten.",
            f"Der Befehl „npx hyperframes skills“ meldet: "
            f"{config.entschaerfe(ausgabe[:300]) or 'keine Ausgabe'} "
            f"(Rückgabewert {code}). Er lässt sich auch von Hand im Terminal ausführen.",
            ursprung=QUELLE)
    logbook.erfolg(QUELLE, f"Hyperframes-Skills eingerichtet ({len(fehlend)} Stück).")


def werkzeuge_sichern(melden=None) -> None:
    """Stellt sicher, dass Claude alles vorfindet, was es für den Bau braucht.

    Läuft bei jedem Auftrag, tut aber nach dem ersten Mal nichts mehr — die Prüfung ist
    ein Dateizugriff.
    """
    gut, grund = bereit()
    if not gut:
        raise errors.KonfigurationsFehler(
            "Für einen Premium-Film fehlt eine Voraussetzung.", grund, ursprung=QUELLE)
    _brag_skill_holen(melden)
    _hyperframes_skills_holen(melden)


# ── ffmpeg für die Laufzeit bereitlegen ──────────────────────────────────────

def _binordner() -> Path:
    """Ein Ordner mit `ffmpeg.exe` (und `ffprobe`, falls vorhanden), der dem Agenten
    vorangestellt wird.

    Grund: Hyperframes ruft schlicht `ffmpeg` auf. Auf diesem Rechner lag im Suchpfad
    eine Fassung von 2013, an der der Tonmix scheiterte — sichtbar erst nach zwei
    Minuten Rendern. Das mitgelieferte ffmpeg ist neu; es muss nur unter dem Namen
    stehen, unter dem es gesucht wird.
    """
    ordner = _WERKZEUGE / "bin"
    ordner.mkdir(parents=True, exist_ok=True)
    endung = ".exe" if os.name == "nt" else ""
    ziel = ordner / f"ffmpeg{endung}"
    quelle = config.ffmpeg_pfad()
    if quelle and (not ziel.exists()
                   or Path(quelle).stat().st_mtime > ziel.stat().st_mtime):
        try:
            if Path(quelle).resolve() != ziel.resolve():
                shutil.copy2(quelle, ziel)
        except OSError as fehler:
            logbook.warnung(QUELLE, f"ffmpeg ließ sich nicht bereitlegen: {fehler}")
    probe = shutil.which("ffprobe")
    probe_ziel = ordner / f"ffprobe{endung}"
    if probe and not probe_ziel.exists():
        try:
            shutil.copy2(probe, probe_ziel)
        except OSError:
            pass
    return ordner


# ── Der Lauf ─────────────────────────────────────────────────────────────────

#: Was der Agent nicht zu sehen braucht. Er baut einen Film aus Dateien im
#: Auftragsordner — mit dem Higgsfield-Schlüssel oder einem Zahlungszugang hat das
#: nichts zu tun. Was ein Prozess nicht kennt, kann er auch nicht versehentlich in eine
#: Datei, ein Protokoll oder einen Netzaufruf schreiben.
_GEHEIM = ("HIGGSFIELD", "OPENAI", "AWS_", "GOOGLE_", "GCP_", "AZURE", "STRIPE",
           "PAYPAL", "SECRET", "PASSWORD", "PASSWD")


def _ohne_geheimnisse(umgebung: dict) -> dict:
    """Räumt fremde Zugangsdaten aus der Umgebung des Agenten.

    Die eine Ausnahme ist `CLAUDE_CODE_OAUTH_TOKEN`: Damit meldet sich die CLI an, es
    ist der Zugang, den sie benutzen soll. Alles andere fliegt raus.
    """
    return {name: wert for name, wert in umgebung.items()
            if name == "CLAUDE_CODE_OAUTH_TOKEN"
            or not any(teil in name.upper() for teil in _GEHEIM)}


@dataclass
class Lauf:
    """Was ein Agentenlauf hinterlässt."""
    text: str = ""
    modell: str = ""
    turns: int = 0
    dauer: float = 0.0
    kosten_usd: float = 0.0
    tokens: dict = field(default_factory=dict)
    werkzeuge: dict = field(default_factory=dict)
    sitzung: str = ""

    @property
    def tokens_gesamt(self) -> int:
        return int(sum(self.tokens.get(k, 0) for k in
                       ("eingabe", "ausgabe", "cache_neu", "cache_gelesen")))

    def als_dict(self) -> dict:
        return {"modell": self.modell, "turns": self.turns, "dauer": round(self.dauer),
                "kosten_usd": round(self.kosten_usd, 4), "tokens": dict(self.tokens),
                "tokens_gesamt": self.tokens_gesamt,
                "werkzeuge": dict(self.werkzeuge), "sitzung": self.sitzung}


def _tokens_aus(nutzung: dict) -> dict:
    return {
        "eingabe": int(nutzung.get("input_tokens") or 0),
        "ausgabe": int(nutzung.get("output_tokens") or 0),
        "cache_neu": int(nutzung.get("cache_creation_input_tokens") or 0),
        "cache_gelesen": int(nutzung.get("cache_read_input_tokens") or 0),
    }


def _kurzfassung(block: dict) -> str:
    """Eine Zeile fürs Logbuch aus einem Werkzeugaufruf — ohne Romane."""
    name = block.get("name") or "Werkzeug"
    eingabe = block.get("input") or {}
    if name == "Bash":
        # Das vorangestellte `cd "<langer Pfad>"` fliegt raus: Es füllte die ganze Zeile,
        # und im Logbuch stand dann dreimal derselbe Pfad statt dessen, was getan wird.
        # (Nebenwirkung, die es zu beheben galt: Die Anzeige sprang nicht auf „Rendern“,
        # weil das Wort hinter dem Pfad abgeschnitten wurde.)
        befehl = re.sub(r'^\s*cd\s+("[^"]*"|\S+)\s*(;|&&)\s*', "",
                        str(eingabe.get("command") or ""))
        return f"Bash: {befehl[:110]}"
    for feld in ("file_path", "path", "pattern", "skill", "prompt", "description"):
        if eingabe.get(feld):
            return f"{name}: {str(eingabe[feld])[:110]}"
    return name


def lauf(arbeitsordner: Path, prompt: str, *, modell: str = "", zeitlimit: int = 0,
         abbruch: "threading.Event | None" = None, melden=None) -> Lauf:
    """Führt einen Agentenlauf im Arbeitsordner aus.

    `melden(text, art)` bekommt jede Regung des Agenten — Werkzeugaufrufe, Zwischentexte.
    Zurück kommt der Schlusstext samt Abrechnung. Ein Abbruchwunsch beendet den Lauf
    innerhalb einer Sekunde; angefangene Dateien bleiben liegen, damit ein zweiter
    Anlauf darauf aufbauen kann.
    """
    pfad = config.claude_cli_pfad()
    if not pfad:
        raise errors.KonfigurationsFehler(
            "Die Claude-CLI ist nicht installiert.",
            "npm i -g @anthropic-ai/claude-code — danach das Programm neu starten.",
            ursprung=QUELLE)

    arbeitsordner = Path(arbeitsordner)
    arbeitsordner.mkdir(parents=True, exist_ok=True)
    modell = modell or config.BRAG_MODEL
    zeitlimit = zeitlimit or config.BRAG_ZEITLIMIT

    from .llm import claude_cli
    umgebung = _ohne_geheimnisse(claude_cli.umgebung())
    umgebung["PATH"] = str(_binordner()) + os.pathsep + umgebung.get("PATH", "")
    # Hyperframes schreibt seinen Zwischenspeicher sonst neben das Projekt; im
    # Auftragsordner hat er nichts verloren.
    umgebung.setdefault("HYPERFRAMES_TELEMETRY", "0")

    befehl = [pfad, "-p", "--output-format", "stream-json", "--verbose",
              "--permission-mode", "bypassPermissions",
              "--disallowedTools", "WebSearch", "WebFetch",
              "--add-dir", str(arbeitsordner)]
    if modell:
        befehl += ["--model", modell]

    ergebnis = Lauf(modell=modell)
    begonnen = time.monotonic()
    logbook.info(QUELLE, f"Agentenlauf beginnt ({modell}), Arbeitsordner "
                         f"{arbeitsordner.name}.")

    try:
        prozess = subprocess.Popen(
            befehl, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            bufsize=1, cwd=str(arbeitsordner), env=umgebung)
    except OSError as fehler:
        raise errors.KonfigurationsFehler(
            "Die Claude-CLI ließ sich nicht starten.", f"Systemmeldung: {fehler}",
            ursprung=QUELLE) from fehler

    fehlertext: list[str] = []

    def stderr_lesen() -> None:
        for zeile in prozess.stderr or []:
            if zeile.strip():
                fehlertext.append(zeile.strip())
    faden = threading.Thread(target=stderr_lesen, daemon=True)
    faden.start()

    try:
        prozess.stdin.write(prompt)
        prozess.stdin.close()
    except OSError:
        pass

    abgebrochen = False
    try:
        for zeile in prozess.stdout or []:
            if abbruch is not None and abbruch.is_set():
                abgebrochen = True
                break
            if time.monotonic() - begonnen > zeitlimit:
                abgebrochen = True
                fehlertext.append(f"Zeitlimit von {zeitlimit} s überschritten")
                break
            zeile = zeile.strip()
            if not zeile or not zeile.startswith("{"):
                continue
            try:
                satz = json.loads(zeile)
            except ValueError:
                continue
            _satz_verarbeiten(satz, ergebnis, melden)
    finally:
        if prozess.poll() is None:
            prozess.terminate()
            try:
                prozess.wait(timeout=20)
            except subprocess.TimeoutExpired:
                prozess.kill()

    ergebnis.dauer = time.monotonic() - begonnen

    if abgebrochen:
        if abbruch is not None and abbruch.is_set():
            raise errors.AbbruchFehler("Abgebrochen.", ursprung=QUELLE)
        raise errors.ZeitFehler(
            f"Der Filmbau hat das Zeitlimit von {zeitlimit // 60} Minuten überschritten.",
            "Ein kürzeres Video oder weniger Material hilft. Der angefangene Stand liegt "
            "im Auftragsordner.", ursprung=QUELLE)

    if not ergebnis.text and prozess.returncode not in (0, None):
        meldung = config.entschaerfe(" ".join(fehlertext)[-400:])
        if any(wort in meldung.lower() for wort in
               ("login", "unauthorized", "oauth", "401", "expired")):
            raise errors.ZugangFehler(
                "Die Claude-CLI ist nicht angemeldet.",
                "Einmal „claude login“ im Terminal ausführen — oder ein gültiges "
                "CLAUDE_CODE_OAUTH_TOKEN in die .env eintragen.", ursprung=QUELLE)
        raise errors.AnbieterFehler(
            f"Der Filmbau ist abgebrochen (Rückgabewert {prozess.returncode}).",
            meldung or "Keine Fehlermeldung.", ursprung=QUELLE)

    logbook.erfolg(QUELLE, f"Agentenlauf fertig: {ergebnis.turns} Schritte, "
                           f"{ergebnis.tokens_gesamt:,} Tokens, "
                           f"{ergebnis.kosten_usd:.2f} $ Listenpreis."
                   .replace(",", "."))
    return ergebnis


def _satz_verarbeiten(satz: dict, ergebnis: Lauf, melden) -> None:
    """Ein Satz aus dem Ereignisstrom der CLI."""
    art = satz.get("type")

    if art == "system" and satz.get("subtype") == "init":
        ergebnis.sitzung = str(satz.get("session_id") or "")
        return

    if art == "assistant":
        for block in (satz.get("message") or {}).get("content", []):
            if block.get("type") == "tool_use":
                name = str(block.get("name") or "Werkzeug")
                ergebnis.werkzeuge[name] = ergebnis.werkzeuge.get(name, 0) + 1
                if melden:
                    melden(_kurzfassung(block), "werkzeug")
            elif block.get("type") == "text" and block.get("text", "").strip():
                if melden:
                    melden(" ".join(block["text"].split())[:220], "text")
        return

    if art == "result":
        ergebnis.text = str(satz.get("result") or "")
        ergebnis.turns = int(satz.get("num_turns") or 0)
        ergebnis.kosten_usd = float(satz.get("total_cost_usd") or 0.0)
        ergebnis.tokens = _tokens_aus(satz.get("usage") or {})
        if satz.get("is_error"):
            raise errors.AnbieterFehler(
                "Claude hat den Filmbau nicht zu Ende gebracht.",
                config.entschaerfe(str(satz.get("result") or "")[:300]) or
                "Keine nähere Angabe.", ursprung=QUELLE)
