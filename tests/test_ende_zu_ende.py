"""
Ende-zu-Ende-Test der gesamten Kette.

Higgsfield wird durch eine Attrappe ersetzt, die dieselben Zusagen einhält wie der echte
Dienst — sie erzeugt aber mit ffmpeg lokale Dateien statt Guthaben zu verbrauchen. Alles
andere ist echt: die Zustandsmaschine, die Montage, die Formate, der Auftragsspeicher, die
Bibliothek und der Ereignisstrom.

Damit lässt sich beweisen, dass das Werkzeug funktioniert, ohne dass ein einziges Credit
fließt. Sobald Guthaben da ist, ändert sich nur, wer die Clips liefert.
"""
from __future__ import annotations

import json
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import (config, errors, higgsfield, jobstore, library, logbook,  # noqa: E402
                 media, pipeline, promptsmith)

HAT_FFMPEG = bool(config.ffmpeg_pfad())
pytestmark = pytest.mark.skipif(not HAT_FFMPEG, reason="kein ffmpeg vorhanden")


# ── Attrappe ─────────────────────────────────────────────────────────────────

class AttrappeHiggsfield:
    """Verhält sich wie der echte Client, erzeugt aber lokale Dateien.

    Wichtig: sie meldet Fortschritt genau wie das Original, damit auch die
    Fortschrittsanzeige und die Restzeitschätzung durch den Test laufen. `name` und
    `verfuegbar` braucht sie, weil die Auswahl in `videoquelle` danach fragt.
    """

    name = "Attrappe"
    verfuegbar = True

    def __init__(self, ordner: Path, scheitert_bei: int = 0):
        self.ordner = Path(ordner)
        self.ordner.mkdir(parents=True, exist_ok=True)
        self.bilder = 0
        self.videos = 0
        self.scheitert_bei = scheitert_bei      # Nummer des Videos, das fehlschlagen soll
        self.scheitert_immer = False            # gar keine Szene kommt durch
        self.abgebrochen = 0

    def bild(self, prompt, *, seitenverhaeltnis="16:9", aufloesung="1080p", modell="",
             verbessern=True, saat=None, abbruch=None, melden=None):
        if abbruch is not None and abbruch.is_set():
            raise errors.AbbruchFehler("Abgebrochen.")
        self.bilder += 1
        if melden:
            melden(0.3, 8, "in_progress")
            melden(1.0, 0, "fertig")
        pfad = self.ordner / f"attrappe_bild_{self.bilder}.jpg"
        clip = media.platzhalter_clip(self.ordner / f"_tmp{self.bilder}.mp4",
                                      sekunden=1, breite=640, hoehe=360)
        media.format_erzeugen(clip, pfad, "poster")
        clip.unlink(missing_ok=True)
        return higgsfield.Ergebnis(f"bild-{self.bilder}", modell or "attrappe",
                                   str(pfad), 1.0, {})

    def video_aus_bild(self, prompt, bild_url, *, dauer=5, modell="", saat=None,
                       bewegungen=None, seitenverhaeltnis="16:9",
                       abbruch=None, melden=None):
        if abbruch is not None and abbruch.is_set():
            raise errors.AbbruchFehler("Abgebrochen.")
        self.videos += 1
        if self.scheitert_immer or (self.scheitert_bei and
                                    self.videos == self.scheitert_bei):
            raise errors.AnbieterFehler("Attrappe: Szene absichtlich fehlgeschlagen.",
                                        "Nur ein Test.")
        if melden:
            melden(0.25, 20, "in_progress")
            melden(0.75, 6, "in_progress")
            melden(1.0, 0, "fertig")
        pfad = media.platzhalter_clip(self.ordner / f"attrappe_video_{self.videos}.mp4",
                                      sekunden=dauer, breite=640, hoehe=360)
        return higgsfield.Ergebnis(f"video-{self.videos}", modell or "attrappe",
                                   str(pfad), 2.0, {})

    def video_aus_text(self, prompt, *, dauer=6, modell="", seitenverhaeltnis="16:9",
                       abbruch=None, melden=None):
        return self.video_aus_bild(prompt, "", dauer=dauer, modell=modell,
                                   seitenverhaeltnis=seitenverhaeltnis,
                                   abbruch=abbruch, melden=melden)

    def herunterladen(self, url, ziel, abbruch=None, melden=None):
        ziel = Path(ziel)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(url, ziel)                 # „Download“ = lokale Kopie
        return ziel

    def abbrechen(self, request_id):
        self.abgebrochen += 1
        return True

    def selbsttest(self):
        return {"zustand": "bereit", "ok": True, "guthaben": "vorhanden",
                "meldung": "Attrappe bereit.", "hinweis": ""}


