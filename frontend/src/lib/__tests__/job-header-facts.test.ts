import { describe, expect, it } from "vitest";

import { jobHeaderFacts, jobWorkModeFact } from "@/lib/job-header-facts";

describe("jobHeaderFacts — klient, budżet, tryb pracy", () => {
  it("komplet: klient, budżet z efektywnej kwoty, tryb z dniami i miastem", () => {
    expect(
      jobHeaderFacts({
        client_name: "Bank Przykładowy S.A.",
        effective_budget_hourly: 93,
        remote_policy: "hybrid",
        onsite_days_per_week: 2,
        location: "Warszawa",
      }),
    ).toEqual([
      { key: "client", label: "Klient", value: "Bank Przykładowy S.A." },
      { key: "budget", label: "Budżet", value: "do 93,00 PLN/h" },
      { key: "work_mode", label: "Tryb pracy", value: "Hybrydowo · 2 dni w tygodniu · Warszawa" },
    ]);
  });

  it("brak danych to `null` (nagłówek mówi „nie podano”), nigdy pusty napis", () => {
    expect(jobHeaderFacts({}).map((f) => f.value)).toEqual([null, null, null]);
    expect(jobHeaderFacts({ client_name: "  " })[0].value).toBeNull();
  });

  it("kwota ukryta dla roli: budżet istnieje, ale go nie pokazujemy", () => {
    const budget = jobHeaderFacts({ has_budget_hourly: true, effective_budget_hourly: null })[1];
    expect(budget.value).toBe("ukryty dla Twojej roli");
  });

  it("budżet z jawnego pola, gdy serwer nie podał efektywnego", () => {
    expect(jobHeaderFacts({ rate_budget_hourly: "120.5" })[1].value).toBe("do 120,50 PLN/h");
    expect(
      jobHeaderFacts({ rate_budget_hourly: 80, rate_budget_hourly_min: 60 })[1].value,
    ).toBe("60,00–80,00 PLN/h");
  });
});

describe("jobWorkModeFact", () => {
  it("zdalnie nie dopisuje miasta ani dni", () => {
    expect(jobWorkModeFact({ remote_policy: "remote", location: "Gdańsk", onsite_days_per_week: 0 })).toBe(
      "Zdalnie",
    );
  });

  it("hybryda z wpisem miesięcznym — miesiąc wygrywa z tygodniem", () => {
    expect(
      jobWorkModeFact({
        remote_policy: "hybrid",
        onsite_days_per_week: 1,
        onsite_days_per_month: 2,
        location: "Kraków, Łódź",
      }),
    ).toBe("Hybrydowo · 2 dni w miesiącu · Kraków, Łódź");
  });

  it("stacjonarnie: samo miasto, bez dni", () => {
    expect(jobWorkModeFact({ remote_policy: "onsite", onsite_days_per_week: 5, location: "Poznań" })).toBe(
      "Stacjonarnie · Poznań",
    );
  });

  it("nieznany tryb = brak faktu", () => {
    expect(jobWorkModeFact({ remote_policy: null })).toBeNull();
    expect(jobWorkModeFact({ remote_policy: "cokolwiek" })).toBeNull();
  });
});
