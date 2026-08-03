/* formular.js — die linke Spalte: Formular und eigener Prompt.
 *
 * Zwei Eingabewege, ein Auftrag. Der Formularweg baut aus Thema, Gegenstand und
 * Merkmalen einen Briefingtext, den der Benutzer VOR dem Start im Klartext sieht — es
 * soll kein Rätsel sein, was gleich an Claude geht. Der Freitextweg reicht den Prompt
 * durch, wahlweise ausgearbeitet oder wörtlich.
 *
 * Alle Eingaben werden im Browser gemerkt: wer das Programm abends schließt, findet am
 * nächsten Morgen sein Formular wieder.
 */
"use strict";

(function (MPW) {
  const { $, $$, el, icon } = MPW;

  const zustand = {
    thema: "",
    argumente: new Set(),
    modus: "formular",
    laenge: "einzel",
    videomodelle: [],
    formate: [],
    katalog: null,
  };

  MPW.formular = { aufbauen, sammeln, sperren, zustand };

  /* ── Aufbau ────────────────────────────────────────────────────────────── */

  function aufbauen(start) {
    zustand.katalog = start.katalog;
    zustand.videomodelle = start.videomodelle;
    zustand.formate = start.formate;

    themenBauen(start.katalog.themen);
    argumenteBauen(start.katalog.argumentgruppen);
    modelleBauen(start.videomodelle);
    formatwahlBauen(start.formate, start.standardformate);
    reiterVerdrahten();
    laengeVerdrahten(start.grenzen);
    knoepfeVerdrahten();

    wiederherstellen();
    briefingErneuern();
  }

  function themenBauen(themen) {
    const behaelter = $("#themen");
    behaelter.replaceChildren(...themen.map((thema) =>
      el("button", {
        klasse: "thema",
        type: "button",
        role: "radio",
        "aria-checked": "false",
        title: thema.beschreibung,
        daten: { thema: thema.kennung },
        onclick: () => themaWaehlen(thema.kennung),
      }, [
        el("span", { klasse: "thema-symbol", text: thema.symbol }),
        el("span", { text: thema.name }),
      ])));
  }

  function themaWaehlen(kennung) {
    zustand.thema = kennung;
    for (const knopf of $$(".thema")) {
      const an = knopf.dataset.thema === kennung;
      knopf.classList.toggle("ist-an", an);
      knopf.setAttribute("aria-checked", an ? "true" : "false");
    }

    const thema = zustand.katalog.themen.find((t) => t.kennung === kennung);
    if (!thema) return;

    $("#betreff").placeholder = thema.platzhalter || "";
    zusatzfelderBauen(thema.felder || []);

    // Die Voreinstellung des Themas übernehmen — ein Social-Clip ist eben hochkant
    // und kurz, ein Markenfilm quer und länger. Der Benutzer kann alles überstimmen.
    const vorschlag = thema.vorschlag || {};
    if (vorschlag.seitenverhaeltnis) $("#verhaeltnis").value = vorschlag.seitenverhaeltnis;
    if (vorschlag.szenen > 1) {
      laengeWaehlen("story");
      $("#szenen").value = Math.min(vorschlag.szenen, Number($("#szenen").max));
      $("#szenen-wert").value = $("#szenen").value;
    }
    laengeHinweisErneuern();
    briefingErneuern();
    merken();
  }

  function zusatzfelderBauen(felder) {
    const behaelter = $("#zusatzfelder");
    const vorhandene = {};
    for (const feld of $$("[data-zusatz]", behaelter)) vorhandene[feld.dataset.zusatz] = feld.value;

    behaelter.replaceChildren(...felder.map((name) => {
      const angaben = zustand.katalog.zusatzfelder[name];
      if (!angaben) return null;
      const kennung = "zusatz-" + name;
      return el("fieldset", { klasse: "feldgruppe" }, [
        el("legend", {}, [el("label", { for: kennung, text: angaben.name })]),
        el("input", {
          klasse: "eingabe", type: "text", id: kennung, autocomplete: "off",
          placeholder: angaben.platzhalter, value: vorhandene[name] || "",
          daten: { zusatz: name },
          oninput: MPW.entprellen(() => { briefingErneuern(); merken(); }, 350),
        }),
        el("p", { klasse: "hinweis", text: angaben.hinweis }),
      ]);
    }).filter(Boolean));
  }

  function argumenteBauen(gruppen) {
    const behaelter = $("#argumentgruppen");
    behaelter.replaceChildren(...gruppen.map((gruppe) =>
      el("div", { klasse: "argumentgruppe" }, [
        el("p", { klasse: "argumentgruppe-name", text: gruppe.name }),
        el("div", { klasse: "haken-reihe" }, gruppe.argumente.map((argument) =>
          el("label", { klasse: "haken", title: argument.text }, [
            el("input", {
              type: "checkbox", value: argument.kennung,
              daten: { gruppe: gruppe.kennung, mehrfach: gruppe.mehrfach ? "ja" : "nein" },
              onchange: (e) => argumentUmschalten(e.target, gruppe),
            }),
            el("span", { klasse: "haken-punkt" }),
            el("span", { text: argument.name }),
          ]))),
      ])));
  }

  function argumentUmschalten(kaestchen, gruppe) {
    // Bei Gruppen ohne Mehrfachwahl (Licht, Kamera, Bildstil) schließen sich die
    // Merkmale gegenseitig aus — zwei Lichtstimmungen gleichzeitig ergeben keinen Sinn.
    if (!gruppe.mehrfach && kaestchen.checked) {
      for (const anderes of $$(`input[data-gruppe="${gruppe.kennung}"]`)) {
        if (anderes !== kaestchen) { anderes.checked = false; zustand.argumente.delete(anderes.value); }
      }
    }
    if (kaestchen.checked) zustand.argumente.add(kaestchen.value);
    else zustand.argumente.delete(kaestchen.value);
    briefingErneuern();
    merken();
  }

  function modelleBauen(modelle) {
    const wahl = $("#videomodell");
    wahl.replaceChildren(...modelle.map((modell) =>
      el("option", {
        value: modell.id,
        selected: modell.empfohlen || null,
        text: modell.name + (modell.empfohlen ? " — empfohlen" : ""),
      })));
    wahl.addEventListener("change", () => { modellHinweisErneuern(); merken(); });
    modellHinweisErneuern();
  }

  function modellHinweisErneuern() {
    const modell = aktuellesModell();
    if (!modell) return;

    $("#modell-hinweis").textContent = modell.beschreibung +
      (modell.startbild ? "" : " Ohne Startbild-Schritt.");

    // Nur die Clipdauern anbieten, die das Modell wirklich kennt — die API weist
    // alles andere ab, und ein Fehler nach zwei Minuten Wartezeit wäre ärgerlich.
    const dauerWahl = $("#clipdauer");
    const bisher = Number(dauerWahl.value) || 0;
    dauerWahl.replaceChildren(...(modell.dauer || [5]).map((sekunden) =>
      el("option", { value: sekunden, text: sekunden + " Sekunden",
                     selected: sekunden === bisher || null })));
    if (!dauerWahl.value) dauerWahl.selectedIndex = 0;
    laengeHinweisErneuern();
  }

  function aktuellesModell() {
    const kennung = $("#videomodell").value;
    return zustand.videomodelle.find((m) => m.id === kennung) || zustand.videomodelle[0];
  }

  function formatwahlBauen(formate, standard) {
    const behaelter = $("#formatwahl");
    behaelter.replaceChildren(...formate
      .filter((format) => format.kennung !== "poster")
      .map((format) =>
        el("label", { klasse: "haken", title: format.beschreibung }, [
          el("input", {
            type: "checkbox", value: format.kennung,
            checked: (standard || []).includes(format.kennung) || null,
            onchange: merken,
          }),
          el("span", { klasse: "haken-punkt" }),
          el("span", { text: format.name }),
        ])));
  }

  /* ── Umschalter und Regler ─────────────────────────────────────────────── */

  function reiterVerdrahten() {
    const wechseln = (modus) => {
      zustand.modus = modus;
      const istFormular = modus === "formular";
      $("#reiter-formular").classList.toggle("ist-an", istFormular);
      $("#reiter-frei").classList.toggle("ist-an", !istFormular);
      $("#reiter-formular").setAttribute("aria-selected", String(istFormular));
      $("#reiter-frei").setAttribute("aria-selected", String(!istFormular));
      $("#feld-formular").hidden = !istFormular;
      $("#feld-frei").hidden = istFormular;
      merken();
    };
    $("#reiter-formular").addEventListener("click", () => wechseln("formular"));
    $("#reiter-frei").addEventListener("click", () => wechseln("frei"));

    $("#betreff").addEventListener("input",
      MPW.entprellen(() => { briefingErneuern(); merken(); }, 350));

    const freitext = $("#freitext");
    freitext.addEventListener("input", MPW.entprellen(() => {
      $("#freitext-zaehler").textContent = String(freitext.value.length);
      merken();
    }, 250));

    $("#woertlich").addEventListener("change", merken);
    $("#weich").addEventListener("change", merken);
    $("#verhaeltnis").addEventListener("change", merken);
    $("#clipdauer").addEventListener("change", () => { laengeHinweisErneuern(); merken(); });
  }

  function laengeVerdrahten() {
    for (const knopf of $$("[data-laenge]")) {
      knopf.addEventListener("click", () => laengeWaehlen(knopf.dataset.laenge));
    }
    const regler = $("#szenen");
    regler.addEventListener("input", () => {
      $("#szenen-wert").value = regler.value;
      laengeHinweisErneuern();
    });
    regler.addEventListener("change", merken);
  }

  function laengeWaehlen(art) {
    zustand.laenge = art;
    for (const knopf of $$("[data-laenge]")) {
      const an = knopf.dataset.laenge === art;
      knopf.classList.toggle("ist-an", an);
      knopf.setAttribute("aria-checked", String(an));
    }
    $("#story-regler").hidden = art !== "story";
    laengeHinweisErneuern();
    merken();
  }

  function laengeHinweisErneuern() {
    const sekunden = Number($("#clipdauer").value) || 5;
    const szenen = zustand.laenge === "story" ? Number($("#szenen").value) || 2 : 1;
    const gesamt = sekunden * szenen;

    let text;
    if (szenen === 1) {
      text = `Ein Clip von ${sekunden} Sekunden.`;
    } else {
      text = `${szenen} Szenen à ${sekunden} s ergeben rund ${gesamt} Sekunden Film.`;
      if ($("#weich").checked) text += " Durch die Überblendungen etwas weniger.";
    }
    // Ehrlich bleiben: mehr Szenen heißt mehr Wartezeit und mehr Guthaben.
    if (szenen > 1) text += ` Es entstehen ${szenen} Aufträge bei Higgsfield.`;
    $("#laenge-hinweis").textContent = text;
  }

  /* ── Briefingvorschau ──────────────────────────────────────────────────── */

  const briefingErneuern = MPW.entprellen(async function () {
    if (zustand.modus !== "formular") return;
    const feld = $("#briefing-vorschau");
    if (!zustand.thema && !$("#betreff").value.trim()) {
      feld.textContent = "Thema wählen und kurz beschreiben, worum es geht.";
      return;
    }
    try {
      const antwort = await MPW.hole("/api/briefing", {
        koerper: {
          thema: zustand.thema,
          betreff: $("#betreff").value,
          argumente: Array.from(zustand.argumente),
          zielgruppe: wertVon("zielgruppe"),
          botschaft: wertVon("botschaft"),
        },
      });
      feld.textContent = antwort.briefing || "—";
    } catch (fehler) {
      feld.textContent = "Vorschau gerade nicht möglich.";
    }
  }, 260);

  function wertVon(name) {
    const feld = $(`[data-zusatz="${name}"]`);
    return feld ? feld.value : "";
  }

  /* ── Auftrag zusammenstellen ───────────────────────────────────────────── */

  function sammeln() {
    const modell = aktuellesModell();
    const sekunden = Number($("#clipdauer").value) || 5;
    const szenen = zustand.laenge === "story" ? Number($("#szenen").value) || 2 : 1;
    const formate = $$("#formatwahl input:checked").map((k) => k.value);

    if (zustand.modus === "frei") {
      const text = $("#freitext").value.trim();
      if (text.length < 3) {
        throw new Error("Bitte zuerst einen Prompt eingeben.");
      }
      return {
        modus: "frei", briefing: text, woertlich: $("#woertlich").checked,
        szenen: $("#woertlich").checked ? 1 : szenen, sekunden,
        videomodell: modell.id, seitenverhaeltnis: $("#verhaeltnis").value,
        weiche_uebergaenge: $("#weich").checked, formate,
      };
    }

    const briefing = $("#briefing-vorschau").textContent.trim();
    if (!zustand.thema) throw new Error("Bitte zuerst ein Thema auswählen.");
    if (!$("#betreff").value.trim()) throw new Error("Bitte kurz beschreiben, worum es geht.");

    return {
      modus: "formular", briefing, szenen, sekunden,
      videomodell: modell.id, seitenverhaeltnis: $("#verhaeltnis").value,
      stil: MPW.formular.stilAusMerkmalen(),
      zielgruppe: wertVon("zielgruppe"), tonfall: "",
      weiche_uebergaenge: $("#weich").checked, formate,
    };
  }

  /** Die angeklickten Merkmale noch einmal getrennt — sie helfen der Prompt-Schmiede,
   *  den Look über alle Szenen gleich zu halten. */
  MPW.formular.stilAusMerkmalen = function () {
    const texte = [];
    for (const gruppe of (zustand.katalog?.argumentgruppen || [])) {
      for (const argument of gruppe.argumente) {
        if (zustand.argumente.has(argument.kennung)) texte.push(argument.text);
      }
    }
    return texte.join(", ");
  };

  function knoepfeVerdrahten() {
    $("#btn-start").addEventListener("click", () => MPW.start.auftragStarten());
    $("#btn-abbruch").addEventListener("click", () => MPW.start.auftragAbbrechen());
  }

  /** Während ein Auftrag läuft, ist die Eingabe gesperrt — sonst ändert jemand die
   *  Einstellungen und wundert sich über das Ergebnis. */
  function sperren(gesperrt) {
    $("#btn-start").disabled = gesperrt;
    $("#btn-start").hidden = gesperrt;
    $("#btn-abbruch").hidden = !gesperrt;
    for (const feld of $$(".rollbereich input, .rollbereich select, .rollbereich textarea, " +
                          ".rollbereich .thema, .rollbereich .segment-knopf")) {
      feld.disabled = gesperrt;
    }
    $("#feld-formular").style.opacity = gesperrt ? ".55" : "";
    $("#feld-frei").style.opacity = gesperrt ? ".55" : "";
  }

  /* ── Eingaben merken ───────────────────────────────────────────────────── */

  const merken = MPW.entprellen(function () {
    MPW.speicher.schreiben("formular", {
      thema: zustand.thema,
      betreff: $("#betreff").value,
      argumente: Array.from(zustand.argumente),
      modus: zustand.modus,
      laenge: zustand.laenge,
      szenen: $("#szenen").value,
      freitext: $("#freitext").value,
      woertlich: $("#woertlich").checked,
      weich: $("#weich").checked,
      verhaeltnis: $("#verhaeltnis").value,
      modell: $("#videomodell").value,
      dauer: $("#clipdauer").value,
      formate: $$("#formatwahl input:checked").map((k) => k.value),
      zusatz: Object.fromEntries($$("[data-zusatz]").map((f) => [f.dataset.zusatz, f.value])),
    });
  }, 500);

  function wiederherstellen() {
    const gemerkt = MPW.speicher.lesen("formular", null);
    if (!gemerkt) {
      themaWaehlen(zustand.katalog.themen[0].kennung);
      return;
    }

    themaWaehlen(gemerkt.thema || zustand.katalog.themen[0].kennung);
    $("#betreff").value = gemerkt.betreff || "";
    $("#freitext").value = gemerkt.freitext || "";
    $("#freitext-zaehler").textContent = String(($("#freitext").value || "").length);
    $("#woertlich").checked = !!gemerkt.woertlich;
    $("#weich").checked = gemerkt.weich !== false;
    if (gemerkt.verhaeltnis) $("#verhaeltnis").value = gemerkt.verhaeltnis;
    if (gemerkt.modell) {
      $("#videomodell").value = gemerkt.modell;
      modellHinweisErneuern();
    }
    if (gemerkt.dauer) $("#clipdauer").value = gemerkt.dauer;

    for (const [name, wert] of Object.entries(gemerkt.zusatz || {})) {
      const feld = $(`[data-zusatz="${name}"]`);
      if (feld) feld.value = wert;
    }

    zustand.argumente = new Set(gemerkt.argumente || []);
    for (const kaestchen of $$("#argumentgruppen input")) {
      kaestchen.checked = zustand.argumente.has(kaestchen.value);
    }
    for (const kaestchen of $$("#formatwahl input")) {
      kaestchen.checked = (gemerkt.formate || []).includes(kaestchen.value);
    }

    if (gemerkt.szenen) {
      $("#szenen").value = gemerkt.szenen;
      $("#szenen-wert").value = gemerkt.szenen;
    }
    laengeWaehlen(gemerkt.laenge || "einzel");
    if (gemerkt.modus === "frei") $("#reiter-frei").click();
  }

})(window.MPW);
