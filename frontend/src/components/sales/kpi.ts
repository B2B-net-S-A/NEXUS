// Sprzedaż → KPI tygodniowe: etykiety i przeliczenia dla tabeli i krzywej WON MRR.

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type { KpiLight, KpiMetric, SalesKpi } from "@/lib/api/sales";

export const KPI_METRICS: { key: KpiMetric; label: string; hint: string }[] = [
  { key: "meetings", label: "Spotkania", hint: "spotkania przy szansach i z kalendarza, bez powtórek do 15 min" },
  { key: "qualified", label: "Leady", hint: "szanse zakwalifikowane w tygodniu" },
  { key: "offers_stage", label: "Oferty (etap)", hint: "firmy, których szansa weszła na etap „Oferta wysłana”" },
];

export const LIGHT_TONE: Record<KpiLight, StatusDotTone> = {
  green: "success",
  yellow: "warning",
  red: "danger",
};

export const LIGHT_LABEL: Record<KpiLight, string> = {
  green: "cel osiągnięty",
  yellow: "co najmniej połowa celu",
  red: "poniżej połowy celu",
};

/** „26.10” — poniedziałek tygodnia (data ISO bez strefy, liczona w API). */
export function shortDate(iso: string): string {
  const [, month, day] = iso.split("-");
  return `${day}.${month}`;
}

/** „31.12.2026”. */
export function longDate(iso: string): string {
  const [year, month, day] = iso.split("-");
  return `${day}.${month}.${year}`;
}

const MONTHS = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];

export interface MrrPoint {
  label: string;
  cumulative: number;
  added: number;
}

/** Ostatnie `count` miesięcy krzywej narastającej (suma z wcześniejszych miesięcy zostaje w pierwszym punkcie). */
export function mrrPoints(months: SalesKpi["company"]["months"], count = 12): MrrPoint[] {
  return months.slice(-count).map((m) => {
    const [year, month] = m.month.split("-");
    return {
      label: `${MONTHS[Number(month) - 1]} ${year.slice(2)}`,
      cumulative: Number(m.cum_net_mrr) || 0,
      added: Number(m.net_mrr) || 0,
    };
  });
}

/** Procent celu (zaokrąglony w dół), `null` gdy celu nie ma. */
export function goalPercent(actual: string | number, goal: string | number | null): number | null {
  const target = Number(goal);
  if (goal === null || goal === "" || !Number.isFinite(target) || target <= 0) return null;
  return Math.floor(((Number(actual) || 0) / target) * 100);
}

/**
 * Czy tydzień od poniedziałku `weekStart` ma już historię etapów („Oferty (etap)”).
 * Historia zmian szansy zaczyna się od wdrożenia — tydzień w całości sprzed
 * niej nie ma danych, więc nie świeci na czerwono.
 */
export function hasStageHistory(weekStart: string, since: string | null): boolean {
  if (!since) return false;
  const [y, m, d] = weekStart.split("-").map(Number);
  const sunday = new Date(Date.UTC(y, m - 1, d + 6)).toISOString().slice(0, 10);
  return since <= sunday;
}
