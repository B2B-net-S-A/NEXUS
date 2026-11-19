import { describe, expect, it } from "vitest";

import { defaultMeetingId, packFigures } from "../MeetingsTab";
import type { BoardMeeting, BudgetMonthView, MeetingPack } from "@/lib/api/supervisory-board";

function meeting(id: number, held_on: string, status: BoardMeeting["status"]): BoardMeeting {
  return {
    id,
    held_on,
    status,
    kind: "meeting",
    title: "",
    place: null,
    agenda: [],
    note: null,
    minutes_document_id: null,
    pack_frozen_at: null,
    has_pack: false,
  };
}

function month(m: number, kind: "actual" | "forecast", sales: number | null, plan: number | null): BudgetMonthView {
  return {
    month: m,
    kind,
    sales,
    plan_sales: plan,
    plan_costs: null,
    costs: null,
    costs_complete: true,
    potential: null,
    potential_renewed: null,
    business_days: 20,
  };
}

describe("posiedzenia Rady", () => {
  it("domyślnie pokazuje najbliższe zaplanowane, potem najnowsze", () => {
    const items = [meeting(3, "2026-12-10", "planned"), meeting(2, "2026-11-25", "planned"), meeting(1, "2026-06-01", "held")];
    expect(defaultMeetingId(items, "2026-11-18")).toBe(2);
    expect(defaultMeetingId([meeting(1, "2026-06-01", "held")], "2026-11-18")).toBe(1);
    expect(defaultMeetingId([], "2026-11-18")).toBeNull();
  });

  it("wykonanie budżetu liczy tylko miesiące wykonane i z planem", () => {
    const pack = {
      summary: { ytd: { sales_months: 10, sales: 98.8, sales_previous: 95.6, result_months: 9, result: 5.4, result_pct: 5.8 } },
      budget: {
        months: [month(1, "actual", 10, 9), month(2, "actual", 9, 10), month(3, "actual", 8, null), month(4, "forecast", 11, 10)],
      },
    } as unknown as MeetingPack;
    const f = packFigures(pack);
    expect(f.actualVsPlan).toEqual({ actual: 19, plan: 19 });
    expect(f.planSales).toBe(29);
    expect(f.salesYtd).toBe(98.8);
    expect(f.resultMonths).toBe(9);
  });
});
