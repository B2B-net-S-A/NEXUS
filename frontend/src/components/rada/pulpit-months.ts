// Tabela miesięcy pulpitu Rady (R7): sama sprzedaż, wykonanie roku
// poprzedniego, budżet, wykonanie i odchylenia. Uwaga Rady z 18.11.2026:
// „uzupełniamy o dane budżetowe — wykonanie 2026, budżet 2027, wykonanie
// 2027, tylko sprzedaż, odchylenia od budżetu i od 2026”.

import type { BoardSummary } from "@/lib/api/supervisory-board";

export interface MonthCell {
  value: number | null;
  /** Odchylenie w % (wiersze odchyleń). */
  pct?: number | null;
  /** Miesiąc bez kompletu faktur — kursywa, bez odchyleń. */
  partial?: boolean;
}

export interface MonthTableRow {
  key: string;
  label: string;
  kind: "actual" | "budget" | "delta";
  cells: MonthCell[];
  total: MonthCell;
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function deltaCell(value: number | null, base: number | null): MonthCell {
  if (value === null || base === null) return { value: null, pct: null };
  return {
    value: round2(value - base),
    pct: base !== 0 ? Math.round((1000 * (value - base)) / Math.abs(base)) / 10 : null,
  };
}

/** Lata do wyboru: bieżący, poprzedni z danymi i następny, gdy ma budżet. */
export function selectableYears(data: BoardSummary, currentYear: number): number[] {
  const withData = new Set(data.months.filter((m) => (m.sales ?? 0) !== 0).map((m) => m.year));
  const years = new Set<number>([currentYear]);
  if (withData.has(currentYear - 1)) years.add(currentYear - 1);
  if (data.budgets[String(currentYear + 1)]) years.add(currentYear + 1);
  return [...years].sort((a, b) => b - a);
}

export function monthTable(data: BoardSummary, year: number): MonthTableRow[] {
  const byKey = new Map(data.months.map((m) => [`${m.year}-${m.month}`, m]));
  const series = (y: number): MonthCell[] =>
    Array.from({ length: 12 }, (_, i) => {
      const m = byKey.get(`${y}-${i + 1}`);
      if (!m) return { value: null };
      // Miesiąc przed importem faktur sprzedaży: kreska, nie „0,0”.
      const empty = !m.sales_complete && !m.sales;
      return { value: empty ? null : m.sales, partial: !m.sales_complete };
    });
  const previous = series(year - 1);
  const current = series(year);
  const plan = data.budgets[String(year)] ?? null;
  // Odchylenia i sumy „Razem” tylko z miesięcy, w których rok ma komplet faktur.
  const done = current.map((c) => c.value !== null && !c.partial);
  const sumOver = (cells: (number | null)[], mask: boolean[]): number | null => {
    const picked = cells.filter((v, i) => mask[i] && v !== null) as number[];
    return picked.length ? round2(picked.reduce((a, b) => a + b, 0)) : null;
  };
  const doneCount = done.filter(Boolean).length;
  const rows: MonthTableRow[] = [
    {
      key: "previous",
      label: `Wykonanie ${year - 1}`,
      kind: "actual",
      cells: previous,
      total: { value: sumOver(previous.map((c) => c.value), doneCount ? done : previous.map(() => true)) },
    },
  ];
  if (plan) {
    rows.push({
      key: "budget",
      label: `Budżet ${year}`,
      kind: "budget",
      cells: plan.map((value) => ({ value })),
      total: { value: sumOver(plan, doneCount ? done : plan.map(() => true)) },
    });
  }
  rows.push({
    key: "current",
    label: `Wykonanie ${year}`,
    kind: "actual",
    cells: current,
    total: { value: sumOver(current.map((c) => c.value), done) },
  });
  if (plan) {
    rows.push({
      key: "vs-budget",
      label: "Odchylenie od budżetu",
      kind: "delta",
      cells: current.map((c, i) => (done[i] ? deltaCell(c.value, plan[i]) : { value: null })),
      total: deltaCell(sumOver(current.map((c) => c.value), done), sumOver(plan, done)),
    });
  }
  rows.push({
    key: "vs-previous",
    label: `Odchylenie od ${year - 1}`,
    kind: "delta",
    cells: current.map((c, i) => (done[i] ? deltaCell(c.value, previous[i].value) : { value: null })),
    total: deltaCell(
      sumOver(current.map((c) => c.value), done),
      sumOver(previous.map((c) => c.value), done),
    ),
  });
  return rows;
}