DREHBUCH = {
    "titel": "Testfilm Bäckerei",
    "dateiname": "testfilm_baeckerei",
    "zusammenfassung": "Ein Test.",
    "stil": "warmes Morgenlicht",
    "szenen": [
        {"beschreibung": f"Szene {i}",
         "bild_prompt": f"Test scene {i}, warm light. no text, no logos, no watermark",
         "video_prompt": f"Slow push-in {i}, one continuous shot"}
        for i in range(1, 5)
    ],
}


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """Vollständige Umgebung: eigene Ordner, Attrappe statt Higgsfield, festes Drehbuch."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    jobstore.einrichten()

    attrappe = AttrappeHiggsfield(tmp_path / "quelle")
    monkeypatch.setattr(higgsfield, "client", attrappe)
    monkeypatch.setattr(pipeline.higgsfield, "client", attrappe)

    # Das Sprachmodell wird ersetzt — sonst dauert jeder Testlauf eine Minute und
    # hinge an einem fremden Dienst.
    monkeypatch.setattr(promptsmith.llm, "erzeuge",
                        lambda *_a, **_k: promptsmith.llm.Antwort(
                            json.dumps(DREHBUCH), "cli", "test", 0.1))

    pipeline._aktuell = None
    return attrappe


def warten_bis_fertig(auftrag_id: str, grenze: float = 240.0) -> jobstore.Auftrag:
    ende = time.monotonic() + grenze
    while time.monotonic() < ende:
        auftrag = jobstore.holen(auftrag_id)
        if auftrag and not auftrag.laeuft_noch:
            return auftrag
        time.sleep(0.25)
    raise AssertionError(f"Auftrag {auftrag_id} wurde in {grenze} s nicht fertig.")


class Mitschrift:
    """Hört den Ereignisstrom mit — damit lässt sich prüfen, was die Oberfläche sähe."""

    def __init__(self):
        self.warteschlange = logbook.abonnieren()
        self.nachrichten: list[dict] = []

    def einlesen(self):
        while True:
            try:
                self.nachrichten.append(self.warteschlange.get_nowait())
            except Exception:
                break
        return self.nachrichten

    def ereignisse(self, name: str) -> list[dict]:
        return [n for n in self.einlesen() if n.get("typ") == "ereignis"
                and n.get("name") == name]

    def warten_auf(self, name: str, aktion: str, grenze: float = 10.0) -> list[dict]:
        """Wartet, bis ein bestimmtes Ereignis eingetroffen ist.

        Der Auftragsspeicher wird **vor** dem Ereignis geschrieben (`pipeline._bearbeiten`).
        Wer also nur auf den Zustand wartet und danach sofort in die Warteschlange sieht,
        kann das Ereignis um Sekundenbruchteile verpassen — unter Last reicht das für
        einen sprunghaften Test.
        """
        ende = time.monotonic() + grenze
        while time.monotonic() < ende:
            treffer = [e for e in self.ereignisse(name) if e.get("aktion") == aktion]
            if treffer:
                return treffer
            time.sleep(0.1)
        return []

    def schliessen(self):
        logbook.abbestellen(self.warteschlange)


# ── Der große Durchlauf ──────────────────────────────────────────────────────

@pytest.mark.langsam
def test_storyboard_von_der_eingabe_bis_zum_fertigen_film(studio):
    """Vier Szenen, Montage, drei Formate — der Alltagsfall des Werkzeugs."""
    mitschrift = Mitschrift()
    try:
        auftrag = pipeline.starten({
            "briefing": "Werbevideo für eine Handwerksbäckerei in Mannheim",
            "szenen": 4, "sekunden": 5,
            "videomodell": "kling-video/v2.6/pro/image-to-video",
            "formate": ["hoch", "quadrat", "breit"],
            "weiche_uebergaenge": True,
        })
        fertig = warten_bis_fertig(auftrag.id)

        # ── Ergebnis ─────────────────────────────────────────────────────────
        assert fertig.zustand == jobstore.FERTIG, fertig.fehler
        assert studio.bilder == 4, "je Szene ein Startbild"
        assert studio.videos == 4, "je Szene ein Clip"

        film = Path(fertig.ergebnis["film"])
        assert film.exists()
        angaben = media.pruefe_video(film)
        # Vier Clips à 5 s mit drei Überblendungen à 0,4 s ≈ 18,8 s
        assert 17.5 < angaben.dauer < 20.5, f"unerwartete Länge: {angaben.dauer}"
        assert (angaben.breite, angaben.hoehe) == (1920, 1080)

        # ── Formate ──────────────────────────────────────────────────────────
        ordner = film.parent
        for kennung, masse in [("hoch", (1080, 1920)), ("quadrat", (1080, 1080)),
                               ("breit", (1920, 1080))]:
            datei = ordner / f"film_{kennung}.mp4"
            assert datei.exists(), f"{kennung} fehlt"
            assert (media.angaben(datei).breite, media.angaben(datei).hoehe) == masse
        assert (ordner / "film_poster.jpg").exists(), "Vorschaubild fehlt"

        # ── Begleitzettel ────────────────────────────────────────────────────
        zettel = library.begleitzettel_lesen(ordner)
        # Umlaute normalisiert vergleichen: dieselbe Zeichenfolge kann als ein Zeichen
        # oder als Buchstabe plus Trema vorliegen, und beides ist gültiges Unicode.
        import unicodedata

        def gleich(a: str) -> str:
            return unicodedata.normalize("NFC", a)

        assert gleich(zettel["titel"]) == gleich("Testfilm Bäckerei")
        assert gleich("Handwerksbäckerei") in gleich(zettel["briefing"])
        assert "Mannheim" in zettel["briefing"]
        assert len(zettel["drehbuch"]["szenen"]) == 4

        # ── Bibliothek ───────────────────────────────────────────────────────
        eintrag = library.eintrag(ordner)
        assert eintrag["szenen"] == 4
        assert set(eintrag["fassungen"]) >= {"hoch", "quadrat", "breit"}
        fehlend = {f["kennung"] for f in eintrag["fehlende"]}
        assert "gif" in fehlend and "web" in fehlend      # bewusst nicht bestellt

        # ── Was die Oberfläche gesehen hätte ────────────────────────────────
        # Erst abwarten, bis das Schlussereignis da ist: der Auftragsspeicher wird
        # vor den Ereignissen geschrieben, sonst liest der Test zu früh.
        assert mitschrift.warten_auf("auftrag", "fertig"), "Schlussmeldung fehlt"

        bloecke = mitschrift.ereignisse("block")
        fertige = {e["block"] for e in bloecke if e["zustand"] == "fertig"}
        assert fertige == {"briefing", "claude", "bild", "video", "ausgabe"}, \
            "jeder Block muss einmal fertig melden"

        uebergaenge = [(e["von"], e["nach"]) for e in mitschrift.ereignisse("uebergang")]
        assert uebergaenge == [("briefing", "claude"), ("claude", "bild"),
                               ("bild", "video"), ("video", "ausgabe")], \
            "die wandernden Punkte müssen der Reihe nach laufen"

        anteile = [e["anteil"] for e in mitschrift.ereignisse("fortschritt")]
        assert anteile and max(anteile) == 1.0
        assert all(0.0 <= a <= 1.0 for a in anteile), "Fortschritt außerhalb 0…1"

        startbilder = mitschrift.ereignisse("startbild")
        assert len(startbilder) == 4, "jedes Startbild muss angezeigt werden können"
    finally:
        mitschrift.schliessen()


@pytest.mark.langsam
def test_einzelclip_ohne_montage(studio):
    """Der schnelle Fall: ein Clip, keine Überblendung, keine Zusatzformate."""
    auftrag = pipeline.starten({
        "briefing": "Ein einzelner Clip zum Testen",
        "szenen": 1, "sekunden": 5, "formate": [],
    })
    fertig = warten_bis_fertig(auftrag.id)

    assert fertig.zustand == jobstore.FERTIG, fertig.fehler
    assert studio.videos == 1
    angaben = media.pruefe_video(Path(fertig.ergebnis["film"]))
    assert 4.5 < angaben.dauer < 5.5
    assert fertig.ergebnis["formate"] == {}


@pytest.mark.langsam
def test_modell_ohne_startbild_ueberspringt_den_block(studio):
    mitschrift = Mitschrift()
    try:
        auftrag = pipeline.starten({
            "briefing": "Test ohne Startbild", "szenen": 1, "sekunden": 6,
            "videomodell": "minimax/hailuo-02/standard/text-to-video", "formate": [],
        })
        fertig = warten_bis_fertig(auftrag.id)

        assert fertig.zustand == jobstore.FERTIG, fertig.fehler
        assert studio.bilder == 0, "es darf kein Startbild erzeugt werden"
        uebersprungen = [e for e in mitschrift.ereignisse("block")
                         if e["zustand"] == "uebersprungen"]
        assert any(e["block"] == "bild" for e in uebersprungen)
    finally:
        mitschrift.schliessen()


@pytest.mark.langsam
def test_eine_ausgefallene_szene_kostet_nicht_den_ganzen_film(tmp_path, monkeypatch):
    """Scheitert die dritte von vier Szenen, entsteht der Film aus den drei anderen.

    Die fertigen Clips sind bezahlt. Sie wegzuwerfen, weil eine Szene von der
    Moderation abgelehnt wurde oder der Dienst einmal gepatzt hat, war der teuerste
    Ausgang, den das Programm kannte — und beim Kunden der wahrscheinlichste.
    """
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    jobstore.einrichten()

    attrappe = AttrappeHiggsfield(tmp_path / "quelle", scheitert_bei=3)
    monkeypatch.setattr(pipeline.higgsfield, "client", attrappe)
    monkeypatch.setattr(promptsmith.llm, "erzeuge",
                        lambda *_a, **_k: promptsmith.llm.Antwort(
                            json.dumps(DREHBUCH), "cli", "test", 0.1))
    pipeline._aktuell = None

    mitschrift = Mitschrift()
    try:
        auftrag = pipeline.starten({"briefing": "Test mit Fehler", "szenen": 4,
                                    "sekunden": 5, "formate": []})
        fertig = warten_bis_fertig(auftrag.id)

        assert fertig.zustand == jobstore.FERTIG
        assert fertig.ergebnis["szenen"] == 3
        # Verschwiegen wird der Ausfall nicht — er steht im Ergebnis und im Logbuch.
        assert len(fertig.ergebnis["ausgefallen"]) == 1
        assert "Szene 3" in fertig.ergebnis["ausgefallen"][0]
        assert Path(fertig.ergebnis["film"]).is_file()
        assert pipeline.laeuft_gerade() == ""
    finally:
        mitschrift.schliessen()


@pytest.mark.langsam
def test_faellt_jede_szene_aus_endet_der_auftrag_im_fehler(tmp_path, monkeypatch):
    """Die Gegenprobe: Ohne eine einzige Szene gibt es nichts zu montieren, und die
    Oberfläche muss den Grund erfahren — kein stiller leerer Film."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    jobstore.einrichten()

    attrappe = AttrappeHiggsfield(tmp_path / "quelle")
    attrappe.scheitert_immer = True
    monkeypatch.setattr(pipeline.higgsfield, "client", attrappe)
    monkeypatch.setattr(promptsmith.llm, "erzeuge",
                        lambda *_a, **_k: promptsmith.llm.Antwort(
                            json.dumps(DREHBUCH), "cli", "test", 0.1))
    pipeline._aktuell = None

    mitschrift = Mitschrift()
    try:
        auftrag = pipeline.starten({"briefing": "Test ganz kaputt", "szenen": 3,
                                    "sekunden": 5, "formate": []})
        fertig = warten_bis_fertig(auftrag.id)

        assert fertig.zustand == jobstore.FEHLER
        assert "absichtlich" in fertig.fehler["meldung"]
        assert fertig.fehler["art"] == "anbieter"
        assert mitschrift.warten_auf("auftrag", "fehler"), \
            "die Oberfläche muss vom Fehler erfahren"
        # Das Wichtigste: das Programm läuft weiter und nimmt sofort neue Aufträge an.
        assert pipeline.laeuft_gerade() == ""
    finally:
        mitschrift.schliessen()


