/** Kolumny mapy cieplnej: działy z sygnałem, „bez działu” na początku (prod 20.10.2026, Nordea). */
import { describe, expect, it } from "vitest";

import { heatColumns } from "@/components/care/heatmap-columns";
import type { HeatCell, HeatRow, MapDepartment } from "@/lib/api/care";

function dept(id: number, consultants = 0): MapDepartment {
  return {
    area: { id, name: `Dział ${id}` },
    technologies: [],
    technologies_total: 0,
    managers: [],
    consultants,
    last_seen: null,
    has_fresh_source: true,
    base: { skills: [], count: null },
  };
}

const sig = (sources = 1, open = 0): HeatCell => ({
  counts: { cards: sources, jobs: 0, consultants: 0, notes: 0 },
  source_count: sources,
  open_jobs: open,
});

function row(id: number, cells: (HeatCell | null)[], unassigned: HeatCell | null = null): HeatRow {
  return { skill_id: id, name: `Tech ${id}`, must_jobs: 0, consultants: 0, last_seen: null, stale: false, cells, unassigned };
}

describe("heatColumns", () => {
  it("Nordea: 67 pustych działów schowanych, „bez działu” pierwsze", () => {
    const depts = Array.from({ length: 67 }, (_, i) => dept(i + 1));
    const rows = Array.from({ length: 40 }, (_, i) => row(i, depts.map(() => null), sig(2)));
    expect(heatColumns(depts, rows, false)).toEqual({ shown: [], hidden: 67, unassignedFirst: true });
    const all = heatColumns(depts, rows, true);
    expect(all.shown).toHaveLength(67);
    expect(all.hidden).toBe(0);
  });

  it("dział z sygnałem w dowolnym wierszu, z otwartą rekrutacją albo naszymi ludźmi zostaje", () => {
    const depts = [dept(1), dept(2), dept(3), dept(4, 2)];
    const rows = [
      row(1, [null, sig(), null, null]),
      row(2, [null, null, sig(0, 1), null]),
      row(3, [{ ...sig(0), source_count: 0 }, null, null, null]),
    ];
    expect(heatColumns(depts, rows, false)).toEqual({ shown: [1, 2, 3], hidden: 1, unassignedFirst: false });
  });

  it("„bez działu” zostaje na końcu, gdy działy niosą więcej sygnału (także przy remisie)", () => {
    const depts = [dept(1), dept(2)];
    const more = [row(1, [sig(), sig()], sig()), row(2, [sig(), null], null)];
    expect(heatColumns(depts, more, false).unassignedFirst).toBe(false);
    const tie = [row(1, [sig(), null], sig())];
    expect(heatColumns(depts, tie, false).unassignedFirst).toBe(false);
  });

  it("bez działów i bez wierszy nic nie pada", () => {
    expect(heatColumns([], [], false)).toEqual({ shown: [], hidden: 0, unassignedFirst: false });
  });
});
