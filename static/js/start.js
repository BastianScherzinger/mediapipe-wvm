/* start.js — bringt alles zusammen.
 *
 * Holt die Grunddaten, baut die Bereiche auf, verbindet den Ereignisstrom und regelt
 * das Starten und Abbrechen eines Auftrags. Der letzte Teil ist der heikelste: die
 * Oberfläche muss auch dann einen richtigen Zustand zeigen, wenn sie mitten in einem
 * laufenden Auftrag neu geladen wird.
 */
"use strict";

(function (MPW) {
  const { $ } = MPW;

  let laufenderAuftrag = "";

  MPW.start = { auftragStarten, auftragAbbrechen };

  document.addEventListener("DOMContentLoaded", hochfahren);

  async function hochfahren() {
    MPW.logbuch.aufbauen();

    let start;
    try {
      start = await MPW.hole("/api/start");
    } catch (fehler) {
      zeile("Das Programm antwortet nicht. Bitte neu starten.", "fehler");
      MPW.melden(fehler.message, "fehler", 12000);
      return;
    }

    document.title = `${start.app.name} ${start.app.version} — KI-Video-Studio`;

    MPW.ablauf.aufbauen(start.bloecke);
    MPW.formular.aufbauen(start);
    MPW.bibliothek.aufbauen();
    MPW.aktualisierung.aufbauen();
    MPW.abo.aufbauen();

    lampenSetzen(start.diagnose);
    $("#btn-selbsttest").addEventListener("click", selbsttest);
    for (const lampe of MPW.$$(".lampe")) lampe.addEventListener("click", selbsttest);

    MPW.stromVerbinden();
    MPW.beiEreignis("auftrag", auftragsereignis);
    MPW.beiEreignis("verbunden", zustandAbgleichen);

    await zustandAbgleichen();

    if (!start.diagnose.startbereit) {
      const offen = start.diagnose.befunde.filter((b) => b.zustand === "fehler");
      zeile(offen.map((b) => b.meldung).join(" "), "fehler");
      MPW.melden("Es fehlt etwas — siehe Selbsttest oben rechts.", "fehler", 10000);
    }
  }

  /* ── Zustand nach Neuladen oder Unterbrechung ──────────────────────────── */

  async function zustandAbgleichen() {
    try {
      const antwort = await MPW.hole("/api/zustand");
      laufenderAuftrag = antwort.laufender_auftrag || "";
      MPW.formular.sperren(Boolean(laufenderAuftrag));
      MPW.aktualisierung.auftragszustand(Boolean(laufenderAuftrag));

      if (laufenderAuftrag && antwort.auftrag) {
        // Die Blöcke vor dem aktuellen sind fertig, der aktuelle arbeitet. Das ist eine
        // Näherung, aber eine ehrliche: sie stimmt mit dem überein, was der Server weiß.
        zeile("Ein Auftrag läuft: " + (antwort.auftrag.titel || "").slice(0, 60));
        MPW.ablauf.notiz("Läuft …");
      } else {
        const letzter = (antwort.letzte || [])[0];
        if (letzter && letzter.zustand === "fehler") {
          zeile(letzter.fehler?.meldung || "Der letzte Auftrag ist fehlgeschlagen.", "fehler");
        } else if (letzter && letzter.zustand === "fertig") {
          zeile("Bereit. Zuletzt: " + (letzter.titel || "").slice(0, 50), "erfolg");
        } else {
          zeile("Bereit.");
        }
      }
    } catch (fehler) {
      zeile("Kein Kontakt zum Programm.", "fehler");
    }
  }

  /* ── Auftrag starten ───────────────────────────────────────────────────── */

  async function auftragStarten() {
    let auftrag;
    try {
      auftrag = MPW.formular.sammeln();
    } catch (fehler) {
      zeile(fehler.message, "fehler");
      MPW.melden(fehler.message, "fehler");
      return;
    }

    MPW.formular.sperren(true);
    zeile("Auftrag wird angenommen …");
    MPW.ablauf.zuruecksetzen();

    try {
      const antwort = await MPW.hole("/api/auftrag", { koerper: auftrag });
      laufenderAuftrag = antwort.auftrag.id;
      zeile("Läuft. Sie können das Fenster offen lassen.");
    } catch (fehler) {
      MPW.formular.sperren(false);
      zeile(fehler.meldung || fehler.message, "fehler");
      MPW.melden(fehler.message, "fehler", 9000);
    }
  }

  async function auftragAbbrechen() {
    if (!laufenderAuftrag) { MPW.formular.sperren(false); return; }
    $("#btn-abbruch").disabled = true;
    try {
      await MPW.hole(`/api/auftrag/${laufenderAuftrag}/abbrechen`, { method: "POST" });
      zeile("Abbruch angefordert — laufende Schritte werden beendet.");
    } catch (fehler) {
      MPW.melden(fehler.message, "fehler");
      // Läuft nichts mehr, ist der Abbruch faktisch schon geschehen.
      MPW.formular.sperren(false);
      laufenderAuftrag = "";
    } finally {
      $("#btn-abbruch").disabled = false;
    }
  }

  function auftragsereignis(nachricht) {
    if (nachricht.aktion === "gestartet") {
      laufenderAuftrag = nachricht.auftrag?.id || laufenderAuftrag;
      MPW.formular.sperren(true);
      // Kein Neustart, solange Guthaben in Arbeit ist.
      MPW.aktualisierung.auftragszustand(true);
      return;
    }
    if (["fertig", "fehler", "abgebrochen"].includes(nachricht.aktion)) {
      laufenderAuftrag = "";
      MPW.formular.sperren(false);
      MPW.aktualisierung.auftragszustand(false);
    }
    if (nachricht.aktion === "fertig") {
      const titel = nachricht.ergebnis?.titel || "Video";
      zeile("Fertig: " + titel, "erfolg");
      MPW.melden("Video fertig — es steht unten in der Übersicht.", "erfolg", 7000);
    } else if (nachricht.aktion === "fehler") {
      const meldung = nachricht.fehler?.meldung || "Fehlgeschlagen.";
      const hinweis = nachricht.fehler?.hinweis || "";
      zeile(meldung + (hinweis ? " " + hinweis : ""), "fehler");
      MPW.melden(meldung, "fehler", 11000);
    } else if (nachricht.aktion === "abgebrochen") {
      zeile("Abgebrochen.");
    }
  }

  /* ── Selbsttest und Lampen ─────────────────────────────────────────────── */

  async function selbsttest() {
    const knopf = $("#btn-selbsttest");
    knopf.disabled = true;
    try {
      const antwort = await MPW.hole("/api/selbsttest", { method: "POST" });
      const e = antwort.ergebnis;

      lampenSetzen(e.system);
      lampeSetzen("higgsfield", e.higgsfield.ok ? "gut" :
                  (e.higgsfield.guthaben === "leer" ? "warnung" : "schlecht"),
                  e.higgsfield.meldung + " " + (e.higgsfield.hinweis || ""));
      lampeSetzen("ffmpeg", e.ffmpeg.ok ? "gut" : "schlecht", e.ffmpeg.meldung);

      const bereit = (e.sprachmodelle || []).filter((w) => w.bereit);
      lampeSetzen("claude", bereit.length ? "gut" : "schlecht",
                  bereit.length ? "Verfügbar: " + bereit.map((w) => w.name).join(", ")
                                : "Kein Sprachmodell verfügbar.");

      const probleme = [
        !e.higgsfield.ok ? "Higgsfield: " + e.higgsfield.meldung : null,
        !e.ffmpeg.ok ? "ffmpeg: " + e.ffmpeg.meldung : null,
        !bereit.length ? "Kein Sprachmodell erreichbar." : null,
      ].filter(Boolean);

      if (probleme.length) MPW.melden(probleme.join(" · "), "fehler", 12000);
      else MPW.melden("Alles bereit.", "erfolg");
    } catch (fehler) {
      MPW.melden(fehler.message, "fehler");
    } finally {
      knopf.disabled = false;
    }
  }

  function lampenSetzen(diagnose) {
    for (const befund of diagnose.befunde || []) {
      const zustand = befund.zustand === "ok" ? "gut"
                    : befund.zustand === "warnung" ? "warnung" : "schlecht";
      if (befund.name === "Higgsfield") lampeSetzen("higgsfield", zustand, befund.meldung);
      if (befund.name === "Sprachmodell") lampeSetzen("claude", zustand, befund.meldung);
      if (befund.name === "ffmpeg") lampeSetzen("ffmpeg", zustand, befund.meldung);
    }
  }

  function lampeSetzen(name, zustand, titel) {
    const lampe = $("#lampe-" + name);
    if (!lampe) return;
    lampe.dataset.zustand = zustand;
    lampe.title = (titel || "").trim() + "  (klicken für den Selbsttest)";
  }

  function zeile(text, art) {
    const feld = $("#startzeile");
    feld.textContent = text;
    if (art) feld.dataset.art = art; else delete feld.dataset.art;
  }

})(window.MPW);
