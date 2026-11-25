import { describe, expect, it } from "vitest";

import {
  daysBetween,
  daysLeftLabel,
  deadlineEntries,
  deadlinesByMonth,
  eventLine,
  orderChanges,
  runSummaryLine,
  safeExternalUrl,
  safeInternalLink,
} from "@/components/compliance/compliance-model";
import type { LawChangeListItem } from "@/lib/api/compliance";

function row(overrides: Partial<LawChangeListItem>): LawChangeListItem {
  return {
    id: 1,
    title: "Zmiana",
    summary: [],
    roles: ["accounting"],
    urgency: "soon",
    stage: "sejm",
    effective_on: null,
    deadline: null,
    legal_ref: null,
    status: "new",
    decision_note: null,
    decided_at: null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    probes: [],
    tasks: { open: 0, done: 0 },
    ...overrides,
  };
}

describe("Przepisy — model", () => {
  it("dni do terminu liczone po dniach kalendarza, także przez przełom roku", () => {
    expect(daysBetween("2026-12-31", "2027-01-01")).toBe(1);
    expect(daysBetween("2026-03-28", "2026-03-30")).toBe(2);
    expect(daysLeftLabel(0)).toBe("dziś");
    expect(daysLeftLabel(-3)).toBe("po terminie 3 dni");
  });

  it("terminy: tylko otwarte zmiany, wejście w życie od dziś, termin także po czasie", () => {
    const today = "2026-11-15";
    const entries = deadlineEntries(
      [
        row({ id: 1, deadline: "2026-11-10", effective_on: "2026-01-01" }),
        row({ id: 2, effective_on: "2027-01-01" }),
        row({ id: 3, deadline: "2026-12-01", status: "done" }),
        row({ id: 4, deadline: "2026-12-05", status: "in_progress" }),
      ],
      today,
    );
    expect(entries.map((e) => [e.changeId, e.kind, e.days])).toEqual([
      [1, "deadline", -5],
      [4, "deadline", 20],
      [2, "effective", 47],
    ]);
    expect(deadlinesByMonth(entries).map((g) => g.month)).toEqual(["2026-11", "2026-12", "2027-01"]);
  });

  it("zamknięte zmiany idą na koniec listy, reszta w kolejności z API", () => {
    const ordered = orderChanges([
      row({ id: 1, status: "not_applicable" }),
      row({ id: 2 }),
      row({ id: 3, status: "done" }),
      row({ id: 4, status: "in_progress" }),
    ]);
    expect(ordered.map((c) => c.id)).toEqual([2, 4, 1, 3]);
  });

  it("linki: zewnętrzne tylko http(s), sondy tylko wewnątrz NEXUSA", () => {
    expect(safeExternalUrl("https://example.gov.pl/a")).toBe("https://example.gov.pl/a");
    expect(safeExternalUrl("javascript:alert(1)")).toBeNull();
    expect(safeInternalLink("/contracts")).toBe("/contracts");
    expect(safeInternalLink("//evil.example")).toBeNull();
    expect(safeInternalLink("https://evil.example")).toBeNull();
  });

  it("linia biegu: znane liczby po polsku, reszta pominięta", () => {
    expect(
      runSummaryLine({ kind: "collect", summary: { items_in: 4, new: 3, known: 1, duplicates: 0, by_class: { official: 3 } } }),
    ).toBe("pozycje w raporcie: 4 · nowe: 3 · znane: 1 · powtórki: 0");
    expect(runSummaryLine({ kind: "analyze", summary: { created: 2, dropped: { no_items: 1 } } })).toBe("nowe zmiany: 2");
  });

  it("linia Zbieracza pokazuje wynik bramki i pominięty LEX", () => {
    expect(
      runSummaryLine({
        kind: "collect",
        summary: { items_in: 9, gate: { verified: 5, unverified: 3, rejected: 1 }, lex_skipped: true },
      }),
    ).toBe(
      "pozycje w raporcie: 9 · bramka: zgodne z API Sejmu 5, bez potwierdzenia 3, odrzucone 1 · LEX pominięty",
    );
  });

  it("odróżnia pominięcie źródła od braku nowych zapisów", () => {
    expect(runSummaryLine({
      kind: "collect",
      summary: { lex_skipped: true, lex_skip_reason: "device_approval", saved_sources: { lex: 0, gofin: 5 } },
    })).toBe("LEX pominięty (wymagane zatwierdzenie urządzenia), zapisane pozycje: 0 · Gofin zapisane pozycje: 5");
    expect(runSummaryLine({ kind: "collect", summary: { saved_sources: { lex: 0, gofin: 0 } } }))
      .toBe("LEX zapisane pozycje: 0 · Gofin zapisane pozycje: 0");
  });

  it("linia Zbieracza pokazuje pominięty Gofin", () => {
    expect(
      runSummaryLine({ kind: "collect", summary: { items_in: 2, lex_skipped: true, gofin_skipped: true } }),
    ).toBe("pozycje w raporcie: 2 · LEX pominięty · Gofin pominięty");
  });
  it("zmianę założoną przez NEXUS (Przejrzyj wzory) dziennik nie przypisuje Analitykowi", () => {
    const base = { id: 1, kind: "created" as const, from: null, to: null, note: null, task_id: null, by: null, at: "2099-01-01T00:00:00Z" };
    expect(eventLine({ ...base, bot: true })).toBe("Zmiana założona przez Analityka");
    expect(eventLine({ ...base, bot: false })).toBe("Zmiana założona przez NEXUS");
  });
});
