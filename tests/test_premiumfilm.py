"""Tests für „Premium-Film“: Fragen prüfen, Material sammeln, Agent führen, Ausgabe ablegen.

Ohne Netz und ohne Claude: Der Agentenlauf wird durch eine Attrappe ersetzt, die zwei
fertige MP4 in den Arbeitsordner legt — genau so, wie es der echte Agent täte. Echt
geprüft werden damit die Teile, die hier geschrieben wurden: Eingabeprüfung,
Materialauszug aus einem Projektordner, Upload-Annahme, die Einsortierung der beiden
Fassungen in die Bibliothek und die Abrechnung.

Der Auszug aus dem Ereignisstrom der CLI wird an echten Zeilen geprüft — an dieser
Stelle entscheidet sich, ob Tokens und Kosten stimmen, und eine falsche Zahl auf einer
Rechnung ist schlimmer als gar keine.
"""
from __future__ import annotations

import shutil
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import (bragagent, bragstudio, config, errors, jobstore,  # noqa: E402
                 library, pipeline)

HAT_FFMPEG = bool(config.ffmpeg_pfad())


def _einstellungen(**felder):
    roh = {"art": "premium", "quelle": "webseite", "url": "beispiel.de"}
    roh.update(felder)
    return pipeline.einstellungen_pruefen(roh)


# ── Die Fragen des Formulars ─────────────────────────────────────────────────

def test_webseite_braucht_einen_link():
    with pytest.raises(errors.EingabeFehler):
        _einstellungen(url="")


def test_ordner_muss_es_geben(tmp_path):
    with pytest.raises(errors.EingabeFehler):
        _einstellungen(quelle="ordner", projektordner=str(tmp_path / "gibtsnicht"))
    e = _einstellungen(quelle="ordner", projektordner=str(tmp_path))
    assert e.premium["projektordner"] == str(tmp_path)


def test_thema_darf_nicht_zu_kurz_sein():
    with pytest.raises(errors.EingabeFehler):
        _einstellungen(quelle="thema", thema="kurz")
    e = _einstellungen(quelle="thema", thema="Eine Bäckerei mit eigener Mühle in Lübeck.")
    assert e.premium["quelle"] == "thema"


def test_unsinnige_werte_werden_zurechtgerueckt():
    e = _einstellungen(tonfall="quatsch", dauer=999, sprache="kl", modell="gpt-9")
    assert e.premium["tonfall"] == "polished"
    assert e.premium["dauer"] in bragstudio.DAUERN
    assert e.premium["sprache"] == "de"
    assert e.premium["modell"] == config.BRAG_MODEL


def test_einstellungen_ueberleben_das_wiederholen():
    """„Erneut versuchen“ schickt die gespeicherten Einstellungen zurück — verschachtelt."""
    erst = _einstellungen(kunde="Luviq", tonfall="cinematic", dauer=25)
    wieder = pipeline.einstellungen_pruefen({**erst.als_dict(), "wiederholung_von": "abc"})
    assert wieder.premium["kunde"] == "Luviq"
    assert wieder.premium["tonfall"] == "cinematic"
    assert wieder.premium["dauer"] == 25
    assert wieder.wiederholung_von == "abc"


# ── Material ─────────────────────────────────────────────────────────────────

def test_projektauszug_nimmt_inhalte_und_laesst_ballast_liegen(tmp_path):
    projekt = tmp_path / "projekt"
    (projekt / "templates").mkdir(parents=True)
    (projekt / "node_modules" / "krempel").mkdir(parents=True)
    (projekt / ".git").mkdir()
    (projekt / "templates" / "index.html").write_text("<h1>Hallo</h1>", encoding="utf-8")
    (projekt / "stil.css").write_text(":root{--gold:#E1B565}", encoding="utf-8")
    (projekt / "logo.webp").write_bytes(b"RIFF0000WEBP")
    (projekt / "schrift.woff2").write_bytes(b"wOF2")
    (projekt / "node_modules" / "krempel" / "gross.js").write_text("x", encoding="utf-8")
    (projekt / ".git" / "config").write_text("[core]", encoding="utf-8")
    (projekt / "video.mkv").write_bytes(b"0" * 100)

    gezaehlt = bragstudio.projekt_auszug(projekt, tmp_path / "ziel")
    genommen = {p.name for p in (tmp_path / "ziel").rglob("*") if p.is_file()}

    assert genommen == {"index.html", "stil.css", "logo.webp", "schrift.woff2"}
    assert gezaehlt["texte"] == 2 and gezaehlt["bilder"] == 1 and gezaehlt["schriften"] == 1
    assert not (tmp_path / "ziel" / "node_modules").exists()


