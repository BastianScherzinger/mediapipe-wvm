/* bibliothek.js — die Videoübersicht ganz unten.
 *
 * Eine Kachel je Video. Vorhandene Formatfassungen sind grün markiert, fehlende sind
 * anklickbar und werden dann erzeugt. Genau so hat der Kunde es sich gewünscht: der
 * Formate-Schritt gehört nicht in die Pipeline, sondern hierher — man erzeugt eine
 * Hochformat-Fassung dann, wenn man sie braucht, und nicht auf Verdacht.
 */
"use strict";

(function (MPW) {
  const { $, $$, el, icon } = MPW;

  let videos = [];
  const laufendeFormate = new Set();      // "ordner|format", damit Doppelklicks ins Leere gehen

  MPW.bibliothek = { aufbauen, laden };

  function aufbauen() {
    $("#btn-biblio-neu").addEventListener("click", () => laden(true));
    $("#btn-schau-zu").addEventListener("click", schliessen);
    $("#schau").addEventListener("close", () => {
      const abspieler = $("#schau-video");
      abspieler.pause();
      abspieler.removeAttribute("src");
      abspieler.load();
    });

    // Nach jedem fertigen Video und nach jeder Änderung im Ordner neu einlesen.
    MPW.beiEreignis("bibliothek", MPW.entprellen(() => laden(), 700));
    MPW.beiEreignis("formatfortschritt", fortschrittZeigen);

    laden();
  }

  /* ── Laden ─────────────────────────────────────────────────────────────── */

  async function laden(mitMeldung) {
    try {
      const antwort = await MPW.hole("/api/bibliothek");
      videos = antwort.videos || [];
      zeichnen();
      $("#biblio-notiz").textContent = videos.length
        ? `${videos.length} Video${videos.length === 1 ? "" : "s"} · ${MPW.groesse(antwort.gesamt_mb)}`
        : "";
      if (mitMeldung) MPW.melden("Ordner neu eingelesen.", "erfolg", 2000);
    } catch (fehler) {
      MPW.melden(fehler.message, "fehler");
    }
  }

  function zeichnen() {
    const behaelter = $("#biblio");
    if (!videos.length) {
      behaelter.replaceChildren(el("div", { klasse: "leer" }, [
        icon("film"),
        el("p", { text: "Noch keine Videos." }),
        el("p", { klasse: "leer-klein",
                  text: "Links ein Briefing eingeben und auf „Video erzeugen“ klicken." }),
      ]));
      return;
    }
    behaelter.replaceChildren(...videos.map(karteBauen));
  }

  /* ── Kachel ────────────────────────────────────────────────────────────── */

  function karteBauen(video) {
    const bild = video.poster
      ? el("img", { src: "/medien/" + video.poster, alt: "", loading: "lazy" })
      : el("div", { klasse: "karte-bild-leer" }, [icon("film")]);

    // Hochkante Videos werden nicht quer beschnitten, sondern ganz gezeigt (siehe CSS).
    const hoch = video.hoehe > video.breite;

    const flaeche = el("button", {
      klasse: "karte-bild",
      type: "button",
      title: "Abspielen",
      "aria-label": "Abspielen: " + video.titel,
      daten: hoch ? { hoch: "ja" } : {},
      style: hoch && video.poster
        ? `--kachel-grund: url("/medien/${encodeURI(video.poster)}")` : null,
      onclick: () => abspielen(video),
    }, [
      bild,
      el("span", { klasse: "karte-play" }, [el("span", {}, [icon("play")])]),
      el("span", { klasse: "karte-dauer", text: MPW.dauer(video.dauer) }),
    ]);

    const angaben = [
      video.breite ? `${video.breite}×${video.hoehe}` : null,
      MPW.groesse(video.mb),
      video.szenen > 1 ? `${video.szenen} Szenen` : null,
      video.erstellt,
    ].filter(Boolean).join(" · ");

    return el("article", { klasse: "karte", daten: { ordner: video.ordner } }, [
      flaeche,
      el("div", { klasse: "karte-inhalt" }, [
        el("h3", { klasse: "karte-titel", text: video.titel, title: video.briefing || "" }),
        el("p", { klasse: "karte-angaben", text: angaben }),
        el("div", { klasse: "karte-formate" }, formatMarken(video)),
      ]),
      el("div", { klasse: "karte-fuss" }, [
        werkzeug("download", "Herunterladen", () => herunterladen(video)),
        werkzeug("ordner", "Im Explorer zeigen", () => explorer(video)),
        werkzeug("stift", "Umbenennen", () => umbenennen(video)),
        werkzeug("muell", "Löschen", () => loeschen(video)),
      ]),
    ]);
  }

  function werkzeug(name, titel, beiKlick) {
    return el("button", {
      klasse: "knopf knopf-mini", type: "button", title: titel,
      "aria-label": titel, onclick: beiKlick,
    }, [icon(name)]);
  }

  function formatMarken(video) {
    const marken = [];

    for (const fassung of Object.values(video.fassungen || {})) {
      if (fassung.kennung === "poster") continue;
      marken.push(el("span", {
        klasse: "marke marke-da",
        title: `${fassung.name} · ${MPW.groesse(fassung.mb)} — zum Öffnen klicken`,
        role: "button", tabindex: "0",
        onclick: () => window.open("/medien/" + fassung.datei, "_blank"),
        onkeydown: (e) => { if (e.key === "Enter") window.open("/medien/" + fassung.datei, "_blank"); },
      }, [icon("haken"), fassung.kurz || fassung.name]));
    }

    for (const fehlend of video.fehlende || []) {
      const marke = "" + video.ordner + "|" + fehlend.kennung;
      const laeuft = laufendeFormate.has(marke);
      marken.push(el("button", {
        klasse: "marke marke-fehlt" + (laeuft ? " marke-laeuft" : ""),
        type: "button",
        disabled: laeuft || null,
        title: fehlend.beschreibung + " — klicken zum Erzeugen",
        daten: { ordner: video.ordner, format: fehlend.kennung },
        onclick: (e) => formatErzeugen(video, fehlend.kennung, e.currentTarget),
      }, [laeuft ? "…" : "+", " " + (fehlend.kurz || fehlend.name)]));
    }

    return marken;
  }

  /* ── Aktionen ──────────────────────────────────────────────────────────── */

  async function formatErzeugen(video, kennung, knopf) {
    const marke = video.ordner + "|" + kennung;
    if (laufendeFormate.has(marke)) return;
    laufendeFormate.add(marke);

    knopf.disabled = true;
    knopf.classList.add("marke-laeuft");
    const alterText = knopf.textContent;
    knopf.textContent = "… 0 %";

    try {
      await MPW.hole("/api/bibliothek/format", {
        koerper: { ordner: video.ordner, format: kennung },
      });
      MPW.melden("Format erzeugt.", "erfolg");
      await laden();
    } catch (fehler) {
      MPW.melden(fehler.message, "fehler");
      knopf.textContent = alterText;
      knopf.disabled = false;
      knopf.classList.remove("marke-laeuft");
    } finally {
      laufendeFormate.delete(marke);
    }
  }

  function fortschrittZeigen(nachricht) {
    const knopf = $(`.marke-fehlt[data-ordner="${cssSicher(nachricht.ordner)}"]` +
                    `[data-format="${nachricht.format}"]`);
    if (knopf) knopf.textContent = "… " + Math.round((nachricht.anteil || 0) * 100) + " %";
  }

  /** Ordnernamen enthalten Punkte und Bindestriche — für einen Auswahlausdruck maskieren. */
  function cssSicher(text) {
    return String(text).replace(/["\\]/g, "\\$&");
  }

  function abspielen(video) {
    $("#schau-titel").textContent = video.titel;
    // Ein 9:16-Clip in einem 1080 px breiten Fenster ist ein schmaler Streifen zwischen
    // zwei schwarzen Flächen. Der Rahmen richtet sich deshalb nach dem Video.
    $("#schau").dataset.hoch = video.hoehe > video.breite ? "ja" : "";
    const abspieler = $("#schau-video");
    abspieler.src = "/medien/" + video.film;
    if (video.poster) abspieler.poster = "/medien/" + video.poster;

    postingZeigen(video);

    const fassungen = Object.values(video.fassungen || {})
      .filter((f) => f.kennung !== "poster");
    $("#schau-fuss").replaceChildren(
      el("span", { text: `${MPW.dauer(video.dauer)} · ${video.breite}×${video.hoehe} · ` +
                         `${MPW.groesse(video.mb)}` }),
      ...fassungen.map((fassung) => el("a", {
        klasse: "knopf knopf-mini",
        href: "/api/herunterladen/" + fassung.datei,
        title: "Herunterladen: " + fassung.name,
      }, [icon("download"), " " + (fassung.kurz || fassung.name)])),
    );

    $("#schau").showModal();
    abspieler.play().catch(() => { /* der Benutzer startet dann von Hand */ });
  }

  /* ── Posting-Text ───────────────────────────────────────────────────────
   *
   * Ein fertiges Video ist nur die halbe Arbeit — danach fehlen noch Titel, Text und
   * Hashtags, und genau daran bleibt man beim Hochladen hängen. Das Sprachmodell hat
   * beides beim Drehbuch ohnehin geschrieben; hier steht es zum Kopieren bereit.
   * Videos aus älteren Fassungen haben es nicht — dann bleibt der Bereich verborgen.
   */
  function postingZeigen(video) {
    const bereich = $("#schau-posting");
    const posting = video.posting || {};
    const text = (posting.text || "").trim();
    const tags = posting.hashtags || [];

    if (!text && !tags.length) {
      bereich.hidden = true;
      bereich.replaceChildren();
      return;
    }

    const zumKopieren = [video.titel, "", text, "",
                         tags.map((w) => "#" + w).join(" ")]
      .join("\n").replace(/\n{3,}/g, "\n\n").trim();

    bereich.hidden = false;
    bereich.replaceChildren(
      el("div", { klasse: "schau-posting-kopf" }, [
        el("span", { klasse: "schau-posting-name", text: "Zum Veröffentlichen" }),
        el("button", {
          klasse: "knopf knopf-mini", type: "button",
          title: "Titel, Text und Hashtags kopieren",
          onclick: () => kopieren(zumKopieren),
        }, [icon("kopieren"), " Kopieren"]),
      ]),
      el("p", { klasse: "schau-posting-text", text }),
      ...(tags.length
        ? [el("p", { klasse: "schau-posting-tags",
                     text: tags.map((w) => "#" + w).join(" ") })]
        : []),
    );
  }

  async function kopieren(text) {
    try {
      await navigator.clipboard.writeText(text);
      MPW.melden("In die Zwischenablage kopiert.", "erfolg", 2000);
    } catch (fehler) {
      MPW.melden("Kopieren hat nicht geklappt.", "fehler");
    }
  }

  function schliessen() {
    $("#schau").close();
  }

  function herunterladen(video) {
    window.location.href = "/api/herunterladen/" + video.film;
  }

  async function explorer(video) {
    try {
      await MPW.hole("/api/bibliothek/explorer", { koerper: { ordner: video.ordner } });
    } catch (fehler) {
      MPW.melden(fehler.message, "fehler");
    }
  }

  async function umbenennen(video) {
    const titel = window.prompt("Neuer Titel:", video.titel);
    if (titel === null) return;
    try {
      await MPW.hole("/api/bibliothek/umbenennen", {
        koerper: { ordner: video.ordner, titel },
      });
      await laden();
    } catch (fehler) {
      MPW.melden(fehler.message, "fehler");
    }
  }

  async function loeschen(video) {
    // Bewusst zweistufig: die Rückfrage nennt den Titel, und der Server verlangt
    // zusätzlich eine ausdrückliche Bestätigung im Auftrag.
    const sicher = window.confirm(
      `„${video.titel}“ mit allen Formatfassungen unwiderruflich löschen?`);
    if (!sicher) return;
    try {
      await MPW.hole("/api/bibliothek/loeschen", {
        koerper: { ordner: video.ordner, bestaetigt: true },
      });
      MPW.melden("Video gelöscht.", "erfolg");
      await laden();
    } catch (fehler) {
      MPW.melden(fehler.message, "fehler");
    }
  }

})(window.MPW);
