import { describe, expect, it } from "vitest";

import type {
  OrderChangeItem,
  OrderEntryItem,
  OrderExitItem,
  OrderGapItem,
  OrderTypeCode,
} from "@/lib/api/finance";
import {
  changeMeta,
  changeTitle,
  changeValue,
  entryDetails,
  entryTags,
  exitDetails,
  exitTone,
  formatDay,
  formatMoment,
  formatRate,
  gapDetails,
  gapStatusLabel,
  initials,
  monthOptions,
  orderTypeLabel,
  parseMonthValue,
  peopleLabel,
} from "@/lib/finance-order-changes";

const ref = {
  order_id: 1,
  order_group_id: null,
  contract_id: 2,
  client_id: 3,
  client_name: "Firma Testowa sp. z o.o.",
  consultant_name: "Jan Testowy",
  order_number: "T-100",
};

function change(overrides: Partial<OrderChangeItem>): OrderChangeItem {
  return {
    ...ref,
    kind: "rate_revenue",
    occurred_at: "2026-09-10T10:00:00Z",
    effective_date: "2026-09-10",
    old_amount: 100,
    new_amount: 120,
    old_unit: "hourly",
    new_unit: "hourly",
    currency: "PLN",
    old_date: null,
    new_date: null,
    is_whole_order: false,
    source: "user",
    author_name: "Anna Przykładowa",
    rate_cost: null,
    rate_revenue: null,
    rate_unit: null,
    other_client_names: [],
    previous_order_number: null,
    previous_end_date: null,
    previous_client_name: null,
    start_date: null,
    engagement_since: null,
    ...overrides,
  };
}

function entry(overrides: Partial<OrderEntryItem> = {}): OrderEntryItem {
  return {
    ...ref,
    start_date: "2027-01-01",
    end_date: null,
    rate_cost: 80,
    rate_revenue: 100,
    rate_unit: "md",
    currency: "PLN",
    order_type: "md",
    status: "active",
    ...overrides,
  };
}

function exit(verdict: OrderExitItem["verdict"]): OrderExitItem {
  return {
    ...ref,
    end_date: "2026-12-31",
    start_date: null,
    rate_cost: null,
    rate_revenue: null,
    rate_unit: null,
    currency: null,
    order_type: "periodic",
    verdict,
    verdict_label: "x",
    intent: null,
  } as OrderExitItem;
}

function gap(overrides: Partial<OrderGapItem>): OrderGapItem {
  return {
    ...ref,
    gap_id: 1,
    ended_on: "2026-12-31",
    detected_on: "2027-01-01",
    status: "filled_late",
    resolved_order_number: "T-101",
    resolved_at: null,
    delay_days: 3,
    ...overrides,
  };
}

describe("parseMonthValue — odmowa", () => {
  it("miesiąc 00 i 13 to nie miesiąc", () => {
    expect(parseMonthValue("2026-00")).toBeNull();
    expect(parseMonthValue("2026-13")).toBeNull();
  });
  it("null, undefined i zły format dają null", () => {
    expect(parseMonthValue(null)).toBeNull();
    expect(parseMonthValue(undefined)).toBeNull();
    expect(parseMonthValue("2026-9")).toBeNull();
  });
  it("grudzień jest poprawny", () => {
    expect(parseMonthValue("2026-12")).toEqual({ year: 2026, month: 12 });
  });
});

describe("monthOptions — granica roku", () => {
  it("w grudniu kolejny miesiąc to styczeń następnego roku", () => {
    const options = monthOptions(new Date(2026, 11, 31), 1);
    expect(options.map((o) => o.value)).toEqual(["2027-01", "2026-12", "2026-11"]);
    expect(options[0].label).toBe("Styczeń 2027");
  });
  it("back = 0: tylko kolejny i bieżący", () => {
    expect(monthOptions(new Date(2027, 0, 1), 0).map((o) => o.value)).toEqual([
      "2027-02",
      "2027-01",
    ]);
  });
});

describe("orderTypeLabel", () => {
  it("znane typy i nieznany kod bez zmian", () => {
    expect(orderTypeLabel("periodic")).toBe("Okresowe");
    expect(orderTypeLabel("cost")).toBe("Kosztowe");
    expect(orderTypeLabel("md")).toBe("MD");
    expect(orderTypeLabel("ryczalt" as OrderTypeCode)).toBe("ryczalt");
  });
});

