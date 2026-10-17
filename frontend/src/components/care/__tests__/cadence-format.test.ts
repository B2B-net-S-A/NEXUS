/**
 * Rytm kontaktu (etap 3, M1–M3): podpis rytmu, sygnały, filtry „Konsultantów”,
 * podpowiedź „Przydziału” i odmiana liczebników.
 */
import { describe, expect, it } from "vitest";

import {
  assignmentHint,
  assignmentRows,
  cadenceSubline,
  consultantsIn,
  contractForm,
  filterCounts,
  loadWidth,
  monthTalks,
  peopleText,
  rowSignals,
  signalText,
  sinceText,
  talksText,
} from "@/components/care/cadence-format";
import type { AssignmentRow, CadenceCurrent, ConsultantRow } from "@/lib/api/care";

function current(overrides: Partial<CadenceCurrent> = {}): CadenceCurrent {
  return {
    level: "monthly",
    source: "default",
    starts_on: null,
    until_on: null,
    returns_to: null,
    reason: null,
    note: null,
    author: null,
    ...overrides,
  };
}

function consultant(overrides: Partial<ConsultantRow> = {}): ConsultantRow {
  return {
    contract_id: 1,
    candidate_id: 1,
    candidate_name: "Anna Przykładowa",
    client_id: 1,
    client_name: "Bank Przykładowy",
    job_title: null,
    contract_type: "b2b",
    start_date: "2026-01-01",
    end_date: null,
    owner: null,
    is_mine: true,
    manager: null,
    cadence: current(),
    next_contact: null,
    last_conversation: null,
    signals: [],
    suggested_level: null,
    conversations: { this_month: 1, next_month: 1 },
    can_change_cadence: true,
    ...overrides,
  };
}

function assignment(overrides: Partial<AssignmentRow> = {}): AssignmentRow {
  return {
    contract_id: 1,
    candidate_id: 1,
    candidate_name: "Anna Przykładowa",
    job_title: null,
    contract_type: "b2b",
    client_id: 1,
    client_name: "Bank Przykładowy",
    start_date: null,
    end_date: null,
    owner: null,
    owner_source: null,
    explicit_owner_id: null,
    client_default_owner: null,
    hint: "no_default",
    ending_soon: false,
    cadence_level: "monthly",
    conversations_next_month: 1,
    ...overrides,
  };
}

describe("podpis rytmu", () => {
  it("program, domyślny, zmiana z datą i powodem albo notatką", () => {
    expect(cadenceSubline(current({ level: "biweekly", source: "program" }))).toBe("pierwsze 90 dni");
    expect(cadenceSubline(current())).toBeNull();
    expect(
      cadenceSubline(
        current({ level: "biweekly", source: "period", until_on: "2026-11-30", reason: "wants_change" }),
      ),
    ).toBe("do 30.11 · chce zmiany projektu");
    expect(
      cadenceSubline(
        current({ level: "quarterly", source: "period", reason: "stable", note: "Stabilnie, 4 lata u klienta." }),
      ),
    ).toBe("Stabilnie, 4 lata u klienta.");
  });
});

describe("sygnały", () => {
  it("opisuje sygnał słowami z makiety", () => {
    expect(signalText({ kind: "weak_feedback", average: 2.7, on: "2026-10-15" })).toBe("opinia 2,7 / 5");
    expect(signalText({ kind: "order_end", days: 34, on: "2026-11-20" })).toBe("koniec zamówienia za 34 dni");
    expect(signalText({ kind: "order_end", days: 1, on: "2026-10-18" })).toBe("koniec zamówienia za 1 dzień");
    expect(signalText({ kind: "wants_change" })).toBe("chce zmiany projektu");
    expect(signalText({ kind: "overdue", days: 3 })).toBe("zaległa 3 dni");
  });

  it("„Koniec projektu” z „Do przepięcia” stoi w kolumnie sygnałów (jak w dawnej liście)", () => {
    expect(signalText({ kind: "project_end", on: "2026-11-26" })).toBe("koniec projektu 26.11");
    expect(signalText({ kind: "project_end", on: null })).toBe("koniec projektu");
    const row = consultant({ signals: [{ kind: "project_end", on: "2026-11-26" }] });
    expect(rowSignals(row)).toEqual([{ kind: "project_end", on: "2026-11-26" }]);
  });

  it("zaległość stoi przy następnej rozmowie, nie w kolumnie sygnałów", () => {
    const row = consultant({ signals: [{ kind: "overdue", days: 3 }, { kind: "wants_change" }] });
    expect(rowSignals(row)).toEqual([{ kind: "wants_change" }]);
  });
});

