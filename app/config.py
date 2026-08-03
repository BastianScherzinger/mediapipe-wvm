"""
config.py — zentrale Konfiguration.

Einziger Ort, an dem die .env gelesen wird. Jedes andere Modul importiert von hier.
Grundsätze:
  * Werte werden beim Laden typisiert und auf sinnvolle Grenzen gestutzt — ein Tippfehler
    in der .env darf das Programm nicht abstürzen lassen, sondern führt zum Standardwert.
  * Zugangsdaten verlassen dieses Modul nur maskiert (`masked()`), damit sie niemals in
    Log, Oberfläche oder Fehlermeldung auftauchen.
  * `diagnose()` liefert den Startbericht: was ist vorhanden, was fehlt, was ist zu tun.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── Verzeichnisse ────────────────────────────────────────────────────────────
# Alle Pfade leiten sich vom Projektordner ab; das Programm ist damit verschiebbar
# und braucht keine absoluten Pfade in der Konfiguration.
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "data"
OUTPUT_DIR: Path = BASE_DIR / "output"
LOG_DIR: Path = BASE_DIR / "logs"
STATIC_DIR: Path = BASE_DIR / "static"
TEMPLATE_DIR: Path = BASE_DIR / "templates"

for _d in (DATA_DIR, OUTPUT_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ── .env laden ───────────────────────────────────────────────────────────────
def _load_env() -> None:
    """Lädt die .env. Nutzt python-dotenv, fällt aber auf einen eigenen Parser zurück,
    damit ein fehlendes Paket den Start nicht verhindert."""
    env_path = BASE_DIR / ".env"
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
        return
    except Exception:
        pass
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()


# ── Typisierte Leser ─────────────────────────────────────────────────────────
def _str(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _int(name: str, default: int, low: int, high: int) -> int:
    """Ganzzahl aus der .env, auf [low, high] begrenzt. Unlesbares → Standardwert."""
    try:
        return max(low, min(high, int(float(_str(name, str(default))))))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = _str(name, "1" if default else "0").lower()
    return raw not in ("0", "false", "nein", "no", "off", "")


def _chain(name: str, default: str, erlaubt: tuple[str, ...]) -> tuple[str, ...]:
    """Kommaliste von Anbieterwegen, gefiltert auf bekannte Namen und ohne Dubletten.
    Ist nach dem Filtern nichts übrig, gilt die Vorgabe — die Kette darf nie leer sein."""
    roh = [t.strip().lower() for t in _str(name, default).split(",")]
    sauber: list[str] = []
    for t in roh:
        if t in erlaubt and t not in sauber:
            sauber.append(t)
    return tuple(sauber) or tuple(d for d in default.split(",") if d in erlaubt)


# ── Zugänge ──────────────────────────────────────────────────────────────────
HIGGSFIELD_API_KEY: str = _str("HIGGSFIELD_API_KEY")
ANTHROPIC_KEY: str = _str("ANTHROPIC_KEY")

# ── Anbieterketten ───────────────────────────────────────────────────────────
LLM_CHAIN: tuple[str, ...] = _chain("MPW_LLM_CHAIN", "cli,api,local", ("cli", "api", "local"))
VIDEO_CHAIN: tuple[str, ...] = _chain("MPW_VIDEO_CHAIN", "platform,demo", ("platform", "demo"))

CLAUDE_CLI_MODEL: str = _str("MPW_CLAUDE_CLI_MODEL", "sonnet")
CLAUDE_API_MODEL: str = _str("MPW_CLAUDE_API_MODEL", "claude-sonnet-4-5-20250929")
LOCAL_MODEL: str = _str("MPW_LOCAL_MODEL", "qwen2.5:7b")
OLLAMA_URL: str = _str("MPW_OLLAMA_URL", "http://localhost:11434").rstrip("/")
LOCAL_AUTOPULL: bool = _bool("MPW_LOCAL_AUTOPULL", True)

# ── Higgsfield-Modelle (Pfade aus docs/API_BEFUND.md) ────────────────────────
HF_BASE: str = "https://platform.higgsfield.ai"
IMAGE_MODEL: str = _str("MPW_IMAGE_MODEL", "higgsfield-ai/soul/standard")
VIDEO_MODEL: str = _str("MPW_VIDEO_MODEL", "kling-video/v2.6/pro/image-to-video")
T2V_MODEL: str = _str("MPW_T2V_MODEL", "minimax/hailuo-02/standard/text-to-video")

# ── Server ───────────────────────────────────────────────────────────────────
# Bewusst fest auf die lokale Schleife: das Werkzeug ist eine Einzelplatz-Anwendung
# und darf unter keinen Umständen im Netzwerk erreichbar sein.
HOST: str = "127.0.0.1"
PORT: int = _int("MPW_PORT", 7788, 1024, 65535)
DESKTOP_WINDOW: bool = _bool("MPW_WINDOW", True)

# ── Grenzen ──────────────────────────────────────────────────────────────────
MAX_SCENES: int = _int("MPW_MAX_SCENES", 12, 1, 30)
HTTP_TIMEOUT: int = _int("MPW_HTTP_TIMEOUT", 45, 5, 300)
JOB_TIMEOUT: int = _int("MPW_JOB_TIMEOUT", 900, 60, 3600)
POLL_INTERVAL: int = _int("MPW_POLL_INTERVAL", 4, 2, 30)
MAX_RETRIES: int = _int("MPW_MAX_RETRIES", 3, 0, 8)

# Grenzen für Benutzereingaben — schützen vor versehentlich riesigen Anfragen.
MAX_PROMPT_CHARS: int = 8000
MAX_BRIEFING_CHARS: int = 4000

APP_NAME: str = "MEDIAPIPE WVM"
APP_VERSION: str = "1.0.0"


# ── ffmpeg finden ────────────────────────────────────────────────────────────
_ffmpeg_gemerkt: str | None = None


def _ffmpeg_taugt(pfad: str) -> bool:
    """Prüft, ob unter diesem Pfad ein echtes ffmpeg liegt.

    Nötig, weil im PATH durchaus etwas anderes stehen kann, das nur so heißt: auf dem
    Entwicklungsrechner lag dort eine Hülle, die `-hide_banner` nicht kannte und jeden
    Aufruf mit „Option not found“ abbrach. Ein kurzer Probeaufruf mit genau den Optionen,
    die das Programm später benutzt, schließt solche Doppelgänger aus.
    """
    if not pfad:
        return False
    try:
        lauf = subprocess.run([pfad, "-hide_banner", "-loglevel", "error", "-version"],
                              capture_output=True, text=True, timeout=20)
    except Exception:
        return False
    return lauf.returncode == 0 and "ffmpeg version" in (lauf.stdout or "").lower()


def ffmpeg_pfad() -> str:
    """Pfad zu einem brauchbaren ffmpeg. Reihenfolge: .env → System-PATH →
    mitgeliefertes imageio-ffmpeg. Jeder Kandidat wird einmal erprobt; das Ergebnis
    wird gemerkt, damit nicht bei jedem Aufruf ein Prozess startet."""
    global _ffmpeg_gemerkt
    if _ffmpeg_gemerkt is not None:
        return _ffmpeg_gemerkt

    kandidaten: list[str] = []
    gesetzt = _str("MPW_FFMPEG")
    if gesetzt:
        kandidaten.append(gesetzt)
    im_pfad = shutil.which("ffmpeg")
    if im_pfad:
        kandidaten.append(im_pfad)
    try:
        import imageio_ffmpeg
        kandidaten.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass

    for kandidat in kandidaten:
        if _ffmpeg_taugt(kandidat):
            _ffmpeg_gemerkt = kandidat
            return kandidat

    _ffmpeg_gemerkt = ""
    return ""


def claude_cli_pfad() -> str:
    """Pfad zur Claude-CLI. Unter Windows liegt sie als .cmd-Hülle vor."""
    for name in ("claude.cmd", "claude.exe", "claude"):
        pfad = shutil.which(name)
        if pfad:
            return pfad
    return ""


# ── Maskierung ───────────────────────────────────────────────────────────────
def masked(wert: str) -> str:
    """Zugangsdaten für Anzeige und Log unkenntlich machen.
    Kurze Werte werden vollständig ersetzt — lieber zu viel verbergen als zu wenig."""
    wert = (wert or "").strip()
    if not wert:
        return "— nicht gesetzt —"
    if len(wert) <= 12:
        return "•" * len(wert)
    return f"{wert[:6]}…{wert[-4:]} ({len(wert)} Zeichen)"


def entschaerfe(text: str) -> str:
    """Entfernt bekannte Zugangsdaten aus beliebigem Text. Letzte Sicherung, bevor etwas
    ins Log oder in eine Fehlermeldung gelangt — auch wenn eine Fremdbibliothek den
    Schlüssel in ihrer Ausnahme mitliefert."""
    if not text:
        return text
    for geheim in (HIGGSFIELD_API_KEY, ANTHROPIC_KEY):
        if geheim and len(geheim) > 8:
            text = text.replace(geheim, "‹Zugangsdaten entfernt›")
            # Auch die Bestandteile eines ID:SECRET-Schlüssels einzeln ersetzen.
            for teil in geheim.split(":"):
                if len(teil) > 12:
                    text = text.replace(teil, "‹Zugangsdaten entfernt›")
    return text


# ── Startdiagnose ────────────────────────────────────────────────────────────
@dataclass
class Befund:
    """Ein geprüfter Baustein des Systems."""
    name: str
    ok: bool
    zustand: str                      # 'ok' | 'warnung' | 'fehler'
    meldung: str
    hinweis: str = ""                 # was der Benutzer tun kann, wenn es klemmt
    details: dict = field(default_factory=dict)

    def als_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "zustand": self.zustand,
                "meldung": self.meldung, "hinweis": self.hinweis, "details": self.details}


def diagnose() -> list[Befund]:
    """Prüft beim Start alle Voraussetzungen — ohne Netzaufrufe, damit der Start schnell
    bleibt. Die teuren Prüfungen (Guthaben, Erreichbarkeit) macht der Selbsttest im
    laufenden Programm."""
    befunde: list[Befund] = []

    # Higgsfield-Schlüssel
    if not HIGGSFIELD_API_KEY:
        befunde.append(Befund(
            "Higgsfield", False, "fehler", "Kein API-Schlüssel hinterlegt.",
            "HIGGSFIELD_API_KEY in der .env eintragen (Format ID:SECRET)."))
    elif ":" not in HIGGSFIELD_API_KEY:
        befunde.append(Befund(
            "Higgsfield", False, "fehler",
            f"Schlüsselformat unerwartet: {masked(HIGGSFIELD_API_KEY)}",
            "Erwartet wird ID:SECRET, wie bei cloud.higgsfield.ai/api-keys erzeugt."))
    else:
        befunde.append(Befund(
            "Higgsfield", True, "ok", f"Schlüssel hinterlegt: {masked(HIGGSFIELD_API_KEY)}",
            details={"modell_bild": IMAGE_MODEL, "modell_video": VIDEO_MODEL}))

    # Sprachmodell-Kette
    cli = claude_cli_pfad()
    wege: list[str] = []
    if "cli" in LLM_CHAIN and cli:
        wege.append("Claude-CLI (Abo)")
    if "api" in LLM_CHAIN and ANTHROPIC_KEY:
        wege.append("Anthropic-API")
    if "local" in LLM_CHAIN:
        wege.append(f"lokal ({LOCAL_MODEL})")
    if wege:
        befunde.append(Befund(
            "Sprachmodell", True, "ok", "Verfügbare Wege: " + " → ".join(wege),
            details={"kette": list(LLM_CHAIN), "cli": bool(cli)}))
    else:
        befunde.append(Befund(
            "Sprachmodell", False, "fehler", "Kein Weg zu einem Sprachmodell verfügbar.",
            "Entweder 'claude login' ausführen, ANTHROPIC_KEY eintragen oder Ollama starten."))

    # ffmpeg
    ff = ffmpeg_pfad()
    if ff:
        herkunft = "System" if shutil.which("ffmpeg") == ff else "mitgeliefert"
        befunde.append(Befund("ffmpeg", True, "ok", f"Einsatzbereit ({herkunft}).",
                              details={"pfad": ff}))
    else:
        befunde.append(Befund(
            "ffmpeg", False, "fehler", "Kein brauchbares ffmpeg gefunden.",
            "python -m pip install imageio-ffmpeg  — danach das Programm neu starten. "
            "(Ein Programm namens ffmpeg im Suchpfad genügt nicht, es muss ein echtes sein.)"))

    # Schreibrechte
    try:
        probe = OUTPUT_DIR / ".schreibprobe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        befunde.append(Befund("Ausgabeordner", True, "ok", str(OUTPUT_DIR)))
    except Exception as fehler:
        befunde.append(Befund(
            "Ausgabeordner", False, "fehler", f"Nicht beschreibbar: {type(fehler).__name__}",
            f"Schreibrechte für {OUTPUT_DIR} prüfen."))

    # Python-Version — Flask 3 und moderne Typangaben brauchen 3.10 aufwärts.
    if sys.version_info < (3, 10):
        befunde.append(Befund(
            "Python", False, "fehler",
            f"Version {sys.version_info.major}.{sys.version_info.minor} ist zu alt.",
            "Python 3.10 oder neuer installieren."))
    else:
        befunde.append(Befund(
            "Python", True, "ok",
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"))

    return befunde


def diagnose_kurz() -> dict:
    """Verdichtet die Diagnose zu einer Ampel für die Oberfläche."""
    befunde = diagnose()
    fehler = [b for b in befunde if b.zustand == "fehler"]
    return {
        "startbereit": not fehler,
        "anzahl_fehler": len(fehler),
        "befunde": [b.als_dict() for b in befunde],
        "version": APP_VERSION,
        "name": APP_NAME,
    }
