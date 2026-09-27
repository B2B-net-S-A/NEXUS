import { describe, expect, it } from "vitest";

import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import {
  contractCostRatePerMd,
  defaultEntryDate,
  effectiveTransferMethod,
  freePoolMd,
  mdOverFreePool,
  sourceDepartingRate,
  swapBlockedReason,
  takeoverSources,
  transferPreview,
} from "@/lib/order-takeover";

function line(overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 1,
    group_id: 10,
    contract_id: 100,
    candidate_id: 5,
    consultant_name: "Konrad Sigda",
    job_id: null,
    job_title: null,
    status: "completed",
    is_active: false,
    start_date: "2025-12-01",
    end_date: "2026-08-31",
    rate_cost: 760,
    rate_revenue: 800,
    input_value: 190,
    input_mode: "md",
    md_total: 190,
    md_remaining: 187,
    md_manual_adjustment: 0,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    md_optional_total: 170,
    md_base_used: 173,
    md_optional_used: 0,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
    ...overrides,
  };
}

function group(lines: OrderLineRead[], overrides: Partial<OrderGroupRead> = {}) {
  return {
    id: 10,
    client_id: 115,
    order_number: "CeZ/242/2025",
    status: "active",
    is_cost_based: false,
    is_md_budget_based: false,
    md_budget_mode: "per_person",
    can_add_consultant: true,
    lines,
    ...overrides,
  } as OrderGroupRead;
}

describe("przejęcie pozostałych MD", () => {
  it("pula w MD przechodzi 1:1 i nie ma wyboru stawki", () => {
    const preview = transferPreview({
      unit: "md",
      remaining: 187,
      departingRate: 800,
      incomingRate: 1000,
    });
    expect(preview?.options).toEqual([{ method: "one_to_one", md: 187 }]);
    expect(effectiveTransferMethod("md", null)).toBe("one_to_one");
  });

  it("pula w kwocie pokazuje obie opcje z wynikiem i niczego nie wybiera", () => {
    const preview = transferPreview({
      unit: "amount",
      remaining: 10,
      departingRate: 1000,
      incomingRate: 1200,
    });
    expect(preview?.amount).toBe(10000);
    expect(preview?.options).toEqual([
      { method: "departing_rate", md: 10 },
      { method: "incoming_rate", md: 8.3 },
    ]);
    expect(effectiveTransferMethod("amount", null)).toBeNull();
    expect(effectiveTransferMethod("amount", "incoming_rate")).toBe("incoming_rate");
  });

  it("stawka z kontraktu godzinowego × 8 (A6)", () => {
    expect(contractCostRatePerMd(85, "hourly")).toEqual({
      value: 680,
      note: "Z kontraktu: 85 PLN/h × 8",
    });
    expect(contractCostRatePerMd(85, "monthly")).toBeNull();
  });

  it("data wejścia domyślnie dzień po zakończeniu", () => {
    expect(defaultEntryDate("2026-08-31", "2026-09-23")).toBe("2026-09-01");
    expect(defaultEntryDate(null, "2026-09-23")).toBe("2026-09-23");
  });

  it("za kogo wchodzi: tylko osoby wskazane przez serwer, z pozostałymi MD", () => {
    const konrad = line({
      takeover_source: "ended",
      departure_date: "2026-08-31",
      offboarding_case: {
        status: "pending",
        remaining_md_snapshot: 187,
        uses_shared_md_pool: false,
      } as OrderLineRead["offboarding_case"],
    });
    const active = line({ id: 2, status: "active", is_active: true });
    const sources = takeoverSources([group([konrad, active])]);
    expect(sources.map((item) => item.line.id)).toEqual([1]);
    expect(sources[0].remaining).toBe(187);
    expect(freePoolMd(group([konrad, active]))).toBe(187);
    expect(mdOverFreePool(200, 187)).toBe(13);
    expect(mdOverFreePool(100, 187)).toBe(0);
  });
});

describe("stawka odchodzącego w podglądzie przejęcia (audyt 24.09, N2)", () => {
  const pendingCase = (rate: number | null) =>
    ({
      status: "pending",
      version: 1,
      remaining_md_snapshot: 20,
      rate_revenue_snapshot: rate,
    }) as OrderLineRead["offboarding_case"];

  it("przy sprawie czekającej na decyzję liczy stawką ze sprawy, nie bieżącą", () => {
    const departing = line({ rate_revenue: 1000, offboarding_case: pendingCase(800) });
    expect(sourceDepartingRate(departing)).toBe(800);
    const preview = transferPreview({
      unit: "amount",
      remaining: 20,
      departingRate: sourceDepartingRate(departing),
      incomingRate: 1000,
    });
    // 20 MD × 800 zł = 16 000 zł → 16 MD po stawce 1000 zł (jak serwer).
    expect(preview?.options.find((o) => o.method === "incoming_rate")?.md).toBe(16);
  });

  it("bez sprawy albo bez zapamiętanej stawki bierze stawkę linii", () => {
    expect(sourceDepartingRate(line({ rate_revenue: 900 }))).toBe(900);
    expect(
      sourceDepartingRate(line({ rate_revenue: 900, offboarding_case: pendingCase(null) })),
    ).toBe(900);
  });
});

describe("zamiana kontraktora a zaplanowany następca (runda 8, N5-1)", () => {
  it("aktywna linia bez następcy — zamiana dozwolona", () => {
    expect(swapBlockedReason({ status: "active", replaced_by_kind: null })).toBeNull();
    expect(
      swapBlockedReason({ status: "active", replaced_by_kind: "replacement" }),
    ).toBeNull();
  });

  it("zaplanowana zamiana albo zastępstwo blokuje drugą zamianę", () => {
    expect(swapBlockedReason({ status: "active", replaced_by_kind: "swap" })).toMatch(
      /już zaplanowana/,
    );
    expect(
      swapBlockedReason({ status: "active", replaced_by_kind: "takeover" }),
    ).toMatch(/zastępstwo/);
  });

  it("linia nieaktywna — jak dotąd", () => {
    expect(swapBlockedReason({ status: "completed", replaced_by_kind: null })).toMatch(
      /tylko aktywną/,
    );
  });
});
