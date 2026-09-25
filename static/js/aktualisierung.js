/* aktualisierung.js — der Knopf, der neue Fassungen holt und neu startet.
 *
 * Der Kunde soll kein Terminal öffnen müssen. Der Knopf sagt schon durch seine Farbe,
 * ob etwas zu tun ist: grün heißt aktuell, gelb mit Anzahl heißt, es liegt etwas bereit.
 *
 * Der heikle Teil ist der Neustart. Das Programm beendet sich dabei selbst, die
 * Verbindung bricht also ab — das ist kein Fehler, sondern der erwartete Ablauf. Die
 * Oberfläche wartet deshalb aktiv darauf, dass der neue Server antwortet, und lädt sich
 * dann selbst neu. Für den Benutzer sieht es aus wie ein kurzer Moment Geduld.
 */
"use strict";

(function (MPW) {
  const { $ } = MPW;

  //: Wie oft im Hintergrund nachgesehen wird (30 Minuten).
  const PRUEFTAKT = 30 * 60 * 1000;

  let stand = null;
  let laeuftGerade = false;
  let auftragLaeuft = false;
  //: Startkennung des Servers, der diese Seite ausgeliefert hat („gestartet“ aus
  //: /api/lebt). Ändert sie sich, läuft ein neuer Prozess — auch wenn der Neustart so
  //: schnell ging, dass zwischendurch keine Anfrage ins Leere lief.
  let bekannterStart = null;

  MPW.aktualisierung = { aufbauen, pruefen, auftragszustand };

  function aufbauen() {
    const knopf = $("#btn-aktualisierung");
    if (!knopf) return;
    knopf.addEventListener("click", anklicken);

    // Erste Prüfung ohne Netz, damit das Fenster sofort etwas anzeigt; die richtige
    // Prüfung folgt gleich danach.
    pruefen(true).then(() => pruefen(false));
    setInterval(() => pruefen(false), PRUEFTAKT);

    MPW.beiEreignis("neustart", () => aufNeustartWarten());
    startkennungHolen().then((kennung) => { bekannterStart = kennung; });
  }

  /** Fragt /api/lebt. Zurück: {erreichbar, kennung} — kennung ist null, wenn der
   *  Server (ältere Fassung) kein Feld „gestartet“ liefert. */
  async function lebt() {
    try {
      const antwort = await fetch("/api/lebt", { cache: "no-store" });
      if (!antwort.ok) return { erreichbar: false, kennung: null };
      let daten = {};
      try { daten = await antwort.json(); } catch (fehler) { /* ältere Fassung */ }
      const kennung = daten && daten.gestartet !== undefined && daten.gestartet !== null
        ? String(daten.gestartet) : null;
      return { erreichbar: true, kennung };
    } catch (fehler) {
      return { erreichbar: false, kennung: null };
    }
  }

  async function startkennungHolen() {
    return (await lebt()).kennung;
  }

  /** Meldet, ob gerade ein Videoauftrag läuft — dann ist der Knopf gesperrt. */
  function auftragszustand(laeuft) {
    auftragLaeuft = Boolean(laeuft);
    zeichnen();
  }

  async function pruefen(schnell) {
    try {
      const antwort = await MPW.hole("/api/aktualisierung" + (schnell ? "?schnell=1" : ""));
      stand = antwort.stand;
      zeichnen();
      return stand;
    } catch (fehler) {
      stand = { moeglich: false, zustand: "unbekannt", anzahl: 0,
                meldung: "Der Stand ließ sich nicht abfragen.", version: "?" };
      zeichnen();
      return stand;
    }
  }

  function zeichnen() {
    const knopf = $("#btn-aktualisierung");
    const text = $("#aktualisierung-text");
    if (!knopf || !stand) return;

    knopf.hidden = false;
    knopf.dataset.zustand = stand.zustand || "unbekannt";
    knopf.dataset.laeuft = laeuftGerade ? "ja" : "nein";

    // Der Knopf heißt immer „Update“ — die Farbe und die Zahl sagen den Rest. Ein
    // wechselnder Text („Aktuell“ / „Version“) lässt ihn wie verschiedene Knöpfe wirken.
    if (stand.zustand === "verfuegbar") {
      text.textContent = `Update (${stand.anzahl})`;
    } else if (stand.zustand === "aktuell" || stand.zustand === "nicht_moeglich") {
      text.textContent = "Update";
    } else {
      text.textContent = "Update ?";
    }

    // Während eines Auftrags bleibt der Knopf klickbar: Der Klick erklärt dann, warum
    // es gerade nicht geht (siehe `anklicken`), statt stumm grau zu sein.
    knopf.disabled = laeuftGerade;

    const teile = [];
    if (stand.version) teile.push("Stand: " + stand.version);
    if (stand.meldung) teile.push(stand.meldung);
    if (stand.hinweis) teile.push(stand.hinweis);
    if (auftragLaeuft && stand.zustand === "verfuegbar") {
      teile.push("Erst möglich, wenn kein Auftrag mehr läuft.");
    } else if (stand.zustand === "verfuegbar") {
      teile.push("Klicken zum Holen und Neustarten.");
    } else if (stand.zustand === "aktuell") {
      teile.push("Klicken, um erneut nachzusehen.");
    }
    knopf.title = teile.join("  ·  ");
  }

  async function anklicken() {
    if (laeuftGerade || !stand) return;

    // Nichts zu holen? Dann ist der Klick eine erneute Nachfrage.
    if (stand.zustand !== "verfuegbar") {
      laeuftGerade = true;
      zeichnen();
      const neu = await pruefen(false);
      laeuftGerade = false;
      zeichnen();
      MPW.melden(neu.meldung || "Geprüft.",
                 neu.zustand === "verfuegbar" ? "info" : "erfolg");
      return;
    }

    if (auftragLaeuft) {
      MPW.melden("Erst möglich, wenn kein Auftrag mehr läuft.", "fehler");
      return;
    }

    const sicher = window.confirm(
      `Update holen? (${stand.anzahl} Änderung${stand.anzahl === 1 ? "" : "en"})\n\n` +
      "Das Programm wird dabei neu gestartet. Fertige Videos und Einstellungen " +
      "bleiben erhalten.");
    if (!sicher) return;

    laeuftGerade = true;
    zeichnen();
    MPW.melden("Neuer Stand wird geholt …", "info", 20000);
    // Die Kennung unmittelbar vor dem Neustart — sie gehört sicher zum alten Prozess.
    const vorher = await startkennungHolen();
    if (vorher) bekannterStart = vorher;

    try {
      const antwort = await MPW.hole("/api/aktualisierung", { method: "POST" });
      if (antwort.ergebnis?.neustart === false) {
        // Während der Installation hat ein Auftrag begonnen — der Neustart kommt, sobald
        // er fertig ist. Bis dahin arbeitet das Programm normal weiter.
        MPW.melden(antwort.ergebnis.meldung, "erfolg", 12000);
        laeuftGerade = false;
        await pruefen(true);
        return;
      }
      MPW.melden(antwort.ergebnis?.meldung || "Aktualisiert. Das Programm startet neu …",
                 "erfolg", 30000);
      aufNeustartWarten();
    } catch (fehler) {
      laeuftGerade = false;
      zeichnen();
      MPW.melden(fehler.message, "fehler", 12000);
    }
  }

  /**
   * Wartet, bis der neu gestartete Server antwortet, und lädt dann die Seite neu.
   *
   * Erkannt wird der neue Server an seiner Startkennung („gestartet“): Weicht sie von
   * der bekannten ab, antwortet ein anderer Prozess. So wird auch ein Neustart erkannt,
   * der schneller ging als ein Abfragetakt. Liefert der Server keine Kennung (ältere
   * Fassung), gilt die alte Regel: Erst muss der alte Server wirklich weg sein — sonst
   * landete die erste Anfrage noch beim sterbenden Prozess und die Seite lüde zu früh.
   */
  async function aufNeustartWarten() {
    if (aufNeustartWarten.aktiv) return;      // Ereignis und Klick rufen beide
    aufNeustartWarten.aktiv = true;
    laeuftGerade = true;
    zeichnen();

    const bis = Date.now() + 90000;
    let warWeg = false;

    while (Date.now() < bis) {
      await new Promise((f) => setTimeout(f, 1200));
      const { erreichbar, kennung } = await lebt();

      if (!erreichbar) {
        warWeg = true;                    // der alte Server ist beendet
        continue;
      }
      const neuerProzess = Boolean(kennung && bekannterStart && kennung !== bekannterStart);
      if (warWeg || neuerProzess) {       // und der neue antwortet wieder
        MPW.melden("Neu gestartet. Die Ansicht wird aufgefrischt …", "erfolg", 4000);
        setTimeout(() => window.location.reload(), 700);
        return;
      }
    }

    aufNeustartWarten.aktiv = false;
    laeuftGerade = false;
    zeichnen();
    MPW.melden("Das Programm meldet sich nicht zurück. Bitte von Hand neu starten.",
               "fehler", 20000);
  }

})(window.MPW);
