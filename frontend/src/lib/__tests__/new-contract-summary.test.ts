import { describe, expect, it } from "vitest";

import type { RecruitmentRate } from "@/lib/api/recruitmentRates";
import { formatPctPl, formatWholeMoney, formatWholeNumber } from "@/lib/money";
import {
  advancedSummary,
  candidateRateOnStart,
  contractMoney,
  createButtonLabel,
  createOutcome,
  laterFields,
  rateToInput,
  recruitmentRateHint,
  type AdvancedSummaryInput,
} from "@/lib/new-contract-summary";

const NBSP = " ";

describe("formatWholeNumber / formatWholeMoney", () => {
  it("grupuje także cztery cyfry spacją twardą i pisze minus „−”", () => {
    expect(formatWholeNumber(6384)).toBe(`6${NBSP}384`);
    expect(formatWholeNumber(-75432.4)).toBe(`−75${NBSP}432`);
    expect(formatWholeNumber(47321, true)).toBe(`+47${NBSP}321`);
    expect(formatWholeMoney(26376, "PLN")).toBe(`26${NBSP}376${NBSP}zł`);
    expect(formatWholeMoney(1200, "EUR")).toBe(`1${NBSP}200${NBSP}EUR`);
  });

  it("zero nie dostaje znaku, a brak kwoty to „—”, nigdy „0 zł”", () => {
    expect(formatWholeNumber(0, true)).toBe("0");
    expect(formatWholeNumber(-0.3)).toBe("0");
    expect(formatWholeMoney(null)).toBe("—");
    expect(formatWholeMoney("nie-liczba")).toBe("—");
  });
});

describe("status przy utworzeniu", () => {
  it("przycisk mówi, co powstanie", () => {
    expect(createButtonLabel("draft")).toBe("Utwórz szkic");
    expect(createButtonLabel("active")).toBe("Utwórz jako aktywny");
    expect(createButtonLabel("ending")).toBe("Utwórz jako kończący się");
    expect(createButtonLabel("ended")).toBe("Utwórz jako zakończony");
  });

  it("nieznany status traktuje jak szkic", () => {
    expect(createButtonLabel("cokolwiek")).toBe("Utwórz szkic");
    expect(createOutcome("cokolwiek").status).toBe("szkic");
  });

  it("zdanie „Po utworzeniu” mówi o aktywacji po podpisie przy szkicu", () => {
    expect(createOutcome("draft")).toEqual({
      status: "szkic",
      detail: "aktywujesz go po podpisaniu umowy.",
    });
    expect(createOutcome("active").detail).toMatch(/stawki klienta i konsultanta/);
  });

  it("pola do uzupełnienia później: tylko puste", () => {
    expect(laterFields({ lineManager: " ", workMode: "" })).toEqual(["line manager", "tryb pracy"]);
    expect(laterFields({ lineManager: "Anna Przykładowa", workMode: "remote" })).toEqual([]);
  });
});

describe("candidateRateOnStart — jak resolver backendu", () => {
  it("pierwszy etap bez daty obowiązuje od startu", () => {
    expect(candidateRateOnStart([{ rate: "110,00", effectiveFrom: "" }], "2026-12-01")).toBe(110);
  });

  it("bierze ostatni etap sprzed startu, nie zaplanowaną podwyżkę", () => {
    const rows = [
      { rate: "110", effectiveFrom: "" },
      { rate: "125", effectiveFrom: "2027-01-01" },
    ];
    expect(candidateRateOnStart(rows, "2026-12-01")).toBe(110);
  });

  it("gdy wszystkie etapy są po starcie — najwcześniejszy", () => {
    const rows = [
      { rate: "130", effectiveFrom: "2027-03-01" },
      { rate: "120", effectiveFrom: "2027-01-01" },
    ];
    expect(candidateRateOnStart(rows, "2026-12-01")).toBe(120);
  });

  it("przy tej samej dacie wygrywa etap dopisany później", () => {
    const rows = [
      { rate: "100", effectiveFrom: "2026-12-01" },
      { rate: "105", effectiveFrom: "2026-12-01" },
    ];
    expect(candidateRateOnStart(rows, "2026-12-01")).toBe(105);
  });

  it("puste stawki to brak stawki", () => {
    expect(candidateRateOnStart([{ rate: "", effectiveFrom: "" }], "2026-12-01")).toBeNull();
    expect(candidateRateOnStart([], "2026-12-01")).toBeNull();
  });
});

