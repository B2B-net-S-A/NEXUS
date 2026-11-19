"use client";

import { cn } from "@/lib/utils";
import { formatDate, type ActiveConsultantItem } from "@/types/client-profile";

/**
 * „Oś czasu” w zakładce Konsultanci (makieta 19.11.2026, wariant B jako drugi
 * widok obok listy): okres bieżącego zamówienia każdej osoby na osi kilku
 * miesięcy. Widać od razu, kiedy kończy się wiele zamówień naraz (PKO BP
 * 19.11.2026: 28 z 32 zamówień do 31.12.2026), czego w tabeli nie widać.
 */

const MONTHS = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];
/** Ile miesięcy pokazuje oś, licząc od bieżącego. */
export const TIMELINE_MONTHS = 8;

function parseDay(iso: string): number {
  return Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);
}

export interface TimelineRange {
  start: number;
  end: number;
  months: { label: string; offset: number }[];
}

/** Oś od pierwszego dnia bieżącego miesiąca przez `TIMELINE_MONTHS` miesięcy. */
export function timelineRange(today: string, months = TIMELINE_MONTHS): TimelineRange {
  const [year, month] = today.slice(0, 7).split("-").map(Number);
  const start = Date.UTC(year, month - 1, 1);
  const end = Date.UTC(year, month - 1 + months, 1);
  const span = end - start;
  return {
    start,
    end,
    months: Array.from({ length: months }, (_, index) => {
      const at = Date.UTC(year, month - 1 + index, 1);
      return { label: MONTHS[new Date(at).getUTCMonth()], offset: (at - start) / span };
    }),
  };
}

export interface TimelineBar {
  /** Lewa krawędź i szerokość jako ułamek osi (0–1). */
  left: number;
  width: number;
  /** Zamówienie bez daty końca — pasek do końca osi, przerywany. */
  openEnded: boolean;
}

/** Pasek okresu zamówienia na osi; `null`, gdy zamówienie leży poza osią albo go nie ma. */
export function timelineBar(
  row: Pick<ActiveConsultantItem, "order_start_date" | "order_end_date">,
  range: TimelineRange,
): TimelineBar | null {
  if (!row.order_start_date && !row.order_end_date) return null;
  const span = range.end - range.start;
  const from = Math.max(row.order_start_date ? parseDay(row.order_start_date) : range.start, range.start);
  const to = row.order_end_date ? Math.min(parseDay(row.order_end_date) + 86_400_000, range.end) : range.end;
  if (to <= range.start || from >= range.end || to <= from) return null;
  return {
    left: (from - range.start) / span,
    width: (to - from) / span,
    openEnded: !row.order_end_date,
  };
}

export function ConsultantsTimeline({
  rows,
  today,
}: {
  rows: ActiveConsultantItem[];
  today: string;
}) {
  const range = timelineRange(today);
  const todayOffset = (parseDay(today) - range.start) / (range.end - range.start);
  return (
    <div className="overflow-x-auto" data-testid="consultants-timeline">
      <div className="min-w-[760px]">
        <div className="grid grid-cols-[220px_minmax(0,1fr)] items-end border-b border-border pb-1 text-[11px] text-muted-foreground">
          <span>Zamówienie od – do</span>
          <div className="relative h-4">
            {range.months.map((month) => (
              <span
                key={`${month.label}-${month.offset}`}
                className="absolute top-0 tabular-nums"
                style={{ left: `${month.offset * 100}%` }}
              >
                {month.label}
              </span>
            ))}
          </div>
        </div>
        <ul>
          {rows.map((row) => {
            const bar = timelineBar(row, range);
            const ending = row.attention?.includes("order_ending");
            const noExtension = row.prolongation_status === "no";
            return (
              <li
                key={row.contract_id}
                className="grid grid-cols-[220px_minmax(0,1fr)] items-center border-b border-border/60 py-1.5 last:border-b-0"
              >
                <span className="min-w-0 truncate pr-3 text-[13px] text-foreground" title={row.candidate.name}>
                  {row.candidate.name}
                  {noExtension ? (
                    <span className="ml-1.5 rounded bg-destructive-muted px-1 text-[10px] font-medium text-destructive-muted-foreground">
                      prolongata: nie
                    </span>
                  ) : null}
                </span>
                <div className="relative h-4">
                  <span
                    aria-hidden
                    className="absolute inset-y-[-6px] w-px bg-primary/50"
                    style={{ left: `${todayOffset * 100}%` }}
                  />
                  {bar ? (
                    <span
                      className={cn(
                        "absolute top-1 h-2 rounded-full",
                        ending ? "bg-warning" : noExtension ? "bg-muted-foreground/40" : "bg-primary/70",
                        bar.openEnded && "bg-[repeating-linear-gradient(90deg,hsl(var(--muted-foreground)/0.5)_0_6px,transparent_6px_10px)]",
                      )}
                      style={{ left: `${bar.left * 100}%`, width: `${bar.width * 100}%` }}
                      title={`${row.order_start_date ? formatDate(row.order_start_date) : "?"} – ${
                        row.order_end_date ? formatDate(row.order_end_date) : "bez daty końca"
                      }`}
                    />
                  ) : (
                    <span className="absolute left-0 top-0 text-[11px] text-muted-foreground">bez zamówienia na osi</span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        <p className="mt-2 text-[11px] text-muted-foreground">
          Pionowa kreska to dziś. Pomarańczowy pasek: zamówienie kończy się bez kontynuacji;
          przerywany: zamówienie bez daty końca.
        </p>
      </div>
    </div>
  );
}
