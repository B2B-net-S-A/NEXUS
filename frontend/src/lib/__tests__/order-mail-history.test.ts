/** Historia automatycznej weryfikacji: co zmienił bieg, które wiersze są „ciche”. */
import { describe, expect, it } from "vitest";

import type { OrderMailRecheckEntry, OrderMailRecheckRun } from "@/lib/api/orderMail";
import { historyRows, isQuiet, recheckEntryLabel, runChanges } from "@/lib/order-mail-history";

function entry(over: Partial<OrderMailRecheckEntry> = {}): OrderMailRecheckEntry {
  return {
    document_id: 1, client_id: 1, client_name: "Bank Przykładowy", order_number: "7/2031", people: ["Jan Kowalski"],
    outcome: "held", category: "other", reasons: ["powód"], alerted: false, ...over,
  };
}

function run(id: number, entries: OrderMailRecheckEntry[], over: Partial<OrderMailRecheckRun> = {}): OrderMailRecheckRun {
  return {
    id, started_at: "2031-03-03T08:00:00Z", finished_at: "2031-03-03T08:00:30Z", trigger: "scheduled",
    checked: entries.length, applied: entries.filter((e) => e.outcome === "applied").length,
    held: entries.filter((e) => e.outcome === "held").length, entries, ...over,
  };
}

describe("runChanges", () => {
  it("opisuje zapis, nowy wpis, zmianę kategorii, powodu i kartę dla DL", () => {
    const older = run(1, [
      entry({ document_id: 1 }),
      entry({ document_id: 2, order_number: "8/2031", category: "awaiting_contract" }),
      entry({ document_id: 3, order_number: "9/2031", reasons: ["stary"] }),
      entry({ document_id: 4, order_number: "10/2031" }),
    ]);
    const newer = run(2, [
      entry({ document_id: 1, outcome: "applied" }),
      entry({ document_id: 2, order_number: "8/2031", category: "other", alerted: true }),
      entry({ document_id: 3, order_number: "9/2031", reasons: ["nowy"] }),
      entry({ document_id: 5, order_number: null, people: [] }),
    ]);
    expect(runChanges(newer, older)).toEqual([
      "zapisano: 7/2031",
      "zmiana na „wymaga weryfikacji”: 8/2031",
      "karta do Delivery Leada: 8/2031",
      "zmiana powodu: 9/2031",
      "nowe do sprawdzenia: Dokument #5",
      "zeszło z kolejki: 10/2031",
    ]);
  });

  it("bieg identyczny z poprzednim nie ma zmian; najstarszy nie wymyśla „nowych”", () => {
    const a = run(1, [entry()]);
    expect(runChanges(run(2, [entry()]), a)).toEqual([]);
    expect(runChanges(a, undefined)).toEqual([]);
    expect(runChanges(run(3, [entry({ outcome: "error" })]), undefined)).toEqual(["błąd przy: 7/2031"]);
  });
});

describe("historyRows i isQuiet", () => {
  it("cichy = zmienił się tylko stan powiadomień; najstarszy i ręczny nigdy nie są cisi", () => {
    // Od najnowszego: karta wróciła do zera (cichy), karta wyszła, stan wyjściowy.
    const runs = [
      run(3, [entry({ alerted: false })]),
      run(2, [entry({ alerted: true })]),
      run(1, [entry({ alerted: false })]),
    ];
    const { rows, quiet } = historyRows(runs);
    expect(rows.map((r) => [r.run.id, r.changes, r.oldest])).toEqual([
      [3, [], false],
      [2, ["karta do Delivery Leada: 7/2031"], false],
      [1, [], true],
    ]);
    expect(quiet).toBe(1);
    expect(rows.map(isQuiet)).toEqual([true, false, false]);
    const manual = historyRows([run(5, [entry()], { trigger: "manual" }), run(4, [entry()])]);
    expect(manual.quiet).toBe(0);
  });

  it("jedyny wiersz historii nie jest „najstarszym” do porównań", () => {
    expect(historyRows([run(1, [entry()])]).rows[0].oldest).toBe(false);
  });

  it("etykieta wpisu: numer, potem osoby, potem numer dokumentu", () => {
    expect(recheckEntryLabel(entry())).toBe("7/2031");
    expect(recheckEntryLabel(entry({ order_number: null }))).toBe("Jan Kowalski");
    expect(recheckEntryLabel(entry({ order_number: null, people: [], document_id: 9 }))).toBe("Dokument #9");
  });
});