describe("lista „Konsultanci”", () => {
  const rows = [
    consultant({ contract_id: 1, cadence: current({ level: "biweekly", source: "program" }) }),
    consultant({ contract_id: 2, cadence: current({ level: "paused", source: "period" }), is_mine: false }),
    consultant({ contract_id: 3, signals: [{ kind: "wants_change" }], conversations: { this_month: 2, next_month: 0 } }),
  ];

  it("liczy filtry w zakresie i sumuje rozmowy z rytmów", () => {
    expect(consultantsIn(rows, "mine").map((row) => row.contract_id)).toEqual([1, 3]);
    expect(filterCounts(rows)).toEqual({ all: 3, biweekly: 1, paused: 1, signals: 1 });
    expect(filterCounts(consultantsIn(rows, "mine"))).toEqual({ all: 2, biweekly: 1, paused: 0, signals: 1 });
    expect(monthTalks(rows)).toBe(4);
  });

  it("forma słowem z kartoteki i „od” w tym roku albo rok", () => {
    expect(contractForm("uzlecenie")).toBe("Zlecenie");
    expect(contractForm("b2b")).toBe("B2B");
    expect(contractForm(null)).toBeNull();
    expect(sinceText("2026-09-01", "2026-10-17")).toBe("od 01.09");
    expect(sinceText("2024-03-01", "2026-10-17")).toBe("od 2024");
  });
});

describe("„Przydział”", () => {
  it("filtruje bez opiekuna, opiekuna i kończących zamówienie", () => {
    const rows = [
      assignment({ contract_id: 1 }),
      assignment({ contract_id: 2, owner: { id: 7, name: "Natalia Opiekuńcza" }, hint: "contract" }),
      assignment({ contract_id: 3, owner: { id: 8, name: "Kamil Testowy" }, ending_soon: true, hint: "delivery_lead" }),
    ];
    expect(assignmentRows(rows, { kind: "none" }).map((r) => r.contract_id)).toEqual([1]);
    expect(assignmentRows(rows, { kind: "owner", id: 7 }).map((r) => r.contract_id)).toEqual([2]);
    expect(assignmentRows(rows, { kind: "ending" }).map((r) => r.contract_id)).toEqual([3]);
  });

  it("podpowiedź mówi, skąd opiekun albo czego brakuje", () => {
    expect(assignmentHint(assignment())).toBe("klient bez domyślnego opiekuna · ustaw go");
    expect(
      assignmentHint(
        assignment({ hint: "client", client_default_owner: { id: 7, name: "Natalia Opiekuńcza" } }),
      ),
    ).toBe("domyślny opiekun klienta: Natalia Opiekuńcza");
    expect(assignmentHint(assignment({ hint: "default_inactive" }))).toBe(
      "domyślny opiekun klienta ma nieaktywne konto",
    );
  });

  it("pasek obciążenia nie wychodzi poza 100%", () => {
    expect(loadWidth(47, 61)).toBe(77);
    expect(loadWidth(80, 61)).toBe(100);
    expect(loadWidth(5, 0)).toBe(0);
  });
});

describe("liczebniki", () => {
  it("odmienia osoby i rozmowy", () => {
    expect([1, 2, 5, 12, 22, 38].map(peopleText)).toEqual([
      "1 osoba",
      "2 osoby",
      "5 osób",
      "12 osób",
      "22 osoby",
      "38 osób",
    ]);
    expect([1, 3, 14, 33, 47].map(talksText)).toEqual([
      "1 rozmowa",
      "3 rozmowy",
      "14 rozmów",
      "33 rozmowy",
      "47 rozmów",
    ]);
  });
});
