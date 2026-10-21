import { afterEach, describe, expect, it, vi } from "vitest";

import type { CaseCard } from "@/lib/api/admin-cases";
import type { CareBoardCard } from "@/lib/api/care-board";

import {
  CARE_COLUMN_VISIBLE,
  buildColumns,
  careCardHref,
  careDueBadge,
  careItem,
  caseItem,
  decisionIdOf,
  filterCareCards,
  listGroups,
  moveAction,
  planItemIdOf,
  readViewPreference,
  scheduledIso,
  validateBoardState,
  visibleColumnItems,
  writeViewPreference,
  type WorkFilters,
} from "../work-board-model";

function caseCard(overrides: Partial<CaseCard>): CaseCard {
  return {
    id: 1,
    title: "Sprawa",
    area: "administration",
    priority: "P2",
    status: "new",
    due_on: null,
    follow_up_on: null,
    overdue: false,
    assignee: null,
    subject_user: null,
    contract: null,
    source: "manual",
    checklist_done: 0,
    checklist_total: 0,
    created_at: "2026-10-16T08:00:00Z",
    updated_at: "2026-10-16T08:00:00Z",
    closed_at: null,
    ...overrides,
  };
}

function careCard(overrides: Partial<CareBoardCard>): CareBoardCard {
  return {
    key: "contact:plan:1",
    kind: "contact",
    column: "new",
    title: "Rozmowa: Anna Przykładowa",
    subtitle: "Bank Przykładowy · menedżer: Jan Wzorcowy",
    reason_label: "dzień 30",
    due_on: "2026-10-22",
    overdue_days: 0,
    scheduled_at: null,
    retry_on: null,
    note_excerpt: null,
    contract_id: 10,
    candidate_id: 20,
    client_id: 30,
    client_name: "Bank Przykładowy",
    owner_user_id: 5,
    owner_name: "Natalia Opiekuńcza",
    health: null,
    ...overrides,
  };
}

const NO_FILTERS: WorkFilters = { area: null, week: false, unassigned: false, query: "" };

describe("kolumny wspólnej tablicy", () => {
  it("sprawa stoi w kolumnie swojego statusu, karta opieki — swojego stanu", () => {
    const columns = buildColumns(
      [
        caseItem(caseCard({ id: 1, status: "in_progress" })),
        caseItem(caseCard({ id: 2, status: "done" })),
        caseItem(caseCard({ id: 3, status: "closed" })),
        careItem(careCard({ key: "contact:plan:7", column: "waiting" })),
      ],
      { careFirst: false },
    );
    expect(columns.in_progress.map((item) => item.key)).toEqual(["case:1"]);
    expect(columns.done.map((item) => item.key)).toEqual(["case:2"]);
    expect(columns.closed.map((item) => item.key)).toEqual(["case:3"]);
    expect(columns.waiting.map((item) => item.key)).toEqual(["contact:plan:7"]);
    expect(columns.new).toEqual([]);
  });

  it("w Sprawach karty opieki stoją pod sprawami, w Opiece — nad nimi, od najbardziej zaległej", () => {
    const items = [
      caseItem(caseCard({ id: 1 })),
      careItem(careCard({ key: "a", due_on: "2026-10-24", overdue_days: 0 })),
      careItem(careCard({ key: "b", due_on: "2026-10-10", overdue_days: 12 })),
      caseItem(caseCard({ id: 2 })),
      careItem(careCard({ key: "c", due_on: null, overdue_days: 0 })),
    ];
    expect(buildColumns(items, { careFirst: false }).new.map((item) => item.key)).toEqual([
      "case:1",
      "case:2",
      "b",
      "a",
      "c",
    ]);
    expect(buildColumns(items, { careFirst: true }).new.map((item) => item.key)).toEqual([
      "b",
      "a",
      "c",
      "case:1",
      "case:2",
    ]);
  });

  it("ruch w toku przestawia kartę od razu (override), zanim serwer odpowie", () => {
    const columns = buildColumns([caseItem(caseCard({ id: 4 }))], {
      careFirst: false,
      overrides: new Map([["case:4", "waiting"]]),
    });
    expect(columns.new).toEqual([]);
    expect(columns.waiting.map((item) => item.key)).toEqual(["case:4"]);
  });

  it("kolumna pokazuje wszystkie sprawy i 8 kart opieki, resztę po rozwinięciu", () => {
    const care = Array.from({ length: CARE_COLUMN_VISIBLE + 3 }, (_, i) =>
      careItem(careCard({ key: `contact:plan:${i}` })),
    );
    const items = [caseItem(caseCard({ id: 1 })), ...care, caseItem(caseCard({ id: 2 }))];
    const folded = visibleColumnItems(items, false);
    expect(folded.hiddenCare).toBe(3);
    expect(folded.visible.filter((item) => item.type === "case")).toHaveLength(2);
    expect(folded.visible.filter((item) => item.type === "care")).toHaveLength(CARE_COLUMN_VISIBLE);
    expect(visibleColumnItems(items, true)).toEqual({ visible: items, hiddenCare: 0 });
  });
});

