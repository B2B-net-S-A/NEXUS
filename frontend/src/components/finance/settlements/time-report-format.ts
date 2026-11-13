// Etykiety i filtry ekranu „Raport klienta (T4T)” (plan Nordei N1.5).
import type { StatusDotTone } from "@/components/ds/StatusDot";
import type { TimeReportPeriod, TimeReportRow, TimeReportStatus, WeekCell } from "@/lib/api/client-time-reports";

export const T4T_STATUS: Record<TimeReportStatus, { label: string; tone: StatusDotTone; next: string }> = {
  ok: { label: "Zgodne", tone: "success", next: "Do faktury dla klienta" },
  waiting: { label: "Czekamy", tone: "neutral", next: "Czekamy na kolejny raport" },
  no_approval: { label: "Brak akceptacji", tone: "warning", next: "Wyjaśnij z konsultantem" },
  differs: { label: "Rozbieżność", tone: "danger", next: "Wyjaśnij z konsultantem" },
  other_amount: { label: "Inna kwota", tone: "warning", next: "Sprawdź dodatek na fakturze" },
  no_invoice: { label: "Brak faktury", tone: "info", next: "Czekamy na fakturę w KSeF" },
  not_in_report: { label: "Brak w raporcie", tone: "info", next: "Zapytaj Cost Control o osobę" },
  unmatched: { label: "Bez kartoteki", tone: "warning", next: "Uzupełnij kartotekę" },
};

/** Kolejność liczników nad listą. */
export const T4T_COUNTERS: TimeReportStatus[] = ["ok", "waiting", "no_approval", "differs", "other_amount", "no_invoice", "not_in_report", "unmatched"];

export type T4tFilter = "todo" | "waiting" | "changed" | "ok" | "all";

export const T4T_FILTERS: { key: T4tFilter; label: string }[] = [
  { key: "todo", label: "Do zrobienia" },
  { key: "waiting", label: "Czekamy" },
  { key: "changed", label: "Zmiany od poprzedniej wersji" },
  { key: "ok", label: "Zgodne" },
  { key: "all", label: "Wszyscy" },
];

const TODO: ReadonlySet<TimeReportStatus> = new Set(["no_approval", "differs", "other_amount", "no_invoice", "not_in_report", "unmatched"]);

export function matchesT4tFilter(filter: T4tFilter, row: Pick<TimeReportRow, "status" | "changed">): boolean {
  switch (filter) {
    case "todo":
      return TODO.has(row.status);
    case "waiting":
      return row.status === "waiting";
    case "changed":
      return row.changed;
    case "ok":
      return row.status === "ok";
    default:
      return true;
  }
}

export function countT4tFilter(filter: T4tFilter, rows: Pick<TimeReportRow, "status" | "changed">[]): number {
  return rows.filter((r) => matchesT4tFilter(filter, r)).length;
}

/** Szukanie po osobie, nazwisku z raportu, numerze osoby i NIDS. */
export function matchesSearch(row: TimeReportRow, needle: string): boolean {
  const q = needle.trim().toLowerCase();
  if (!q) return true;
  return [row.name, row.report_name ?? "", row.person_no ?? "", ...row.projects].some((v) => v.toLowerCase().includes(q));
}

/** „168.00” → „168 h”, „7.50” → „7,5 h”; brak → „–”. */
export function hoursText(value: string | null | undefined): string {
  if (value == null) return "–";
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toLocaleString("pl-PL", { maximumFractionDigits: 2 })} h` : "–";
}

/** Przedział T4T: „1–6.09”. */
export function periodLabel(period: TimeReportPeriod): string {
  const [, sm, sd] = period.start.split("-");
  const [, em, ed] = period.end.split("-");
  return sm === em ? `${Number(sd)}–${Number(ed)}.${em}` : `${Number(sd)}.${sm}–${Number(ed)}.${em}`;
}

/** „2026-10-01” → „01.10.2026”. */
export function dateText(iso: string | null | undefined): string {
  if (!iso) return "–";
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

export function weekState(cell: WeekCell): "submitted" | "approved" | "empty" {
  if (Number(cell[1]) > 0) return "submitted";
  if (Number(cell[0]) > 0) return "approved";
  return "empty";
}
