import { describe, expect, it } from "vitest";

import {
  addMonths,
  agreementState,
  agreementStateLabel,
  endingSummary,
  groupByMonth,
  lastWorkingDay,
  monthYearLabel,
  orderConflict,
  sortByLastDay,
  timelineScale,
  type EndingRowFacts,
} from "@/lib/contract-ending";

const row = (over: Partial<EndingRowFacts> & { id: number }): EndingRowFacts => ({
  status: "ending",
  contract_type: "b2b",
  end_date: "2026-11-30",
  terminated_at: "2026-11-30",
  agreement_termination_mode: null,
  client_order_start_date: "2026-01-01",
  client_order_end_date: "2026-11-30",
  margin: 40,
  rate_unit: "hourly",
  billing_hours_per_month: 168,
  currency: "PLN",
  candidate_id: over.id + 100,
  ...over,
});

describe("stan umowy z wypowiedzeniem w Dokumentach (22.11.2026)", () => {
  const doc = {
  id: 5,
  doc_type: "termination_notice" as const,
  filename: "Wypowiedzenie.pdf",
  source: "sharepoint_import",
  created_at: "2026-09-29T10:00:00Z",
};

  it("niezapisane rozwiązanie z plikiem nie jest „nierozwiązana”", () => {
    expect(agreementStateLabel(row({ id: 1, termination_document: doc }))).toBe(
      "wypowiedzenie w Dokumentach, niezapisane",
    );
    expect(agreementStateLabel(row({ id: 2 }))).toBe("nierozwiązana");
  });

  it("zapisane rozwiązanie wygrywa z plikiem", () => {
    expect(
      agreementStateLabel(row({ id: 3, agreement_termination_mode: "notice", termination_document: doc })),
    ).toBe("wypowiedziana");
  });
});

describe("odejścia do domknięcia", () => {
  it("ostatni dzień: koniec umowy, bez niego koniec zamówienia", () => {
    expect(lastWorkingDay(row({ id: 1 }))).toBe("2026-11-30");
    expect(lastWorkingDay(row({ id: 2, end_date: null, terminated_at: null, client_order_end_date: "2026-12-15" }))).toBe(
      "2026-12-15",
    );
    expect(
      lastWorkingDay(row({ id: 3, end_date: null, terminated_at: null, client_order_end_date: null, latest_order_end_date: null })),
    ).toBeNull();
  });

  it("stan umowy B2B: nierozwiązana, wypowiedziana, porozumienie; inna umowa — nie dotyczy", () => {
    expect(agreementState(row({ id: 1 }))).toBe("open");
    expect(agreementState(row({ id: 1, agreement_termination_mode: "notice" }))).toBe("notice");
    expect(agreementState(row({ id: 1, agreement_termination_mode: "mutual_agreement" }))).toBe("mutual_agreement");
    expect(agreementState(row({ id: 1, contract_type: "uzlecenie" }))).toBe("not_applicable");
  });

  it("niespójność: zamówienie trwa po odejściu albo nie ma daty końca", () => {
    expect(orderConflict(row({ id: 1 }))).toBeNull();
    expect(orderConflict(row({ id: 2, client_order_start_date: "2026-12-01", client_order_end_date: "2027-05-31" }))).toBe(
      "Zamówienie 01.12.2026 – 31.05.2027 trwa po odejściu — sprawdź zakończenie",
    );
    expect(orderConflict(row({ id: 3, client_order_start_date: "2026-02-16", client_order_end_date: null }))).toBe(
      "Zamówienie od 16.02.2026 bez daty końca trwa po odejściu — sprawdź zakończenie",
    );
    expect(orderConflict(row({ id: 4, client_order_start_date: null, client_order_end_date: null }))).toBeNull();
  });

  it("kolejność od najbliższego odejścia, bez daty na końcu", () => {
    const sorted = sortByLastDay([
      row({ id: 1, end_date: "2026-12-31", terminated_at: "2026-12-31" }),
      row({ id: 2, end_date: null, terminated_at: null, client_order_end_date: null }),
      row({ id: 3 }),
    ]);
    expect(sorted.map((r) => r.id)).toEqual([3, 1, 2]);
  });

  it("podsumowanie: osoby, najpóźniejsze odejście, marża w złotych i nierozwiązane umowy B2B", () => {
    const summary = endingSummary([
      row({ id: 1 }),
      row({ id: 2, end_date: "2026-12-31", terminated_at: "2026-12-31", agreement_termination_mode: "notice" }),
      row({ id: 3, candidate_id: 101, contract_type: "uzlecenie", margin: null }),
    ]);
    expect(summary).toEqual({
      contracts: 3,
      people: 2,
      latest: "2026-12-31",
      margin: { total: 2 * 6720, unpriced: 1 },
      b2b: 2,
      openAgreements: 1,
    });
  });
});

describe("oś czasu odejść", () => {
  it("od początku bieżącego miesiąca, co najmniej dwa miesiące", () => {
    const scale = timelineScale("2026-11-20", ["2026-11-30"]);
    expect(scale.from).toBe("2026-11-01");
    expect(scale.to).toBe("2027-01-01");
    expect(scale.months).toEqual(["2026-11-01", "2026-12-01"]);
    expect(scale.pos("2026-11-01")).toBe(0);
    expect(scale.pos("2027-03-01")).toBe(100);
    expect(scale.pos("2026-12-01")).toBeCloseTo((30 / 61) * 100, 5);
  });

  it("kończy się po miesiącu najpóźniejszego odejścia", () => {
    const scale = timelineScale("2026-11-20", ["2026-11-30", "2027-02-28", null]);
    expect(scale.months).toEqual(["2026-11-01", "2026-12-01", "2027-01-01", "2027-02-01"]);
  });

  it("miesiące: przejście przez koniec roku i nazwa po polsku", () => {
    expect(addMonths("2026-12-31", 1)).toBe("2027-01-01");
    expect(monthYearLabel("2026-11-30")).toBe("Listopad 2026");
  });

  it("grupy po miesiącu ostatniego dnia", () => {
    const groups = groupByMonth(
      sortByLastDay([row({ id: 1 }), row({ id: 2, end_date: "2026-12-31", terminated_at: "2026-12-31" }), row({ id: 3 })]),
    );
    expect(groups.map((g) => [g.month, g.rows.map((r) => r.id)])).toEqual([
      ["2026-11", [1, 3]],
      ["2026-12", [2]],
    ]);
  });
});