describe("contractMoney — marża w podsumowaniu", () => {
  const base = {
    clientRate: 157,
    candidateRate: 110,
    clientCurrency: "PLN",
    candidateCurrency: "PLN",
    rateUnit: "hourly",
    billingHours: 168,
  };

  it("godzinowo: marża na godzinę, procent i miesiąc × godziny", () => {
    const m = contractMoney(base);
    expect(m.marginPerUnit).toBe(47);
    expect(formatPctPl(m.marginPct)).toBe(`29,9${NBSP}%`);
    expect(m.monthlyRevenue).toBe(26376);
    expect(m.monthlyCost).toBe(18480);
    expect(m.monthlyMargin).toBe(7896);
    expect(m.hours).toBe(168);
  });

  it("puste albo zerowe godziny liczą się jak 168 (jak zapis kontraktu)", () => {
    expect(contractMoney({ ...base, billingHours: null }).hours).toBe(168);
    expect(contractMoney({ ...base, billingHours: 0 }).monthlyMargin).toBe(7896);
  });

  it("ryczałt miesięczny nie mnoży przez godziny", () => {
    const m = contractMoney({ ...base, rateUnit: "monthly", clientRate: 26000, candidateRate: 19000 });
    expect(m.hours).toBeNull();
    expect(m.monthlyMargin).toBe(7000);
  });

  it("różne waluty: bez marży, ale przychód i koszt zostają", () => {
    const m = contractMoney({ ...base, clientCurrency: "EUR" });
    expect(m.sameCurrency).toBe(false);
    expect(m.marginPerUnit).toBeNull();
    expect(m.marginPct).toBeNull();
    expect(m.monthlyMargin).toBeNull();
    expect(m.monthlyRevenue).toBe(26376);
  });

  it("brak jednej stawki: bez marży i bez procentu", () => {
    const m = contractMoney({ ...base, clientRate: null });
    expect(m.marginPerUnit).toBeNull();
    expect(m.monthlyRevenue).toBeNull();
    expect(m.monthlyCost).toBe(18480);
  });

  it("ujemna marża zostaje ujemna; stawka klienta 0 nie dzieli przez zero", () => {
    expect(contractMoney({ ...base, candidateRate: 170 }).marginPerUnit).toBe(-13);
    expect(contractMoney({ ...base, clientRate: 0 }).marginPct).toBeNull();
  });
});

describe("advancedSummary — skrót zwiniętych „Zaawansowanych”", () => {
  const input: AdvancedSummaryInput = {
    canManageFinance: true,
    clientCurrency: "PLN",
    candidateCurrency: "PLN",
    rateUnit: "hourly",
    billingHours: "168",
    frameworkRows: [{ rate: "", effectiveFrom: "" }],
    candidateRows: [{ rate: "110", effectiveFrom: "" }],
    consumption: "",
    consumptionUnit: "rbh",
    status: "draft",
  };

  it("domyślny formularz", () => {
    expect(advancedSummary(input)).toBe(
      "PLN · godzinowo, 168 h/mies. · bez stawki ramowej · bez zmian stawki · bez zużycia zamówienia · status: szkic",
    );
  });

  it("różne waluty, ryczałt, stawka ramowa, zmiany stawki i zużycie", () => {
    expect(
      advancedSummary({
        ...input,
        clientCurrency: "EUR",
        rateUnit: "monthly",
        frameworkRows: [{ rate: "150", effectiveFrom: "" }],
        candidateRows: [
          { rate: "110", effectiveFrom: "" },
          { rate: "120", effectiveFrom: "2027-01-01" },
          { rate: "130", effectiveFrom: "2027-06-01" },
        ],
        consumption: "40",
        consumptionUnit: "md",
        status: "active",
      }),
    ).toBe("EUR / PLN · ryczałt miesięczny · stawka ramowa · 2 zmiany stawki · zużycie 40 MD · status: aktywny");
  });

  it("bez uprawnienia do kwot: tylko zużycie i status", () => {
    expect(advancedSummary({ ...input, canManageFinance: false })).toBe(
      "bez zużycia zamówienia · status: szkic",
    );
  });
});

