/* kern.js — Gemeinsames für alle Bereiche der Oberfläche.
 *
 * Enthält den Zugriff auf den Server, die Verbindung zum Ereignisstrom und ein paar
 * kleine Helfer. Alles hängt am Namensraum `MPW`; es gibt bewusst kein Modulsystem und
 * keinen Bauschritt — die Oberfläche soll auch in fünf Jahren noch ohne Werkzeugkette
 * änderbar sein.
 */
"use strict";

window.MPW = window.MPW || {};

(function (MPW) {

  /* ── Kurzschreibweisen ─────────────────────────────────────────────────── */

  MPW.$ = (auswahl, wurzel) => (wurzel || document).querySelector(auswahl);
  MPW.$$ = (auswahl, wurzel) => Array.from((wurzel || document).querySelectorAll(auswahl));

  /** Element bauen. Kürzt das ewige createElement/appendChild-Geflecht ab. */
  MPW.el = function (tag, eigenschaften, kinder) {
    const knoten = document.createElement(tag);
    for (const [name, wert] of Object.entries(eigenschaften || {})) {
      if (wert === null || wert === undefined || wert === false) continue;
      if (name === "klasse") knoten.className = wert;
      else if (name === "text") knoten.textContent = wert;
      else if (name === "html") knoten.innerHTML = wert;
      else if (name.startsWith("on")) knoten.addEventListener(name.slice(2), wert);
      else if (name === "daten") {
        for (const [d, v] of Object.entries(wert)) knoten.dataset[d] = v;
      } else knoten.setAttribute(name, wert === true ? "" : wert);
    }
    for (const kind of [].concat(kinder || [])) {
      if (kind === null || kind === undefined || kind === false) continue;
      knoten.append(kind.nodeType ? kind : document.createTextNode(String(kind)));
    }
    return knoten;
  };

  /** Ein Icon aus dem eingebetteten Satz. */
  MPW.icon = function (name, klasse) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "icon " + (klasse || ""));
    svg.setAttribute("aria-hidden", "true");
    const nutzung = document.createElementNS("http://www.w3.org/2000/svg", "use");
    nutzung.setAttribute("href", "#i-" + name);
    svg.append(nutzung);
    return svg;
  };

  /* ── Formatierung ──────────────────────────────────────────────────────── */

  MPW.zeitspanne = function (sekunden) {
    sekunden = Math.max(0, Math.round(Number(sekunden) || 0));
    if (sekunden < 60) return sekunden + " s";
    const minuten = Math.floor(sekunden / 60);
    const rest = sekunden % 60;
    if (minuten < 60) return rest ? `${minuten} min ${rest} s` : `${minuten} min`;
    return `${Math.floor(minuten / 60)} h ${minuten % 60} min`;
  };

  MPW.dauer = function (sekunden) {
    const gesamt = Math.max(0, Math.round(Number(sekunden) || 0));
    return `${Math.floor(gesamt / 60)}:${String(gesamt % 60).padStart(2, "0")}`;
  };

  MPW.groesse = (mb) => (Number(mb) || 0).toFixed(1).replace(".", ",") + " MB";

  /* ── Serverzugriff ─────────────────────────────────────────────────────── */

  /**
   * Ruft den Server. Wirft einen Fehler, dessen `message` bereits der Satz ist, der
   * dem Benutzer gezeigt werden kann — die Aufrufer müssen nichts mehr übersetzen.
   */
  MPW.hole = async function (pfad, optionen) {
    const einstellungen = Object.assign({ headers: {} }, optionen || {});
    if (einstellungen.koerper !== undefined) {
      einstellungen.method = einstellungen.method || "POST";
      einstellungen.headers["Content-Type"] = "application/json";
      einstellungen.body = JSON.stringify(einstellungen.koerper);
      delete einstellungen.koerper;
    }

    let antwort;
    try {
      antwort = await fetch(pfad, einstellungen);
    } catch (fehler) {
      throw new Error("Keine Verbindung zum Programm. Läuft es noch?");
    }

    let daten = {};
    try { daten = await antwort.json(); } catch (fehler) { /* leere Antwort ist erlaubt */ }

    if (!antwort.ok || daten.ok === false) {
      const meldung = daten.meldung || `Unerwartete Antwort (${antwort.status}).`;
      const fehler = new Error(daten.hinweis ? `${meldung} ${daten.hinweis}` : meldung);
      fehler.meldung = meldung;
      fehler.hinweis = daten.hinweis || "";
      fehler.art = daten.art || "";
      throw fehler;
    }
    return daten;
  };

  /* ── Kurzmeldung unten ─────────────────────────────────────────────────── */

  let meldungsUhr = null;

  MPW.melden = function (text, art, dauerMs) {
    const kasten = MPW.$("#meldung");
    if (!kasten) return;
    kasten.textContent = text;
    kasten.dataset.art = art || "info";
    kasten.hidden = false;
    clearTimeout(meldungsUhr);
    meldungsUhr = setTimeout(() => { kasten.hidden = true; },
                             dauerMs || (art === "fehler" ? 8000 : 4000));
  };

  /* ── Ereignisstrom ─────────────────────────────────────────────────────── */

  const hoerer = new Map();          // Ereignisname → Menge von Rückrufen

  /** Auf ein Ereignis hören. Rückgabe: Funktion zum Abmelden. */
  MPW.beiEreignis = function (name, rueckruf) {
    if (!hoerer.has(name)) hoerer.set(name, new Set());
    hoerer.get(name).add(rueckruf);
    return () => hoerer.get(name).delete(rueckruf);
  };

  function verteilen(name, nachricht) {
    for (const rueckruf of hoerer.get(name) || []) {
      try { rueckruf(nachricht); }
      catch (fehler) { console.error("Fehler im Empfänger für", name, fehler); }
    }
  }

  let strom = null;
  let versuche = 0;

  MPW.stromVerbinden = function () {
    if (strom) strom.close();
    strom = new EventSource("/api/strom");

    strom.onopen = function () {
      if (versuche > 0) MPW.melden("Verbindung wiederhergestellt.", "erfolg");
      versuche = 0;
      verteilen("verbunden", {});
    };

    strom.onmessage = function (ereignis) {
      let nachricht;
      try { nachricht = JSON.parse(ereignis.data); }
      catch (fehler) { return; }
      if (nachricht.typ === "log") verteilen("log", nachricht);
      else if (nachricht.typ === "ereignis") verteilen(nachricht.name, nachricht);
    };

    strom.onerror = function () {
      // Der Browser versucht von sich aus erneut. Wir sagen nur einmal Bescheid,
      // statt bei jedem Fehlschlag eine Meldung einzublenden.
      if (versuche === 0) MPW.melden("Verbindung unterbrochen — es wird erneut versucht …",
                                     "fehler", 6000);
      versuche += 1;
      verteilen("getrennt", {});
    };
  };

  /* ── Kleine Helfer ─────────────────────────────────────────────────────── */

  MPW.entprellen = function (funktion, ms) {
    let uhr = null;
    return function (...argumente) {
      clearTimeout(uhr);
      uhr = setTimeout(() => funktion.apply(this, argumente), ms);
    };
  };

  /** Merkt Formulareingaben im Browser, damit nach einem Neustart nichts weg ist. */
  MPW.speicher = {
    lesen(schluessel, ersatz) {
      try {
        const roh = localStorage.getItem("mpw." + schluessel);
        return roh === null ? ersatz : JSON.parse(roh);
      } catch (fehler) { return ersatz; }
    },
    schreiben(schluessel, wert) {
      try { localStorage.setItem("mpw." + schluessel, JSON.stringify(wert)); }
      catch (fehler) { /* voller Speicher darf die Bedienung nicht stören */ }
    },
  };

})(window.MPW);
