/* premium.js — die Seite „Premium-Film“.
 *
 * Der Bereich stellt Fragen, statt ein Formular hinzustellen: Zuerst *worüber*, und erst
 * danach erscheinen die Felder, die zu dieser Antwort gehören. Wer einen Link hat, soll
 * kein Ordnerfeld sehen; wer nur ein Thema hat, keinen Prüfen-Knopf.
 *
 * Hochgeladenes Material geht sofort in einen Korb auf dem Server — nicht erst beim
 * Start. So kostet ein großer Ordner keine Wartezeit im Moment des Klicks, und die
 * Anzeige kann sagen, was wirklich angekommen ist.
 *
 * Der Auftrag läuft anschließend durch dieselbe Warteschlange, denselben Ablauf und
 * dieselbe Bibliothek wie jedes andere Video.
 */
"use strict";

(function (MPW) {
  const { $, $$, el } = MPW;

  const zustand = {
    katalog: null,
    quelle: "webseite",
    fokus: "auto",
    tonfall: "polished",
    dauer: 22,
    korb: "",
    material: [],
    geprueft: null,
    geprueftFuer: "",
    ordner: null,
    laeuft: false,
  };

  const SPEICHER = "mpw.premium";

  MPW.premium = { aufbauen, sperren, zeile, promptZeigen, fokusGemeldet };

  function aufbauen(start) {
    zustand.katalog = start.premium || null;
    if (!zustand.katalog) return;

    quellenBauen();
    fokusBauen();
    tonfaelleBauen();
    dauerBauen();
    modelleBauen();
    sprachenBauen();
    befundZeigen(zustand.katalog.befund || {});

    $("#pr-form").addEventListener("submit", (e) => { e.preventDefault(); urlPruefen(); });
    $("#pr-url").addEventListener("input", () => {
      if (zustand.geprueft && $("#pr-url").value.trim() !== zustand.geprueftFuer) {
        zustand.geprueft = null;
        $("#pr-karte").hidden = true;
      }
      merken();
    });
    $("#btn-pr-ordner").addEventListener("click", ordnerWaehlen);
    $("#pr-ordner").addEventListener("change", () => ordnerPruefen($("#pr-ordner").value));

    $("#btn-pr-bilder").addEventListener("click", () => $("#pr-dateien").click());
    $("#btn-pr-ordner-hoch").addEventListener("click", () => $("#pr-ordnerdateien").click());
    $("#pr-dateien").addEventListener("change", (e) => hochladen(e.target.files));
    $("#pr-ordnerdateien").addEventListener("change", (e) => hochladen(e.target.files));
    $("#btn-pr-material-weg").addEventListener("click", materialVerwerfen);

    for (const feld of ["#pr-kunde", "#pr-zielgruppe", "#pr-botschaft", "#pr-cta",
                        "#pr-kontakt", "#pr-wunsch", "#pr-thema", "#pr-modell",
                        "#pr-sprache"]) {
      $(feld).addEventListener("change", merken);
    }
    $("#btn-pr-start").addEventListener("click", starten);

    wiederherstellen();
    quelleSetzen(zustand.quelle);
  }

  /* ── Bausteine ─────────────────────────────────────────────────────────── */

  function quellenBauen() {
    $("#pr-quellen").replaceChildren(...zustand.katalog.quellen.map((q) =>
      el("button", {
        klasse: "stil", type: "button", role: "radio", "aria-checked": "false",
        daten: { quelle: q.kennung }, onclick: () => quelleSetzen(q.kennung),
      }, [
        el("span", { klasse: "stil-name", text: q.name }),
        el("span", { klasse: "stil-text", text: q.beschreibung }),
      ])));
  }

  function fokusBauen() {
    $("#pr-fokus").replaceChildren(...(zustand.katalog.fokus || []).map((f) =>
      el("button", {
        klasse: "stil", type: "button", role: "radio", "aria-checked": "false",
        daten: { fokus: f.kennung }, onclick: () => fokusSetzen(f.kennung),
      }, [
        el("span", { klasse: "stil-name", text: f.name }),
        el("span", { klasse: "stil-text", text: f.beschreibung }),
      ])));
  }

  function fokusSetzen(kennung) {
    zustand.fokus = kennung;
    for (const knopf of $$("#pr-fokus .stil")) {
      const an = knopf.dataset.fokus === kennung;
      knopf.classList.toggle("ist-an", an);
      knopf.setAttribute("aria-checked", an ? "true" : "false");
    }
    merken();
  }

  function tonfaelleBauen() {
    $("#pr-tonfaelle").replaceChildren(...zustand.katalog.tonfaelle.map((t) =>
      el("button", {
        klasse: "stil", type: "button", role: "radio", "aria-checked": "false",
        daten: { tonfall: t.kennung }, onclick: () => tonfallSetzen(t.kennung),
      }, [
        el("span", { klasse: "stil-name", text: t.name }),
        el("span", { klasse: "stil-text", text: t.beschreibung }),
      ])));
  }

  function dauerBauen() {
    $("#pr-dauer").replaceChildren(...zustand.katalog.dauern.map((d) =>
      el("button", {
        klasse: "segment-knopf", type: "button", role: "radio", "aria-checked": "false",
        daten: { dauer: String(d) }, text: d + " s",
        onclick: () => dauerSetzen(d),
      })));
  }

  function modelleBauen() {
    $("#pr-modell").replaceChildren(...zustand.katalog.modelle.map((m) =>
      el("option", { value: m.id, text: m.name })));
    $("#pr-modell").value = zustand.katalog.modell_vorgabe;
  }

  function sprachenBauen() {
    $("#pr-sprache").replaceChildren(...zustand.katalog.sprachen.map((s) =>
      el("option", { value: s.kennung, text: s.name })));
  }

  function befundZeigen(befund) {
    const feld = $("#pr-befund");
    if (befund.bereit) {
      feld.textContent = `Bereit — Claude-CLI, Node ${befund.node} und ffmpeg sind da. ` +
        "Ein Film braucht je nach Material 8 bis 25 Minuten.";
      feld.dataset.art = "gut";
    } else {
      feld.textContent = "Noch nicht einsatzbereit: " + (befund.grund || "unbekannt") +
        ". Beim ersten Lauf holt sich das Programm fehlende Skills selbst.";
      feld.dataset.art = "warnung";
    }
  }

  /* ── Auswahl ───────────────────────────────────────────────────────────── */

  function quelleSetzen(kennung) {
    zustand.quelle = kennung;
    for (const knopf of $$("#pr-quellen .stil")) {
      const an = knopf.dataset.quelle === kennung;
      knopf.classList.toggle("ist-an", an);
      knopf.setAttribute("aria-checked", an ? "true" : "false");
    }
    $("#pr-feld-webseite").hidden = kennung !== "webseite";
    $("#pr-feld-ordner").hidden = kennung !== "ordner";
    $("#pr-feld-thema").hidden = kennung !== "thema";
    merken();
  }

  function tonfallSetzen(kennung) {
    zustand.tonfall = kennung;
    for (const knopf of $$("#pr-tonfaelle .stil")) {
      const an = knopf.dataset.tonfall === kennung;
      knopf.classList.toggle("ist-an", an);
      knopf.setAttribute("aria-checked", an ? "true" : "false");
    }
    merken();
  }

  function dauerSetzen(wert) {
    zustand.dauer = wert;
    for (const knopf of $$("#pr-dauer .segment-knopf")) {
      const an = Number(knopf.dataset.dauer) === wert;
      knopf.classList.toggle("ist-an", an);
      knopf.setAttribute("aria-checked", an ? "true" : "false");
    }
    merken();
  }

  /* ── Webseite prüfen ───────────────────────────────────────────────────── */

  async function urlPruefen() {
    const url = $("#pr-url").value.trim();
    if (!url) { zeile("Bitte einen Link eingeben.", "fehler"); return; }
    zeile("Der Link wird geprüft …");
    $("#btn-pr-pruefen").disabled = true;
    try {
      const antwort = await MPW.hole("/api/webseite/pruefen", { koerper: { url } });
      zustand.geprueft = antwort.webseite;
      zustand.geprueftFuer = url;
      karteZeichnen(antwort.webseite);
      zeile("Seite erreichbar: " + (antwort.webseite.titel || antwort.webseite.host),
            "erfolg");
      if (!$("#pr-kunde").value) $("#pr-kunde").value = antwort.webseite.marke || "";
      if (!$("#pr-kontakt").value) $("#pr-kontakt").value = antwort.webseite.host || "";
      merken();
    } catch (fehler) {
      zustand.geprueft = null;
      $("#pr-karte").hidden = true;
      zeile(fehler.meldung || fehler.message, "fehler");
    } finally {
      $("#btn-pr-pruefen").disabled = false;
    }
  }

  function karteZeichnen(seite) {
    const karte = $("#pr-karte");
    karte.hidden = false;
    karte.replaceChildren(
      el("div", { klasse: "webkarte-text" }, [
        el("strong", { text: seite.titel || seite.host }),
        el("p", { text: (seite.beschreibung || "").slice(0, 160) }),
        el("span", { klasse: "hinweis", text: seite.host }),
      ]));
  }

  /* ── Projektordner ─────────────────────────────────────────────────────── */

  async function ordnerWaehlen() {
    $("#btn-pr-ordner").disabled = true;
    zeile("Der Ordner-Dialog ist offen — er kann hinter dem Fenster liegen.");
    try {
      const antwort = await MPW.hole("/api/premium/ordner", { method: "POST" });
      if (antwort.ordner.abgebrochen) { zeile("Keine Auswahl getroffen."); return; }
      ordnerUebernehmen(antwort.ordner);
    } catch (fehler) {
      zeile(fehler.meldung || fehler.message, "fehler");
    } finally {
      $("#btn-pr-ordner").disabled = false;
    }
  }

  async function ordnerPruefen(pfad) {
    if (!pfad.trim()) return;
    try {
      const antwort = await MPW.hole("/api/premium/ordner/pruefen",
                                     { koerper: { ordner: pfad } });
      ordnerUebernehmen(antwort.ordner);
    } catch (fehler) {
      zeile(fehler.meldung || fehler.message, "fehler");
    }
  }

  function ordnerUebernehmen(ordner) {
    zustand.ordner = ordner;
    $("#pr-ordner").value = ordner.pfad;
    $("#pr-ordner-hinweis").textContent = ordner.taugt
      ? `„${ordner.name}“ — ${ordner.texte} Textdatei(en), ${ordner.bilder} Bild(er) gefunden.`
      : ordner.hinweis;
    $("#pr-ordner-hinweis").dataset.art = ordner.taugt ? "gut" : "warnung";
    if (!$("#pr-kunde").value) $("#pr-kunde").value = ordner.name || "";
    zeile(ordner.taugt ? "Ordner übernommen." : ordner.hinweis,
          ordner.taugt ? "erfolg" : "fehler");
    merken();
  }

  /* ── Material ──────────────────────────────────────────────────────────── */

  function korbKennung() {
    if (!zustand.korb) {
      zustand.korb = Math.random().toString(36).slice(2, 12) +
                     Date.now().toString(36).slice(-4);
    }
    return zustand.korb;
  }

  async function hochladen(dateiliste) {
    const dateien = Array.from(dateiliste || []);
    if (!dateien.length) return;
    const daten = new FormData();
    daten.append("korb", korbKennung());
    let bytes = 0;
    for (const datei of dateien) {
      bytes += datei.size;
      daten.append("dateien", datei, datei.webkitRelativePath || datei.name);
    }
    if (bytes > 240 * 1024 * 1024) {
      zeile("Das Material ist zu groß (über 240 MB). Bitte weniger auswählen.", "fehler");
      return;
    }
    zeile(`${dateien.length} Datei(en) werden übertragen …`);
    try {
      const antwort = await fetch("/api/premium/material", { method: "POST", body: daten })
        .then((a) => a.json());
      if (!antwort.ok) throw new Error(antwort.meldung || "Übertragung fehlgeschlagen.");
      zustand.material = zustand.material.concat(antwort.angenommen || []);
      materialZeigen();
      const weg = (antwort.abgewiesen || []).length;
      zeile(`${antwort.anzahl} Datei(en) angenommen (${antwort.mb} MB)` +
            (weg ? `, ${weg} übergangen` : "") + ".", "erfolg");
      merken();
    } catch (fehler) {
      zeile(fehler.message, "fehler");
    }
  }

  function materialZeigen() {
    const kasten = $("#pr-material");
    if (!zustand.material.length) {
      kasten.hidden = true;
      $("#btn-pr-material-weg").hidden = true;
      return;
    }
    kasten.hidden = false;
    $("#btn-pr-material-weg").hidden = false;
    const sichtbar = zustand.material.slice(0, 12);
    kasten.replaceChildren(
      ...sichtbar.map((name) => el("span", { klasse: "material-marke", text: name })),
      zustand.material.length > sichtbar.length
        ? el("span", { klasse: "material-marke",
                       text: `+ ${zustand.material.length - sichtbar.length} weitere` })
        : null);
  }

  async function materialVerwerfen() {
    if (!zustand.korb) return;
    try {
      await MPW.hole(`/api/premium/material/${zustand.korb}`, { method: "DELETE" });
    } catch (fehler) { /* Der Korb wird ohnehin beim Start geleert. */ }
    zustand.korb = "";
    zustand.material = [];
    materialZeigen();
    zeile("Material verworfen.");
    merken();
  }

  /* ── Starten ───────────────────────────────────────────────────────────── */

  function sammeln() {
    const auftrag = {
      art: "premium",
      quelle: zustand.quelle,
      url: $("#pr-url").value.trim(),
      projektordner: $("#pr-ordner").value.trim(),
      thema: $("#pr-thema").value.trim(),
      kunde: $("#pr-kunde").value.trim(),
      zielgruppe: $("#pr-zielgruppe").value.trim(),
      botschaft: $("#pr-botschaft").value.trim(),
      cta: $("#pr-cta").value.trim(),
      kontakt: $("#pr-kontakt").value.trim(),
      wunsch: $("#pr-wunsch").value.trim(),
      fokus: zustand.fokus,
      tonfall: zustand.tonfall,
      dauer: zustand.dauer,
      sprache: $("#pr-sprache").value,
      modell: $("#pr-modell").value,
      korb: zustand.korb,
    };
    if (auftrag.quelle === "webseite" && !auftrag.url) {
      throw new Error("Es fehlt der Link zur Webseite.");
    }
    if (auftrag.quelle === "ordner" && !auftrag.projektordner) {
      throw new Error("Es fehlt der Projektordner — auf „Ordner wählen“ klicken.");
    }
    if (auftrag.quelle === "thema" && auftrag.thema.length < 10) {
      throw new Error("Bitte kurz beschreiben, worum es geht.");
    }
    return auftrag;
  }

  async function starten() {
    let auftrag;
    try {
      auftrag = sammeln();
    } catch (fehler) {
      zeile(fehler.message, "fehler");
      MPW.melden(fehler.message, "fehler");
      return;
    }
    $("#pr-prompt-box").hidden = true;
    const angenommen = await MPW.start.auftragAbschicken(auftrag, zeile);
    // Abgewiesen (etwa „Diesen Ordner gibt es nicht“): Das Material bleibt ausgewählt,
    // sonst lägen die Dateien verwaist im Korb und der Kunde müsste neu hochladen.
    if (!angenommen) return;
    // Der Korb ist nach dem Start verbraucht — der Auftrag hat ihn übernommen.
    zustand.korb = "";
    zustand.material = [];
    materialZeigen();
    merken();
  }

  /** Was das Programm aus dem Material gemacht hat — Sorte samt Begründung. */
  function fokusGemeldet(nachricht) {
    const befund = nachricht?.fokus;
    if (!befund) return;
    const name = (zustand.katalog?.fokus || [])
      .find((f) => f.kennung === befund.fokus)?.name || befund.fokus;
    $("#pr-fokus-hinweis").textContent = `Erkannt: ${name} — ${befund.begruendung}`;
    $("#pr-fokus-hinweis").dataset.art = "gut";
  }

  /** Zeigt den Auftrag, den Claude geschrieben hat — sobald er im Ablauf gemeldet wird. */
  function promptZeigen(text) {
    if (!text) return;
    $("#pr-prompt-box").hidden = false;
    $("#pr-prompt").textContent = text;
  }

  function sperren(laeuft) {
    zustand.laeuft = laeuft;
    $("#btn-pr-start").disabled = laeuft;
    $("#btn-pr-start-text").textContent = laeuft ? "Läuft …" : "Video generieren";
  }

  function zeile(text, art) {
    const feld = $("#pr-zeile");
    if (!feld) return;
    feld.textContent = text;
    feld.dataset.art = art || "";
  }

  /* ── Merken ────────────────────────────────────────────────────────────── */

  function merken() {
    try {
      localStorage.setItem(SPEICHER, JSON.stringify({
        quelle: zustand.quelle, fokus: zustand.fokus,
        tonfall: zustand.tonfall, dauer: zustand.dauer,
        korb: zustand.korb, material: zustand.material,
        url: $("#pr-url").value, ordner: $("#pr-ordner").value,
        thema: $("#pr-thema").value, kunde: $("#pr-kunde").value,
        zielgruppe: $("#pr-zielgruppe").value, botschaft: $("#pr-botschaft").value,
        cta: $("#pr-cta").value, kontakt: $("#pr-kontakt").value,
        wunsch: $("#pr-wunsch").value, modell: $("#pr-modell").value,
        sprache: $("#pr-sprache").value,
      }));
    } catch (fehler) { /* Speicher voll oder gesperrt — kein Grund für eine Meldung. */ }
  }

  function wiederherstellen() {
    let gemerkt = null;
    try {
      gemerkt = JSON.parse(localStorage.getItem(SPEICHER) || "null");
    } catch (fehler) { gemerkt = null; }

    const felder = {
      "#pr-url": "url", "#pr-ordner": "ordner", "#pr-thema": "thema",
      "#pr-kunde": "kunde", "#pr-zielgruppe": "zielgruppe", "#pr-botschaft": "botschaft",
      "#pr-cta": "cta", "#pr-kontakt": "kontakt", "#pr-wunsch": "wunsch",
      "#pr-modell": "modell", "#pr-sprache": "sprache",
    };
    if (gemerkt) {
      for (const [wahl, schluessel] of Object.entries(felder)) {
        if (gemerkt[schluessel]) $(wahl).value = gemerkt[schluessel];
      }
      zustand.korb = gemerkt.korb || "";
      zustand.material = gemerkt.material || [];
      materialZeigen();
    }
    quelleSetzen(gemerkt?.quelle || "webseite");
    // „marke" gab es bis zum 18.09.2026; wer es gespeichert hat, landet auf „auto".
    const gemerkterFokus = (zustand.katalog.fokus || [])
      .some((f) => f.kennung === gemerkt?.fokus) ? gemerkt.fokus : "auto";
    fokusSetzen(gemerkterFokus);
    tonfallSetzen(gemerkt?.tonfall || "polished");
    dauerSetzen(gemerkt?.dauer || zustand.katalog.dauern[1] || 22);
  }
})(window.MPW);