function recruitment(overrides: Partial<RecruitmentRate> = {}): RecruitmentRate {
  return {
    candidate_id: 42,
    job_id: 17,
    job_title: "Backend Engineer",
    client_rate_value: 157,
    client_rate_unit: "hourly",
    client_rate_currency: "PLN",
    client_rate_at: "2026-10-27T09:30:00Z",
    client_rate_by_name: "Anna Przykładowa",
    client_rate_redacted: false,
    candidate_rate_value: "110.00",
    candidate_rate_unit: "hourly",
    candidate_rate_currency: "PLN",
    candidate_rate_at: "2026-10-26T08:00:00Z",
    ...overrides,
  };
}

describe("recruitmentRateHint — podpowiedź z rekrutacji (D7)", () => {
  const hourlyPln = { unit: "hourly", currency: "PLN" };
  // `formatMoney` stawia spację twardą przed walutą.
  const plain = (text: string | undefined) => text?.replace(/ /g, " ");

  it("zgodna stawka: „z rekrutacji”, bez przycisku", () => {
    const hint = recruitmentRateHint(recruitment(), "candidate", { value: "110,00", ...hourlyPln });
    expect(plain(hint?.text)).toBe("z rekrutacji: 110,00 zł/h · 26.10.2026");
    expect(hint?.matches).toBe(true);
    expect(hint?.useValue).toBeNull();
  });

  it("puste pole stawki konsultanta: „w rekrutacji” i „Użyj” z wartością do pola", () => {
    const hint = recruitmentRateHint(recruitment(), "candidate", { value: "", ...hourlyPln });
    expect(plain(hint?.text)).toBe("w rekrutacji: 110,00 zł/h · 26.10.2026");
    expect(hint?.useValue).toBe("110,00");
  });

  it("stawka klienta nigdy nie dostaje „Użyj”, ale mówi kto i kiedy", () => {
    const hint = recruitmentRateHint(recruitment(), "client", { value: "", ...hourlyPln });
    expect(plain(hint?.text)).toBe("w rekrutacji: 157,00 zł/h · Anna Przykładowa, 27.10.2026");
    expect(hint?.useValue).toBeNull();
  });

  it("inna jednostka albo waluta: sama informacja, bez przepisywania", () => {
    const md = recruitmentRateHint(
      recruitment({ candidate_rate_value: 880, candidate_rate_unit: "daily" }),
      "candidate",
      { value: "", ...hourlyPln },
    );
    expect(plain(md?.text)).toBe("w rekrutacji: 880,00 zł/MD · 26.10.2026");
    expect(md?.useValue).toBeNull();
    const eur = recruitmentRateHint(recruitment(), "candidate", { value: "", unit: "hourly", currency: "EUR" });
    expect(eur?.useValue).toBeNull();
  });

  it("MD równe stawce godzinowej × 8 liczy się jako zgodne", () => {
    const hint = recruitmentRateHint(
      recruitment({ candidate_rate_value: 880, candidate_rate_unit: "daily" }),
      "candidate",
      { value: "110", ...hourlyPln },
    );
    expect(hint?.matches).toBe(true);
  });

  it("brak rekrutacji, brak stawki albo stawka ukryta: bez podpowiedzi", () => {
    expect(recruitmentRateHint(null, "candidate", { value: "", ...hourlyPln })).toBeNull();
    expect(
      recruitmentRateHint(
        recruitment({ client_rate_value: null, client_rate_redacted: true }),
        "client",
        { value: "", ...hourlyPln },
      ),
    ).toBeNull();
  });
});

describe("rateToInput", () => {
  it("dwa miejsca po przecinku, puste dla braku", () => {
    expect(rateToInput(157)).toBe("157,00");
    expect(rateToInput("110.5")).toBe("110,50");
    expect(rateToInput(null)).toBe("");
    expect(rateToInput("x")).toBe("");
  });
});