describe("filtry kart opieki", () => {
  const cards = [
    careCard({ key: "k1", due_on: "2026-10-23", title: "Rozmowa: Łucja Żółta" }),
    careCard({ key: "k2", due_on: "2026-10-30", overdue_days: 0 }),
    careCard({ key: "k3", due_on: "2026-10-01", overdue_days: 21 }),
    careCard({ key: "k4", kind: "decision", due_on: null, owner_user_id: null, owner_name: null }),
  ];

  it("chip obszaru sprawy chowa karty opieki, „Opieka” i „Wszystkie” je pokazują", () => {
    expect(filterCareCards(cards, { ...NO_FILTERS, area: "onboarding" }, "2026-10-24")).toEqual([]);
    expect(filterCareCards(cards, { ...NO_FILTERS, area: "care" }, "2026-10-24")).toHaveLength(4);
    expect(filterCareCards(cards, NO_FILTERS, "2026-10-24")).toHaveLength(4);
  });

  it("„Na ten tydzień” = po terminie albo termin do piątku; decyzja bez terminu odpada", () => {
    const keys = filterCareCards(cards, { ...NO_FILTERS, week: true }, "2026-10-24").map((c) => c.key);
    expect(keys).toEqual(["k1", "k3"]);
  });

  it("„Bez osoby” = karta bez opiekuna", () => {
    expect(
      filterCareCards(cards, { ...NO_FILTERS, unassigned: true }, "2026-10-24").map((c) => c.key),
    ).toEqual(["k4"]);
  });

  it("szukanie bez wielkości liter i polskich znaków", () => {
    expect(
      filterCareCards(cards, { ...NO_FILTERS, query: "lucja zolta" }, "2026-10-24").map((c) => c.key),
    ).toEqual(["k1"]);
  });
});

describe("ruch karty", () => {
  const options = { canManageCases: true };

  it("sprawa: status z wersją; bez prawa — odmowa; ta sama kolumna — nic", () => {
    const item = caseItem(caseCard({ status: "new" }));
    expect(moveAction(item, "waiting", options)).toEqual({ type: "case-status", status: "waiting" });
    expect(moveAction(item, "done", options)).toEqual({ type: "case-status", status: "done" });
    expect(moveAction(item, "new", options)).toEqual({ type: "none" });
    expect(moveAction(item, "waiting", { canManageCases: false }).type).toBe("forbidden");
  });

  it("rozmowa i opinia w „W toku” pytają o dzień i godzinę, decyzja i popyt — nie", () => {
    expect(moveAction(careItem(careCard({ kind: "contact" })), "in_progress", options)).toEqual({
      type: "care-state",
      column: "in_progress",
      ask: "schedule",
    });
    expect(
      moveAction(careItem(careCard({ kind: "feedback", key: "feedback:3" })), "in_progress", options),
    ).toMatchObject({ ask: "schedule" });
    expect(
      moveAction(careItem(careCard({ kind: "decision", key: "decision:3" })), "in_progress", options),
    ).toMatchObject({ ask: null });
    expect(
      moveAction(careItem(careCard({ kind: "demand", key: "demand:1:0:2" })), "in_progress", options),
    ).toMatchObject({ ask: null });
  });

  it("„Czeka” pyta o dzień ponownej próby, „Nowa” kasuje stan bez pytania", () => {
    const item = careItem(careCard({ column: "in_progress" }));
    expect(moveAction(item, "waiting", options)).toEqual({
      type: "care-state",
      column: "waiting",
      ask: "retry",
    });
    expect(moveAction(item, "new", options)).toEqual({ type: "care-state", column: "new", ask: null });
  });

  it("„Zrobione” otwiera okno zapisu zamiast zmiany stanu", () => {
    expect(moveAction(careItem(careCard({ kind: "contact" })), "done", options).type).toBe(
      "open-conversation",
    );
    expect(moveAction(careItem(careCard({ kind: "feedback" })), "done", options).type).toBe(
      "open-feedback",
    );
    expect(moveAction(careItem(careCard({ kind: "decision" })), "done", options).type).toBe(
      "close-decision",
    );
    expect(moveAction(careItem(careCard({ kind: "demand" })), "done", options).type).toBe(
      "open-demand",
    );
  });

  it("karty opieki rusza się bez prawa do spraw (prawo sprawdza serwer)", () => {
    expect(
      moveAction(careItem(careCard({})), "waiting", { canManageCases: false }).type,
    ).toBe("care-state");
  });
});

