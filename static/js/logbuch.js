/* logbuch.js — das Logfenster unter dem Ablauf.
 *
 * Zeigt, was das Programm gerade tut. Wichtig für ein Werkzeug, das minutenlang
 * arbeitet: der Benutzer soll nie vor einer stillen Oberfläche sitzen und rätseln,
 * ob noch etwas passiert.
 *
 * Zwei Kleinigkeiten mit großer Wirkung:
 *   - Automatisch nachrollen nur, solange der Benutzer unten steht. Wer nach oben
 *     gescrollt hat, um etwas zu lesen, wird nicht weggerissen.
 *   - Höchstzahl an Zeilen im Fenster. Ein stundenlanger Lauf soll den Browser nicht
 *     langsam machen.
 */
"use strict";

(function (MPW) {
  const { $, el } = MPW;

  const HOECHSTZAHL = 400;
  const RANG = { debug: 0, info: 1, erfolg: 1, warnung: 2, fehler: 3 };

  let mindestRang = 1;
  let listeEl = null;
  let folgtUnten = true;

  MPW.logbuch = { aufbauen, anhaengen, leeren };

  function aufbauen() {
    listeEl = $("#log");

    listeEl.addEventListener("scroll", () => {
      const abstand = listeEl.scrollHeight - listeEl.scrollTop - listeEl.clientHeight;
      folgtUnten = abstand < 40;
    });

    $("#log-ebene").addEventListener("change", (ereignis) => {
      mindestRang = RANG[ereignis.target.value] ?? 0;
      neuZeichnen();
      MPW.speicher.schreiben("log-ebene", ereignis.target.value);
    });

    const gemerkt = MPW.speicher.lesen("log-ebene", "info");
    $("#log-ebene").value = gemerkt;
    mindestRang = RANG[gemerkt] ?? 0;

    $("#btn-log-kopieren").addEventListener("click", kopieren);

    $("#btn-log-klappen").addEventListener("click", () => {
      const kasten = $("#log-glas");
      const zu = kasten.classList.toggle("zu");
      $("#btn-log-klappen").setAttribute("aria-expanded", String(!zu));
      MPW.speicher.schreiben("log-zu", zu);
    });
    if (MPW.speicher.lesen("log-zu", false)) $("#btn-log-klappen").click();

    MPW.beiEreignis("log", anhaengen);

    nachladen();
  }

  /** Holt den bisherigen Verlauf — wichtig nach dem Neuladen der Seite und nach einer
   *  Unterbrechung: die Vorgeschichte darf nicht fehlen. */
  async function nachladen() {
    try {
      const antwort = await MPW.hole("/api/log?grenze=200");
      leeren();
      for (const zeile of antwort.zeilen || []) anhaengen(zeile, true);
      nachRollen(true);
    } catch (fehler) { /* ohne Verlauf lässt es sich auch arbeiten */ }
  }

  function anhaengen(eintrag, ohneRollen) {
    if (!listeEl) return;
    const zeile = zeileBauen(eintrag);
    listeEl.append(zeile);

    while (listeEl.childElementCount > HOECHSTZAHL) listeEl.firstElementChild.remove();
    if (!ohneRollen) nachRollen();
  }

  function zeileBauen(eintrag) {
    const sichtbar = (RANG[eintrag.ebene] ?? 1) >= mindestRang;
    return el("li", {
      klasse: "log-zeile",
      daten: { ebene: eintrag.ebene, rang: String(RANG[eintrag.ebene] ?? 1) },
      hidden: !sichtbar || null,
    }, [
      el("span", { klasse: "log-zeit", text: eintrag.zeit || "" }),
      el("span", { klasse: "log-quelle", text: eintrag.quelle || "" }),
      el("span", { klasse: "log-text", text: eintrag.text || "" }),
    ]);
  }

  function neuZeichnen() {
    for (const zeile of MPW.$$(".log-zeile", listeEl)) {
      zeile.hidden = Number(zeile.dataset.rang) < mindestRang;
    }
    nachRollen(true);
  }

  function nachRollen(erzwingen) {
    if (!folgtUnten && !erzwingen) return;
    // Am Ende des Anzeigedurchlaufs rollen, sonst kennt der Browser die neue Höhe noch nicht.
    requestAnimationFrame(() => { listeEl.scrollTop = listeEl.scrollHeight; });
  }

  function leeren() {
    if (listeEl) listeEl.replaceChildren();
  }

  async function kopieren() {
    const text = MPW.$$(".log-zeile", listeEl)
      .filter((zeile) => !zeile.hidden)
      .map((zeile) => Array.from(zeile.children).map((s) => s.textContent).join("  "))
      .join("\n");
    try {
      await navigator.clipboard.writeText(text);
      MPW.melden("Logbuch kopiert.", "erfolg");
    } catch (fehler) {
      MPW.melden("Kopieren war nicht möglich.", "fehler");
    }
  }

})(window.MPW);