def test_projektauszug_laesst_das_original_unberuehrt(tmp_path):
    projekt = tmp_path / "projekt"
    projekt.mkdir()
    (projekt / "index.html").write_text("original", encoding="utf-8")
    bragstudio.projekt_auszug(projekt, tmp_path / "ziel")
    assert (projekt / "index.html").read_text(encoding="utf-8") == "original"


class _Hochgeladen:
    """Eine Datei, wie Flask sie an die Route reicht."""

    def __init__(self, name: str, inhalt: bytes = b"x"):
        self.filename = name
        self._inhalt = inhalt

    def save(self, pfad):
        Path(pfad).write_bytes(self._inhalt)


def test_upload_haelt_sich_an_den_korb(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    ergebnis = bragstudio.material_annehmen("korb1", [
        _Hochgeladen("logo.png"),
        _Hochgeladen("bilder/produkt.jpg"),
        _Hochgeladen("../../../boese.png"),      # Ausbruchsversuch
        _Hochgeladen("schadsoftware.exe"),       # falsche Art
    ])
    korb = tmp_path / "material" / "korb1"
    abgelegt = sorted(p.relative_to(korb).as_posix() for p in korb.rglob("*") if p.is_file())

    assert ergebnis["anzahl"] == 3
    assert ergebnis["abgewiesen"] == ["schadsoftware.exe"]
    assert abgelegt == ["bilder/produkt.jpg", "boese.png", "logo.png"]
    # Nichts darf außerhalb des Korbs gelandet sein.
    assert not list(tmp_path.glob("boese.png"))


def test_korb_leeren(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    bragstudio.material_annehmen("korb2", [_Hochgeladen("a.png"), _Hochgeladen("b.png")])
    assert bragstudio.korb_leeren("korb2") == 2
    assert not (tmp_path / "material" / "korb2").exists()


def test_ordner_pruefen_zaehlt_inhalte(tmp_path):
    (tmp_path / "seite.html").write_text("<p>x</p>", encoding="utf-8")
    (tmp_path / "bild.webp").write_bytes(b"x")
    befund = bragstudio.ordner_pruefen(str(tmp_path))
    assert befund["taugt"] and befund["texte"] == 1 and befund["bilder"] == 1

    leer = tmp_path / "leer"
    leer.mkdir()
    assert not bragstudio.ordner_pruefen(str(leer))["taugt"]


# ── Welche Sorte Film? ───────────────────────────────────────────────────────

def _bilder(anzahl: int, name: str = "foto"):
    return [{"hinweis": f"{name}_{i}", "breite": 1200, "hoehe": 900,
             "datei": Path(f"{name}_{i}.jpg")} for i in range(anzahl)]


def test_dienstleister_bekommt_den_dienstleistungsfilm():
    """Gebäudereinigung mit Galeriefotos — das ist Arbeit, keine Ware."""
    befund = bragstudio.fokus_bestimmen(
        _bilder(8, "galerie"),
        {"titel": "Flügel Haus & Gebäudeservice",
         "ueberschriften": ["Gebäudereinigung", "Gartenpflege", "Winterdienst"],
         "knoepfe": ["Angebot einholen", "Termin vereinbaren"]})
    assert befund["fokus"] == "dienstleistung"
    assert "Arbeitsfotos" in befund["begruendung"]


def test_shop_bekommt_den_produktfilm():
    befund = bragstudio.fokus_bestimmen(
        _bilder(6, "produkt"),
        {"titel": "Handbemalte Second-Hand-Mode",
         "ueberschriften": ["Aktuelle Unikate", "Kollektion"],
         "knoepfe": ["In den Warenkorb", "Bestellen"]})
    assert befund["fokus"] == "produkt"


def test_ohne_bilder_gibt_es_den_webseitenfilm():
    """Was nicht fotografiert ist, wird nicht behauptet."""
    befund = bragstudio.fokus_bestimmen(
        [], {"titel": "Webagentur", "ueberschriften": ["Festpreis", "Website"]})
    assert befund["fokus"] == "webseite"


def test_eigene_wahl_schlaegt_die_erkennung():
    befund = bragstudio.fokus_bestimmen(_bilder(9, "galerie"),
                                        {"titel": "Reinigung"}, gewaehlt="webseite")
    assert befund["fokus"] == "webseite" and befund["gewaehlt"]


def test_alte_kennung_marke_faellt_auf_die_erkennung_zurueck():
    """Bis zum 18.09.2026 hieß die Sorte „marke“ — gespeicherte Aufträge müssen laufen."""
    befund = bragstudio.fokus_bestimmen(_bilder(6, "galerie"),
                                        {"titel": "Gartenpflege und Reinigung"},
                                        gewaehlt="marke")
    assert befund["fokus"] in ("dienstleistung", "produkt")
    assert not befund["gewaehlt"]


def test_jede_sorte_hat_einen_eigenen_bauplan():
    """Ohne eigenen Bauplan wäre die Auswahl eine Attrappe."""
    bauplaene = {bragstudio._FOKUS_PRODUKT, bragstudio._FOKUS_DIENSTLEISTUNG,
                 bragstudio._FOKUS_WEBSEITE}
    assert len(bauplaene) == 3
    assert "End-Card" in bragstudio._FOKUS_DIENSTLEISTUNG
    assert "Vorher/Nachher" in bragstudio._FOKUS_DIENSTLEISTUNG
    bildregeln = {bragstudio._BILDREGEL_PRODUKT, bragstudio._BILDREGEL_DIENSTLEISTUNG,
                  bragstudio._BILDREGEL_WEBSEITE}
    assert len(bildregeln) == 3


def test_handwerkswissen_liegt_bei():
    """Der Agent liest es bei jedem Dienstleistungsfilm — fehlt es, baut er ins Blaue."""
    vorlage = config.BASE_DIR / "bragvorlage"
    for datei in ("REZEPT.md", "HANDWERK-werbefilm.md",
                  "referenz-dienstleistung-hochformat.html",
                  "referenz-querformat.html", "referenz-hochformat.html"):
        assert (vorlage / datei).exists(), f"{datei} fehlt"
    assert "HANDWERK-werbefilm.md" in bragstudio._AGENT_VORSPANN


# ── Der Ereignisstrom der CLI ────────────────────────────────────────────────

def test_ereignisstrom_wird_zu_einer_abrechnung():
    lauf = bragagent.Lauf()
    gemeldet: list[tuple[str, str]] = []

    saetze = [
        {"type": "system", "subtype": "init", "session_id": "s-1"},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "npx hyperframes check"}}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Write", "input": {"file_path": "index.html"}}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Baue Szene 1"}]}},
        {"type": "result", "subtype": "success", "is_error": False, "num_turns": 42,
         "total_cost_usd": 3.5, "result": "fertig",
         "usage": {"input_tokens": 10, "output_tokens": 20,
                   "cache_creation_input_tokens": 30, "cache_read_input_tokens": 40}},
    ]
    for satz in saetze:
        bragagent._satz_verarbeiten(satz, lauf, lambda t, a: gemeldet.append((a, t)))

    assert lauf.sitzung == "s-1"
    assert lauf.turns == 42 and lauf.kosten_usd == 3.5
    assert lauf.tokens_gesamt == 100
    assert lauf.werkzeuge == {"Bash": 1, "Write": 1}
    assert ("werkzeug", "Bash: npx hyperframes check") in gemeldet
    assert ("text", "Baue Szene 1") in gemeldet


