import { describe, expect, it } from "vitest";

import type { AssignmentRow } from "@/lib/api/equipment";
import type { BonusRow, RateRow } from "@/lib/api/hr-payroll";

import {
  bonusTotals,
  buildTimeline,
  previousRate,
  ringParts,
  tabFromHash,
} from "../person-view";

function rate(id: number, from: string, amount: string, reason: string | null = null): RateRow {
  return {
    id,
    user_id: 1,
    hourly_rate: amount,
    currency: "PLN",
    effective_from: from,
    effective_to: null,
    reason,
    set_by: null,
  };
}

function bonus(id: number, status: BonusRow["status"], amount: string, year = 2026): BonusRow {
  return {
    id,
    recipient_user_id: 1,
    recipient_name: null,
    proposed_by: null,
    proposed_by_name: null,
    amount,
    currency: "PLN",
    category: "recruiter",
    category_label: "Placement",
    period_year: year,
    period_month: 9,
    status,
    source: "manual",
    contract_id: null,
    eligible_on: `${year}-09-30`,
    description: null,
    assigned_by: null,
  } as BonusRow;
}

describe("tabFromHash", () => {
  it("dzwonek Płac `#place` otwiera „Płace i premie”", () => {
    expect(tabFromHash("#place")).toBe("payroll");
    expect(tabFromHash("#sprzet")).toBe("equipment");
    expect(tabFromHash("")).toBe("overview");
    expect(tabFromHash("#cokolwiek")).toBe("overview");
  });
});

describe("ringParts", () => {
  it("wykorzystane, zaplanowane i zostało z puli + zaległych", () => {
    const ring = ringParts({
      year: 2026,
      has_paid_pool: true,
      entitlement_days: "26.0",
      carried_over_days: "2.0",
      used_days: "14.0",
      planned_days: "2.5",
      remaining_days: "11.5",
    });
    expect(ring).toMatchObject({ pool: 28, used: 14, planned: 2.5, remaining: 11.5 });
    expect(ring?.usedPct).toBeCloseTo(50);
    expect(ring?.plannedPct).toBeCloseTo((2.5 / 28) * 100);
  });

  it("bez puli albo z pulą zero — bez pierścienia", () => {
    expect(ringParts(null)).toBeNull();
    expect(
      ringParts({
        year: 2026,
        has_paid_pool: false,
        entitlement_days: "0.0",
        carried_over_days: "0.0",
        used_days: "0.0",
        planned_days: "0.0",
        remaining_days: "0.0",
      }),
    ).toBeNull();
  });

  it("przekroczona pula nie wychodzi poza 100%", () => {
    const ring = ringParts({
      year: 2026,
      has_paid_pool: true,
      entitlement_days: "10.0",
      carried_over_days: "0.0",
      used_days: "12.0",
      planned_days: "3.0",
      remaining_days: "-5.0",
    });
    expect(ring?.usedPct).toBe(100);
    expect(ring?.plannedPct).toBe(0);
  });
});

describe("bonusTotals i previousRate", () => {
  it("przyznane i czekające w roku, anulowane i inne lata poza sumą", () => {
    expect(
      bonusTotals(
        [
          bonus(1, "assigned", "1500.00"),
          bonus(2, "proposed", "3000.00"),
          bonus(3, "cancelled", "999.00"),
          bonus(4, "assigned", "700.00", 2025),
        ],
        2026,
      ),
    ).toEqual({ granted: 1500, waiting: 3000, currency: "PLN", waitingCount: 1 });
  });

  it("poprzednia stawka to najnowsza sprzed bieżącej", () => {
    const rates = [rate(1, "2025-03-01", "110.00"), rate(2, "2026-07-01", "120.00"), rate(3, "2024-01-01", "90.00")];
    expect(previousRate(rates, rates[1])?.id).toBe(1);
    expect(previousRate(rates, rates[2])).toBeNull();
    expect(previousRate(rates, null)).toBeNull();
  });
});

describe("buildTimeline — oś „Ostatnio”", () => {
  it("łączy stawki, premie, sprzęt i start; najnowsze na górze", () => {
    const equipment = [
      { assignment_id: 1, issued_at: "2025-03-03T09:00:00Z", issue_protocol: "PZO/2025/03/006" },
      { assignment_id: 2, issued_at: "2025-03-03T09:00:00Z", issue_protocol: "PZO/2025/03/006" },
    ] as AssignmentRow[];
    const timeline = buildTimeline({
      workStart: "2025-03-03",
      rates: [rate(1, "2025-03-03", "110.00", "Stawka z umowy"), rate(2, "2026-07-01", "120.00", "Aneks")],
      bonuses: [bonus(7, "assigned", "1500.00"), bonus(8, "cancelled", "100.00")],
      equipment,
      today: "2026-10-19",
    });
    expect(timeline.map((entry) => entry.key)).toEqual([
      "bonus-7",
      "rate-2",
      "eq-PZO/2025/03/006",
      "rate-1",
      "start",
    ]);
    expect(timeline[1].title).toMatch(/^Nowa stawka · 120/);
    expect(timeline[2].title).toBe("Wydanie sprzętu · 2 pozycje");
    expect(timeline[3].title).toMatch(/^Stawka startowa/);
  });

  it("przełożony bez stawek (D2) — oś bez wierszy stawek", () => {
    const timeline = buildTimeline({ rates: [], bonuses: [], today: "2026-10-19" });
    expect(timeline).toEqual([]);
  });

  it("start w przyszłości się nie pokazuje, odejście tak", () => {
    const timeline = buildTimeline({
      workStart: "2026-11-04",
      lastWorkingDay: "2026-11-30",
      today: "2026-10-19",
    });
    expect(timeline.map((entry) => entry.title)).toEqual(["Ostatni dzień pracy (zaplanowany)"]);
  });
});
