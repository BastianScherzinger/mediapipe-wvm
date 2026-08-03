/* abo.js — Anmeldung des Higgsfield-Abos.
 *
 * Hintergrund: Higgsfield führt zwei getrennte Guthaben. Der API-Schlüssel greift auf den
 * einen zu, das Web-Abo auf den anderen. Ist der API-Topf leer, ist die Anmeldung am Abo
 * der einzige Weg zu echten Videos — und die braucht genau einen Klick im Browser.
 *
 * Der Knopf zeigt sich nur, wenn er gebraucht wird: entweder ist das Abo verbunden (dann
 * steht es dort), oder es ist nicht verbunden und der API-Weg hat kein Guthaben (dann
 * lädt der Knopf zur Anmeldung ein).
 */
"use strict";

(function (MPW) {
  const { $, el } = MPW;

  let stand = null;
  let wartetAufBestaetigung = false;

  MPW.abo = { aufbauen, laden };

  function aufbauen() {
    const knopf = $("#btn-abo");
    if (!knopf) return;
    knopf.addEventListener("click", anklicken);
    laden();
  }

  async function laden() {
    try {
      const antwort = await MPW.hole("/api/abo");
      stand = antwort;
      zeichnen();
    } catch (fehler) {
      // Kein Grund zur Aufregung — dann bleibt der Knopf eben verborgen.
    }
    return stand;
  }

  function zeichnen() {
    const knopf = $("#btn-abo");
    const text = $("#abo-text");
    if (!knopf || !stand) return;

    const angemeldet = Boolean(stand.abo?.angemeldet);
    const platform = (stand.wege || []).find((w) => w.weg === "platform") || {};
    const abo = (stand.wege || []).find((w) => w.weg === "abo") || {};

    // Der Knopf erscheint, sobald er etwas nützt: wenn das Abo verbunden ist (dann
    // zeigt er das an), oder wenn beim API-Weg nicht zweifelsfrei Guthaben vorhanden
    // ist. „Zuletzt bestätigt“ zählt dabei nicht als Gewissheit — ein leerer Topf
    // fällt sonst erst mitten im Auftrag auf.
    const platformSicher = platform.bereit && platform.guthaben === "vorhanden" &&
                           platform.zustand === "bereit";
    knopf.hidden = !(angemeldet || !platformSicher);
    if (knopf.hidden) return;

    if (wartetAufBestaetigung) {
      text.textContent = "Warte auf Bestätigung …";
      knopf.dataset.zustand = "wartet";
      knopf.disabled = true;
      return;
    }

    knopf.disabled = false;
    if (angemeldet) {
      text.textContent = "Abo verbunden";
      knopf.dataset.zustand = "verbunden";
      knopf.title = (abo.meldung || "") +
        "  ·  Aktiver Weg für Videos: " + (stand.aktiv || "?") +
        "  ·  Klicken zum Abmelden.";
    } else {
      text.textContent = "Abo anmelden";
      knopf.dataset.zustand = "offen";
      knopf.title = "Higgsfield-Abo verbinden — einmalig im Browser bestätigen. " +
        "Danach laufen die Videos über die Credits des Abos statt über den " +
        "(leeren) API-Topf.";
    }
  }

  async function anklicken() {
    if (!stand) return;

    if (stand.abo?.angemeldet) {
      if (!window.confirm("Higgsfield-Abo abmelden?\n\nDanach laufen Videos wieder über " +
                          "den API-Schlüssel.")) return;
      try {
        await MPW.hole("/api/abo/abmelden", { method: "POST" });
        MPW.melden("Abo abgemeldet.", "erfolg");
        await laden();
      } catch (fehler) {
        MPW.melden(fehler.message, "fehler");
      }
      return;
    }

    wartetAufBestaetigung = true;
    zeichnen();

    let adresse = "";
    try {
      const antwort = await MPW.hole("/api/abo/anmelden", { koerper: { browser: true } });
      adresse = antwort.anmeldung?.url || "";
    } catch (fehler) {
      wartetAufBestaetigung = false;
      zeichnen();
      MPW.melden(fehler.message, "fehler", 12000);
      return;
    }

    if (adresse) fensterZeigen(adresse);

    // Auf die Bestätigung warten. Der Server hält den Rückruf offen, wir fragen nur nach.
    const bis = Date.now() + 305000;
    while (Date.now() < bis) {
      await new Promise((f) => setTimeout(f, 2000));
      let jetzt;
      try {
        jetzt = (await MPW.hole("/api/abo/anmelden")).anmeldung;
      } catch (fehler) {
        continue;
      }
      if (jetzt.angemeldet) {
        wartetAufBestaetigung = false;
        fensterSchliessen();
        await laden();
        MPW.melden("Higgsfield-Abo verbunden — Videos laufen jetzt über die Abo-Credits.",
                   "erfolg", 9000);
        return;
      }
      if (!jetzt.laeuft && jetzt.ergebnis && jetzt.ergebnis.ok === false) {
        wartetAufBestaetigung = false;
        fensterSchliessen();
        zeichnen();
        MPW.melden((jetzt.ergebnis.meldung || "Anmeldung fehlgeschlagen.") + " " +
                   (jetzt.ergebnis.hinweis || ""), "fehler", 14000);
        return;
      }
    }

    wartetAufBestaetigung = false;
    fensterSchliessen();
    zeichnen();
    MPW.melden("Die Anmeldung wurde nicht bestätigt.", "fehler", 9000);
  }

  /* ── Hinweisfenster mit der Adresse ─────────────────────────────────────── */

  function fensterZeigen(adresse) {
    fensterSchliessen();
    const fenster = el("dialog", { klasse: "schau abo-fenster", id: "abo-fenster" }, [
      el("div", { klasse: "schau-kopf" }, [
        el("h3", { text: "Higgsfield-Abo verbinden" }),
      ]),
      el("div", { klasse: "abo-inhalt" }, [
        el("p", { text: "Im Browser hat sich die Anmeldeseite von Higgsfield geöffnet. " +
                        "Bitte dort bestätigen — danach geht es hier automatisch weiter." }),
        el("p", { klasse: "hinweis",
                  text: "Falls sich kein Browser geöffnet hat, diese Adresse aufrufen:" }),
        el("div", { klasse: "abo-adresse" }, [
          el("code", { text: adresse }),
        ]),
        el("div", { klasse: "abo-knoepfe" }, [
          el("button", {
            klasse: "knopf", type: "button", text: "Adresse kopieren",
            onclick: async () => {
              try {
                await navigator.clipboard.writeText(adresse);
                MPW.melden("Adresse kopiert.", "erfolg", 2500);
              } catch (fehler) {
                MPW.melden("Kopieren war nicht möglich.", "fehler");
              }
            },
          }),
          el("a", { klasse: "knopf knopf-haupt", href: adresse, target: "_blank",
                    rel: "noopener", text: "Im Browser öffnen" }),
        ]),
        el("p", { klasse: "abo-warten", text: "Warte auf die Bestätigung …" }),
      ]),
    ]);
    document.body.append(fenster);
    fenster.showModal();
  }

  function fensterSchliessen() {
    const fenster = $("#abo-fenster");
    if (fenster) {
      try { fenster.close(); } catch (e) { /* war schon zu */ }
      fenster.remove();
    }
  }

})(window.MPW);
