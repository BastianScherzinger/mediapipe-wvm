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
    ziel: "",                 // Zielplattform: tiktok, shorts, feed, youtube
    argumente: new Set(),
    modus: "formular",
    laenge: "einzel",
    videomodelle: [],
    formate: [],
    katalog: null,
    briefing: "",             // der zuletzt gebaute Briefingtext
  };

  MPW.formular = { aufbauen, sammeln, sperren, zustand };

  /* ── Aufbau ────────────────────────────────────────────────────────────── */

  function aufbauen(start) {
    zustand.katalog = start.katalog;
    zustand.videomodelle = start.videomodelle;
    zustand.formate = start.formate;

    zieleBauen(start.katalog.plattformen || []);
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

  /* ── Zielplattform ──────────────────────────────────────────────────────
   *
   * Was ein TikTok-Video von einem YouTube-Video unterscheidet, sind vier Zahlen:
   * Bildformat, Szenenzahl, Clipdauer und die Ausgabefassungen. Sie einzeln unter
   * „Weitere Einstellungen“ zusammenzusuchen hat in der Praxis dazu geführt, dass
   * am Ende doch 16:9 eingestellt blieb — und ein Breitbildvideo bei TikTok landete.
   * Ein Klick setzt jetzt alle vier. Überstimmen lässt sich hinterher jede einzelne.
   */
  function zieleBauen(plattformen) {
    const behaelter = $("#ziele");
    if (!behaelter || !plattformen.length) return;
    behaelter.style.gridTemplateColumns = `repeat(${plattformen.length}, 1fr)`;
    behaelter.replaceChildren(...plattformen.map((ziel) =>
      el("button", {
        klasse: "ziel",
        type: "button",
        role: "radio",
        "aria-checked": "false",
        title: ziel.beschreibung,
        daten: { ziel: ziel.kennung },
        onclick: () => zielWaehlen(ziel.kennung),
      }, [
        // Ein Miniaturrahmen im Zielformat statt eines Symbols: Er zeigt unmittelbar,
        // welche Form das Video bekommt — und das ist die eigentliche Entscheidung.
        el("span", {
          klasse: "ziel-rahmen",
          style: "aspect-ratio: " + ziel.seitenverhaeltnis.replace(":", " / "),
        }),
        el("span", { text: ziel.name }),
        el("span", { klasse: "ziel-format", text: ziel.seitenverhaeltnis }),
      ])));
  }

  function zielWaehlen(kennung, nurMarkieren) {
    zustand.ziel = kennung;
    for (const knopf of $$(".ziel")) {
      const an = knopf.dataset.ziel === kennung;
      knopf.classList.toggle("ist-an", an);
      knopf.setAttribute("aria-checked", an ? "true" : "false");
    }

    const ziel = (zustand.katalog.plattformen || []).find((p) => p.kennung === kennung);
    if (!ziel) return;
    $("#ziel-hinweis").textContent = ziel.hinweis || "";
    // Beim Wiederherstellen wird nur markiert: sonst überschriebe die Plattform die
    // Einstellungen, die der Benutzer beim letzten Mal von Hand geändert hat.
    if (nurMarkieren) return;

    $("#verhaeltnis").value = ziel.seitenverhaeltnis;
    $("#clipdauer").value = String(ziel.sekunden);
    if (!$("#clipdauer").value) $("#clipdauer").selectedIndex = 0;

    if (ziel.szenen > 1) {
      laengeWaehlen("story");
      $("#szenen").value = Math.min(ziel.szenen, Number($("#szenen").max));
      $("#szenen-wert").value = $("#szenen").value;
    } else {
      laengeWaehlen("einzel");
    }

    // Die Ausgabefassungen gleich mit: Wer für TikTok erzeugt, will die 9:16-Fassung
    // und nicht drei Fassungen, von denen zwei niemand braucht.
    for (const kaestchen of $$("#formatwahl input")) {
      kaestchen.checked = (ziel.formate || []).includes(kaestchen.value);
    }

    laengeHinweisErneuern();
    merken();
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
    //
    // Die Zielplattform steht dabei über dem Thema: Sie ist die ausdrückliche Wahl
    // „das geht auf TikTok“, das Thema nur die Sorte Video. Wer beides setzt, will
    // nicht, dass ein Themenwechsel sein Hochformat wieder auf Breitbild dreht.
    const vorschlag = thema.vorschlag || {};
    if (vorschlag.seitenverhaeltnis && !zustand.ziel) {
      $("#verhaeltnis").value = vorschlag.seitenverhaeltnis;
    }
    if (vorschlag.szenen > 1 && !zustand.ziel) {
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
      zustand.briefing = "";
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
      zustand.briefing = antwort.briefing || "";
      feld.textContent = zustand.briefing || "—";
    } catch (fehler) {
      // Den letzten guten Text NICHT verwerfen: Er ist die Vorlage für den Auftrag.
      // Vorher wurde der Briefingtext beim Start aus diesem Feld zurückgelesen — ein
      // Aussetzer hier hätte also „Vorschau gerade nicht möglich.“ ins Video gebracht.
      feld.textContent = zustand.briefing ||
        "Vorschau gerade nicht möglich. Bitte kurz warten.";
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

    if (!zustand.thema) throw new Error("Bitte zuerst ein Thema auswählen.");
    if (!$("#betreff").value.trim()) throw new Error("Bitte kurz beschreiben, worum es geht.");
    const briefing = zustand.briefing.trim();
    if (!briefing) throw new Error("Das Briefing ist noch nicht fertig — bitte einen Moment.");

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
      ziel: zustand.ziel,
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
      // Beim allerersten Start: TikTok/Reels ist die häufigste Absicht — und das
      // Format, bei dem eine falsche Voreinstellung am meisten kostet.
      const erste = (zustand.katalog.plattformen || [])[0];
      if (erste) zielWaehlen(erste.kennung);
      themaWaehlen(zustand.katalog.themen[0].kennung);
      return;
    }

    if (gemerkt.ziel) zielWaehlen(gemerkt.ziel, true);
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
