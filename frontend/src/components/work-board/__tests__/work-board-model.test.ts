import { afterEach, describe, expect, it, vi } from "vitest";

import type { CaseCard } from "@/lib/api/admin-cases";
import type { CareBoardCard } from "@/lib/api/care-board";

import {
  CARE_COLUMN_VISIBLE,
  buildColumns,
  careActionHref,
  careActionLabel,
  careBadge,
  careCardHref,
  careDueBadge,
  careHeaderText,
  careMoveOptions,
  carePanelKicker,
  carePanelSubtitle,
  careTileTitle,
  caseDueThisWeek,
  caseStubFromCardCase,
  consultantBriefRows,
  dataSummaryText,
  doneSummary,
  formatScheduledShort,
  initialSurname,
  isOrderEndDecision,
  listFilterCounts,
  listFilterFromParam,
  matchesListFilter,
  paginateGroups,
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

  it("rozmowa, opinia i popyt w „W toku” pytają o dzień i godzinę, decyzja — nie", () => {
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
      moveAction(careItem(careCard({ kind: "demand", key: "demand:1:2" })), "in_progress", options),
    ).toMatchObject({ ask: "schedule" });
  });

  it("„Czeka”: decyzja bez daty (czeka na front office), popyt bez daty (nie teraz — 30 dni)", () => {
    expect(
      moveAction(careItem(careCard({ kind: "decision", key: "decision:3" })), "waiting", options),
    ).toEqual({ type: "care-state", column: "waiting", ask: null });
    expect(
      moveAction(careItem(careCard({ kind: "demand", key: "demand:1:2" })), "waiting", options),
    ).toEqual({ type: "care-state", column: "waiting", ask: null });
    expect(
      moveAction(careItem(careCard({ kind: "feedback", key: "feedback:3" })), "waiting", options),
    ).toMatchObject({ ask: "retry" });
  });

  it("karta „Dane do uzupełnienia” nie przesuwa się", () => {
    const data = careItem(careCard({ kind: "data", key: "data:5" }));
    expect(moveAction(data, "in_progress", options).type).toBe("forbidden");
    expect(moveAction(data, "done", options).type).toBe("forbidden");
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
        careItem(careCard({ key: "demand:1:7", kind: "demand", due_on: null })),
      ],
      "2026-10-24",
    );
    expect(groups.map((group) => [group.label, group.items.map((item) => item.key)])).toEqual([
      ["Po terminie", ["case:1", "contact:plan:9"]],
      ["Do piątku", ["case:2"]],
      ["Decyzje", ["decision:5"]],
      ["Popyt do sprawdzenia", ["demand:1:7"]],
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
    expect(decisionIdOf("demand:1:7")).toBeNull();
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

describe("linia stanu karty opieki", () => {
  it("notatka z przeniesienia (`state_note`) dochodzi do „ponowna próba”, sama — gdy brak daty", async () => {
    const { careStateNote } = await import("../CareTile");
    const waiting = careCard({ column: "waiting", retry_on: "2026-10-24", state_note: "nie odbiera, SMS wysłany" });
    expect(careStateNote(waiting)).toBe("nie odbiera — spróbować 24.10 · nie odbiera, SMS wysłany");
    expect(careStateNote(careCard({ column: "in_progress", state_note: "czeka na grafik" }))).toBe("czeka na grafik");
    expect(careStateNote(careCard({ column: "new", state_note: "stara notatka" }))).toBeNull();
    expect(careStateNote(careCard({ column: "waiting", retry_on: "2026-10-24" }))).toBe(
      "nie odbiera — spróbować 24.10",
    );
    expect(careStateNote(careCard({ kind: "feedback", column: "waiting", retry_on: "2026-10-27" }))).toBe(
      "czeka na menedżera — do 27.10",
    );
    expect(careStateNote(careCard({ kind: "decision", column: "waiting" }))).toBe("czeka na front office");
    expect(careStateNote(careCard({ kind: "demand", column: "waiting", retry_on: "2026-11-21" }))).toBe(
      "nie teraz — wraca 21.11",
    );
    // Umówiona rozmowa stoi w plakietce terminu, nie w ramce.
    expect(careStateNote(careCard({ column: "in_progress", scheduled_at: "2026-10-24T12:00:00Z" }))).toBeNull();
  });
});

describe("wygląd karty opieki (makiety K1, K2)", () => {
  const TODAY = "2026-10-22";
  const FRIDAY = "2026-10-23";

  it("tytuł z rodzajem, bez podwójnego przedrostka", () => {
    expect(careTileTitle({ kind: "contact", title: "Karolina Przykładowa" })).toBe("Rozmowa: Karolina Przykładowa");
    expect(careTileTitle({ kind: "feedback", title: "Piotr Menedżerski" })).toBe("Opinia: Piotr Menedżerski");
    expect(careTileTitle({ kind: "contact", title: "Rozmowa: Anna P." })).toBe("Rozmowa: Anna P.");
    expect(careTileTitle({ kind: "demand", title: "Popyt do sprawdzenia: Java" })).toBe("Popyt do sprawdzenia: Java");
  });

  it("nagłówek: „rozmowa · dzień 30”, „rozmowa · umówiona”, „rozmowa · kamień”", () => {
    expect(careHeaderText(careCard({ reason_kind: "day_30" }))).toBe("rozmowa · dzień 30");
    expect(careHeaderText(careCard({ reason_kind: "pre_end" }))).toBe("rozmowa · kamień");
    expect(
      careHeaderText(careCard({ column: "in_progress", scheduled_at: "2026-10-24T12:00:00Z" })),
    ).toBe("rozmowa · umówiona");
    expect(careHeaderText(careCard({ kind: "feedback" }))).toBe("opinia menedżera");
    expect(careHeaderText(careCard({ kind: "decision", reason_kind: "wants_change" }))).toBe("decyzja · chce zmiany");
    // Starsza odpowiedź bez `reason_kind` — etykieta serwera małymi literami.
    expect(careHeaderText(careCard({ reason_kind: undefined, reason_label: "Dzień 7" }))).toBe("rozmowa · dzień 7");
  });

  it("plakietka: „3 dni po”, umówiona „24.10 · 14:00”, opinia „czeka od 19.10”", () => {
    expect(careBadge(careCard({ due_on: "2026-10-19", overdue_days: 3 }), TODAY, FRIDAY)).toEqual({
      text: "3 dni po",
      tone: "overdue",
    });
    expect(careBadge(careCard({ due_on: "2026-10-21", overdue_days: 1 }), TODAY, FRIDAY)?.text).toBe("1 dzień po");
    expect(
      careBadge(careCard({ column: "in_progress", scheduled_at: "2026-10-24T12:00:00Z" }), TODAY, FRIDAY),
    ).toEqual({ text: "24.10 · 14:00", tone: "week" });
    expect(
      careBadge(careCard({ kind: "feedback", due_on: "2026-10-19", overdue_days: 3 }), TODAY, FRIDAY)?.text,
    ).toBe("czeka od 19.10");
    expect(careBadge(careCard({ due_on: "2026-10-23", overdue_days: 0 }), TODAY, FRIDAY)?.text).toBe("jutro · 23.10");
    expect(careBadge(careCard({ kind: "data", due_on: null }), TODAY, FRIDAY)).toBeNull();
  });

  it("umówiony termin w czasie firmy", () => {
    expect(formatScheduledShort("2026-10-24T12:00:00Z")).toBe("24.10 · 14:00");
    expect(formatScheduledShort("nie-data")).toBeNull();
    expect(formatScheduledShort(null)).toBeNull();
  });

  it("panel: nagłówek z terminem i podtytuł z rolą, klientem i opiekunem", () => {
    const card = careCard({
      reason_kind: "day_30",
      overdue_days: 3,
      role_label: "QA",
      client_name: "Telekom Wzorcowy",
      owner_name: "Natalia Opiekuńcza",
    });
    expect(carePanelKicker(card)).toBe("Opieka · rozmowa · dzień 30 · 3 dni po terminie");
    expect(carePanelSubtitle(card)).toBe("QA · Telekom Wzorcowy · opiekun Natalia O.");
  });

  it("„Przenieś na tablicy”: trzy pola z podpowiedzią, bez „Zrobione”; dane — żadnego", () => {
    expect(careMoveOptions("contact").map((option) => `${option.label} — ${option.hint}`)).toEqual([
      "Nowa — do zrobienia",
      "W toku · Umówiona — podaj dzień i godzinę",
      "Czeka · Nie odbiera — spróbować ponownie dnia…",
    ]);
    expect(careMoveOptions("feedback")[2].label).toBe("Czeka na menedżera");
    expect(careMoveOptions("demand")[2].hint).toBe("wraca za 30 dni");
    expect(careMoveOptions("data")).toEqual([]);
  });

  it("„Konsultant w skrócie”: ocena i cytat, prośba o opinię, koniec zamówienia, rytm", () => {
    const rows = consultantBriefRows(
      careCard({
        note_excerpt: "Dobrze, chce więcej automatyzacji.",
        last_satisfaction: 5,
        manager: { contact_id: 1, name: "Katarzyna Kierownicza", feedback_due_on: "2026-10-16" },
      }),
      {
        cadence: { label: "co 2 tygodnie", until_on: "2026-12-15" },
        kpis: {
          last_contact: { on: "2026-09-26", days_ago: 26 },
          satisfaction: { value: 4, previous: null },
          order_end: { on: "2026-11-15", days: 24 },
        },
        known_project: null,
      },
    );
    expect(rows).toEqual([
      { label: "Ostatnia rozmowa", value: "26.09 · 5/5 · „Dobrze, chce więcej automatyzacji.”" },
      { label: "Menedżer u klienta", value: "Katarzyna Kierownicza · prośba o opinię czeka od 16.10" },
      { label: "Koniec zamówienia", value: "15.11 · za 24 dni" },
      { label: "Rytm", value: "co 2 tygodnie · do 15.12" },
    ]);
    const empty = consultantBriefRows(careCard({ note_excerpt: null, manager: null, last_satisfaction: null }), null);
    expect(empty.map((row) => row.value)).toEqual(["jeszcze nie było", "nie wskazano", "bez końca", "—"]);
  });

  it("dane do uzupełnienia słowami", () => {
    expect(dataSummaryText({ certain: 2, uncertain: 1, gaps: 3, consultants: 6 })).toBe(
      "2 pewne propozycje menedżera + 1 do sprawdzenia · 3 luki w mapie technologii",
    );
    expect(dataSummaryText({ certain: 0, uncertain: 2, gaps: null, consultants: 2 })).toBe(
      "2 propozycje menedżera do sprawdzenia",
    );
    expect(dataSummaryText({ certain: 0, uncertain: 0, gaps: 5, consultants: 1 })).toBe("5 luk w mapie technologii");
  });

  it("akcja: dane i popyt bez menedżera prowadzą do „Ludzie i technologie”", () => {
    const data = careCard({ kind: "data", key: "data:30", client_id: 30, contract_id: null });
    expect(careActionLabel(data)).toBe("Przejrzyj");
    expect(careActionHref(data)).toBe("/clients/30?tab=ludzie");
    const blind = careCard({
      kind: "demand",
      key: "demand:30:4",
      client_id: 30,
      contract_id: null,
      demand: { roles: [".NET"], source: null, area: null, conversation_id: 4, manager: null, open_job: null },
    });
    expect(careActionLabel(blind)).toBe("Uzupełnij menedżera");
    expect(careActionHref(blind)).toBe("/clients/30?tab=ludzie&view=drzewo");
    const known = careCard({
      kind: "demand",
      key: "demand:30:5",
      demand: {
        roles: ["Java"],
        source: null,
        area: null,
        conversation_id: 5,
        manager: { contact_id: 7, name: "M. Rogalski" },
        open_job: null,
      },
    });
    expect(careActionLabel(known)).toBe("Porozmawiaj z menedżerem");
  });

  it("menedżer w wierszu: „K. Kierownicza”", () => {
    expect(initialSurname("Katarzyna Kierownicza")).toBe("K. Kierownicza");
    expect(initialSurname("Jan")).toBe("Jan");
    expect(initialSurname(null)).toBe("");
  });

  it("decyzja z końca zamówienia bez wpisu ma własny klucz", () => {
    expect(isOrderEndDecision("decision:end:12")).toBe(true);
    expect(isOrderEndDecision("decision:12")).toBe(false);
    expect(decisionIdOf("decision:end:12")).toBeNull();
  });
});

describe("„Zrobione”, sprawy w opiece, kolejka", () => {
  it("jedna liczba i „41 spraw w miesiącu · 5 rozmów i opinii w tym tygodniu”", () => {
    expect(doneSummary({ casesMonth: 41, careWeek: 5 })).toEqual({
      total: 46,
      text: "41 spraw w miesiącu · 5 rozmów i opinii w tym tygodniu",
    });
    expect(doneSummary({ casesMonth: null, careWeek: 2 }).text).toBe("2 rozmowy i opinie w tym tygodniu");
    expect(doneSummary({ casesMonth: 1, careWeek: null })).toEqual({ total: 1, text: "1 sprawa w miesiącu" });
  });

  it("sprawa w „Do zrobienia” tylko do piątku albo po terminie (S3)", () => {
    const friday = "2026-10-23";
    expect(caseDueThisWeek(caseCard({ due_on: "2026-10-23" }), friday)).toBe(true);
    expect(caseDueThisWeek(caseCard({ due_on: "2026-10-10", overdue: true }), friday)).toBe(true);
    expect(caseDueThisWeek(caseCard({ due_on: "2026-10-27" }), friday)).toBe(false);
    expect(caseDueThisWeek(caseCard({ due_on: null }), friday)).toBe(false);
    // Zrobione zostają w wąskiej kolumnie.
    expect(caseDueThisWeek(caseCard({ status: "done" }), friday)).toBe(true);
  });

  it("sprawa z karty konsultanta otwiera panel od razu (skrót → `CaseCard`)", () => {
    const stub = caseStubFromCardCase(
      {
        id: 931,
        title: "Negocjacje stawki",
        area: "negotiation",
        area_label: "Negocjacje",
        status: "in_progress",
        status_label: "W toku",
        due_on: "2026-10-20",
        follow_up_on: null,
        assignee_name: "Natalia Opiekuńcza",
        source: "manual",
        content_hidden: true,
      },
      "2026-10-22",
    );
    expect(stub).toMatchObject({ id: 931, status: "in_progress", area: "negotiation", overdue: true });
    expect(stub.assignee?.name).toBe("Natalia Opiekuńcza");
  });

  it("`?filter=` z dzwonka → filtr; nieznany → wszystko", () => {
    expect(listFilterFromParam("po-terminie")).toBe("overdue");
    expect(listFilterFromParam("do-piatku")).toBe("week");
    expect(listFilterFromParam("rozmowy")).toBe("contact");
    expect(listFilterFromParam("opinie")).toBe("feedback");
    expect(listFilterFromParam("decyzje")).toBe("decision");
    expect(listFilterFromParam("dane")).toBe("data");
    expect(listFilterFromParam("popyt")).toBe("demand");
    expect(listFilterFromParam("cokolwiek")).toBe("all");
    expect(listFilterFromParam(null)).toBe("all");
  });

  it("liczniki chipów listy liczą te same karty co lista (bez zrobionych)", () => {
    const items = [
      careItem(careCard({ key: "contact:plan:1", overdue_days: 2, due_on: "2026-10-20" })),
      careItem(careCard({ key: "contact:plan:2", overdue_days: 0, due_on: "2026-10-23" })),
      careItem(careCard({ key: "feedback:3", kind: "feedback", overdue_days: 0, due_on: "2026-10-30" })),
      careItem(careCard({ key: "decision:4", kind: "decision", due_on: null, overdue_days: 0 })),
      careItem(careCard({ key: "data:5", kind: "data", due_on: null, overdue_days: 0 })),
      caseItem(caseCard({ id: 6, due_on: "2026-10-19", overdue: true })),
      caseItem(caseCard({ id: 7, status: "done" })),
    ];
    expect(listFilterCounts(items, "2026-10-23")).toEqual({
      all: 6,
      overdue: 2,
      week: 3,
      contact: 2,
      feedback: 1,
      decision: 1,
      data: 1,
      demand: 0,
    });
    expect(matchesListFilter(items[5], "overdue", "2026-10-23")).toBe(true);
    expect(matchesListFilter(items[5], "contact", "2026-10-23")).toBe(false);
  });

  it("stronicowanie kolejki: pierwsze N wierszy w kolejności grup", () => {
    const make = (count: number, prefix: string) =>
      Array.from({ length: count }, (_, index) => careItem(careCard({ key: `${prefix}:${index}` })));
    const groups = [
      { key: "overdue", items: make(30, "a") },
      { key: "week", items: make(30, "b") },
      { key: "later", items: make(5, "c") },
    ];
    const page = paginateGroups(groups, 50);
    expect(page.groups.map((group) => [group.key, group.items.length])).toEqual([
      ["overdue", 30],
      ["week", 20],
    ]);
    expect(page.hidden).toBe(15);
    expect(paginateGroups(groups, 100).hidden).toBe(0);
  });
});
