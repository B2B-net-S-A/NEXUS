// Stawka przychodowa linii od dnia aneksu (0724, ticket Finansów 16.11.2026).
// Dane fikcyjne.

import { describe, expect, it } from "vitest";

import type { OrderLineRead } from "@/lib/api/orderGroups";
import {
  displayLineRate,
  lineRevenueStepNote,
} from "@/components/client-profile/orders/order-line-display";
import {
  impactMonthNote,
  impactRateLabel,
  type AnnexClientRateImpactRow,
} from "@/components/contracts/AnnexClientRateImpact";

function line(over: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 1,
    group_id: 1,
    contract_id: 1,
    candidate_id: 1,
    consultant_name: "Ola Przykładowa",
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2026-02-01",
    end_date: "2026-12-31",
    rate_cost: 1000,
    rate_revenue: 1200,
    source_rate_revenue: 1200,
    rate_client_currency: "PLN",
    input_value: null,
    ...over,
  } as OrderLineRead;
}

const STEP = { effective_from: "2026-11-01", first_month: "2026-11-01", md_rate_revenue: 1300 };

describe("stawka przychodowa linii z krokiem aneksu", () => {
  it("pokazuje stawkę obowiązującą dziś zamiast stawki ze startu", () => {
    expect(displayLineRate(line({ current_rate_revenue: 1300, revenue_steps: [STEP] }), "revenue")).toBe(
      "1300,000 zł/MD",
    );
  });

  it("linia bez kroków wygląda jak dotąd i nie ma dopisku", () => {
    expect(displayLineRate(line(), "revenue")).toBe("1200,000 zł/MD");
    expect(lineRevenueStepNote(line(), "2026-11-16")).toBeNull();
  });

  it("po dniu aneksu dopisek mówi, od kiedy i ile było wcześniej", () => {
    expect(lineRevenueStepNote(line({ revenue_steps: [STEP] }), "2026-11-16")).toBe(
      "od 01.11.2026 · wcześniej 1200,000",
    );
  });

  it("aneks z przyszłą datą zapowiada nową stawkę", () => {
    const future = { ...STEP, effective_from: "2026-12-01", first_month: "2026-12-01" };
    expect(lineRevenueStepNote(line({ revenue_steps: [future] }), "2026-11-16")).toBe(
      "od 01.12.2026: 1300,000",
    );
  });

  it("drugi aneks porównuje z poprzednim krokiem, nie ze startem", () => {
    const second = { effective_from: "2027-01-01", first_month: "2027-01-01", md_rate_revenue: 1400 };
    expect(lineRevenueStepNote(line({ revenue_steps: [second, STEP] }), "2027-01-10")).toBe(
      "od 01.01.2027 · wcześniej 1300,000",
    );
  });
});

describe("podgląd aneksu w oknie „Zmień stawkę”", () => {
  const row: AnnexClientRateImpactRow = {
    order_id: 113,
    order_group_id: 17,
    order_number: "AN-2026-1",
    unit: "daily",
    currency: "PLN",
    effective_from: "2026-11-01",
    first_month: "2026-11-01",
    old_rate: "1200.000",
    new_rate: "1300.00",
    old_md_rate: "1200.000",
    new_md_rate: "1300.00",
  };

  it("pokazuje zmianę w zł/MD", () => {
    expect(impactRateLabel(row)).toBe("1200,000 → 1300,000 zł/MD");
  });

  it("aneks od 1. dnia miesiąca nie potrzebuje uwagi o miesiącu", () => {
    expect(impactMonthNote(row)).toBeNull();
  });

  it("aneks od połowy miesiąca mówi, od którego rozliczenia liczy się nowa stawka", () => {
    expect(
      impactMonthNote({ ...row, effective_from: "2026-11-15", first_month: "2026-12-01" }),
    ).toBe("Zużycie MD liczy się miesiącami: nowa stawka od rozliczenia za grudzień 2026.");
  });

  it("zamówienie godzinowe pokazuje stawkę za godzinę", () => {
    expect(
      impactRateLabel({ ...row, unit: "hourly", old_rate: 150, new_rate: 162.5, old_md_rate: null, new_md_rate: null }),
    ).toBe("150,000 → 162,500 zł/h");
  });
});