@pytest.mark.langsam
def test_leeres_guthaben_beendet_den_lauf_sofort(tmp_path, monkeypatch):
    """Kein Guthaben trifft jede Szene gleich. Da ist Weitermachen sinnlos — der Lauf
    muss auf der Stelle enden, statt fünfmal in dieselbe Wand zu laufen."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    jobstore.einrichten()

    attrappe = AttrappeHiggsfield(tmp_path / "quelle")

    def kein_guthaben(*_a, **_k):
        raise errors.GuthabenFehler("Kein Guthaben mehr.", "Aufladen.")

    monkeypatch.setattr(attrappe, "video_aus_bild", kein_guthaben)
    monkeypatch.setattr(pipeline.higgsfield, "client", attrappe)
    monkeypatch.setattr(promptsmith.llm, "erzeuge",
                        lambda *_a, **_k: promptsmith.llm.Antwort(
                            json.dumps(DREHBUCH), "cli", "test", 0.1))
    pipeline._aktuell = None

    auftrag = pipeline.starten({"briefing": "Test ohne Guthaben", "szenen": 5,
                                "sekunden": 5, "formate": []})
    fertig = warten_bis_fertig(auftrag.id)

    assert fertig.zustand == jobstore.FEHLER
    assert fertig.fehler["art"] == "guthaben"
    assert attrappe.bilder == 1, "nach dem Guthabenfehler darf nichts mehr bestellt werden"


@pytest.mark.langsam
def test_abbruch_mitten_im_lauf(studio):
    """Der Abbruchknopf muss wirken, solange noch etwas läuft."""
    auftrag = pipeline.starten({"briefing": "Test zum Abbrechen", "szenen": 8,
                                "sekunden": 5, "formate": []})
    time.sleep(1.5)                       # ein, zwei Szenen laufen lassen
    assert pipeline.abbrechen(auftrag.id) is True

    fertig = warten_bis_fertig(auftrag.id, grenze=90)
    assert fertig.zustand == jobstore.ABGEBROCHEN
    assert studio.videos < 8, "es dürfen nicht alle Szenen fertig geworden sein"
    assert pipeline.laeuft_gerade() == ""


@pytest.mark.langsam
def test_zweiter_auftrag_prallt_ab(studio):
    auftrag = pipeline.starten({"briefing": "Der erste Auftrag", "szenen": 4,
                                "sekunden": 5, "formate": []})
    try:
        with pytest.raises(errors.EingabeFehler):
            pipeline.starten({"briefing": "Der zweite Auftrag", "szenen": 1})
    finally:
        pipeline.abbrechen(auftrag.id)
        warten_bis_fertig(auftrag.id, grenze=90)


@pytest.mark.langsam
def test_format_spaeter_nachziehen(studio):
    """Der Kern des Bibliothekskonzepts: fehlende Fassungen entstehen auf Klick."""
    auftrag = pipeline.starten({"briefing": "Test fürs Nachziehen", "szenen": 1,
                                "sekunden": 5, "formate": []})
    fertig = warten_bis_fertig(auftrag.id)
    assert fertig.zustand == jobstore.FERTIG, fertig.fehler

    ordner_rel = library.web_pfad(Path(fertig.ergebnis["ordner"]))
    assert "hoch" not in library.eintrag(fertig.ergebnis["ordner"])["fassungen"]

    ergebnis = library.format_nachziehen(ordner_rel, "hoch")
    assert ergebnis["ok"]

    danach = library.eintrag(fertig.ergebnis["ordner"])
    assert "hoch" in danach["fassungen"]
    datei = Path(fertig.ergebnis["ordner"]) / "film_hoch.mp4"
    assert (media.angaben(datei).breite, media.angaben(datei).hoehe) == (1080, 1920)


@pytest.mark.langsam
def test_auftrag_ueberlebt_einen_neustart(studio):
    """Nach einem Absturz darf kein Auftrag als „läuft“ hängenbleiben."""
    auftrag = pipeline.starten({"briefing": "Test Neustart", "szenen": 6,
                                "sekunden": 5, "formate": []})
    time.sleep(1.0)
    assert jobstore.holen(auftrag.id).zustand == jobstore.LAEUFT

    pipeline.abbrechen(auftrag.id)
    warten_bis_fertig(auftrag.id, grenze=90)

    # Zustand von Hand auf „läuft“ zurücksetzen, als wäre das Programm abgestürzt.
    jobstore.aktualisieren(auftrag.id, zustand=jobstore.LAEUFT)
    jobstore.einrichten()                        # entspricht dem nächsten Programmstart
    assert jobstore.holen(auftrag.id).zustand == jobstore.ABGEBROCHEN
