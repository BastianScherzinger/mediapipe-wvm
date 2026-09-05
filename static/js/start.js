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
  let reihe = [];

  // `pruefen` heißt nach außen so, wie der Knopf beschriftet ist. Die Abo-Anmeldung
  // ruft es auf, damit die Lampen sofort den neuen Zugang zeigen.
  MPW.start = { auftragStarten, auftragAbbrechen, pruefen: selbsttest };

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
    MPW.beiEreignis("warteschlange", () => zustandAbgleichen());
    MPW.beiEreignis("verbunden", zustandAbgleichen);

    await zustandAbgleichen();

    if (!start.diagnose.startbereit) {
      const offen = start.diagnose.befunde.filter((b) => b.zustand === "fehler");
      zeile(offen.map((b) => b.meldung).join(" "), "fehler");
      MPW.melden("Es fehlt etwas — oben rechts auf „Prüfen“ klicken.", "fehler", 10000);
    }
  }

  /* ── Zustand nach Neuladen oder Unterbrechung ──────────────────────────── */

  async function zustandAbgleichen() {
    try {
      const antwort = await MPW.hole("/api/zustand");
      laufenderAuftrag = antwort.laufender_auftrag || "";
      reiheZeichnen(antwort.warteschlange || []);
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

    // Läuft schon etwas, wird dieser Auftrag eingereiht statt abgewiesen. Der Ablauf
    // links darf dann NICHT zurückgesetzt werden — dort läuft ja noch der andere.
    const stelltSichAn = Boolean(laufenderAuftrag);
    if (!stelltSichAn) {
      MPW.formular.sperren(true);
      MPW.ablauf.zuruecksetzen();
    }
    zeile(stelltSichAn ? "Auftrag wird eingereiht …" : "Auftrag wird angenommen …");

    try {
      const antwort = await MPW.hole("/api/auftrag", { koerper: auftrag });
      reiheZeichnen(antwort.warteschlange || []);
      if (antwort.gestartet) {
        laufenderAuftrag = antwort.auftrag.id;
        zeile("Läuft. Sie können das Fenster offen lassen.");
      } else {
        const platz = (antwort.warteschlange || []).length;
        zeile(`Eingereiht — Platz ${platz}. Startet von selbst, sobald der laufende ` +
              "Auftrag fertig ist.", "erfolg");
        MPW.melden("Auftrag eingereiht.", "erfolg", 3500);
      }
    } catch (fehler) {
      if (!stelltSichAn) MPW.formular.sperren(false);
      zeile(fehler.meldung || fehler.message, "fehler");
      MPW.melden(fehler.message, "fehler", 9000);
    }
  }

  /* ── Warteschlange ──────────────────────────────────────────────────────
   *
   * Sie erscheint nur, wenn wirklich etwas ansteht. Wer ein einzelnes Video macht,
   * soll von ihr nichts mitbekommen.
   */
  function reiheZeichnen(eintraege) {
    reihe = eintraege || [];
    const behaelter = MPW.$("#reihe");
    if (!reihe.length) {
      behaelter.hidden = true;
      behaelter.replaceChildren();
      return;
    }
    behaelter.hidden = false;
    behaelter.replaceChildren(...reihe.map((eintrag) =>
      MPW.el("div", { klasse: "reihe-zeile" }, [
        MPW.el("span", { klasse: "reihe-platz", text: String(eintrag.platz) }),
        MPW.el("span", { klasse: "reihe-titel", text: eintrag.titel || "Auftrag",
                         title: eintrag.briefing || "" }),
        MPW.el("button", {
          klasse: "knopf knopf-mini", type: "button",
          title: "Aus der Reihe nehmen", "aria-label": "Aus der Reihe nehmen",
          onclick: () => ausReiheNehmen(eintrag.id),
        }, [MPW.icon("schliessen")]),
      ])));
  }

  async function ausReiheNehmen(kennung) {
    try {
      const antwort = await MPW.hole(`/api/warteschlange/${kennung}`,
                                     { method: "DELETE" });
      reiheZeichnen(antwort.warteschlange || []);
    } catch (fehler) {
      MPW.melden(fehler.message, "fehler");
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
      // Steht noch etwas an, startet es in diesem Moment von selbst. Kurz später
      // nachfragen, statt den Zustand zu erraten.
      window.setTimeout(zustandAbgleichen, 900);
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

      // Die Higgsfield-Lampe steht für „es können Videos entstehen“, nicht für einen
      // bestimmten Zugang. Grün also auch dann, wenn nicht die Platform-API, sondern
      // das verbundene Abo die Arbeit macht.
      const wege = e.videowege || [];
      const echt = wege.find((w) => (w.weg === "platform" || w.weg === "abo") && w.ok);
      const probe = wege.find((w) => w.weg === "demo" && w.ok);
      lampeSetzen("higgsfield",
                  echt ? "gut" : (probe ? "warnung" : "schlecht"),
                  echt ? echt.name + ": " + echt.meldung
                       : (e.higgsfield.meldung + " " + (e.higgsfield.hinweis || "")));

      lampeSetzen("ffmpeg", e.ffmpeg.ok ? "gut" : "schlecht", e.ffmpeg.meldung);

      const bereit = (e.sprachmodelle || []).filter((w) => w.bereit);
      lampeSetzen("claude", bereit.length ? "gut" : "schlecht",
                  bereit.length ? "Schreibt das Drehbuch. Verfügbar: " +
                                  bereit.map((w) => w.name).join(", ")
                                : "Kein Sprachmodell verfügbar.");

      const probleme = [
        !echt ? "Higgsfield: " + e.higgsfield.meldung : null,
        !e.ffmpeg.ok ? "Videoschnitt: " + e.ffmpeg.meldung : null,
        !bereit.length ? "Kein Sprachmodell für das Drehbuch erreichbar." : null,
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
    lampe.title = (titel || "").trim() + "  (klicken, um alles zu prüfen)";
  }

  function zeile(text, art) {
    const feld = $("#startzeile");
    feld.textContent = text;
    if (art) feld.dataset.art = art; else delete feld.dataset.art;
  }

})(window.MPW);
