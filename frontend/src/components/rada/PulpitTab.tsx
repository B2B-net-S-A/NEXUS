"use client";

import * as React from "react";
import { AlertTriangle, Info } from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import { cn, formatDate } from "@/lib/utils";
import { useBoardSummary, type BoardSummary, type FilingKind } from "@/lib/api/supervisory-board";
import { resolveViewState, isBlockingViewState } from "@/lib/view-state";

const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"];
const FILING_LABELS: Record<FilingKind, string> = {
  financial_statement: "sprawozdania",
  activity_report: "sprawozdania z działalności",
  audit_opinion: "opinii biegłego",
  approval: "uchwały zatwierdzającej",
};
// Progi „Do uwagi Rady” — opisane w docs/claude/rada/.
const CONCENTRATION_ALERT = 30;
const ENDING_ALERT = 30;
const RESULT_DROP_ALERT = 1;

export function mln(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString("pl-PL", { minimumFractionDigits: digits, maximumFractionDigits: digits })} mln`;
}

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
}

function range(months: number): string {
  return months <= 1 ? ROMAN[0] : `${ROMAN[0]}–${ROMAN[months - 1]}`;
}

export interface Attention {
  tone: "bad" | "warn" | "info";
  title: string;
  text: string;
}

/** Sygnały dla Rady z liczb pulpitu (czysta funkcja — test w __tests__). */
export function attentionItems(data: BoardSummary, year: number): Attention[] {
  const items: Attention[] = [];
  const { ytd } = data;
  if (
    ytd.result_pct != null &&
    ytd.result_previous_pct != null &&
    ytd.result_pct < ytd.result_previous_pct - RESULT_DROP_ALERT
  ) {
    items.push({
      tone: "bad",
      title: `Wynik z faktur niższy niż rok wcześniej (${range(ytd.result_months)})`,
      text: `${pct(ytd.result_pct)} sprzedaży wobec ${pct(ytd.result_previous_pct)} w ${year - 1}. Do potwierdzenia z RZiS: faktury kosztowe mogą zawierać refaktury.`,
    });
  }
  const { orders } = data;
  if (orders.active > 0 && (100 * orders.ending) / orders.active >= ENDING_ALERT) {
    items.push({
      tone: "warn",
      title: `${orders.ending} z ${orders.active} kontraktów: umowa albo zamówienie kończy się do ${formatDate(orders.year_end)}`,
      text: `To ${mln(orders.ending_potential_month)} miesięcznie z ${mln(orders.potential_month)} potencjału — zależy od przedłużeń na ${year + 1}.`,
    });
  }
  const top = data.top_clients.items[0];
  if (top && top.share >= CONCENTRATION_ALERT) {
    items.push({
      tone: "warn",
      title: `${top.name}: ${pct(top.share)} sprzedaży ${data.top_clients.year}`,
      text: "Jeden klient powyżej 30% sprzedaży — pierwsze pytanie banku i inwestora.",
    });
  }
  for (const gap of data.krs_missing) {
    items.push({
      tone: "warn",
      title: `KRS: brak ${gap.missing.map((k) => FILING_LABELS[k]).join(", ")} za ${gap.year}`,
      text: "Wzmianka o złożeniu nie pojawiła się w odpisie, a sprawozdanie za ten rok jest.",
    });
  }
  if (data.documents_without_file > 0) {
    items.push({
      tone: "info",
      title: `${data.documents_without_file} dokumentów bez skanu`,
      text: "Wiersze założone z KRS czekają na plik od Zarządu (zakładka Dokumenty).",
    });
  }
  return items;
}

export function PulpitTab() {
  const summary = useBoardSummary();
  const state = resolveViewState({
    isLoading: summary.isLoading,
    isError: summary.isError,
    error: summary.error,
    isSuccess: summary.isSuccess,
    isEmpty: (summary.data?.years.length ?? 0) === 0,
  });
  if (isBlockingViewState(state)) {
    return <QueryStateNotice state={state as "forbidden" | "not_found" | "error"} onRetry={() => summary.refetch()} />;
  }
  if (state === "loading" || !summary.data) {
    return <div className="h-40 animate-pulse rounded-lg border border-border bg-card" aria-hidden />;
  }
  const data = summary.data;
  const year = new Date().getFullYear();
  return (
    <div className="space-y-3">
      {state === "empty" ? (
        <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          Archiwum faktur nie jest jeszcze w NEXUSIE. Po imporcie z eBI24 (Finanse → Archiwum) pulpit pokaże sprzedaż, koszty i wynik za trzy lata.
        </p>
      ) : (
        <Kpis data={data} year={year} />
      )}
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        {state === "empty" ? <div /> : <YearsPanel data={data} />}
        <AttentionPanel items={attentionItems(data, year)} />
      </div>
      {state === "empty" ? null : <MonthsPanel data={data} year={year} />}
    </div>
  );
}

function Kpis({ data, year }: { data: BoardSummary; year: number }) {
  const { ytd, orders } = data;
  const salesChange =
    ytd.sales && ytd.sales_previous ? (100 * (ytd.sales - ytd.sales_previous)) / ytd.sales_previous : null;
  const lastYear = data.years.find((y) => y.year === year - 1);
  const top = data.top_clients.items[0];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
      <Figure
        label={`Sprzedaż ${range(ytd.sales_months)} ${year}`}
        value={mln(ytd.sales)}
        sub={
          <>
            rok wcześniej {mln(ytd.sales_previous)}
            {salesChange !== null ? (
              <span className={cn(" ml-1", salesChange >= 0 ? "text-success" : "text-destructive")}>
                {salesChange >= 0 ? "+" : ""}
                {pct(salesChange)}
              </span>
            ) : null}
          </>
        }
      />
      <Figure
        label={`Wynik z faktur ${range(ytd.result_months)}`}
        value={mln(ytd.result)}
        tone={ytd.result_pct != null && ytd.result_previous_pct != null && ytd.result_pct < ytd.result_previous_pct ? "bad" : "neutral"}
        sub={`${pct(ytd.result_pct)} sprzedaży · rok wcześniej ${pct(ytd.result_previous_pct)}`}
      />
      <Figure
        label={`Sprzedaż ${year - 1}`}
        value={mln(lastYear?.sales)}
        sub={`wynik z faktur ${mln(lastYear?.result)} (${pct(lastYear?.result_pct)})`}
      />
      <Figure
        label="Aktywne kontrakty"
        value={String(orders.active)}
        sub={`potencjał ${mln(orders.potential_month)} / mies. (160 h)`}
      />
      <Figure
        label={`Kończą się do ${formatDate(orders.year_end).slice(0, 5)}`}
        value={String(orders.ending)}
        tone={orders.active && (100 * orders.ending) / orders.active >= ENDING_ALERT ? "warn" : "neutral"}
        sub={`${mln(orders.ending_potential_month)} / mies. bez przedłużenia`}
      />
      <Figure
        label="Największy klient"
        value={top ? pct(top.share) : "—"}
        tone={top && top.share >= CONCENTRATION_ALERT ? "warn" : "neutral"}
        sub={top ? `${top.name}, ${data.top_clients.year}` : undefined}
      />
    </div>
  );
}

function Figure({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string;
  sub?: React.ReactNode;
  tone?: "neutral" | "bad" | "warn";
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card px-3.5 py-3">
      <div className="truncate text-[12px] font-medium text-muted-foreground" title={label}>
        {label}
      </div>
      <div
        className={cn(
          "mt-1 text-[22px] font-semibold leading-tight tabular-nums tracking-tight",
          tone === "bad" && "text-destructive",
          tone === "warn" && "text-warning-muted-foreground",
          tone === "neutral" && "text-foreground",
        )}
      >
        {value}
      </div>
      {sub ? <div className="mt-1 text-[11px] leading-snug text-muted-foreground">{sub}</div> : null}
    </div>
  );
}

function YearsPanel({ data }: { data: BoardSummary }) {
  const max = Math.max(...data.years.flatMap((y) => [y.sales ?? 0, y.costs ?? 0]), 1);
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">Sprzedaż, koszty i wynik z faktur</h2>
        <span className="text-[11px] text-muted-foreground">mln zł netto</span>
      </div>
      <div className="flex h-[120px] items-end gap-3">
        {data.years.map((y) => (
          <div key={y.year} className={cn("flex h-full min-w-0 flex-1 flex-col justify-end", !y.complete && "opacity-60")}>
            <div className="flex h-full items-end justify-center gap-1">
              <div className="w-1/2 max-w-5 rounded-t-sm bg-primary" style={{ height: `${((y.sales ?? 0) / max) * 100}%` }} />
              <div className="w-1/2 max-w-5 rounded-t-sm bg-muted-foreground/35" style={{ height: `${((y.costs ?? 0) / max) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
      <table className="mt-2 w-full text-[12px]">
        <thead>
          <tr className="text-[11px] text-muted-foreground">
            <th className="py-1 text-left font-medium" />
            {data.years.map((y) => (
              <th key={y.year} className="py-1 text-right font-medium tabular-nums">
                {y.year}
                {y.complete ? "" : " (do dziś)"}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border tabular-nums">
          <Row label="Sprzedaż" values={data.years.map((y) => mln(y.sales))} />
          <Row label="Koszty z faktur" values={data.years.map((y) => mln(y.costs))} />
          <Row label="Wynik z faktur" values={data.years.map((y) => mln(y.result))} strong />
          <Row label="% sprzedaży" values={data.years.map((y) => pct(y.result_pct))} />
        </tbody>
      </table>
      <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
        Faktury z archiwum eBI24 wg daty wystawienia
        {data.source.last_date ? `, do ${formatDate(data.source.last_date)}` : ""}. „Wynik z faktur” to sprzedaż minus faktury kosztowe, bez płac
        UoP, ZUS i amortyzacji — nie zastępuje RZiS.
        {currentResult(data)}
      </p>
    </section>
  );
}

function currentResult(data: BoardSummary): string {
  const current = data.years.find((y) => !y.complete);
  if (!current?.result_months) return "";
  return ` Wynik ${current.year} liczony za ${range(current.result_months)} — koszty kolejnych miesięcy jeszcze spływają.`;
}

function Row({ label, values, strong }: { label: string; values: string[]; strong?: boolean }) {
  return (
    <tr>
      <td className={cn("py-1.5 text-left", strong && "font-semibold")}>{label}</td>
      {values.map((v, i) => (
        <td key={i} className={cn("py-1.5 text-right", strong && "font-semibold")}>
          {v}
        </td>
      ))}
    </tr>
  );
}

function AttentionPanel({ items }: { items: Attention[] }) {
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold text-foreground">Do uwagi Rady</h2>
      {items.length === 0 ? (
        <p className="text-[12px] text-muted-foreground">Nic nie odbiega od progów.</p>
      ) : (
        <ul className="space-y-2.5 text-[12px] leading-snug">
          {items.map((item) => (
            <li key={item.title} className="flex gap-2">
              {item.tone === "info" ? (
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              ) : (
                <AlertTriangle
                  className={cn(
                    "mt-0.5 h-3.5 w-3.5 shrink-0",
                    item.tone === "bad" ? "text-destructive" : "text-warning-muted-foreground",
                  )}
                />
              )}
              <div>
                <div className="font-medium text-foreground">{item.title}</div>
                <div className="text-muted-foreground">{item.text}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function MonthsPanel({ data, year }: { data: BoardSummary; year: number }) {
  const byKey = new Map(data.months.map((m) => [`${m.year}-${m.month}`, m]));
  const rows = [year - 1, year];
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">Miesiące — sprzedaż / koszty z faktur</h2>
        <span className="text-[11px] text-muted-foreground">mln zł netto · kursywa = koszty jeszcze spływają</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px] tabular-nums">
          <thead>
            <tr className="text-[11px] text-muted-foreground">
              <th className="py-1 text-left font-medium" />
              {ROMAN.map((m) => (
                <th key={m} className="py-1 text-right font-medium">
                  {m}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((y) => (
              <tr key={y}>
                <td className="py-1.5 pr-2 text-left font-medium">{y}</td>
                {ROMAN.map((_, i) => {
                  const m = byKey.get(`${y}-${i + 1}`);
                  return (
                    <td key={i} className="py-1.5 text-right">
                      {m ? (
                        <>
                          <div>{(m.sales ?? 0).toLocaleString("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}</div>
                          <div className={cn("text-muted-foreground", !m.costs_complete && "italic")}>
                            {(m.costs ?? 0).toLocaleString("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                          </div>
                        </>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
