// Czyste reguły zakładki „Stawki ramowe” (F2, 15.11.2026) — testowane osobno.
import type { FrameworkCounts, FrameworkOverviewRow, FrameworkStatus } from "@/lib/api/framework-rates";

export type OverviewFilter = FrameworkStatus | "all";

export function filterRows(rows: FrameworkOverviewRow[], filter: OverviewFilter, query: string): FrameworkOverviewRow[] {
  const needle = query.trim().toLocaleLowerCase("pl");
  return rows.filter(
    (row) =>
      (filter === "all" || row.status === filter) &&
      (!needle ||
        row.person.toLocaleLowerCase("pl").includes(needle) ||
        (row.category ?? "").toLocaleLowerCase("pl").includes(needle)),
  );
}

/** Udział „w stawce” (z dopłatą) wśród osób, które mają limit z umowy. */
export function inRateShare(counts: FrameworkCounts): number | null {
  const withLimit = counts.in + counts.in_addon + counts.over;
  if (withLimit === 0) return null;
  return Math.round(((counts.in + counts.in_addon) / withLimit) * 100);
}

/** „Q3 2026” z ostatniego dnia kwartału; dziś — „dziś”. */
export function quarterLabel(iso: string, todayIso: string): string {
  if (iso === todayIso) return "dziś";
  const [y, m] = iso.split("-").map(Number);
  return `Q${Math.ceil(m / 3)} ${y}`;
}
