import { describe, expect, it } from "vitest";

import {
  formatPlnWhole,
  groupRowsByClient,
  isLeaving,
  listNextSteps,
  monthlyMargin,
  peopleLabel,
  sumMonthlyMarginPln,
  type ClientGroupRow,
  type ListRowFacts,
} from "@/lib/contract-list-next";

const TODAY = "2026-11-20";

const base: ListRowFacts = {
  status: "active",
  contract_type: "b2b",
  start_date: "2025-01-01",
  end_date: null,
  terminated_at: null,
  termination_reason: null,
  agreement_termination_mode: null,
  client_order_start_date: "2026-01-01",
  client_order_end_date: "2027-06-30",
  prolongation_status: "unknown",
  rate_client: 160,
  margin: 40,
  rate_unit: "hourly",
  billing_hours_per_month: 168,
  currency: "PLN",
};

const rates = { canSeeRates: true };

describe("„Co dalej” w wierszu listy", () => {
  it("spokojny kontrakt nie ma nic do zrobienia", () => {
    expect(listNextSteps(base, TODAY, rates)).toEqual([]);
  });

  it("zamówienie w 60 dni: to samo zdanie co pas strony, z decyzją o przedłużeniu", () => {
    const steps = listNextSteps({ ...base, client_order_end_date: "2026-12-31" }, TODAY, rates);
    expect(steps).toHaveLength(1);
    expect(steps[0]).toMatchObject({
      id: "order_end",
      tone: "warning",
      text: "Zamówienie kończy się 31.12.2026 — za 41 dni",
      detail: "Brak decyzji o przedłużeniu.",
    });
  });

  it("zamówienie do 14 dni jest czerwone, a dalej niż 60 dni — milczy", () => {
    expect(listNextSteps({ ...base, client_order_end_date: "2026-11-30" }, TODAY, rates)[0].tone).toBe("danger");
    expect(listNextSteps({ ...base, client_order_end_date: "2027-01-20" }, TODAY, rates)).toEqual([]);
  });

  it("zaplanowane odejście: zdanie z datą, a pod nim powód i nierozwiązana umowa B2B", () => {
    const steps = listNextSteps(
      {
        ...base,
        status: "ending",
        end_date: "2026-11-30",
        terminated_at: "2026-11-30",
        termination_reason: "project_ended",
        client_order_end_date: "2026-11-30",
      },
      TODAY,
      rates,
    );
    expect(steps).toHaveLength(1);
    expect(steps[0]).toMatchObject({
      id: "end",
      tone: "danger",
      text: "Współpraca kończy się 30.11.2026 — za 10 dni",
      detail: "Koniec projektu · umowa B2B nierozwiązana",
    });
    expect(steps[0].hint).toContain("Umowa B2B nie jest rozwiązana");
  });

  it("wypowiedziana umowa nie dostaje dopisku o nierozwiązanej", () => {
    const [step] = listNextSteps(
      { ...base, status: "ending", end_date: "2026-12-31", terminated_at: "2026-12-31", agreement_termination_mode: "notice" },
      TODAY,
      rates,
    );
    expect(step.tone).toBe("warning");
    expect(step.detail).toBeNull();
  });

  it("zakończona współpraca z nierozwiązaną umową nie powtarza stanu umowy w dopisku", () => {
    const [step] = listNextSteps(
      { ...base, status: "ended", end_date: "2026-10-31", terminated_at: "2026-10-31", termination_reason: "better_offer" },
      TODAY,
      rates,
    );
    expect(step.text).toBe("Współpraca zakończona 31.10.2026 — umowa B2B nie jest rozwiązana");
    expect(step.detail).toBe("Dostał lepszą ofertę");
  });

  it("brak stawki klienta tylko z wglądem w kwoty", () => {
    const row = { ...base, rate_client: null };
    expect(listNextSteps(row, TODAY, rates).map((s) => s.text)).toEqual(["Brak stawki klienta"]);
    expect(listNextSteps(row, TODAY, { canSeeRates: false })).toEqual([]);
  });

  it("brak aktywnego zamówienia: bez okresu albo po końcu ostatniego", () => {
    const none = listNextSteps({ ...base, client_order_start_date: null, client_order_end_date: null }, TODAY, rates);
    expect(none[0]).toMatchObject({ id: "no_order", tone: "danger", detail: null });
    const past = listNextSteps({ ...base, client_order_end_date: "2026-10-31" }, TODAY, rates);
    expect(past[0].detail).toBe("Ostatnie skończyło się 31.10.2026.");
  });

  it("szkic i zakończony kontrakt nie dostają ostrzeżenia o zamówieniu", () => {
    const noOrder = { client_order_start_date: null, client_order_end_date: null };
    expect(listNextSteps({ ...base, ...noOrder, status: "draft" }, TODAY, rates)).toEqual([]);
    expect(
      listNextSteps({ ...base, ...noOrder, status: "ended", agreement_termination_mode: "notice" }, TODAY, rates),
    ).toEqual([]);
  });

  it("start w przyszłości stoi po sprawie pilnej, przed brakiem stawki", () => {
    const steps = listNextSteps(
      { ...base, start_date: "2026-11-23", client_order_end_date: "2026-12-31", rate_client: null },
      TODAY,
      rates,
    );
    expect(steps.map((s) => s.id)).toEqual(["order_end", "start", "rate"]);
    expect(steps[1].text).toBe("Startuje 23.11.2026 — za 3 dni");
  });
});