describe("formatRate — kwoty, waluty, jednostki", () => {
  it("brak kwoty (null/undefined) to kreska, zero to 0,00", () => {
    expect(formatRate(null, "hourly", "PLN")).toBe("—");
    expect(formatRate(undefined, "hourly", "PLN")).toBe("—");
    expect(formatRate(0, "md", "PLN")).toMatch(/^0,00 zł\/MD$/);
  });
  it("brak waluty = PLN, mała litera waluty normalizowana", () => {
    expect(formatRate(100, "daily", null)).toMatch(/^100,00 zł\/dzień$/);
    expect(formatRate(100, "monthly", "eur")).toMatch(/^100,00 EUR\/mc$/);
  });
  it("bez jednostki sama kwota; ujemna kwota zachowuje znak; grosze zaokrąglone", () => {
    expect(formatRate(99.999, null, "USD")).toMatch(/^100,00 USD$/);
    expect(formatRate(-12.345, undefined, "PLN")).toMatch(/^-12,3[45] zł$/);
    // pl-PL grupuje tysiące dopiero od pięciu cyfr
    expect(formatRate(1234.5, "hourly", "PLN")).toBe("1234,50 zł/h");
    expect(formatRate(12345.5, "hourly", "PLN").replace(/\s/g, " ")).toBe("12 345,50 zł/h");
  });
});

describe("formatDay / formatMoment", () => {
  it("formatDay przyjmuje datę z czasem, odrzuca brak i śmieci", () => {
    expect(formatDay("2026-12-31T23:59:00Z")).toBe("31.12.2026");
    expect(formatDay(null)).toBe("—");
    expect(formatDay("31.12.2026")).toBe("—");
  });
  it("formatMoment: brak i niepoprawna data to kreska", () => {
    expect(formatMoment(null)).toBe("—");
    expect(formatMoment("")).toBe("—");
    expect(formatMoment("nie-data")).toBe("—");
    expect(formatMoment("2026-09-22T10:00:00Z").slice(0, 10)).toBe("22.09.2026");
  });
});

describe("initials", () => {
  it("same znaki niebędące literami dają kreskę", () => {
    expect(initials("123 !!")).toBe("—");
  });
  it("jedno słowo daje jedną literę, nazwisko z myślnikiem bierze ostatni człon", () => {
    expect(initials("anna")).toBe("A");
    expect(initials("Anna Przykładowa-Testowa")).toBe("AT");
  });
});

describe("Wejścia", () => {
  it("entryDetails składa klienta, numer, datę i obie stawki z jednostką", () => {
    expect(entryDetails(entry())).toMatch(
      /^Firma Testowa sp\. z o\.o\. · zam\. T-100 · od 01\.01\.2027 · koszt 80,00 zł\/MD · przychód 100,00 zł\/MD$/,
    );
  });
  it("entryDetails bez stawek i daty pokazuje kreski", () => {
    expect(
      entryDetails(entry({ start_date: null, rate_cost: null, rate_revenue: null })),
    ).toBe("Firma Testowa sp. z o.o. · zam. T-100 · od — · koszt — · przychód —");
  });
  it("entryTags: przejście od innego klienta + szkic", () => {
    expect(entryTags(entry({ previous_client_name: "Inna Firma Testowa", status: "draft" }))).toEqual([
      "Zmiana klienta",
      "Szkic",
    ]);
  });
});

describe("Zejścia", () => {
  it("exitDetails z datą końca", () => {
    expect(exitDetails(exit("ended_intent"))).toBe(
      "Firma Testowa sp. z o.o. · zam. T-100 · do 31.12.2026",
    );
  });
  it("exitTone dla wszystkich werdyktów", () => {
    expect(exitTone(exit("ended_intent"))).toBe("neutral");
    expect(exitTone(exit("ending_pending"))).toBe("warning");
    expect(exitTone(exit("no_successor"))).toBe("danger");
  });
});