describe("okienko „W toku” / „Czeka”", () => {
  it("rozmowa wymaga dnia i godziny", () => {
    expect(validateBoardState("schedule", { day: "", time: "10:00" }, "2026-10-22")).toBe(
      "Podaj dzień rozmowy.",
    );
    expect(validateBoardState("schedule", { day: "2026-10-23", time: "" }, "2026-10-22")).toBe(
      "Podaj godzinę.",
    );
    expect(validateBoardState("schedule", { day: "2026-10-23", time: "10:30" }, "2026-10-22")).toBeNull();
  });

  it("ponowna próba najwcześniej jutro (dziś wróciłaby od razu do „Nowa”)", () => {
    expect(validateBoardState("retry", { day: "2026-10-22", time: "" }, "2026-10-22")).toBe(
      "Ponowna próba najwcześniej jutro.",
    );
    expect(validateBoardState("retry", { day: "", time: "" }, "2026-10-22")).toBe(
      "Podaj dzień ponownej próby.",
    );
    expect(validateBoardState("retry", { day: "2026-10-23", time: "" }, "2026-10-22")).toBeNull();
  });

  it("dzień i godzina z pól → chwila ISO; zły format → null", () => {
    expect(scheduledIso("2026-10-23", "10:30")).toBe(new Date("2026-10-23T10:30:00").toISOString());
    expect(scheduledIso("23.10.2026", "10:30")).toBeNull();
    expect(scheduledIso("2026-10-23", "1030")).toBeNull();
  });
});

describe("lista „Do zrobienia”", () => {
  it("grupy Po terminie · Do piątku · Decyzje · Popyt, bez zrobionych, puste znikają", () => {
    const groups = listGroups(
      [
        caseItem(caseCard({ id: 1, due_on: "2026-10-20", overdue: true })),
        caseItem(caseCard({ id: 2, due_on: "2026-10-23" })),
        caseItem(caseCard({ id: 3, due_on: "2026-11-30" })),
        caseItem(caseCard({ id: 4, status: "done" })),
        careItem(careCard({ key: "contact:plan:9", due_on: "2026-10-21", overdue_days: 1 })),
        careItem(careCard({ key: "decision:5", kind: "decision", due_on: null })),
        careItem(careCard({ key: "demand:1:0:7", kind: "demand", due_on: null })),
      ],
      "2026-10-24",
    );
    expect(groups.map((group) => [group.label, group.items.map((item) => item.key)])).toEqual([
      ["Po terminie", ["case:1", "contact:plan:9"]],
      ["Do piątku", ["case:2"]],
      ["Decyzje", ["decision:5"]],
      ["Popyt", ["demand:1:0:7"]],
      ["Później i bez terminu", ["case:3"]],
    ]);
  });
});

describe("drobne", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("klucze kart opieki: punkt planu i wpis „Do przepięcia”", () => {
    expect(planItemIdOf("contact:plan:42")).toBe(42);
    expect(planItemIdOf("contact:followup:42")).toBeNull();
    expect(decisionIdOf("decision:7")).toBe(7);
    expect(decisionIdOf("demand:1:0:7")).toBeNull();
  });

  it("adres karty poza /care: kontrakt albo klucz karty", () => {
    expect(careCardHref({ contract_id: 10, key: "contact:plan:1" })).toBe("/care?contract=10");
    expect(careCardHref({ contract_id: null, key: "feedback:3" })).toBe("/care?card=feedback%3A3");
  });

  it("termin karty opieki: po terminie czerwony, do piątku żółty, bez terminu nic", () => {
    expect(careDueBadge({ due_on: "2026-10-20", overdue_days: 2 }, "2026-10-22", "2026-10-23")).toEqual({
      text: "po terminie · 20.10",
      tone: "overdue",
    });
    expect(careDueBadge({ due_on: "2026-10-23", overdue_days: 0 }, "2026-10-22", "2026-10-23")).toEqual({
      text: "jutro · 23.10",
      tone: "week",
    });
    expect(careDueBadge({ due_on: null, overdue_days: 0 }, "2026-10-22", "2026-10-23")).toBeNull();
  });

  it("widok pamiętany per osoba i zakres; zablokowana pamięć nie psuje ekranu", () => {
    expect(readViewPreference("care", 7, "board")).toBe("board");
    writeViewPreference("care", 7, "list");
    expect(readViewPreference("care", 7, "board")).toBe("list");
    expect(readViewPreference("care", 8, "board")).toBe("board");
    expect(readViewPreference("cases", 7, "board")).toBe("board");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(() => writeViewPreference("care", 7, "board")).not.toThrow();
    expect(readViewPreference("care", 7, "board")).toBe("board");
  });
});