def test_erschoepftes_kontingent_wird_als_solches_gemeldet():
    """Am 18.09.2026 stand im Dashboard „Claude hat den Filmbau nicht zu Ende gebracht",
    während die CLI in Wahrheit „monthly spend limit" meldete. Wer das liest, sucht den
    Fehler im Programm — dabei ist nur das Kontingent alle."""
    lauf = bragagent.Lauf()
    with pytest.raises(errors.GuthabenFehler) as fehler:
        bragagent._satz_verarbeiten(
            {"type": "result", "is_error": True,
             "result": "You've hit your monthly spend limit - raise it at "
                       "claude.ai/settings/usage - your session limit resets 2:30pm "
                       "(Europe/Berlin)"},
            lauf, None)
    assert "Kontingent" in fehler.value.meldung
    assert "2:30pm" in fehler.value.hinweis
    assert "claude.ai/settings/usage" in fehler.value.hinweis


def test_gewoehnlicher_fehler_bleibt_ein_gewoehnlicher_fehler():
    lauf = bragagent.Lauf()
    with pytest.raises(errors.AnbieterFehler):
        bragagent._satz_verarbeiten(
            {"type": "result", "is_error": True, "result": "context window exceeded"},
            lauf, None)


def test_fehlschlag_des_agenten_wird_zum_erklaerten_fehler():
    lauf = bragagent.Lauf()
    with pytest.raises(errors.AnbieterFehler):
        bragagent._satz_verarbeiten(
            {"type": "result", "is_error": True, "result": "context window exceeded"},
            lauf, None)


