/* webseite.js — die Seite „Webseite → TikTok“ und der Wechsel zwischen den Bereichen.
 *
 * Ein Link hinein, ein Werbevideo heraus. Die Oberfläche hält den Weg dorthin kurz:
 * Link eingeben, prüfen lassen (das Programm zeigt Titel, Beschreibung und Vorschaubild
 * der Seite — so sieht man sofort, ob es die richtige ist), Länge und Stil wählen, los.
 *
 * Der Auftrag läuft durch dieselbe Warteschlange, denselben Ablauf und dieselbe
 * Bibliothek wie jedes andere Video. Nur die Blöcke im Ablauf heißen anders.
 */
"use strict";

(function (MPW) {
  const { $, $$, el } = MPW;

  const zustand = {
    katalog: null,
    videoweg: "",
    geprueft: null,          // Antwort der letzten erfolgreichen Prüfung
    geprueftFuer: "",        // … für genau diese Eingabe
    dauer: 20,
    stil: "energisch",
    prueftGerade: false,
  };

  //: Farbe je Stil, nur für die Kachel — die Farben im Video kommen von der Webseite.
  const STILFARBEN = { energisch: "#FF406E", freundlich: "#22D3EE", edel: "#D4AF5C" };

  MPW.webseite = { aufbauen, sperren, wegSetzen, zeile };
  MPW.seiten = { zeigen };

  function aufbauen(start) {
    zustand.katalog = start.webseite || { dauern: [15, 20, 30], stile: [] };
    zustand.videoweg = start.videoweg || "";

    for (const knopf of $$(".seitenwahl-knopf")) {
      knopf.addEventListener("click", () => zeigen(knopf.dataset.seite));
    }
    dauerBauen();
    stileBauen();
    formateBauen(start.formate || []);

    $("#web-form").addEventListener("submit", (e) => { e.preventDefault(); pruefen(); });
    $("#web-url").addEventListener("input", () => {
      if (zustand.geprueft && $("#web-url").value.trim() !== zustand.geprueftFuer) {
        zustand.geprueft = null;
        $("#web-karte").hidden = true;
        zeile("Link geändert — bitte erneut prüfen.");
      }
      merken();
    });
    for (const feld of ["#web-cta", "#web-hinweis", "#web-musik", "#web-ki"]) {
      $(feld).addEventListener("change", merken);
    }
    $("#btn-web-start").addEventListener("click", starten);
    for (const knopf of $$("[data-abbruch]")) {
      knopf.addEventListener("click", () => MPW.start.auftragAbbrechen());
    }

    wegSetzen(zustand.videoweg);
    wiederherstellen();
    const gewuenscht = window.location.hash === "#webseite"
      ? "webseite" : MPW.speicher.lesen("seite", "studio");
    zeigen(gewuenscht, true);
  }

  /* ── Bereich wechseln ──────────────────────────────────────────────────── */

  function zeigen(seite, stumm) {
    // Welche Seiten es gibt, sagt die Seite selbst — nicht eine Liste hier. Beim
    // Einbau des Premium-Bereichs stand hier eine feste Aufzählung: Der Knopf leuchtete
    // auf, und der Inhalt blieb der alte. Ein dritter Bereich darf nur an einer Stelle
    // eingetragen werden müssen, und das ist das HTML.
    const bekannt = $$("[data-seite-inhalt]").map((k) => k.dataset.seiteInhalt);
    if (!bekannt.includes(seite)) seite = "studio";
    for (const inhalt of $$("[data-seite-inhalt]")) {
      inhalt.hidden = inhalt.dataset.seiteInhalt !== seite;
    }
    for (const knopf of $$(".seitenwahl-knopf")) {
      const an = knopf.dataset.seite === seite;
      knopf.classList.toggle("ist-an", an);
      if (an) knopf.setAttribute("aria-current", "page");
      else knopf.removeAttribute("aria-current");
    }
    MPW.speicher.schreiben("seite", seite);
    try {
      window.history.replaceState(null, "", seite === "studio" ? "#" : "#" + seite);
    } catch (fehler) { /* im Desktop-Fenster ohne Bedeutung */ }
    if (!stumm && seite === "webseite" && !$("#web-url").value) $("#web-url").focus();
  }

  /* ── Auswahlfelder ─────────────────────────────────────────────────────── */

  function dauerBauen() {
    const behaelter = $("#web-dauer");
    behaelter.replaceChildren(...(zustand.katalog.dauern || [15, 20, 30]).map((sekunden) =>
      el("button", {
        klasse: "segment-knopf", type: "button", role: "radio",
        "aria-checked": "false", daten: { dauer: String(sekunden) },
        text: `${sekunden} s`,
        onclick: () => { dauerWaehlen(sekunden); merken(); },
      })));
  }

  function dauerWaehlen(sekunden) {
    zustand.dauer = Number(sekunden) || 20;
    for (const knopf of $$("#web-dauer .segment-knopf")) {
      const an = Number(knopf.dataset.dauer) === zustand.dauer;
      knopf.classList.toggle("ist-an", an);
      knopf.setAttribute("aria-checked", String(an));
    }
  }

  function stileBauen() {
    const behaelter = $("#web-stile");
    behaelter.replaceChildren(...(zustand.katalog.stile || []).map((stil) =>
      el("button", {
        klasse: "stil", type: "button", role: "radio", "aria-checked": "false",
        daten: { stil: stil.kennung }, title: stil.beschreibung,
        style: `--stilfarbe: ${STILFARBEN[stil.kennung] || "var(--akzent)"}`,
        onclick: () => { stilWaehlen(stil.kennung); merken(); },
      }, [
        el("span", { klasse: "stil-punkt", "aria-hidden": "true" }),
        el("span", { klasse: "stil-name", text: stil.name }),
        el("span", { klasse: "stil-text", text: stil.beschreibung }),
      ])));
  }

  function stilWaehlen(kennung) {
    zustand.stil = kennung;
    for (const knopf of $$("#web-stile .stil")) {
      const an = knopf.dataset.stil === kennung;
      knopf.classList.toggle("ist-an", an);
      knopf.setAttribute("aria-checked", String(an));
    }
  }

  function formateBauen(formate) {
    $("#web-formate").replaceChildren(...formate
      .filter((f) => ["quadrat", "breit", "web", "gif"].includes(f.kennung))
      .map((format) => el("label", { klasse: "haken", title: format.beschreibung }, [
        el("input", { type: "checkbox", value: format.kennung, onchange: merken }),
        el("span", { klasse: "haken-punkt" }),
        el("span", { text: format.name }),
      ])));
  }

  /** Die KI-Szene braucht einen echten Higgsfield-Zugang. Im Probelauf gibt es sie nicht. */
  function wegSetzen(weg) {
    if (weg !== undefined) zustand.videoweg = weg || "";
    const moeglich = ["abo", "platform"].includes(zustand.videoweg);
    const schalter = $("#web-ki");
    schalter.disabled = !moeglich;
    if (!moeglich) schalter.checked = false;
    $("#web-ki-schalter").classList.toggle("ist-aus", !moeglich);
    $("#web-ki-hinweis").textContent = moeglich
      ? "Eine stimmungsvolle Szene über Higgsfield — kostet Credits (etwa ein Bild und ein Clip)."
      : "Nur mit verbundenem Higgsfield-Abo oder API-Guthaben möglich.";
  }

  /* ── Link prüfen ───────────────────────────────────────────────────────── */

  async function pruefen() {
    const eingabe = $("#web-url").value.trim();
    if (!eingabe) {
      zeile("Bitte zuerst einen Link eingeben.", "fehler");
      $("#web-url").focus();
      return null;
    }
    if (zustand.prueftGerade) return null;
    zustand.prueftGerade = true;
    const knopf = $("#btn-web-pruefen");
    knopf.disabled = true;
    knopf.textContent = "Prüft …";
    zeile("Die Seite wird aufgerufen …");

    try {
      const antwort = await MPW.hole("/api/webseite/pruefen", { koerper: { url: eingabe } });
      zustand.geprueft = antwort.webseite;
      zustand.geprueftFuer = eingabe;
      karteZeigen(antwort.webseite);
      zeile("Seite erreichbar — jetzt das Werbevideo erzeugen.", "erfolg");
      merken();
      return antwort.webseite;
    } catch (fehler) {
      zustand.geprueft = null;
      karteFehler(fehler);
      zeile(fehler.meldung || fehler.message, "fehler");
      return null;
    } finally {
      zustand.prueftGerade = false;
      knopf.disabled = false;
      knopf.textContent = "Prüfen";
    }
  }

  function karteZeigen(w) {
    const karte = $("#web-karte");
    const bild = w.bild
      ? el("img", { klasse: "webkarte-bild", src: w.bild, alt: "", loading: "lazy",
                    referrerpolicy: "no-referrer",
                    onerror: (e) => e.target.remove() })
      : null;
    const icon = el("img", { klasse: "webkarte-icon", src: w.favicon || "", alt: "",
                             referrerpolicy: "no-referrer",
                             onerror: (e) => { e.target.style.visibility = "hidden"; } });
    karte.dataset.art = "ok";
    karte.replaceChildren(
      bild,
      el("div", { klasse: "webkarte-inhalt" }, [
        el("div", { klasse: "webkarte-kopf" }, [
          icon,
          el("span", { klasse: "webkarte-host", text: w.host }),
          el("span", { klasse: "webkarte-marke", text: `Erreichbar · ${w.dauer_ms} ms` }),
        ]),
        el("p", { klasse: "webkarte-titel", text: w.titel || w.host }),
        w.beschreibung ? el("p", { klasse: "webkarte-text", text: w.beschreibung }) : null,
      ]),
    );
    karte.hidden = false;
  }

  function karteFehler(fehler) {
    const karte = $("#web-karte");
    karte.dataset.art = "fehler";
    karte.replaceChildren(el("div", { klasse: "webkarte-inhalt" }, [
      el("p", { klasse: "webkarte-titel", text: fehler.meldung || fehler.message }),
      fehler.hinweis ? el("p", { klasse: "webkarte-text", text: fehler.hinweis }) : null,
    ]));
    karte.hidden = false;
  }

  /* ── Starten ───────────────────────────────────────────────────────────── */

  async function starten() {
    if (!zustand.geprueft || $("#web-url").value.trim() !== zustand.geprueftFuer) {
      const ergebnis = await pruefen();
      if (!ergebnis) return;
    }
    const auftrag = {
      art: "webseite",
      url: zustand.geprueft.url,
      dauer: zustand.dauer,
      stil: zustand.stil,
      cta: $("#web-cta").value.trim(),
      hinweis: $("#web-hinweis").value.trim(),
      musik: $("#web-musik").checked,
      ki_szene: $("#web-ki").checked && !$("#web-ki").disabled,
      formate: $$("#web-formate input:checked").map((k) => k.value),
    };
    await MPW.start.auftragAbschicken(auftrag, zeile);
  }

  /** Läuft ein Auftrag, reiht sich ein neuer ein — der Knopf sagt das. */
  function sperren(laeuft) {
    $("#btn-web-start-text").textContent = laeuft ? "Einreihen" : "Werbevideo erzeugen";
    for (const knopf of $$("[data-abbruch]")) knopf.hidden = !laeuft;
  }

  function zeile(text, art) {
    const feld = $("#web-zeile");
    feld.textContent = text;
    if (art) feld.dataset.art = art; else delete feld.dataset.art;
  }

  /* ── Eingaben merken ───────────────────────────────────────────────────── */

  const merken = MPW.entprellen(function () {
    MPW.speicher.schreiben("webseite", {
      url: $("#web-url").value, dauer: zustand.dauer, stil: zustand.stil,
      cta: $("#web-cta").value, hinweis: $("#web-hinweis").value,
      musik: $("#web-musik").checked, ki: $("#web-ki").checked,
      formate: $$("#web-formate input:checked").map((k) => k.value),
    });
  }, 400);

  function wiederherstellen() {
    const g = MPW.speicher.lesen("webseite", {}) || {};
    $("#web-url").value = g.url || "";
    $("#web-cta").value = g.cta || "";
    $("#web-hinweis").value = g.hinweis || "";
    $("#web-musik").checked = g.musik !== false;
    if (!$("#web-ki").disabled) $("#web-ki").checked = Boolean(g.ki);
    for (const kaestchen of $$("#web-formate input")) {
      kaestchen.checked = (g.formate || []).includes(kaestchen.value);
    }
    dauerWaehlen(g.dauer || 20);
    stilWaehlen(g.stil || "energisch");
  }

})(window.MPW);
