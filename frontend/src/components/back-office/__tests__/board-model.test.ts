import { describe, expect, it } from "vitest";

import type { BoCard } from "@/lib/api/back-office";

import {
  amountLabel,
  defaultTeam,
  dueTone,
  matchesFilter,
  matchesSearch,
  othersPriority,
  stepSummary,
  waitLabel,
  weekEnd,
} from "../board-model";

function card(fields: Partial<BoCard> = {}): BoCard {
  return {
    id: 1,
    team: "care",
    lane: "help",
    source_kind: "case",
    title: "Pytanie o dostęp",
    person: "Jan Przykładowy",
    client: "Firma Testowa",
    state: "new",
    waiting_on: null,
    due_on: null,
    href: null,
    assignee: null,
    substituting: false,
    created_at: "2026-11-02T10:00:00+01:00",
    updated_at: "2026-11-02T10:00:00+01:00",
    escalated: false,
    priority: null,
    needs_review: false,
    triage_guess: null,
    case_id: null,
    case_source: null,
    actions: [],
    amounts: null,
    count: null,
    steps: null,
    parent_title: null,
    meta: {},
    ...fields,
  };
}

describe("termin karty", () => {
  it("po terminie = czerwony, do 3 dni = żółty, reszta i brak daty = neutralny", () => {
    expect(dueTone("2026-11-01", "2026-11-02")).toBe("danger");
    expect(dueTone("2026-11-05", "2026-11-02")).toBe("warning");
    expect(dueTone("2026-11-06", "2026-11-02")).toBe("neutral");
    expect(dueTone(null, "2026-11-02")).toBe("neutral");
  });

  it("tydzień kończy się w piątek, a w weekend liczy się ten, który się zaczyna", () => {
    expect(weekEnd("2026-11-02")).toBe("2026-11-06");
    expect(weekEnd("2026-11-06")).toBe("2026-11-06");
    expect(weekEnd("2026-11-07")).toBe("2026-11-13");
    expect(weekEnd("2026-11-08")).toBe("2026-11-13");
  });
});

describe("filtry", () => {
  const mine = card({ assignee: { id: 7, name: "Ja" } });
  const free = card();

  it("Moje i Do wzięcia rozdzielają karty po osobie", () => {
    expect(matchesFilter(mine, "mine", 7, "2026-11-02")).toBe(true);
    expect(matchesFilter(free, "mine", 7, "2026-11-02")).toBe(false);
    expect(matchesFilter(free, "free", 7, "2026-11-02")).toBe(true);
    expect(matchesFilter(mine, "free", 7, "2026-11-02")).toBe(false);
  });

  it("Do przydzielenia to karta po eskalacji i dalej bez osoby", () => {
    expect(matchesFilter(card({ escalated: true }), "escalated", 7, "2026-11-02")).toBe(true);
    expect(matchesFilter(card({ escalated: false }), "escalated", 7, "2026-11-02")).toBe(false);
    expect(
      matchesFilter(card({ escalated: true, assignee: { id: 1, name: "X" } }), "escalated", 7, "2026-11-02"),
    ).toBe(false);
  });

  it("Na ten tydzień pomija kartę bez terminu", () => {
    expect(matchesFilter(card({ due_on: "2026-11-06" }), "week", 7, "2026-11-02")).toBe(true);
    expect(matchesFilter(card({ due_on: "2026-11-07" }), "week", 7, "2026-11-02")).toBe(false);
    expect(matchesFilter(card(), "week", 7, "2026-11-02")).toBe(false);
  });

  it("szukanie bez wielkości liter, po tytule, osobie, kliencie i prowadzącym", () => {
    expect(matchesSearch(card(), "PRZYKŁADOWY")).toBe(true);
    expect(matchesSearch(card(), "firma")).toBe(true);
    expect(matchesSearch(card({ assignee: { id: 1, name: "Anna" } }), "anna")).toBe(true);
    expect(matchesSearch(card(), "nieistnieje")).toBe(false);
    expect(matchesSearch(card(), "  ")).toBe(true);
  });
});

describe("opis na karcie", () => {
  it("czas bez osoby liczy od założenia, a karta z akceptem go nie pokazuje", () => {
    expect(waitLabel(card(), "2026-11-02")).toBe("dziś");
    expect(waitLabel(card(), "2026-11-03")).toBe("1 dzień bez osoby");
    expect(waitLabel(card(), "2026-11-05")).toBe("3 dni bez osoby");
    expect(waitLabel(card({ actions: ["approve"] }), "2026-11-05")).toBe("");
    expect(waitLabel(card({ state: "waiting", waiting_on: "klienta" }), "2026-11-05")).toBe("czeka na: klienta");
  });

  it("kwota tylko gdy serwer ją dał", () => {
    expect(amountLabel(card())).toBeNull();
    expect(amountLabel(card({ amounts: [{ total: "1512.00", currency: "PLN" }] }))).toMatch(/1\s?512 PLN/);
  });

  it("kroki opisują wejście, wyjście i krok w cudzej kolumnie", () => {
    expect(stepSummary(card())).toBeNull();
    expect(stepSummary(card({ lane: "exit", steps: { done: 2, total: 5 } }))).toBe("Wyjście · 2 z 5 kroków");
    expect(stepSummary(card({ lane: "entry", steps: { done: 1, total: 4 } }))).toBe("Wejście · 1 z 4 kroków");
    expect(stepSummary(card({ source_kind: "step", parent_title: "Koniec współpracy" }))).toBe(
      "Krok sprawy: Koniec współpracy",
    );
  });

  it("cudze pierwszeństwo wygasa z datą, własne nie blokuje", () => {
    const priority = { user_id: 5, name: "Anna", until: "2026-11-05" };
    expect(othersPriority(card({ priority }), 7, "2026-11-05")).toBe(true);
    expect(othersPriority(card({ priority }), 7, "2026-11-06")).toBe(false);
    expect(othersPriority(card({ priority }), 5, "2026-11-05")).toBe(false);
  });

  it("kierownik startuje od całości, zespół od swojej tablicy", () => {
    const teams = [{ id: "care", label: "Opieka", lanes: [] }] as never;
    const me = { user_id: 1, name: "A", in_progress: 0, limit: 5, sees_amounts: false };
    expect(defaultTeam({ teams, me: { ...me, teams: [], is_lead: true } })).toBe("all");
    expect(defaultTeam({ teams, me: { ...me, teams: ["finance"], is_lead: false } })).toBe("finance");
  });
});