describe("marża miesięczna wiersza", () => {
  it("godzinowa × godziny rozliczeniowe, dzienna × 21 MD, miesięczna bez zmian", () => {
    expect(monthlyMargin(base)).toBe(40 * 168);
    expect(monthlyMargin({ ...base, billing_hours_per_month: 160 })).toBe(6400);
    expect(monthlyMargin({ ...base, billing_hours_per_month: null })).toBe(40 * 168);
    expect(monthlyMargin({ ...base, rate_unit: "daily", margin: 300 })).toBe(6300);
    expect(monthlyMargin({ ...base, rate_unit: "monthly", margin: 5000 })).toBe(5000);
  });

  it("różne waluty stron albo brak marży = brak kwoty", () => {
    expect(monthlyMargin({ ...base, rate_client_currency: "EUR", rate_candidate_currency: "PLN" })).toBeNull();
    expect(monthlyMargin({ ...base, margin: null })).toBeNull();
  });

  it("suma w złotych pomija umowy bez stawki i w euro, ale je liczy", () => {
    const sum = sumMonthlyMarginPln([
      base,
      { ...base, margin: null },
      { ...base, rate_client_currency: "EUR", rate_candidate_currency: "EUR" },
    ]);
    expect(sum).toEqual({ total: 6720, unpriced: 2 });
    // Polska typografia: separator tysięcy dopiero od pięciu cyfr.
    expect(formatPlnWhole(sum.total)).toBe("6720 zł");
    expect(formatPlnWhole(13440.4)).toBe(`13${" "}440 zł`);
  });
});

describe("„Grupuj: klient”", () => {
  const row = (over: Partial<ClientGroupRow> & { id: number }): ClientGroupRow => ({
    ...base,
    client_id: 1,
    client_name: "Bank Alfa",
    candidate_id: over.id + 100,
    ...over,
  });

  it("grupy od największej, liczba osób po kandydacie, odchodzi i startuje", () => {
    const groups = groupRowsByClient(
      [
        row({ id: 1, client_id: 2, client_name: "Bank Beta" }),
        row({ id: 2 }),
        row({ id: 3, candidate_id: 102 }),
        row({ id: 4, status: "ending", end_date: "2026-12-31", terminated_at: "2026-12-31" }),
        row({ id: 5, start_date: "2026-12-01" }),
      ],
      TODAY,
    );
    expect(groups.map((g) => [g.name, g.rows.length, g.people])).toEqual([
      ["Bank Alfa", 4, 3],
      ["Bank Beta", 1, 1],
    ]);
    expect(groups[0].leaving).toBe(1);
    expect(groups[0].starting).toBe(1);
    expect(groups[0].margin).toEqual({ total: 4 * 6720, unpriced: 0 });
  });

  it("wiersz bez klienta trafia do własnej grupy, remis rozstrzyga nazwa", () => {
    const groups = groupRowsByClient(
      [row({ id: 1, client_id: null, client_name: null }), row({ id: 2, client_id: 3, client_name: "Agencja" })],
      TODAY,
    );
    expect(groups.map((g) => g.name)).toEqual(["Agencja", "Bez klienta"]);
  });

  it("odchodzi: status „Kończący się” albo zakończenie z datą od dziś", () => {
    expect(isLeaving({ ...base, status: "ending" }, TODAY)).toBe(true);
    expect(isLeaving({ ...base, terminated_at: "2026-11-30", end_date: "2026-11-30" }, TODAY)).toBe(true);
    expect(isLeaving({ ...base, terminated_at: "2026-11-01", end_date: "2026-11-01" }, TODAY)).toBe(false);
    expect(isLeaving({ ...base, status: "ended", terminated_at: "2026-12-01", end_date: "2026-12-01" }, TODAY)).toBe(false);
  });

  it("polska liczba mnoga osób", () => {
    expect([1, 2, 5, 12, 22].map(peopleLabel)).toEqual(["1 osoba", "2 osoby", "5 osób", "12 osób", "22 osoby"]);
  });
});