# ── Der ganze Auftrag mit einem Agenten aus Pappe ────────────────────────────

def _video_schreiben(ziel: Path, breite: int, hoehe: int, sekunden: int = 4) -> None:
    """Ein echtes, winziges MP4 — damit `media.angaben()` etwas zu messen hat."""
    import subprocess
    ziel.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [config.ffmpeg_pfad(), "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"color=c=black:s={breite}x{hoehe}:d={sekunden}",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(ziel)],
        check=True, capture_output=True, timeout=120)


@pytest.mark.skipif(not HAT_FFMPEG, reason="ohne ffmpeg nicht prüfbar")
def test_auftrag_legt_beide_fassungen_ab(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.OUTPUT_DIR.mkdir(parents=True)

    e = _einstellungen(quelle="thema",
                       thema="Handbemalte Einzelstücke aus Second-Hand-Mode.",
                       kunde="Luviq Universe")
    auftrag = jobstore.anlegen(e.briefing, e.als_dict())

    monkeypatch.setattr(bragstudio, "master_prompt_schreiben",
                        lambda *a, **k: "# Auftrag: Luviq\n## Storyboard\n…")
    monkeypatch.setattr(bragagent, "werkzeuge_sichern", lambda melden=None: None)

    def agent_attrappe(arbeit, prompt, **rest):
        ausgabe = Path(arbeit) / "brag-output"
        ausgabe.mkdir(parents=True, exist_ok=True)
        _video_schreiben(ausgabe / "brag.mp4", 640, 360)
        _video_schreiben(ausgabe / "brag-hochformat.mp4", 360, 640)
        (ausgabe / "share-copy.txt").write_text("Jedes Teil ein Einzelstück.",
                                                encoding="utf-8")
        (ausgabe / "brag-plan.md").write_text("# Plan", encoding="utf-8")
        return bragagent.Lauf(text="fertig", modell="claude-opus-5", turns=37,
                              kosten_usd=4.2, dauer=900,
                              tokens={"eingabe": 1000, "ausgabe": 2000,
                                      "cache_neu": 3000, "cache_gelesen": 4000},
                              werkzeuge={"Bash": 12})

    monkeypatch.setattr(bragagent, "lauf", agent_attrappe)

    ergebnis = bragstudio.ablauf(auftrag.id, e, threading.Event())
    ordner = Path(ergebnis["ordner"])

    assert (ordner / "film.mp4").exists(), "Querformat fehlt"
    assert (ordner / "film_hoch.mp4").exists(), "Hochformat fehlt"
    assert (ordner / "film_poster.jpg").exists(), "Vorschaubild fehlt"
    assert ergebnis["breite"] > ergebnis["hoehe"], "film.mp4 muss das Querformat sein"
    assert not ergebnis["ausgefallen"], "beide Fassungen kamen vom Agenten"

    # Die Abrechnung muss beim Video liegen, nicht nur im Logbuch.
    assert ergebnis["aufwand"]["tokens_gesamt"] == 10000
    assert ergebnis["aufwand"]["kosten_usd"] == 4.2

    eintrag = library.eintrag(ordner)
    assert eintrag["art"] == "premium"
    assert eintrag["aufwand"]["tokens_gesamt"] == 10000
    assert "hoch" in eintrag["fassungen"], "die TikTok-Fassung muss in der Bibliothek stehen"
    assert eintrag["posting"]["text"].startswith("Jedes Teil")


@pytest.mark.skipif(not HAT_FFMPEG, reason="ohne ffmpeg nicht prüfbar")
def test_fehlendes_hochformat_wird_geschnitten(tmp_path, monkeypatch):
    """Liefert der Agent nur eine Fassung, bekommt der Kunde trotzdem beide — mit Vermerk."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.OUTPUT_DIR.mkdir(parents=True)

    e = _einstellungen(quelle="thema", thema="Ein Betrieb, der Dächer deckt, seit 1968.")
    auftrag = jobstore.anlegen(e.briefing, e.als_dict())
    monkeypatch.setattr(bragstudio, "master_prompt_schreiben", lambda *a, **k: "# Auftrag")
    monkeypatch.setattr(bragagent, "werkzeuge_sichern", lambda melden=None: None)

    def nur_quer(arbeit, prompt, **rest):
        ausgabe = Path(arbeit) / "brag-output"
        ausgabe.mkdir(parents=True, exist_ok=True)
        _video_schreiben(ausgabe / "brag.mp4", 640, 360)
        return bragagent.Lauf(text="fertig", modell="m", turns=1, kosten_usd=1.0,
                              tokens={"eingabe": 1, "ausgabe": 1})

    monkeypatch.setattr(bragagent, "lauf", nur_quer)
    ergebnis = bragstudio.ablauf(auftrag.id, e, threading.Event())

    assert (Path(ergebnis["ordner"]) / "film_hoch.mp4").exists()
    assert any("Hochformat" in satz for satz in ergebnis["ausgefallen"])


@pytest.mark.skipif(not HAT_FFMPEG, reason="ohne ffmpeg nicht prüfbar")
def test_ohne_video_gibt_es_einen_erklaerten_fehler(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.OUTPUT_DIR.mkdir(parents=True)
    e = _einstellungen(quelle="thema", thema="Irgendetwas, das nicht fertig wird.")
    auftrag = jobstore.anlegen(e.briefing, e.als_dict())
    monkeypatch.setattr(bragstudio, "master_prompt_schreiben", lambda *a, **k: "# Auftrag")
    monkeypatch.setattr(bragagent, "werkzeuge_sichern", lambda melden=None: None)
    monkeypatch.setattr(bragagent, "lauf",
                        lambda arbeit, prompt, **rest: bragagent.Lauf(text="leider nichts"))

    with pytest.raises(errors.VerarbeitungsFehler) as fehler:
        bragstudio.ablauf(auftrag.id, e, threading.Event())
    assert "Arbeitsordner" in fehler.value.hinweis


# ── Zusammenspiel mit der übrigen Anwendung ──────────────────────────────────

def test_katalog_hat_alles_was_die_oberflaeche_zeichnet():
    katalog = bragstudio.katalog()
    for feld in ("quellen", "tonfaelle", "dauern", "sprachen", "modelle", "bloecke",
                 "befund", "modell_vorgabe"):
        assert katalog[feld], f"{feld} fehlt im Katalog"
    assert [b["kennung"] for b in katalog["bloecke"]] == list(bragstudio.BLOECKE)


def test_pipeline_kennt_die_bloecke_des_premiumfilms():
    """Die Anzeige rechts richtet sich nach `art` — steht der Block nicht im Satz,
    zeichnet die Oberfläche die Blöcke des Video-Studios und zeigt Unsinn."""
    e = _einstellungen()
    assert e.art == "premium"
    assert set(bragstudio.BLOCKNAMEN) == set(bragstudio.BLOECKE)


# ── Befunde der Durchsicht vom 25.09.2026 ────────────────────────────────────

def test_ballastname_ueber_dem_projektordner_stoert_nicht(tmp_path):
    """Liegt das Projekt unter …/build/kunde, ist das kein Grund, alles zu überspringen —
    nur Ballast *innerhalb* des Projekts zählt."""
    projekt = tmp_path / "build" / "kunde"
    (projekt / "node_modules" / "paket").mkdir(parents=True)
    (projekt / "index.html").write_text("<h1>Hallo</h1>", encoding="utf-8")
    (projekt / "node_modules" / "paket" / "x.js").write_text("x", encoding="utf-8")
    befund = bragstudio.ordner_pruefen(str(projekt))
    assert befund["taugt"] and befund["texte"] == 1
    gezaehlt = bragstudio.projekt_auszug(projekt, tmp_path / "ziel")
    assert gezaehlt["texte"] == 1


def test_zugangsdaten_verlassen_den_projektordner_nicht(tmp_path):
    projekt = tmp_path / "projekt"
    projekt.mkdir()
    (projekt / "index.html").write_text("<h1>Marke</h1>", encoding="utf-8")
    for geheim in (".env", "settings.py", "credentials.json", "secrets.yaml.txt",
                   "server.pem", "id_rsa"):
        (projekt / geheim).write_text("SECRET_KEY=abc", encoding="utf-8")
    gezaehlt = bragstudio.projekt_auszug(projekt, tmp_path / "ziel")
    kopiert = sorted(p.name for p in (tmp_path / "ziel").rglob("*") if p.is_file())
    assert kopiert == ["index.html"]
    assert gezaehlt["geheim"] >= 4


def test_projektauszug_laesst_sich_abbrechen(tmp_path):
    projekt = tmp_path / "projekt"
    projekt.mkdir()
    (projekt / "index.html").write_text("x", encoding="utf-8")
    abbruch = threading.Event()
    abbruch.set()
    with pytest.raises(errors.AbbruchFehler):
        bragstudio.projekt_auszug(projekt, tmp_path / "ziel", abbruch)


def test_liegen_gebliebene_koerbe_werden_aufgeraeumt(tmp_path, monkeypatch):
    import os
    import time as zeit
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    bragstudio.material_annehmen("alt", [_Hochgeladen("a.png")])
    bragstudio.material_annehmen("neu", [_Hochgeladen("b.png")])
    vor_zwei_tagen = zeit.time() - 2 * 86400
    os.utime(tmp_path / "material" / "alt", (vor_zwei_tagen, vor_zwei_tagen))
    assert bragstudio.koerbe_aufraeumen() == 1
    assert not (tmp_path / "material" / "alt").exists()
    assert (tmp_path / "material" / "neu").exists()


def test_korb_hat_eine_gesamtgrenze(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(bragstudio, "MAX_UPLOAD_BYTES", 10)
    bragstudio.material_annehmen("k", [_Hochgeladen("a.png", b"x" * 8)])
    zweiter = bragstudio.material_annehmen("k", [_Hochgeladen("b.png", b"x" * 8),
                                                 _Hochgeladen("c.png", b"x" * 8)])
    assert zweiter["anzahl"] == 1 and zweiter["abgewiesen"] == ["c.png"]


def test_aufwerten_nimmt_die_maengel_nicht_den_alten_wunsch(tmp_path):
    erst = _einstellungen(quelle="ordner", projektordner=str(tmp_path),
                          wunsch="Bitte viel Gold")
    roh = {**erst.als_dict(), "aufwerten_von": "abc123", "maengel": "Logo zu klein. " * 100}
    neu = pipeline.einstellungen_pruefen(roh)
    assert neu.premium["maengel"].startswith("Logo zu klein.")
    assert len(neu.premium["maengel"]) > 600, "die Mängelliste darf nicht auf 600 schrumpfen"
    # Ohne Aufwertung gibt es keine Mängel — der Wunsch bleibt, wo er hingehört.
    assert pipeline.einstellungen_pruefen(erst.als_dict()).premium["maengel"] == ""


def test_aufwerten_geht_auch_ohne_den_alten_projektordner(tmp_path):
    projekt = tmp_path / "projekt"
    projekt.mkdir()
    erst = _einstellungen(quelle="ordner", projektordner=str(projekt))
    projekt.rmdir()
    neu = pipeline.einstellungen_pruefen({**erst.als_dict(), "aufwerten_von": "abc123"})
    assert neu.premium["aufwerten_von"] == "abc123"
    with pytest.raises(errors.EingabeFehler):
        pipeline.einstellungen_pruefen(erst.als_dict())


def test_nur_ein_shellbefehl_zum_rendern_schaltet_die_anzeige_weiter():
    assert bragstudio._ist_render("Bash: npx hyperframes render composition")
    assert not bragstudio._ist_render("Read: brag-output/render-notes.md")


def test_agent_sieht_keine_fremden_zugangsdaten():
    umgebung = bragagent._ohne_geheimnisse({
        "PATH": "/bin", "CLAUDE_CODE_OAUTH_TOKEN": "abo", "GITHUB_TOKEN": "g",
        "HF_TOKEN": "h", "NPM_TOKEN": "n", "MEIN_API_KEY": "k", "HIGGSFIELD_API_KEY": "x"})
    assert umgebung == {"PATH": "/bin", "CLAUDE_CODE_OAUTH_TOKEN": "abo"}


def test_oauth_token_wird_geschwaerzt(monkeypatch):
    monkeypatch.setattr(config, "CLAUDE_OAUTH_TOKEN", "sk-ant-oat01-geheimgeheim")
    assert "geheimgeheim" not in config.entschaerfe("Fehler mit sk-ant-oat01-geheimgeheim")


def test_hilfsprogramme_werden_samt_endung_aufgeloest(monkeypatch):
    """Unter Windows liegt npx als npx.cmd vor; ohne Auflösung findet subprocess es nicht."""
    gefunden = {"npx.cmd": r"C:\nodejs\npx.cmd"}
    monkeypatch.setattr(bragagent.shutil, "which", lambda name: gefunden.get(name))
    assert bragagent._programm("npx") == r"C:\nodejs\npx.cmd"
    assert bragagent._programm("gibtsnicht") == "gibtsnicht"


@pytest.mark.skipif(sys.platform == "win32", reason="Attrappe ist ein Shell-Skript")
def test_abbruch_wirkt_auch_wenn_der_agent_schweigt(tmp_path, monkeypatch):
    """Ein Werkzeugaufruf wie `hyperframes render` gibt minutenlang nichts aus. Der
    Abbruch muss trotzdem sofort greifen — und die Kindprozesse mitnehmen."""
    import time as zeit
    kind_pid = tmp_path / "kind.pid"
    cli = tmp_path / "claude"
    cli.write_text("#!/bin/sh\nsleep 300 &\necho $! > " + str(kind_pid) + "\nwait\n",
                   encoding="utf-8")
    cli.chmod(0o755)
    monkeypatch.setattr(config, "claude_cli_pfad", lambda: str(cli))
    monkeypatch.setattr(bragagent, "_binordner", lambda: tmp_path)

    abbruch = threading.Event()
    threading.Timer(1.0, abbruch.set).start()
    begonnen = zeit.monotonic()
    with pytest.raises(errors.AbbruchFehler):
        bragagent.lauf(tmp_path / "arbeit", "baue", modell="m", zeitlimit=600,
                       abbruch=abbruch)
    assert zeit.monotonic() - begonnen < 15

    import os
    pid = int(kind_pid.read_text().strip())
    zeit.sleep(0.3)
    try:
        os.kill(pid, 0)
        # Zombie zählt nicht als lebendig.
        with open(f"/proc/{pid}/stat") as f:
            lebt = f.read().split()[2] != "Z"
    except (OSError, FileNotFoundError):
        lebt = False
    assert not lebt, "der Kindprozess des Agenten läuft nach dem Abbruch weiter"


@pytest.mark.skipif(sys.platform == "win32", reason="Attrappe ist ein Shell-Skript")
def test_zeitlimit_wirkt_auch_wenn_der_agent_schweigt(tmp_path, monkeypatch):
    import time as zeit
    cli = tmp_path / "claude"
    cli.write_text("#!/bin/sh\nsleep 300\n", encoding="utf-8")
    cli.chmod(0o755)
    monkeypatch.setattr(config, "claude_cli_pfad", lambda: str(cli))
    monkeypatch.setattr(bragagent, "_binordner", lambda: tmp_path)
    begonnen = zeit.monotonic()
    with pytest.raises(errors.ZeitFehler):
        bragagent.lauf(tmp_path / "arbeit", "baue", modell="m", zeitlimit=1)
    assert zeit.monotonic() - begonnen < 15


def test_unlesbare_seite_laesst_den_auftrag_weiterlaufen(tmp_path, monkeypatch):
    """403 an Programme ist Alltag — der Film entsteht dann aus Material und Beschreibung."""
    def abgelehnt(url):
        raise errors.EingabeFehler("Die Seite antwortet mit 403.")
    monkeypatch.setattr(bragstudio.webaufnahme, "adresse_pruefen", abgelehnt)
    monkeypatch.setattr(bragstudio, "_bilder_von_der_seite", lambda *a, **k: [])
    monkeypatch.setattr(bragstudio, "_aufnehmen_mit_grenze", lambda *a, **k: None)
    material = bragstudio._material_sammeln(
        "x", {"quelle": "webseite", "url": "https://beispiel.de", "fokus": "auto"},
        tmp_path / "arbeit", threading.Event())
    assert material["texte"] == {}
    assert "keine Bildschirmaufnahmen" in material["kurz"]


def test_produktfilm_mit_eigenen_fotos_spart_sich_die_aufnahme(tmp_path, monkeypatch):
    monkeypatch.setattr(bragstudio.webaufnahme, "adresse_pruefen",
                        lambda url: {"titel": "Mode-Shop", "ueberschriften": ["Kollektion"]})
    monkeypatch.setattr(bragstudio, "_bilder_von_der_seite",
                        lambda *a, **k: _bilder(6, "kleid"))
    monkeypatch.setattr(bragstudio, "fokus_bestimmen",
                        lambda b, t, g="auto": {"fokus": "produkt", "gewaehlt": False,
                                                "begruendung": "Test"})
    monkeypatch.setattr(bragstudio.library, "web_pfad", lambda p: str(p))

    def aufnahme(*a, **k):
        raise AssertionError("die Aufnahme hätte übersprungen werden müssen")
    monkeypatch.setattr(bragstudio, "_aufnehmen_mit_grenze", aufnahme)
    material = bragstudio._material_sammeln(
        "x", {"quelle": "webseite", "url": "https://beispiel.de", "fokus": "auto"},
        tmp_path / "arbeit", threading.Event())
    assert "Bildschirmaufnahme nicht nötig" in material["kurz"]


@pytest.mark.skipif(not HAT_FFMPEG, reason="ohne ffmpeg nicht prüfbar")
def test_material_video_ist_kein_fertiger_film(tmp_path):
    """Ein hochgeladener großer Clip im Material darf nie als Ergebnis gelten."""
    arbeit = tmp_path / "arbeit"
    _video_schreiben(arbeit / "material" / "gross.mp4", 1280, 720)
    _video_schreiben(arbeit / "brag-output" / "brag.mp4", 640, 360)
    videos = bragstudio._gerenderte_videos(arbeit)
    assert [p.name for p, _ in videos] == ["brag.mp4"]

    nur_material = tmp_path / "leer"
    _video_schreiben(nur_material / "material" / "gross.mp4", 1280, 720)
    assert bragstudio._gerenderte_videos(nur_material) == []


@pytest.mark.skipif(not HAT_FFMPEG, reason="ohne ffmpeg nicht prüfbar")
def test_aufwertung_sichert_den_alten_film_und_nutzt_keine_alten_renders(tmp_path,
                                                                       monkeypatch):
    import time as zeit
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.OUTPUT_DIR.mkdir(parents=True)
    monkeypatch.setattr(bragagent, "werkzeuge_sichern", lambda melden=None: None)

    # Der Vorgänger: fertiger Film samt Komposition und Auftrag.
    erst = _einstellungen(quelle="thema", thema="Ein Dachdecker seit 1968 in Leipzig.")
    vorher = jobstore.anlegen(erst.briefing, erst.als_dict())
    ordner = config.OUTPUT_DIR / "premium_dach"
    _video_schreiben(ordner / "arbeit" / "brag-output" / "brag.mp4", 640, 360)
    shutil.copy2(ordner / "arbeit" / "brag-output" / "brag.mp4", ordner / "film.mp4")
    (ordner / "master-prompt.md").write_text("# Alter Auftrag", encoding="utf-8")
    jobstore.aktualisieren(vorher.id, ordner=str(ordner), zustand=jobstore.FERTIG)
    alt = zeit.time() - 3600
    import os
    os.utime(ordner / "arbeit" / "brag-output" / "brag.mp4", (alt, alt))

    e = pipeline.einstellungen_pruefen({**erst.als_dict(), "aufwerten_von": vorher.id,
                                        "maengel": "Das Logo ist zu klein."})
    auftrag = jobstore.anlegen(e.briefing, e.als_dict())
    gesehen = {}

    def nichts_gerendert(arbeit, prompt, **rest):
        gesehen["prompt"] = prompt
        return bragagent.Lauf(text="fertig")
    monkeypatch.setattr(bragagent, "lauf", nichts_gerendert)

    with pytest.raises(errors.VerarbeitungsFehler):
        bragstudio.ablauf(auftrag.id, e, threading.Event())
    assert "Das Logo ist zu klein." in gesehen["prompt"]
    assert "# Alter Auftrag" in gesehen["prompt"]
    gesichert = list((ordner / "fruehere_fassungen").rglob("film.mp4"))
    assert gesichert, "der abgenommene Film muss vor der Aufwertung gesichert werden"