describe("Zmiany", () => {
  it("changeTitle dla każdego rodzaju", () => {
    expect(changeTitle(change({ kind: "rate_cost" }))).toBe("Zmiana stawki kosztowej");
    expect(changeTitle(change({ kind: "rate_revenue" }))).toBe("Zmiana stawki przychodowej");
    expect(changeTitle(change({ kind: "end_date" }))).toBe("Zmiana daty końca zamówienia");
    expect(changeTitle(change({ kind: "additional_project" }))).toBe("Dodatkowy projekt");
    expect(changeTitle(change({ kind: "order_continuation" }))).toBe("Kontynuacja zamówienia");
    expect(changeTitle(change({ kind: "client_change" }))).toBe("Zmiana klienta");
  });

  it("kontynuacja bez poprzedniego zamówienia: data startu umowy", () => {
    const value = changeValue(
      change({ kind: "order_continuation", engagement_since: "2025-03-01", effective_date: "2027-01-01" }),
    );
    expect(value.startsWith("współpraca od 01.03.2025 · od 01.01.2027")).toBe(true);
  });

  it("kontynuacja bez żadnego dowodu: kreska, nie „po —”", () => {
    const value = changeValue(change({ kind: "order_continuation" }));
    expect(value.startsWith("— · od 10.09.2026")).toBe(true);
  });

  it("kontynuacja po poprzednim zamówieniu z datą końca na granicy roku", () => {
    const value = changeValue(
      change({
        kind: "order_continuation",
        previous_order_number: "T-099",
        previous_end_date: "2026-12-31",
        effective_date: "2027-01-01",
      }),
    );
    expect(value.startsWith("po zam. T-099 (do 31.12.2026) · od 01.01.2027")).toBe(true);
  });

  it("zmiana klienta bez nazwy poprzedniego klienta i bez zamówienia", () => {
    expect(changeValue(change({ kind: "client_change" })).startsWith("z: — · — · od ")).toBe(true);
  });

  it("dodatkowy projekt: lista klientów albo kreska", () => {
    expect(
      changeValue(change({ kind: "additional_project", other_client_names: ["A", "B"] })),
    ).toMatch(/równolegle u: A, B$/);
    expect(changeValue(change({ kind: "additional_project" }))).toMatch(/równolegle u: —$/);
  });

  it("data końca: z daty na bezterminowo i odwrotnie", () => {
    expect(changeValue(change({ kind: "end_date", old_date: "2026-12-31", new_date: null }))).toBe(
      "31.12.2026 → bezterminowo",
    );
    expect(changeValue(change({ kind: "end_date", old_date: null, new_date: "2027-01-31" }))).toBe(
      "bezterminowo → 31.01.2027",
    );
  });

  it("zmiana stawki ze zmianą waluty i jednostki: stara strona w swojej walucie", () => {
    const value = changeValue(
      change({
        kind: "rate_cost",
        old_amount: 100,
        old_unit: "hourly",
        old_currency: "EUR",
        new_amount: 800,
        new_unit: "md",
        currency: "PLN",
      }),
    );
    expect(value).toMatch(/^100,00 EUR\/h → 800,00 zł\/MD$/);
  });

  it("zmiana stawki bez starej kwoty: kreska po lewej", () => {
    expect(changeValue(change({ old_amount: null }))).toMatch(/^— → 120,00 zł\/h$/);
  });

  it("changeMeta: nowe zamówienie bez autora i chwili", () => {
    expect(changeMeta(change({ kind: "client_change" }))).toBe(
      "Firma Testowa sp. z o.o. · zam. T-100",
    );
  });

  it("changeMeta: brak autora — system albo nieznany autor", () => {
    expect(changeMeta(change({ author_name: null, source: "system" }))).toMatch(/ · system$/);
    expect(changeMeta(change({ author_name: null, source: "integration" }))).toMatch(
      / · nieznany autor$/,
    );
    expect(changeMeta(change({ author_name: null, source: null, occurred_at: null }))).toBe(
      "Firma Testowa sp. z o.o. · zam. T-100 · — · nieznany autor",
    );
  });
});

describe("Braki zamówień", () => {
  it("gapDetails na granicy roku", () => {
    expect(gapDetails(gap({}))).toBe(
      "Firma Testowa sp. z o.o. · zam. T-100 · zakończone 31.12.2026 · brak od 01.01.2027",
    );
  });

  it("gapStatusLabel: otwarty, bez opóźnienia, 0 dni, 1 dzień, wiele dni, brak numeru", () => {
    expect(gapStatusLabel(gap({ status: "open" }))).toBe("Brak zamówienia");
    expect(gapStatusLabel(gap({ delay_days: null }))).toBe(
      "Uzupełnione z opóźnieniem: zam. T-101",
    );
    expect(gapStatusLabel(gap({ delay_days: 0 }))).toBe(
      "Uzupełnione z opóźnieniem: zam. T-101 (w dniu wykrycia braku)",
    );
    expect(gapStatusLabel(gap({ delay_days: 1 }))).toMatch(/\(1 dzień po terminie\)$/);
    expect(gapStatusLabel(gap({ delay_days: 5, resolved_order_number: null }))).toBe(
      "Uzupełnione z opóźnieniem: zam. — (5 dni po terminie)",
    );
  });
});

describe("peopleLabel — odmiana", () => {
  it("0, 1, 2–4, 5, 12–14, 22, 112", () => {
    expect(peopleLabel(0)).toBe("0 osób ma");
    expect(peopleLabel(1)).toBe("1 osoba ma");
    expect(peopleLabel(3)).toBe("3 osoby mają");
    expect(peopleLabel(5)).toBe("5 osób ma");
    expect(peopleLabel(12)).toBe("12 osób ma");
    expect(peopleLabel(14)).toBe("14 osób ma");
    expect(peopleLabel(22)).toBe("22 osoby mają");
    expect(peopleLabel(112)).toBe("112 osób ma");
  });
});
