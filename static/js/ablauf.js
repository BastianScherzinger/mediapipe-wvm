/* ablauf.js — die Blockkette rechts oben.
 *
 * Fünf Blöcke nebeneinander, dazwischen Verbindungen. Der arbeitende Block leuchtet
 * hinter der Glasfläche, und beim Übergang läuft ein Punkt zum nächsten. Das ist keine
 * Dekoration: es ist die einzige Stelle, an der man auf einen Blick sieht, wo der
 * Auftrag steht, ohne das Logbuch lesen zu müssen.
 *
 * Es gibt zwei Blocksätze: den des Video-Studios (Briefing → Claude → Startbild →
 * Higgsfield → Ausgabe) und den der Webseiten-Werbung (Webseite → Aufnahmen → Konzept →
 * Schnitt → Ausgabe). Welcher gezeigt wird, entscheidet der laufende Auftrag.
 *
 * Die Anzeige folgt ausschließlich Ereignissen vom Server. Sie fragt nichts ab und
 * erfindet nichts — was hier leuchtet, passiert wirklich gerade.
 */
"use strict";

(function (MPW) {
  const { $, el, icon } = MPW;

  const SYMBOLE = {
    briefing: "briefing", claude: "claude", bild: "bild", video: "film", ausgabe: "ausgabe",
    pruefen: "link", aufnahme: "handy", konzept: "claude", schnitt: "film",
    material: "ordner", prompt: "claude", bauen: "stern", render: "film",
  };

  const saetze = { video: [], webseite: [], premium: [] };
  let bloecke = [];
  const knoten = new Map();          // Blockkennung → Elemente
  let restUhr = null;
  let verdrahtet = false;

  MPW.ablauf = { aufbauen, zuruecksetzen, notiz, fuerAuftrag, fuerBereich };

  /* ── Aufbau ────────────────────────────────────────────────────────────── */

  function aufbauen(liste, webseitenListe, premiumListe) {
    saetze.video = liste || [];
    saetze.webseite = webseitenListe || [];
    saetze.premium = premiumListe || [];
    zeichnen(saetze.video);
    if (!verdrahtet) { verdrahten(); verdrahtet = true; }
  }

  /** Stellt den Blocksatz passend zum Auftrag ein — nur, wenn er sich ändert. */
  function fuerAuftrag(auftrag) {
    const gemeldet = auftrag?.einstellungen?.art;
    const art = saetze[gemeldet]?.length ? gemeldet : "video";
    const liste = saetze[art].length ? saetze[art] : saetze.video;
    if (liste.map((b) => b.kennung).join() !== bloecke.map((b) => b.kennung).join()) {
      zeichnen(liste);
    }
  }

  /** Zeigt beim Wechsel des Bereichs dessen Blöcke — aber nur, solange nichts läuft.
   *  Vorher stand im Premium-Bereich bis zum ersten Auftrag „Briefing · Claude ·
   *  Startbild · Higgsfield“, also der Ablauf eines ganz anderen Werkzeugs. */
  function fuerBereich(seite) {
    if (MPW.start?.laeuft?.()) return;
    const art = { studio: "video", webseite: "webseite", premium: "premium" }[seite] || "video";
    fuerAuftrag({ einstellungen: { art } });
  }

  function zeichnen(liste) {
    bloecke = liste;
    knoten.clear();
    stoppeZaehler();
    const teile = [];
    liste.forEach((block, stelle) => {
      if (stelle > 0) teile.push(verbindungBauen(liste[stelle - 1].kennung, block.kennung));
      teile.push(blockBauen(block));
    });
    $("#ablauf").replaceChildren(...teile);
  }

  function blockBauen(block) {
    const symbol = el("div", { klasse: "block-symbol" }, [icon(SYMBOLE[block.kennung] || "briefing")]);
    const name = el("div", { klasse: "block-name", text: block.name });
    const notizFeld = el("div", { klasse: "block-notiz", text: "" });
    const fuellung = el("div", { klasse: "block-fuellung" });
    const balken = el("div", { klasse: "block-balken" }, [fuellung]);
    const rest = el("div", { klasse: "block-rest", text: "" });

    const wurzel = el("div", {
      klasse: "block",
      daten: { block: block.kennung, zustand: "wartend" },
      role: "group",
      "aria-label": block.name,
    }, [symbol, name, notizFeld, balken, rest]);

    knoten.set(block.kennung, { wurzel, notiz: notizFeld, fuellung, rest, vorschau: null });
    return wurzel;
  }

  function verbindungBauen(von, nach) {
    const punkt = el("span", { klasse: "punkt" });
    return el("div", {
      klasse: "verbindung",
      daten: { von, nach, genommen: "nein" },
      "aria-hidden": "true",
    }, [punkt]);
  }

  /* ── Ereignisse ────────────────────────────────────────────────────────── */

  function verdrahten() {
    MPW.beiEreignis("block", (nachricht) => {
      const eintrag = knoten.get(nachricht.block);
      if (!eintrag) return;

      eintrag.wurzel.dataset.zustand = nachricht.zustand;
      eintrag.notiz.textContent = nachricht.text || "";

      if (nachricht.zustand === "fertig") {
        eintrag.fuellung.style.width = "100%";
        eintrag.rest.textContent = "";
      } else if (nachricht.zustand === "wartend") {
        eintrag.fuellung.style.width = "0";
        eintrag.rest.textContent = "";
        vorschauEntfernen(eintrag);
      } else if (nachricht.zustand === "fehler") {
        eintrag.rest.textContent = "";
      }

      if (nachricht.zustand === "aktiv") notiz(blockName(nachricht.block) + " arbeitet …");
    });

    MPW.beiEreignis("fortschritt", (nachricht) => {
      const eintrag = knoten.get(nachricht.block);
      if (!eintrag) return;
      eintrag.fuellung.style.width = Math.round((nachricht.anteil || 0) * 100) + "%";

      if (nachricht.rest > 2) {
        eintrag.rest.textContent = "noch ~" + MPW.zeitspanne(nachricht.rest);
        // Die Restzeit soll auch zwischen zwei Meldungen weiterlaufen, sonst wirkt
        // die Anzeige eingefroren, obwohl alles in Ordnung ist.
        weiterzaehlen(eintrag, nachricht.rest);
      } else {
        stoppeZaehler();
        eintrag.rest.textContent = nachricht.text || "";
      }
      if (nachricht.text) eintrag.notiz.textContent = nachricht.text;
    });

    MPW.beiEreignis("uebergang", (nachricht) => {
      const leitung = $(`.verbindung[data-von="${nachricht.von}"][data-nach="${nachricht.nach}"]`);
      if (!leitung) return;
      const punkt = $(".punkt", leitung);
      punkt.classList.remove("wandert");
      void punkt.offsetWidth;                     // Neustart der Abspielfolge erzwingen
      punkt.classList.add("wandert");
      leitung.dataset.genommen = "ja";
    });

    const vorschauZeigen = (block, datei, text, hoch) => {
      const eintrag = knoten.get(block);
      if (!eintrag || !datei) return;
      vorschauEntfernen(eintrag);
      eintrag.vorschau = el("img", {
        klasse: "block-vorschau", src: "/medien/" + datei, alt: text, loading: "lazy",
        daten: hoch ? { hoch: "ja" } : {},
      });
      eintrag.wurzel.append(eintrag.vorschau);
    };
    MPW.beiEreignis("startbild", (n) =>
      vorschauZeigen("bild", n.datei, "Startbild der Szene " + (n.szene || "")));
    MPW.beiEreignis("vorschau", (n) =>
      vorschauZeigen(n.block, n.datei, "Aufnahme der Webseite", true));

    MPW.beiEreignis("auftrag", (nachricht) => {
      if (nachricht.aktion === "gestartet") {
        fuerAuftrag(nachricht.auftrag);
        zuruecksetzen();
      } else if (nachricht.aktion === "fertig") { stoppeZaehler(); notiz("Fertig."); }
      else if (nachricht.aktion === "abgebrochen") { stoppeZaehler(); notiz("Abgebrochen."); }
      else if (nachricht.aktion === "fehler") {
        stoppeZaehler();
        notiz(nachricht.fehler?.meldung || "Fehlgeschlagen.");
      }
    });
  }

  function blockName(kennung) {
    return (bloecke.find((b) => b.kennung === kennung) || {}).name || kennung;
  }

  /* ── Restzeit weiterlaufen lassen ──────────────────────────────────────── */

  function weiterzaehlen(eintrag, sekunden) {
    stoppeZaehler();
    let rest = sekunden;
    restUhr = setInterval(() => {
      rest -= 1;
      if (rest <= 1) { stoppeZaehler(); eintrag.rest.textContent = "gleich fertig"; return; }
      eintrag.rest.textContent = "noch ~" + MPW.zeitspanne(rest);
    }, 1000);
  }

  function stoppeZaehler() {
    if (restUhr) { clearInterval(restUhr); restUhr = null; }
  }

  function vorschauEntfernen(eintrag) {
    if (eintrag.vorschau) { eintrag.vorschau.remove(); eintrag.vorschau = null; }
  }

  /* ── Zurücksetzen ──────────────────────────────────────────────────────── */

  function zuruecksetzen() {
    stoppeZaehler();
    for (const eintrag of knoten.values()) {
      eintrag.wurzel.dataset.zustand = "wartend";
      eintrag.notiz.textContent = "";
      eintrag.rest.textContent = "";
      eintrag.fuellung.style.width = "0";
      vorschauEntfernen(eintrag);
    }
    for (const leitung of MPW.$$(".verbindung")) {
      leitung.dataset.genommen = "nein";
      MPW.$(".punkt", leitung).classList.remove("wandert");
    }
  }

  function notiz(text) {
    $("#ablauf-notiz").textContent = text;
  }

})(window.MPW);
